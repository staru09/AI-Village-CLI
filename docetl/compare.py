"""Compare the DocETL pipelines' output with our verified answers and with `village label`.

    .venv/bin/python docetl/compare.py            # reads docetl/out/, village.db, labels.db

For each ground-truth answer it prints what DocETL's output gives and whether it matches. It also reports how many
units each pipeline dropped (DocETL drops a row whose output fails validation), and the agreement with our own labels.
"""
import collections, json, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from village_graph.core import maker  # noqa: E402

OUT = Path(__file__).resolve().parent / 'out'
LO, HI = '2026-05-11', '2026-05-16'
MODEL = sys.argv[1] if len(sys.argv) > 1 else 'claude-sonnet-5-5'


def load(name):
    p, m = OUT / f'{name}-{MODEL}.json', OUT / f'{name}-{MODEL}.meta.json'
    return (json.loads(p.read_text()), json.loads(m.read_text())) if p.exists() else (None, None)


def main():
    con = sqlite3.connect(f'file:{ROOT / "village.db"}?mode=ro', uri=True)
    con.execute(f"ATTACH 'file:{ROOT / 'labels.db'}?mode=ro' AS L")
    N = dict(con.execute('SELECT id, name FROM nodes'))
    fam = {N[i]: maker(m) for i, m in con.execute('SELECT id, model FROM nodes')}
    ours = {r: dict(con.execute("SELECT ref, coalesce(verdict, label) FROM L.labels WHERE rubric = ?", (r,))) for r in ('delegation', 'goal_fit')}
    ok = lambda b: 'MATCH' if b else 'DIFFERENT'

    rows, meta = load('delegation')
    if rows:
        lab = {r['ref']: r['label'] for r in rows}
        both = [r for r in lab if r in ours['delegation']]
        print(f"## delegation: {meta['rows_out']} of {meta['units_in']} units returned ({meta['units_in'] - meta['rows_out']} dropped), "
              f"{meta['seconds']}s, ${meta['cost_usd_reported']:.2f} reported")
        print(f"   same label as `village label` on {sum(lab[r] == ours['delegation'][r] for r in both)} of {len(both)}; "
              f"same on directs-or-not: {sum((lab[r] == 'directs') == (ours['delegation'][r] == 'directs') for r in both)} of {len(both)}")
        to = collections.defaultdict(list)
        for mid, src, dst in con.execute("SELECT msg_id, src, dst FROM edges WHERE kind = 'addressed' AND src != 'human' AND dst != 'human' AND ts >= ? AND ts < ?", (LO, HI)):
            to['m:' + mid.replace('-', '')[:12]].append((N[src], N[dst]))
        directs = collections.Counter(to[r][0][0] for r, l in lab.items() if l == 'directs' and to.get(r))
        pairs = collections.Counter(p for r, l in lab.items() if l == 'directs' for p in to.get(r, []))
        speakers = {s for v in to.values() for s, _ in v}
        never = sorted(speakers - set(directs)) + ['GPT-5']
        top3 = [a for a, _ in directs.most_common(3)]
        print('   task-assigning messages per agent:', directs.most_common(6))
        print('   G8 top assigners (truth: DeepSeek-V3.2 19, then Claude Haiku 4.5 and Claude Opus 4.7 with 16):', ok('DeepSeek-V3.2' in top3 and {'Claude Haiku 4.5', 'Claude Opus 4.7'} & set(top3)))
        print('   G8 never assigned (truth: GPT-5.5, Kimi K2.6, GPT-5.1, Gemini 2.5 Pro, Claude Sonnet 4.6, GPT-5):', never,
              ok(set(never) == {'GPT-5.5', 'Kimi K2.6', 'GPT-5.1', 'Gemini 2.5 Pro', 'Claude Sonnet 4.6', 'GPT-5'}))
        best = collections.Counter({a: n for a, n in directs.items() if a in ('Claude Opus 4.7', 'GPT-5.5', 'Gemini 3.1 Pro', 'Kimi K2.6')})
        print('   G6 #best (truth: Claude Opus 4.7 assigns, 16; GPT-5.5 and Kimi never):', dict(best), ok(best.most_common(1)[0][0] == 'Claude Opus 4.7' and not best['GPT-5.5'] and not best['Kimi K2.6']))
        o47 = collections.Counter({d: n for (s, d), n in pairs.items() if s == 'Claude Opus 4.7'})
        print('   G7 whom Claude Opus 4.7 directs most (truth: GPT-5.5, 13):', o47.most_common(3), ok(o47.most_common(1)[0][0] == 'GPT-5.5'))
        same = sum(n for (s, d), n in pairs.items() if fam[s] == fam[d])
        print(f'   G9 same-maker share of assignments (truth: 47 of 214, 22%): {same} of {sum(pairs.values())}, {100 * same / sum(pairs.values()):.0f}%',
              ok(abs(same / sum(pairs.values()) - 0.22) < 0.05))

    rows, meta = load('goal_fit')
    if rows:
        lab = {r['ref']: r['label'] for r in rows}
        both = [r for r in lab if r in ours['goal_fit']]
        print(f"\n## goal_fit: {meta['rows_out']} of {meta['units_in']} units returned ({meta['units_in'] - meta['rows_out']} dropped), "
              f"{meta['seconds']}s, ${meta['cost_usd_reported']:.2f} reported")
        print(f"   same label as `village label` on {sum(lab[r] == ours['goal_fit'][r] for r in both)} of {len(both)}")
        per, day = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
        for sid, agent, ts in con.execute('SELECT id, agent, ts FROM sessions WHERE ts >= ? AND ts < ?', (LO, HI)):
            l = lab.get('s:' + sid.replace('-', '')[:12])
            if l:
                per[N[agent]][l] += 1
                day[ts[:10]][l] += 1
        share = lambda c, *ls: 100 * sum(c[l] for l in ls) / max(sum(c.values()), 1)
        a, b, c = per['Claude Opus 4.7'], per['Claude Sonnet 4.5'], per['Claude Opus 4.6']
        print(f"   G10 on goal: Claude Opus 4.7 {share(a, 'on_goal'):.0f}% (truth 90% by intent, 100% by commands), Claude Sonnet 4.5 {share(b, 'on_goal'):.0f}% (truth about 10%)",
              ok(share(a, 'on_goal') >= 85 and share(b, 'on_goal') <= 15))
        print(f"   G11 Claude Opus 4.6: side project {share(c, 'side_project'):.0f}% (truth 57%), on goal or support {share(c, 'on_goal', 'support'):.0f}% (truth 34%)",
              ok(share(c, 'side_project') > 50 and 25 <= share(c, 'on_goal', 'support') <= 45))
        days = {d: share(c, 'on_goal') for d, c in sorted(day.items())}
        first = next((d for d, s in days.items() if s < 50), None)
        print('   G12 on-goal share per day (truth: turns on 13 May; 77, 51, 31, 18, 34):', {d[5:]: round(s) for d, s in days.items()}, ok(first == '2026-05-13'))

    rows, meta = load('groups')
    if rows:
        r = rows[0]
        print(f"\n## groups: {meta['seconds']}s, ${meta['cost_usd_reported']:.2f} reported")
        trio = set(r.get('top_trio') or [])
        print('   G4 trio on most days (truth: Claude Opus 4.7, GPT-5.5, Gemini 3.1 Pro, #best, 4 of 5 days):', sorted(trio), r.get('top_trio_room'), r.get('top_trio_days'),
              ok(trio == {'Claude Opus 4.7', 'GPT-5.5', 'Gemini 3.1 Pro'}))
        pairs = {frozenset(p) for p in r.get('pairs_every_day') or []}
        truth = {frozenset(('Claude Haiku 4.5', 'DeepSeek-V3.2')), frozenset(('Claude Opus 4.5', 'GPT-5.4'))}
        print('   G5 pairs every day (truth: Haiku 4.5 + DeepSeek-V3.2; Opus 4.5 + GPT-5.4):', [sorted(p) for p in pairs], ok(pairs == truth),
              f'({len(pairs & truth)} of the 2 true pairs named, {len(pairs - truth)} others)')


if __name__ == '__main__':
    main()
