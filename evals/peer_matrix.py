"""Peer-relationship matrix for village goal 41 ("Perform novel research!"), from existing chat only.

For each ordered pair (speaker -> target) it counts the messages in which the speaker mentions the target (table
`edges`) and in which a sentence about the target matches one of four fixed regular expressions.

    python peer_matrix.py                      the report
    python peer_matrix.py --sample praise      25 random matches of one class, to judge by hand (--seed N, default 41)
    python peer_matrix.py --json               the pairs with at least 5 mentions, as JSON
    python peer_matrix.py --pair "GPT-5.4" "GPT-5.1" [--cls criticism]   the matching sentences of one pair
"""
import argparse, json, random, re, sqlite3
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

DB = f'file:{Path(__file__).resolve().parent.parent / "village.db"}?mode=ro'
SINCE, UNTIL = '2026-05-11', '2026-05-16'  # goal 41, Pacific time (the database clock)

# One expression per class, fixed after two validation rounds (25 hand-judged matches each, see m4_matrix.json):
# praise 24/25, criticism 16/25 (35 of all 51 matches by hand), request 21/25, deference 24/25.
# ponytail: keyword rules, so criticism is under-counted and a third of its matches are wrong; and the `edges` table
# only knows full names ("Gemini — ..." alone leaves no edge). Use a labelling model if the criticism count matters.
REGEX = {
    'praise': r"\b(excellent|brilliant|great (work|catch|job|point|approach|idea|find|analysis|call|question)|"
              r"good (work|catch|job|call|find)|nice (work|catch|job|find)|fantastic|impressive|outstanding|superb|"
              r"thank you|thanks|appreciate[ds]?|well done|kudos|congratulations|congrats|elegant|exemplary|invaluable|"
              r"strong (work|analysis|result|contribution|proposal|design|catch))\b",
    'criticism': r"(\b(you|your)\b[^.!?\n]{0,60}\b(stale|incorrect|wrong|mismatch\w*|outdated|broken|inaccurate|blocking|blocker)\b|"
                 r"\b(stale|incorrect|wrong|mismatch\w*|outdated|inaccurate)\b[^.!?\n]{0,60}\byou\b|"
                 r"\bfound\b[^.!?\n]{0,40}\b(stale|mismatch\w*|discrepanc\w*|inconsistenc\w*|lingering)\b|"
                 r"\b(did not|didn't) (confirm|respond|check in|push|run|include|land)\b|"
                 r"\b(has not|hasn't|have not|haven't) (landed|pushed|responded|confirmed)\b|"
                 r"\b(does not|doesn't) exist\b|\b(not|n't) actually\b|\bwrong[- ]task\b|\b(overwrote|clobbered)\b|"
                 r"\b(is|are|was|were) (a problem|the only blocker|the critical blocker|aspirational|premature|misleading|"
                 r"overstated|not accurate|not correct)\b|\bblocked on\b|\b(I|we) (disagree|don't agree|do not agree)\b|"
                 r"\bre-?push\b|\b(pause|stop) (the|your)\b|\b(audit|QA|hygiene|risk) note\b|"
                 r"\b(quick|minor|small) (heads[- ]up|clarification)\b|\bcareful w(ith|/)|\bhigh risk\b|"
                 r"\b(polish|nits?|fix(es)?) (on|to|for|in) your\b)",
    'request': r"\b(please|could you|can you|would you|need you to|will you)\b",
    'deference': r"(\byou're right\b|\byou are right\b|\bgood point\b|\bagreed\b|\bI agree\b|\bI accept\b|\bwill do\b|"
                 r"\bas you (suggested|noted|recommended|pointed out)\b|\bper your (suggestion|recommendation|request)\b|"
                 r"\b(is|are|was|were) (correct|right)\b|\bI stand corrected\b|\bdefer(ring)? to\b)",
}
CLASSES = list(REGEX)
RX = {k: re.compile(v, re.I) for k, v in REGEX.items()}

HYPHENS = str.maketrans({'‐': '-', '‑': '-', '–': '-', '’': "'"})
SPLIT = re.compile(r'(?<=[.!?])\s+|\n+')          # a sentence ends at . ! ? before a space, or at a line break
YOU = re.compile(r'^\W*(you|your)\b', re.I)
QUOTED = re.compile(r'`[^`\n]*`|“[^”\n]*”|"[^"\n]*"')  # code spans and quoted strings are not the speaker's own words
HOME = {'Gemini 3.1 Pro': 'best', 'Gemini 2.5 Pro': 'rest'}


@lru_cache(None)
def name_rx(name, room=None):
    """The target's full name as the edges extractor matches it, plus the unambiguous short form used in chat
    ("Opus 4.5", "Kimi", "DeepSeek", "Gemini 3.1"). Bare "Gemini" means the Gemini of the room the message is in;
    bare "Claude"/"Opus"/"Sonnet" are ambiguous and not matched. A name right after "| " is a page or table string
    ("64 features | Claude Opus 4.6"), not a mention."""
    forms = {name}
    if room and HOME.get(name) == room:
        forms.add('Gemini')
    if name.startswith('Claude '):
        forms.add(name[len('Claude '):])
    if name.startswith('Gemini '):
        forms.add(name.rsplit(' ', 1)[0])
    if name in ('Kimi K2.6', 'DeepSeek-V3.2'):
        forms.add(re.split(r'[ -]', name)[0])
    alt = '|'.join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    return re.compile(rf'(?<![\w./-])(?<!\| )(?<!\| Claude )({alt})(?![\w-]|\.\d)', re.I)  # GPT-5 must not eat GPT-5.1


def target_sentences(text, rx):
    """Sentences that name the target, plus sentences that directly follow one and start with you/your."""
    out, prev = [], False
    for s in SPLIT.split(QUOTED.sub(' ', text.translate(HYPHENS))):
        if not s.strip():
            continue
        prev = bool(rx.search(s)) or (prev and bool(YOU.match(s)))
        if prev:
            out.append(s.strip())
    return out


def classify(text, rx):
    sents = target_sentences(text, rx)
    return {c: [s for s in sents if RX[c].search(s)] for c in CLASSES}


def load():
    con = sqlite3.connect(DB, uri=True)
    agents = [r[0] for r in con.execute(
        "SELECT n.name FROM messages m JOIN nodes n ON n.id = m.src WHERE m.ts >= ? AND m.ts < ? AND m.src != 'human' "
        "GROUP BY 1 ORDER BY 1", (SINCE, UNTIL))]
    rows = con.execute(
        "SELECT m.id, s.name, d.name, m.room, m.ts, m.content FROM edges e JOIN messages m ON m.id = e.msg_id "
        "JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst WHERE e.ts >= ? AND e.ts < ? AND e.src != 'human' "
        "ORDER BY m.ts, d.name", (SINCE, UNTIL)).fetchall()
    return agents, [r for r in rows if r[1] in agents and r[2] in agents]


def short(n):
    return n.replace('Claude ', '').replace('Gemini ', 'Gem ').replace('DeepSeek-V3.2', 'DeepSeek').replace(' K2.6', '')


def grid(title, cell, agents):
    print(f'\n## {title} (rows: speaker, columns: target; rows with no count dropped)')
    w = max(len(short(a)) for a in agents) + 1
    print(' ' * w + ''.join(f'{short(a)[:8]:>9}' for a in agents) + f'{"given":>8}')
    for a in agents:
        vals = [cell(a, b) for b in agents]
        if sum(vals):
            print(f'{short(a):<{w}}' + ''.join(f'{v or ".":>9}' for v in vals) + f'{sum(vals):>8}')
    print(f'{"received":<{w}}' + ''.join(f'{sum(cell(a, b) for a in agents):>9}' for b in agents))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sample', choices=CLASSES)
    p.add_argument('--seed', type=int, default=41)
    p.add_argument('--json', action='store_true')
    p.add_argument('--pair', nargs=2)
    p.add_argument('--cls', choices=CLASSES)
    a = p.parse_args()

    agents, rows = load()
    n = defaultdict(Counter)   # (src, dst) -> Counter(mentions, praise, ...)
    hits = defaultdict(list)   # class -> [(msg id, ts, src, dst, sentences)]
    for mid, src, dst, room, ts, text in rows:
        n[src, dst]['mentions'] += 1
        for c, sents in classify(text, name_rx(dst, room)).items():
            if sents:
                n[src, dst][c] += 1
                hits[c].append((mid, ts, src, dst, sents))

    if a.sample:
        for mid, ts, src, dst, sents in random.Random(a.seed).sample(hits[a.sample], 25):
            print(f'm:{mid.replace("-", "")[:12]} {ts[:16]} {src} -> {dst}\n    ' + '\n    '.join(sents) + '\n')
        return
    if a.pair:
        for c in ([a.cls] if a.cls else CLASSES):
            for mid, ts, src, dst, sents in hits[c]:
                if [src, dst] == a.pair:
                    print(f'[{c}] m:{mid.replace("-", "")[:12]} {ts[:16]}\n    ' + '\n    '.join(sents) + '\n')
        return
    pairs = sorted(n, key=lambda k: -n[k]['mentions'])
    if a.json:
        print(json.dumps([{'from': s, 'to': d, 'mentions': n[s, d]['mentions'], **{c: n[s, d][c] for c in CLASSES}}
                          for s, d in pairs if n[s, d]['mentions'] >= 5], indent=1))
        return

    print(f'goal 41 chat, {SINCE} to {UNTIL} PT: {len(rows)} mention edges in {len({r[0] for r in rows})} messages, '
          f'{len(agents)} agents, {len(n)} ordered pairs')
    for c in ['mentions'] + CLASSES:
        grid(c, lambda s, d, c=c: n[s, d][c], agents)

    print('\n## totals per agent (given as speaker / received as target)')
    print(f'{"agent":<19}' + ''.join(f'{c + " g/r":>17}' for c in ['mentions'] + CLASSES) + f'{"net received":>14}')
    for ag in agents:
        g = {c: sum(n[ag, b][c] for b in agents) for c in ['mentions'] + CLASSES}
        r = {c: sum(n[b, ag][c] for b in agents) for c in ['mentions'] + CLASSES}
        print(f'{ag:<19}' + ''.join(f'{str(g[c]) + " / " + str(r[c]):>17}' for c in g) + f'{r["praise"] - r["criticism"]:>14}')

    net = lambda k: n[k]['praise'] - n[k]['criticism']
    line = lambda k: (f'{k[0]:<18} -> {k[1]:<18} mentions {n[k]["mentions"]:>3}  praise {n[k]["praise"]:>3}  criticism '
                      f'{n[k]["criticism"]:>3}  request {n[k]["request"]:>3}  deference {n[k]["deference"]:>3}  net {net(k):>+4}')
    print('\n## ordered pairs with at least 5 mentions (net = praise minus criticism)')
    for k in pairs:
        if n[k]['mentions'] >= 5:
            print(line(k))
    for c in ('praise', 'criticism'):
        print(f'\n## top 10 pairs by {c}')
        for k in sorted(n, key=lambda k: (-n[k][c], -n[k]['mentions']))[:10]:
            print(line(k))

    print('\n## reciprocity (unordered pairs)')
    both, one = [], []
    for s, d in n:
        if s < d and n[s, d]['praise'] >= 3 and n[d, s]['praise'] >= 3 and net((s, d)) > 0 and net((d, s)) > 0:
            both.append((s, d))
    for k in n:
        if n[k]['criticism'] >= 3 and net(k) < 0:
            one.append(k)
    print('both directions praise-heavy (praise >= 3 and praise > criticism each way):')
    for s, d in sorted(both, key=lambda k: -(n[k]['praise'] + n[k[::-1]]['praise'])):
        print(f'  {s} <-> {d}: {n[s, d]["praise"]}p/{n[s, d]["criticism"]}c one way, {n[d, s]["praise"]}p/{n[d, s]["criticism"]}c back')
    print('one direction criticism-heavy (criticism >= 3 and criticism > praise):')
    for s, d in sorted(one, key=net):
        print(f'  {s} -> {d}: {n[s, d]["praise"]}p/{n[s, d]["criticism"]}c; back {d} -> {s}: '
              f'{n[d, s]["praise"]}p/{n[d, s]["criticism"]}c over {n[d, s]["mentions"]} mentions')
    print('one-sided attention (A mentions B at least 10 times, B mentions A at most a fifth as often):')
    for s, d in pairs:
        if n[s, d]['mentions'] >= 10 and n[d, s]['mentions'] * 5 <= n[s, d]['mentions']:
            print(f'  {s} -> {d}: {n[s, d]["mentions"]} mentions, back {n[d, s]["mentions"]}')


def _selfcheck():
    a, b = name_rx('Claude Opus 4.5'), name_rx('GPT-5')
    t = "@Claude Opus 4.5 excellent catch. Your fix is elegant. GPT-5 please rerun.\nGPT-5.1 was wrong."
    assert classify(t, a)['praise'] and len(classify(t, a)['praise']) == 2      # the "Your ..." sentence follows
    assert not classify(t, b)['praise'] and classify(t, b)['request']          # praise for A is not credited to B
    assert not classify(t, b)['criticism']                                     # GPT-5 does not eat GPT-5.1
    assert classify('Opus 4.5 is correct.', a)['deference']                    # short form
    assert not target_sentences('still shows **64 features | Claude Opus 4.5** and `Claude Opus 4.5`', a)  # page strings
    assert target_sentences("Gemini's commit overwrote it", name_rx('Gemini 3.1 Pro', 'best'))
    assert not target_sentences("Gemini's commit overwrote it", name_rx('Gemini 3.1 Pro', 'rest'))


if __name__ == '__main__':
    _selfcheck()
    main()
