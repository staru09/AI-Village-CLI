"""Render ground-truth files as one HTML page for review.

    python3 evals/review_page.py OUT.html GROUP=FILE.json [GROUP=FILE.json ...]

Each file is a ground-truth answer in the shape `evals/check_citations.py` checks: question, answer, reasoning,
findings (claim, kind, citations with ref, field, quote, quote_ok), searches, could_not_check, confidence, and an
optional `review` ({status, notes}) written by whoever verified it; sweeps add incident fields per finding, and a file
may carry a `tally` (one verdict per flagged unit) or a `matrix` with `regex` and `precision`. GROUP is the heading the file is listed under.
The page has no dependencies: it is a fragment (title + style + content) ready for an artifact or a browser.
"""
import html, json, sys
from pathlib import Path

E = lambda s: html.escape(str(s if s is not None else ''))
KIND = {'ground truth': 'truth', 'claim': 'claim', 'interpretation': 'interp'}


def kind_of(f):
    k = (f.get('kind') or '').lower()
    return next((v for key, v in KIND.items() if key in k), 'interp')


def citation(c):
    ok = c.get('quote_ok')
    mark = '<span class="ok" title="This quote was found in the cited record by code">found in record</span>' if ok else \
        ('<span class="bad">no such record</span>' if c.get('missing') else '<span class="bad">quote NOT found in the record</span>')
    return (f'<li class="cite {"good" if ok else "fail"}"><div class="chead"><code class="ref">{E(c.get("ref"))}</code>'
            f'<span class="field">{E(c.get("field"))}</span>{mark}</div><blockquote>{E(c.get("quote"))}</blockquote></li>')


def finding(f, n, key=''):
    k = kind_of(f)
    label = {'truth': 'ground truth', 'claim': 'claim', 'interp': 'interpretation'}[k]
    extra = ''
    if f.get('title'):  # an incident from a sweep
        rows = [(x, f.get(y)) for x, y in (('In short', 'claim'), ('What happened', 'what_happened'), ('Disclosed', 'disclosed'), ('Caught by', 'caught_by'),
                                           ('Outcome', 'outcome'), ('Assessment', 'assessment')) if f.get(y)]
        extra = (f'<div class="inc"><div class="meta"><span>{E(", ".join(f.get("agents") or []))}</span>'
                 f'<span>{E(f.get("when"))}</span><span class="cat">{E(f.get("category"))}</span></div>'
                 f'<dl>{"".join(f"<dt>{E(a)}</dt><dd>{E(b)}</dd>" for a, b in rows)}</dl></div>')
    cites = f.get('citations') or []
    bad = sum(not c.get('quote_ok') for c in cites)
    return (f'<li id="{E(key)}-{n}" class="finding k-{k}{" has-bad" if bad or not cites else ""}"><div class="fhead"><span class="num">{n}</span>'
            f'<span class="pill {k}">{label}</span>' + (f'<h4 class="claim">{E(f["title"])}</h4>' if f.get('title') else f'<p class="claim">{E(f.get("claim"))}</p>') + f'</div>{extra}'
            f'<details class="cites"{" open" if bad else ""}><summary>{len(cites)} citation{"s" if len(cites) != 1 else ""}'
            f'{f" · {bad} not verified" if bad else ""}</summary><ul>{"".join(map(citation, cites))}</ul></details></li>')


def card(key, d):
    fs = d.get('findings') or []
    cites = [c for f in fs for c in f.get('citations') or []]
    ok = sum(bool(c.get('quote_ok')) for c in cites)
    rev = d.get('review') or {}
    conf = (d.get('confidence') or '').strip()
    level = next((l for l in ('high', 'medium', 'low') if conf.lower().startswith(l)), 'medium')
    searches = d.get('searches') or []
    matrix = (matrix_table(d['matrix']) if d.get('matrix') else '') + precision(d) + tally(d.get('tally'))
    return f'''<article class="card" id="{E(key)}">
  <header><div class="eyebrow">{E(d.get("_group"))} · {E(key)}</div><h2>{E(d.get("question"))}</h2></header>
  <div class="answer"><div class="label">Answer</div><p>{E(d.get("answer"))}</p></div>
  <div class="chips"><span class="chip conf-{level}">confidence: {E(conf)}</span>
    <span class="chip {"allok" if ok == len(cites) else "someBad"}">{ok} of {len(cites)} quotes found in their records</span>
    <span class="chip">{len(fs)} findings</span></div>
  {f'<div class="review"><div class="label">Checked by Claude · {E(rev.get("status"))}</div><p>{E(rev.get("notes"))}</p></div>' if rev else ''}
  <details class="block"><summary>Reasoning</summary><p>{E(d.get("reasoning"))}</p></details>
  <section><h3>Findings and citations</h3><ol class="findings">{"".join(finding(f, i + 1, key) for i, f in enumerate(fs))}</ol></section>
  {matrix}
  {f'<section><h3>Could not be checked</h3><ul class="limits">{"".join(f"<li>{E(x)}</li>" for x in d.get("could_not_check") or [])}</ul></section>' if d.get('could_not_check') else ''}
  {f'<details class="block"><summary>{len(searches)} searches and counts that were run</summary><div class="scroll"><table><thead><tr><th>Command</th><th>Hits</th><th>What it showed</th></tr></thead><tbody>' + ''.join(f'<tr><td><code>{E(s.get("command"))}</code></td><td class="num">{E(s.get("hits"))}</td><td>{E(s.get("note"))}</td></tr>' for s in searches) + '</tbody></table></div></details>' if searches else ''}
</article>'''


def tally(rows):
    """A sweep that verified model labels: one verdict per flagged unit."""
    if not rows:
        return ''
    count = {}
    for r in rows:
        count[r.get('verdict')] = count.get(r.get('verdict'), 0) + 1
    return (f'<details class="block"><summary>Verdict on each of the {len(rows)} flagged sessions ('
            + E(', '.join(f'{n} {v}' for v, n in sorted(count.items(), key=lambda x: -x[1]))) + ')</summary><div class="scroll"><table><thead><tr>'
            '<th>Session</th><th>Agent</th><th>Verdict</th><th>Why</th></tr></thead><tbody>'
            + ''.join(f'<tr><td><code>{E(r.get("ref"))}</code></td><td>{E(r.get("agent"))}</td><td>{E(r.get("verdict"))}</td><td>{E(r.get("why"))}</td></tr>' for r in rows)
            + '</tbody></table></div></details>')


def precision(d):
    """How often each fixed expression matched what it was meant to, judged by hand on a sample."""
    if not d.get('precision'):
        return ''
    return ('<details class="block"><summary>How well each expression measures its target</summary><div class="scroll"><table><thead><tr>'
            '<th>Class</th><th>Correct in a hand-read sample</th><th>Expression</th></tr></thead><tbody>'
            + ''.join(f'<tr><td>{E(k)}</td><td>{E(v)}</td><td><code class="rx">{E((d.get("regex") or {}).get(k))}</code></td></tr>' for k, v in d['precision'].items())
            + '</tbody></table></div></details>')


def incidents(items):
    """Every incident the sweeps reported (findings with a title), as one index."""
    rows = [(k, i + 1, f) for k, d in items for i, f in enumerate(d.get('findings') or []) if f.get('title') and f.get('incident', True)]
    if not rows:
        return ''
    return (f'<section class="summary scroll" id="incidents"><table><thead><tr><th>#</th><th>Incident ({len(rows)} reported by the sweeps; the same event can appear in more than one sweep)</th>'
            '<th>Agents</th><th>Kind</th><th>Caught by</th></tr></thead><tbody>'
            + ''.join(f'<tr><td class="num">{n}</td><td><a href="#{E(k)}-{i}">{E(f["title"])}</a></td><td>{E(", ".join(f.get("agents") or []))}</td>'
                      f'<td>{E(f.get("category"))}</td><td>{E(f.get("caught_by"))}</td></tr>' for n, (k, i, f) in enumerate(rows, 1))
            + '</tbody></table></section>')


def matrix_table(rows):
    names = sorted({r['from'] for r in rows} | {r['to'] for r in rows})
    cell = {(r['from'], r['to']): r for r in rows}
    short = lambda n: n.replace('Claude ', '').replace('Gemini ', 'Gem ').replace('DeepSeek-V3.2', 'DeepSeek')

    def td(a, b):
        r = cell.get((a, b))
        if a == b:
            return '<td class="self"></td>'
        if not r:
            return '<td></td>'
        if not r.get('praise') and not r.get('criticism'):
            return f'<td class="zero" title="{E(a)} about {E(b)}: {r.get("mentions", 0)} mentions, no praise or criticism matched">·</td>'
        net = r.get('praise', 0) - r.get('criticism', 0)
        cls = 'pos' if net > 0 else 'neg' if net < 0 else 'zero'
        strength = min(4, 1 + abs(net) // 3)
        return (f'<td class="{cls} s{strength}" title="{E(a)} about {E(b)}: {r.get("mentions", 0)} mentions, {r.get("praise", 0)} praise, '
                f'{r.get("criticism", 0)} criticism, {r.get("request", 0)} requests, {r.get("deference", 0)} deference">'
                f'<b>+{r.get("praise", 0)}</b> <i>−{r.get("criticism", 0)}</i></td>')
    return ('<section><h3>Peer matrix: who says what about whom</h3><p class="note">Rows speak about columns. Each cell: messages with praise (+) and with criticism (−) '
            'counted by fixed regular expressions; green where praise outweighs criticism, red where criticism does. Pairs with fewer than 5 mentions are blank.</p>'
            '<div class="scroll"><table class="matrix"><thead><tr><th>speaker \\ about</th>' + ''.join(f'<th>{E(short(n))}</th>' for n in names) + '</tr></thead><tbody>' +
            ''.join(f'<tr><th>{E(short(a))}</th>' + ''.join(td(a, b) for b in names) + '</tr>' for a in names) + '</tbody></table></div></section>')


CSS = '''
/* Layout: a review dossier. A summary table first, then one card per question; a sticky index on wide screens. */
:root {
  --bg: #f3f5f4; --card: #ffffff; --fg: #1a2320; --muted: #5b6862; --line: #d9dfdb; --code: #edf1ee;
  --truth: #17795a; --truth-soft: #e1f2ea; --claim: #9a5a00; --claim-soft: #fbefd9; --interp: #55607c; --interp-soft: #e8eaf2;
  --bad: #b3361f; --bad-soft: #fbe9e5; --accent: #2b5f8e; --accent-soft: #e3edf6;
  --display: "Newsreader", Georgia, "Times New Roman", serif;
  --body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #111513; --card: #171d1a; --fg: #e2e8e4; --muted: #96a49d; --line: #2a332f; --code: #1d2421;
  --truth: #5cc79f; --truth-soft: #17302a; --claim: #e5a54f; --claim-soft: #33281a; --interp: #a5aecb; --interp-soft: #23273a;
  --bad: #f07f68; --bad-soft: #3a1f1a; --accent: #82b3e3; --accent-soft: #1b2a3a; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #111513; --card: #171d1a; --fg: #e2e8e4; --muted: #96a49d; --line: #2a332f; --code: #1d2421;
  --truth: #5cc79f; --truth-soft: #17302a; --claim: #e5a54f; --claim-soft: #33281a; --interp: #a5aecb; --interp-soft: #23273a;
  --bad: #f07f68; --bad-soft: #3a1f1a; --accent: #82b3e3; --accent-soft: #1b2a3a; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font: 15px/1.55 var(--body); overflow-wrap: break-word; }
.wrap { max-width: 1240px; margin: 0 auto; padding-inline: 20px; padding-block: 28px 80px; display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 32px; align-items: start; }
h1, h2, h3, h4 { font-family: var(--display); font-weight: 600; margin: 0; text-wrap: balance; }
h1 { font-size: clamp(28px, 4vw, 38px); line-height: 1.1; }
h2 { font-size: 22px; line-height: 1.25; }
h3 { font-size: 17px; margin-bottom: 8px; }
h4 { font-size: 16px; }
p { margin: 0; }
code, .ref { font-family: var(--mono); font-size: 12.5px; }
a { color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
nav { position: sticky; top: calc(env(safe-area-inset-top, 0px) + 16px); display: grid; gap: 14px; font-size: 13.5px; max-height: calc(100vh - 40px); overflow-y: auto; }
nav .g { font: 600 11px/1.3 var(--body); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-bottom: 4px; }
nav ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 3px; }
nav a { text-decoration: none; display: block; padding: 3px 0; line-height: 1.35; }
nav a:hover { text-decoration: underline; }
main { display: grid; grid-template-columns: minmax(0, 1fr); gap: 28px; min-width: 0; }
.intro { display: grid; gap: 12px; max-width: 78ch; }
.intro p { color: var(--muted); }
.legend { display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: 13.5px; color: var(--muted); align-items: center; }
.pill { display: inline-block; font: 600 10.5px/1 var(--body); letter-spacing: .04em; text-transform: uppercase; padding: 4px 7px; border-radius: 4px; white-space: nowrap; }
.pill.truth { color: var(--truth); background: var(--truth-soft); }
.pill.claim { color: var(--claim); background: var(--claim-soft); }
.pill.interp { color: var(--interp); background: var(--interp-soft); }
.controls { display: flex; flex-wrap: wrap; gap: 8px; }
.btn { font: 500 13px/1 var(--body); padding: 8px 12px; border-radius: 999px; border: 1px solid var(--line); background: var(--card); color: var(--fg); cursor: pointer; }
.btn[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--card); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th, td { text-align: left; padding: 8px 10px; border-top: 1px solid var(--line); vertical-align: top; }
thead th { font: 600 11px/1.3 var(--body); letter-spacing: .05em; text-transform: uppercase; color: var(--muted); border-top: 0; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.summary { background: var(--card); border: 1px solid var(--line); border-radius: 10px; }
.summary td:first-child { white-space: nowrap; }
.rx { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11.5px; }
.finding { scroll-margin-top: 16px; }
.summary .st { white-space: nowrap; font-variant-numeric: tabular-nums; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 22px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; min-width: 0; scroll-margin-top: 16px; }
.eyebrow, .label { font: 600 11px/1.3 var(--body); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.card header { display: grid; gap: 6px; }
.answer { border-left: 4px solid var(--accent); background: var(--accent-soft); border-radius: 0 8px 8px 0; padding: 12px 16px; display: grid; gap: 6px; }
.answer p { font-size: 15.5px; max-width: 82ch; }
.review { border-left: 4px solid var(--truth); background: var(--truth-soft); border-radius: 0 8px 8px 0; padding: 10px 16px; display: grid; gap: 4px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { font-size: 12.5px; padding: 4px 10px; border-radius: 8px; border: 1px solid var(--line); color: var(--muted); max-width: 100%; overflow-wrap: anywhere; }
.chip.conf-high, .chip.allok { color: var(--truth); border-color: var(--truth); }
.chip.conf-medium { color: var(--claim); border-color: var(--claim); }
.chip.conf-low, .chip.someBad { color: var(--bad); border-color: var(--bad); }
details.block > summary, details.cites > summary { cursor: pointer; font-weight: 500; font-size: 13.5px; color: var(--accent); }
details.block p { margin-top: 8px; max-width: 82ch; white-space: pre-wrap; }
.findings { list-style: none; margin: 0; padding: 0; display: grid; gap: 0; }
.finding { display: grid; gap: 8px; padding: 12px 0; border-top: 1px solid var(--line); min-width: 0; }
.finding:first-child { border-top: 0; padding-top: 0; }
.fhead { display: grid; grid-template-columns: 2em auto minmax(0, 1fr); gap: 8px; align-items: baseline; }
.num { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 12.5px; }
.claim { max-width: 82ch; }
.finding.has-bad .claim { text-decoration: underline wavy var(--bad); text-underline-offset: 4px; }
.cites { margin-left: 2em; }
.cites ul { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 8px; }
.chead { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; font-size: 12.5px; }
.field { color: var(--muted); }
.ok { color: var(--truth); }
.bad { color: var(--bad); font-weight: 600; }
blockquote { margin: 4px 0 0; padding: 8px 12px; background: var(--code); border-radius: 6px; font-family: var(--mono); font-size: 12.5px; white-space: pre-wrap; overflow-wrap: anywhere; }
.cite.fail blockquote { background: var(--bad-soft); }
.inc { margin-left: 2em; display: grid; gap: 6px; }
.inc .meta { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 13px; color: var(--muted); }
.inc .cat { color: var(--bad); font-weight: 600; }
.inc dl { display: grid; grid-template-columns: 8.5em minmax(0, 1fr); gap: 4px 12px; margin: 0; font-size: 14px; }
.inc dt { color: var(--muted); }
.inc dd { margin: 0; max-width: 76ch; }
.limits { margin: 0; padding-left: 1.2em; display: grid; gap: 4px; max-width: 82ch; }
.note { color: var(--muted); font-size: 13.5px; max-width: 82ch; margin-bottom: 8px; }
.matrix th, .matrix td { padding: 5px 6px; font-size: 11.5px; white-space: nowrap; text-align: center; }
.matrix tbody th { text-align: left; }
.matrix td b { font-weight: 600; color: var(--truth); } .matrix td i { font-style: normal; color: var(--bad); }
.matrix td.zero { color: var(--muted); } .matrix td.pos { background: var(--truth-soft); } .matrix td.neg { background: var(--bad-soft); } .matrix td.self { background: var(--code); }
body.only-bad .finding:not(.has-bad) { display: none; }
@media (max-width: 900px) { .wrap { grid-template-columns: minmax(0, 1fr); } nav { position: static; max-height: none; } .cites, .inc { margin-left: 0; } .inc dl { grid-template-columns: 1fr; } }
'''

JS = '''
document.addEventListener('click', function (e) {
  var b = e.target.closest('.btn'); if (!b) return;
  var on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', on ? 'true' : 'false');
  if (b.id === 'b-bad') document.body.classList.toggle('only-bad', on);
  if (b.id === 'b-open') document.querySelectorAll('details.cites').forEach(function (d) { d.open = on; });
});
'''


def main():
    out, items = sys.argv[1], []
    for arg in sys.argv[2:]:
        group, path = arg.split('=', 1)
        d = json.loads(Path(path).read_text())
        d['_group'] = group
        items.append((Path(path).stem, d))
    groups = list(dict.fromkeys(d['_group'] for _, d in items))
    total = [c for _, d in items for f in d.get('findings') or [] for c in f.get('citations') or []]
    ok = sum(bool(c.get('quote_ok')) for c in total)
    nav = ''.join(f'<div><div class="g">{E(g)}</div><ul>' + ''.join(f'<li><a href="#{E(k)}">{E(short_q(d))}</a></li>' for k, d in items if d['_group'] == g) + '</ul></div>'
                  for g in groups)
    rows = ''.join(f'<tr><td><a href="#{E(k)}">{E(k)}</a></td><td>{E(short_q(d, 150))}</td><td>{E(first_sentence(d.get("answer")))}</td>'
                   f'<td class="st">{sum(bool(c.get("quote_ok")) for f in d.get("findings") or [] for c in f.get("citations") or [])} / '
                   f'{sum(len(f.get("citations") or []) for f in d.get("findings") or [])}</td><td>{E(((d.get("confidence") or "").replace(":", " ").replace(",", " ").split() or [""])[0])}</td></tr>'
                   for k, d in items)
    page = f'''<title>Village Ground Truth Review</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,500;6..72,600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<nav aria-label="Questions">{nav}</nav>
<main>
  <header class="intro">
    <div class="eyebrow">AI Village · “Perform novel research!” · 11–15 May 2026 · 15 agents</div>
    <h1>Village Ground Truth Review</h1>
    <p>{len(items)} questions answered from the raw records, for your review. Every finding cites the record it rests on with an exact quote, and code checked each quote against the database: {ok} of {len(total)} were found in the cited record. Open any ref with <code>village show REF</code>.</p>
    <div class="legend"><span><span class="pill truth">ground truth</span> recorded by the system: commands, outputs, errors, events</span>
      <span><span class="pill claim">claim</span> an agent's own words: chat, reasoning, intent, memory</span>
      <span><span class="pill interp">interpretation</span> the investigator's reading of the records</span></div>
    <div class="controls"><button class="btn" id="b-open" aria-pressed="false">Open all citations</button>
      <button class="btn" id="b-bad" aria-pressed="false">Show only findings with an unverified quote</button></div>
  </header>
  <section class="summary scroll"><table><thead><tr><th>Id</th><th>Question</th><th>Answer in one line</th><th>Quotes found</th><th>Confidence</th></tr></thead><tbody>{rows}</tbody></table></section>
  {incidents(items)}
  {"".join(card(k, d) for k, d in items)}
</main></div>
<script>{JS}</script>'''
    Path(out).write_text(page)
    print(f'{out}: {len(items)} questions, {ok} of {len(total)} citations verified, {len(page):,} bytes')


def short_q(d, n=70):
    q = ' '.join((d.get('question') or '').split())
    return q if len(q) <= n else q[:n - 1] + '…'


def first_sentence(s, n=260):
    s = ' '.join((s or '').split())
    cut = s.find('. ')
    return s[:cut + 1] if 0 < cut < n else s if len(s) <= n else s[:n].rsplit(' ', 1)[0] + ' …'


if __name__ == '__main__':
    main()
