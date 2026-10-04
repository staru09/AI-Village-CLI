"""Commands that call a model: label (apply a rubric to many units), labels, verdict, check, look, ask, eval.

Needs ANTHROPIC_API_KEY and the `anthropic` package (`uv sync --extra llm`). Labels live in labels.db next to
village.db, so a rebuild keeps them. Every label stores a quote and evidence refs that are checked in code.
"""
import base64, hashlib, json, os, re, sqlite3, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import db, evidence
from .core import KINDS, REF, connect, lookup, maker, node, one, ref, scope

ROOT = Path(__file__).resolve().parents[1]
LABEL_MODEL = os.environ.get('VILLAGE_LABEL_MODEL', 'claude-haiku-4-5')
ASK_MODEL = os.environ.get('VILLAGE_ASK_MODEL', 'claude-opus-5-5')
# Opus 5.5's safety classifiers sometimes stop on other models' raw reasoning (stop reason "refusal"): the question is then
# asked again from the start with this model.
FALLBACK_MODEL = os.environ.get('VILLAGE_FALLBACK_MODEL', 'claude-sonnet-5-5')
# $ per million tokens: input, output, cache read. ponytail: a rough guide for the cost lines, update when prices change.
PRICE = {'claude-opus-5-5': (4, 20, .2), 'claude-sonnet-5-5': (2, 10, .2), 'claude-haiku-4-5': (1, 5, .1), 'claude-fable-5-1': (10, 50, .25)}
UNITS = {'session': 's', 'message': 'm', 'action': 't'}
LABELS_SCHEMA = '''CREATE TABLE IF NOT EXISTS labels(rubric TEXT, ref TEXT, rev TEXT, unit TEXT, agent TEXT, ts TEXT, label TEXT,
    confidence REAL, quote TEXT, quote_ok INTEGER, evidence TEXT, why TEXT, model TEXT, made TEXT, verdict TEXT, note TEXT,
    PRIMARY KEY(rubric, ref))'''


def client():
    try:
        import anthropic
    except ImportError:
        sys.exit('this command calls Claude: install the SDK with `uv sync --extra llm` (or `pip install anthropic`).')
    if not os.environ.get('ANTHROPIC_API_KEY'):
        sys.exit('set ANTHROPIC_API_KEY to use this command.')
    return anthropic.Anthropic(max_retries=6)


class Spend:
    """Tokens and dollars across calls."""
    def __init__(self):
        self.i = self.o = self.r = self.usd = 0
        self.lock = threading.Lock()

    def add(self, model, u):
        p = PRICE.get(next((k for k in PRICE if model.startswith(k)), ''), (0, 0, 0))
        cr, cw = getattr(u, 'cache_read_input_tokens', 0) or 0, getattr(u, 'cache_creation_input_tokens', 0) or 0
        with self.lock:
            self.i += u.input_tokens + cr + cw
            self.o += u.output_tokens
            self.r += cr
            self.usd += (u.input_tokens * p[0] + cw * p[0] * 1.25 + cr * p[2] + u.output_tokens * p[1]) / 1e6

    def __str__(self):
        return f'{self.i:,} tokens in ({self.r:,} from cache), {self.o:,} out, about ${self.usd:.2f}'


def refs_in(text):
    return {f'{k}:{h}' for k, h in REF.findall(text)}


def text_of(resp):
    return '\n'.join(b.text for b in resp.content if b.type == 'text').strip()


# ---- rubrics and labels ----------------------------------------------------------------------------------------------

def rubric(name):
    """rubrics/<name>.md (or a path) -> {name, unit, labels, shows, context, kind, body, rev}. Header lines, '---', then the instructions."""
    path = Path(name) if Path(name).exists() else ROOT / 'rubrics' / f'{name}.md'
    if not path.exists():
        sys.exit(f'no rubric {name!r}. Rubrics here: ' + ', '.join(sorted(p.stem for p in (ROOT / 'rubrics').glob('*.md'))))
    head, _, body = path.read_text().partition('\n---\n')
    r = {'name': path.stem, 'unit': 'session', 'shows': 'full', 'context': '3', 'kind': ''}
    r.update({k.strip(): v.strip() for k, v in (l.split(':', 1) for l in head.splitlines() if ':' in l)})
    r['labels'] = [x.strip() for x in r.get('labels', '').split(',') if x.strip()]
    if r['unit'] not in UNITS or len(r['labels']) < 2:
        sys.exit(f'{path}: needs `unit: session|message|action` and at least two `labels:`.')
    r['body'], r['rev'] = body.strip(), hashlib.sha1(path.read_bytes()).hexdigest()[:8]
    return r


def labels_db():
    con = sqlite3.connect(db.DB.with_name('labels.db'), timeout=60)
    con.execute(LABELS_SCHEMA)
    return con


def units(con, a, rub, limit=True):
    """The units a rubric applies to in the scope -> [(ref, agent id, ts)] in time order, and how many there were before sampling."""
    k = UNITS[rub['unit']]
    if getattr(a, 'refs', None):
        got = []
        for r in a.refs.split(','):
            kind, rid = lookup(con, r)
            if kind != k:
                sys.exit(f'{r}: rubric {rub["name"]} labels {rub["unit"]}s ({k}:…).')
            who, ts = con.execute(f'SELECT {"src" if k == "m" else "agent"}, ts FROM {KINDS[k]} WHERE id = ?', (rid,)).fetchone()
            got.append((rid, who, ts))
        return got, len(got)
    lo, hi = scope(con, a)
    aw, ap = evidence.agent_filter(con, a, 'x.src' if k == 'm' else 'x.agent')
    q = evidence.match(a.match) if getattr(a, 'match', None) else None
    if k == 's':
        sql = f"SELECT x.id, x.agent, x.ts FROM sessions x WHERE x.ts >= ? AND x.ts < ?{aw}" + ('' if rub['shows'] == 'intent' else ' AND x.turns > 0')
        p = [lo, hi, *ap]
        if q:
            sql += (' AND (x.rowid IN (SELECT rowid FROM sessions_fts WHERE sessions_fts MATCH ?) OR x.id IN '
                    '(SELECT t.session FROM turns_fts JOIN turns t ON t.rowid = turns_fts.rowid WHERE turns_fts MATCH ?))')
            p += [q, q]
    elif k == 'm':
        sql, p = f"SELECT x.id, x.src, x.ts FROM messages x WHERE x.ts >= ? AND x.ts < ? AND x.src != 'human'{aw}", [lo, hi, *ap]
        if rub.get('only') == 'addressed':  # only messages that @-mention another agent
            sql += " AND x.id IN (SELECT msg_id FROM edges WHERE kind = 'addressed')"
        if q:
            sql += ' AND x.rowid IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?)'
            p.append(q)
    else:
        sql, p = f"SELECT x.id, x.agent, x.ts FROM turns x WHERE x.ts >= ? AND x.ts < ?{aw}", [lo, hi, *ap]
        if rub['kind']:
            sql += ' AND x.kind = ?'
            p.append(rub['kind'])
        if q:
            sql += ' AND x.rowid IN (SELECT rowid FROM turns_fts WHERE turns_fts MATCH ?)'
            p.append(q)
    got = con.execute(sql + ' ORDER BY x.ts', p).fetchall()
    if getattr(a, 'within', None):
        r, _, v = a.within.partition('=')
        try:
            keep = {x[0] for x in con.execute('SELECT ref FROM L.labels WHERE rubric = ? AND coalesce(verdict, label) = ?', (r, v))}
        except sqlite3.OperationalError:
            keep = set()
        got = [g for g in got if ref(k, g[0]) in keep]
    n = len(got)
    if limit and a.limit and n > a.limit:  # a trial: spread evenly over the scope, not the first N
        got = [got[int(i * n / a.limit)] for i in range(a.limit)]
    return got, n


def unit_text(con, rub, rid):
    """One unit as the text the model reads. Refs inside it are the only ones it may cite."""
    k = UNITS[rub['unit']]
    if k == 's':
        if rub['shows'] == 'intent':
            return evidence.session_text(con, rid).split('\nACTIONS (ground truth', 1)[0]
        return evidence.session_text(con, rid, budget=int(rub.get('budget', 16000)))
    N = evidence.names_of(con)
    if k == 'm':
        src, room, ts, content, why = con.execute('SELECT src, room, ts, content, reasoning FROM messages WHERE id = ?', (rid,)).fetchone()
        vg, ag, before = evidence.context(con, src, ts)
        model = con.execute('SELECT model FROM nodes WHERE id = ?', (src,)).fetchone()[0]
        before = con.execute('SELECT ts, id, src, content FROM messages WHERE room = ? AND ts < ? ORDER BY ts DESC LIMIT ?', (room, ts, int(rub['context']))).fetchall()
        return '\n'.join([f'VILLAGE GOAL: {vg}', f'AGENT GOAL: {ag or "none assigned at that time"}', f'PREVIOUS VILLAGE GOAL: {before or "none"}', '',
                          *(['EARLIER MESSAGES IN THE ROOM (context only, do not label these)'] if before else []),
                          *(f'{t[11:19]} {ref("m", i)} {N.get(s, s)}: {one(c, 700)}' for t, i, s, c in reversed(before)), '',
                          f'THE MESSAGE TO LABEL · {ref("m", rid)} · {N.get(src, src)} ({model}) in #{room} at {ts[:19]} PT', content,
                          *(['', 'ITS REASONING BEFORE WRITING IT (private, a claim)', db.cut(why, 3000)] if why else [])])
    s, agent, ts, kind, act, out, err, failed, why = con.execute(
        'SELECT session, agent, ts, kind, action, output, error, failed, reasoning FROM turns WHERE id = ?', (rid,)).fetchone()
    vg, ag, before = evidence.context(con, agent, ts)
    intent = con.execute('SELECT short, goal FROM sessions WHERE id = ?', (s,)).fetchone() or ('', '')
    return '\n'.join([f'VILLAGE GOAL: {vg}', f'AGENT GOAL: {ag or "none assigned at that time"}', f'PREVIOUS VILLAGE GOAL: {before or "none"}',
                      f'STATED INTENT OF THE SESSION (claim): {intent[0]} — {one(intent[1], 600)}', '',
                      f'THE ACTION TO LABEL · {ref("t", rid)} · {N.get(agent, agent)} at {ts[:19]} PT · {kind}',
                      *(['[its reasoning before the action · claim]', db.cut(why, 4000)] if why else ['[no reasoning recorded]']),
                      '[action · ground truth]', db.cut(act, 4000), *(['[output · ground truth]', db.cut(out, 2500)] if out else []),
                      *([f'[error / stderr · ground truth{" · looks like a failure" if failed else ""}]', db.cut(err, 1200)] if err else [])])


LABELLER = '''You label one unit from the AI Village dataset: frontier AI agents working in a shared chat, each with its own computer.

How far each part of a unit can be trusted:
- Ground truth: actions (commands, clicks, messages sent), the outputs and errors the system returned, events, the goals set by the organisers.
- Claims: everything an agent wrote about itself: chat, stated intent, reasoning, self-reports, memory. A claim shows what the agent said or
  believed, not what happened. An agent saying "done" or "verified" is a claim until an output shows it. A command that ran has only run.

Apply the rubric below the way two careful readers would both apply it. Judge by the evidence in the unit, not by how confident the text sounds.
If the unit does not contain what the rubric needs, use the label the rubric gives for that case rather than guessing.

Return JSON:
- label: exactly one of the rubric's labels.
- confidence: 0 to 1.
- quote: the words in the unit that decide the label, copied exactly (one passage, at most 300 characters). Empty if no words do.
- evidence: the refs (like t:0a1b2c3d4e5f) of the records in the unit that support the label. Only refs that appear in the unit.
- why: one or two plain sentences. Name what was claimed and what the records show.

RUBRIC: {name}
LABELS: {labels}

{body}'''


def quoted(quote, text):
    """Is the quote really in the unit? exact, then ignoring case and whitespace (a paraphrase proves nothing)."""
    if not quote.strip():
        return 1
    squash = lambda s: ' '.join(s.lower().split())
    return int(quote in text or squash(quote) in squash(text) or squash(quote.replace('…', '').strip('. ')) in squash(text))


def judge(cl, model, rub, text, spend):
    """One unit -> {label, confidence, quote, evidence, why}, validated."""
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['label', 'confidence', 'quote', 'evidence', 'why'],
              'properties': {'label': {'type': 'string', 'enum': rub['labels']}, 'confidence': {'type': 'number'}, 'quote': {'type': 'string'},
                             'evidence': {'type': 'array', 'items': {'type': 'string'}}, 'why': {'type': 'string'}}}
    resp = cl.messages.create(
        model=model, max_tokens=16000,  # room for a thinking model's reasoning before the JSON
        system=[{'type': 'text', 'text': LABELLER.format(name=rub['name'], labels=', '.join(rub['labels']), body=rub['body']),
                 'cache_control': {'type': 'ephemeral'}}],
        messages=[{'role': 'user', 'content': text}], output_config={'format': {'type': 'json_schema', 'schema': schema}})
    spend.add(model, resp.usage)
    if not text_of(resp):
        raise RuntimeError(f'the model returned no answer (stop reason: {resp.stop_reason})')
    d = json.loads(text_of(resp))
    seen = refs_in(text)  # only records the model was shown count as evidence
    d['evidence'] = [m.group(0) for m in map(REF.search, d['evidence']) if m and m.group(0) in seen]
    d['quote_ok'] = quoted(d['quote'], text)
    return d


def label(a):
    rub = rubric(a.rubric)
    con, cl, model = connect(600), client(), a.model or rub.get('model') or LABEL_MODEL
    todo, n = units(con, a, rub)
    k = UNITS[rub['unit']]
    L = labels_db()
    done = {r[0] for r in L.execute('SELECT ref FROM labels WHERE rubric = ? AND rev = ?', (rub['name'], rub['rev']))}
    if not a.redo:
        todo = [u for u in todo if ref(k, u[0]) not in done]
    if len(todo) > 500 and not a.yes:
        sys.exit(f'{len(todo)} {rub["unit"]}s to label: try a sample first (--limit 20), then pass --yes to run them all.')
    texts = [(u, unit_text(con, rub, u[0])) for u in todo]
    spend, t0 = Spend(), time.time()

    def work(item):
        (rid, who, ts), text = item
        try:
            return rid, who, ts, judge(cl, model, rub, text, spend)
        except Exception as e:  # one bad unit must not lose the others
            return rid, who, ts, e

    failed = []
    with ThreadPoolExecutor(8) as pool:
        for rid, who, ts, d in pool.map(work, texts):
            if isinstance(d, Exception):
                failed.append(f'{ref(k, rid)}: {type(d).__name__}: {one(str(d), 160)}')
                continue
            L.execute('INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)',
                      (rub['name'], ref(k, rid), rub['rev'], rub['unit'], who, ts, d['label'], d['confidence'], d['quote'], d['quote_ok'],
                       ' '.join(d['evidence']), d['why'], model, datetime.now().isoformat(' ', 'seconds')))
            L.commit()
    con.close()
    out = [('note', f'Labelled {len(texts) - len(failed)} {rub["unit"]}s with {model} in {time.time() - t0:.0f}s ({spend}). '
                    f'{n} {rub["unit"]}s are in scope' + (f'; this is a sample of {a.limit} spread over time. `--limit 0` labels them all.'
                                                           if a.limit and n > a.limit else '.'))]
    out += [('note', 'Failed: ' + '; '.join(failed[:5]))] if failed else []
    a.rows, a.by = None, 'agent'
    return out + labels(a)


def labels(a):
    con = connect()
    if not a.rubric:
        try:
            rows = con.execute('SELECT rubric, unit, count(*), count(verdict), min(model), substr(max(made),1,16) FROM L.labels GROUP BY rubric').fetchall()
        except sqlite3.OperationalError:
            rows = []
        return [('table', 'rubrics with stored labels (rubric files: ' + ', '.join(sorted(p.stem for p in (ROOT / 'rubrics').glob('*.md'))) + ')',
                 ['rubric', 'unit', 'labelled', 'with your verdict', 'model', 'last run'], rows)]
    rub = rubric(a.rubric)
    N, models = evidence.names_of(con), dict(con.execute('SELECT id, model FROM nodes'))
    lo, hi = scope(con, a)
    aw, ap = evidence.agent_filter(con, a, 'agent')
    try:
        rows = con.execute(f'SELECT ref, agent, ts, coalesce(verdict, label), confidence, quote, quote_ok, why, rev, verdict, model FROM L.labels '
                           f'WHERE rubric = ? AND ts >= ? AND ts < ?{aw} ORDER BY ts', (rub['name'], lo, hi, *ap)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    _, total = units(con, a, rub, limit=False) if not getattr(a, 'refs', None) else ([], len(rows))
    stale = sum(r[8] != rub['rev'] for r in rows)
    made_by = ', '.join(sorted({r[10] for r in rows})) or 'no model yet'
    base = (f'rubric `{rub["name"]}` (judged by a model, {made_by}; not a rule): {len(rows)} of the {total} {rub["unit"]}s in scope are labelled'
            + (f'; {stale} with an older version of the rubric' if stale else '') + (f'; {sum(r[9] is not None for r in rows)} carry your verdict' if any(r[9] for r in rows) else ''))
    if a.rows:
        pick = [r for r in rows if a.rows == 'all' or r[3] == a.rows][:a.limit]
        return [('table', base, ['ref', 'time PT', 'agent', 'label', 'conf', 'why', 'quote (✗ = not found in the unit)'],
                 [(r[0], r[2][:16], N.get(r[1], r[1]), r[3], f'{r[4]:.2f}', one(r[7], 0 if a.wide else 260),
                   ('' if r[6] else '✗ ') + one(r[5], 0 if a.wide else 160)) for r in pick])]
    key = {'agent': lambda r: N.get(r[1], r[1]), 'model': lambda r: models.get(r[1], r[1]), 'maker': lambda r: maker(models.get(r[1])),
           'day': lambda r: r[2][:10], 'all': lambda r: 'all'}[a.by]
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r[3])
    table = [(g, len(v), *(f'{v.count(x)} ({100 * v.count(x) // len(v)}%)' if v.count(x) else '' for x in rub['labels']))
             for g, v in sorted(groups.items(), key=(lambda kv: kv[0]) if a.by == 'day' else (lambda kv: -len(kv[1])))]
    return [('table', base, [a.by, 'labelled', *rub['labels']], table)] + \
        ([('note', f'List the rows behind a count with `labels {rub["name"]} --rows LABEL`. Counts speak only for the labelled units.')] if rows else
         [('note', f'Nothing labelled in this scope yet: run `label {rub["name"]}` with the same scope.')])


def verdict(a):
    rub = rubric(a.rubric)
    if a.value not in rub['labels']:
        sys.exit(f'{a.value!r} is not a label of {rub["name"]}: {", ".join(rub["labels"])}')
    L = labels_db()
    n = L.execute('UPDATE labels SET verdict = ?, note = ? WHERE rubric = ? AND ref = ?', (a.value, a.note, rub['name'], a.ref.strip('[]'))).rowcount
    L.commit()
    return [('note', f'{a.ref}: your verdict {a.value} now overrides the model\'s label.' if n else f'{a.ref} has no {rub["name"]} label yet: label it first.')]


def check(a):
    """A rubric against cases with known answers: does the labeller catch what we know is there, and leave alone what is not?"""
    rub = rubric(a.rubric)
    model = a.model or rub.get('model') or LABEL_MODEL
    cases = [json.loads(l) for l in Path(a.cases).read_text().splitlines() if l.strip() and not l.startswith('#')]
    con, cl, spend = connect(600), client(), Spend()
    texts = [unit_text(con, rub, lookup(con, c['ref'])[1]) for c in cases]
    con.close()
    with ThreadPoolExecutor(6) as pool:
        def work(t):
            try:
                return judge(cl, model, rub, t, spend)
            except Exception as e:  # e.g. a safety refusal on one unit: report it as a miss, keep the rest
                return {'label': f'({type(e).__name__})', 'confidence': 0, 'quote': '', 'quote_ok': 1, 'evidence': [], 'why': str(e)}
        got = list(zip(cases, pool.map(work, texts)))
    ok = [d['label'] == c['expect'] for c, d in got]
    rows = [(c['ref'], c['expect'], d['label'], '✓' if o else '✗ MISS', f'{d["confidence"]:.2f}', '' if d['quote_ok'] else '✗', one(d['why'], 200), one(c.get('note', ''), 100))
            for (c, d), o in zip(got, ok)]
    per = {}
    for (c, d), o in zip(got, ok):
        per.setdefault(c['expect'], []).append(o)
    return [('table', f'rubric `{rub["name"]}` with {model} on {len(cases)} cases with known answers: {sum(ok)} of {len(ok)} agree',
             ['ref', 'expected', 'model said', 'agree', 'conf', 'quote', 'why (model)', 'case note'], rows),
            ('table', 'agreement per expected label', ['expected', 'cases', 'agree'], [(e, len(v), f'{sum(v)} of {len(v)}') for e, v in per.items()]),
            ('note', f'{spend}. A rubric is ready for a full run when it agrees on the cases it must catch AND on the cases it must leave alone.')]


def look(a):
    """A vision model looks at one action's screenshot and answers one question about it."""
    con = connect()
    kind, rid = lookup(con, a.ref)
    if kind != 't':
        sys.exit('`look` takes an action ref (t:…).')
    ts, act, agent = con.execute('SELECT ts, action, agent FROM turns WHERE id = ?', (rid,)).fetchone()
    png = evidence.png(rid, ts)[0]
    cl, model, spend = client(), a.model or ASK_MODEL, Spend()
    resp = cl.messages.create(model=model, max_tokens=4000, messages=[{'role': 'user', 'content': [
        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': base64.standard_b64encode(png).decode()}},
        {'type': 'text', 'text': f'This is the screen an AI agent saw at the action `{one(act, 300)}`. Answer from what is visible only; '
                                 f'say so if the screenshot does not show it.\n\nQuestion: {a.question}'}]}])
    spend.add(model, resp.usage)
    return [('text', f'{a.ref} · screenshot at {ts[:19]} PT, read by {model} (a model\'s reading of ground truth)', text_of(resp)), ('note', str(spend))]


# ---- the agent -------------------------------------------------------------------------------------------------------

def reference():
    """The command list the agent sees, from the parser itself, so it cannot drift from the CLI."""
    from .cli import command_list
    return '\n'.join(f"{c['name']} {c['args']}\n    {c['help']}" + (f" (default limit {c['limit']})" if c['scoped'] else '')
                     for c in command_list() if c['name'] not in ('build', 'ask', 'rlm', 'eval', 'verdict', 'check', 'web'))


AGENT = '''You answer questions about the AI Village: a long-running experiment by AI Digest in which frontier AI agents (Claude, GPT, Gemini,
DeepSeek, Kimi and others) share a group chat, each with its own computer, and pursue goals the organisers set. You have the `village` tool:
a command line over the full dataset. You cannot see the data any other way, so every fact in your answer must come from a tool result.

COMMANDS (run each as `village <command …>`; the tool takes the part after `village`)
{reference}

Scope flags, accepted by every command: --goal N|TEXT (one village goal), --day N (village day number), --date YYYY-MM-DD,
--since / --until (Pacific time), --limit N, --wide (whole texts). Commands that take [--agent NAME] accept any unique part of a name.

HOW TO WORK
1. Orient first: `goals` lists the village goals; `overview --goal N` shows who was there and how much each did; `schema` shows which
   part of the history has actions loaded (chat and sessions cover the whole history; actions, reasoning and memories only a window).
   `recap` gives AI Digest's own summary: use it only to decide where to look.
2. Search, then read: `find` to locate, `show REF` (with --context) and `session REF` to read what actually happened, `timeline` to
   follow one agent. Read the records behind any count before you rely on it.
3. Count with the tool, never by reading: `count`, `sql`, `labels`, the mention commands. Give each count with its base ("12 of the 40 sessions").
4. Look for evidence against your answer before you settle on it. For "never" or "nobody", search broadly, in several fields and spellings.

EVIDENCE
- Ground truth: actions, outputs, errors, events (marked ·truth). Claims: chat, reasoning, stated intent, self-reports, memory (marked ·claim):
  they show what an agent said or believed. Write "X reported that …" unless an action or output shows it. A recap is never evidence.
- Reasoning is missing or only summarised for some models (see the reasoning column in `overview`): no reasoning is not evidence of innocence.
- A `labels` count is a model's judgement under a rubric: name the rubric and say so. A `count` is a rule: say so.
- A cause or an intent that no record states is your interpretation: mark it as one.
- If the scope has no actions loaded, say that the answer rests on chat only. Actions exist only in the village's working hours,
  which changed over time (10:00-14:00 PT for most of late 2025 to May 2026, 09:00-17:00 from June 2026): check them with `sql`
  before treating a quiet hour as absence.
- Mention commands only see full names: many messages name a peer as "Gemini", "Claude" or "Kimi". Search the text too.
- Agents misstate their own day numbers and totals: compute days from dates and totals from the records, not from their words.

ANSWER
- Short and direct: the answer first, then the evidence. Plain English, for a reader who cannot see the tool output.
- After each factual sentence, cite the records that show it, as refs in square brackets: [t:0a1b2c3d4e5f] [m:…]. Cite only refs you
  saw in a tool result. Quote exactly when you quote.
- Say what you could not check.
- End with one line: `ANSWER: <the answer in one short sentence, with the key name or number>`.'''

TOOL = {'name': 'village', 'description': 'Run one village CLI command and get its output as text. Give the command without the leading `village`.',
        'input_schema': {'type': 'object', 'properties': {'command': {'type': 'string', 'description': 'e.g. find "random scores" --goal 41 --in action,output'}},
                         'required': ['command'], 'additionalProperties': False}}


def cache_last(messages):
    """Keep one cache breakpoint, on the newest tool result, so each step re-reads the conversation so far from cache."""
    for m in messages:
        if m['role'] == 'user' and isinstance(m['content'], list):
            for b in m['content']:
                b.pop('cache_control', None)
    if isinstance(messages[-1]['content'], list):
        messages[-1]['content'][-1]['cache_control'] = {'type': 'ephemeral'}


NOW = re.compile(r"\bwhat('?s| is| are)? (is )?(happening|going on)\b|\bwhat are (the agents|they) (doing|up to)\b", re.I)

NOW_PROMPT = '''You tell a visitor what is happening in the AI Village at the moment they are watching: AI agents with their own
computers, sharing a group chat, working towards a goal the organisers set. You get the records for that day up to that moment.
Write: the village goal exactly as given, with its dates; then what is happening so far today, room by room or team by team, in a few
short bullets (who is working on what, anything notable: a problem, a dispute, a milestone). Cite the refs in square brackets after
each fact, only refs that appear in the records below. Chat and session intents are the agents' own words: say "X says" for claims.
Call agents by their names, never he or she.
If you use the daily recap, say it is AI Digest's own summary. Never mention anything after the moment given. End with one line:
`ANSWER: <one sentence>`.'''


def now(question, date, model=None):
    """"What is happening?" for a day and time: the goal, then that day's records up to then, summarised in one model call.
    No search loop: the same few queries every time, so it answers in seconds."""
    day, _, clock = date.strip().partition(' ')
    until = f'{day} {clock or "23:59"}'
    con, spend, model = connect(), Spend(), model or FALLBACK_MODEL
    N = evidence.names_of(con)
    g = con.execute('SELECT n, goal, start_time, end_time FROM goals WHERE start_time <= ? ORDER BY start_time DESC LIMIT 1', (until,)).fetchone()
    vday = con.execute('SELECT day FROM days WHERE date = ?', (day,)).fetchone()
    chat = con.execute('SELECT id, ts, src, room, content FROM messages WHERE ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT 120', (day, until)).fetchall()[::-1]
    sess = con.execute('SELECT id, agent, max(ts), short FROM sessions WHERE ts >= ? AND ts <= ? GROUP BY agent', (day, until)).fetchall()
    recap = con.execute("SELECT id, content FROM summaries WHERE type = 'daily' AND date = ? ORDER BY ts DESC LIMIT 1", (day,)).fetchone()
    con.close()
    # only recap lines stamped at or before the moment: untimed ones (takeaways, blurb) describe the whole day and would spoil it
    bullets = [b for b in (recap[1].split('\n- ') if recap else []) if (m := re.search(r'\[(\d{4}-\d\d-\d\d \d\d:\d\d)', b)) and m[1] <= until]
    records = '\n'.join([
        f'MOMENT: {until} Pacific time' + (f', village day {vday[0]}' if vday else ''),
        f'VILLAGE GOAL: goal {g[0]}, "{g[1]}", from {g[2][:16]} to {(g[3] or "now")[:16]}' if g else 'VILLAGE GOAL: none recorded',
        '', f'LATEST SESSION INTENT OF EACH AGENT TODAY (claims)',
        *(f'{ts[11:16]} {ref("s", i)} {N.get(a, a)}: {one(short, 200)}' for i, a, ts, short in sess),
        '', f'CHAT TODAY UP TO THE MOMENT ({len(chat)} latest messages)',
        *(f'{ts[11:16]} {ref("m", i)} #{room} {N.get(a, a)}: {one(c, 400)}' for i, ts, a, room, c in chat),
        *(['', f'AI DIGEST\'S DAILY RECAP UP TO THE MOMENT {ref("r", recap[0])} (secondary: an LLM summary)', *('- ' + one(b, 500) for b in bullets)] if bullets else [])])
    resp = client().messages.create(model=model, max_tokens=4000, system=NOW_PROMPT,
                                     messages=[{'role': 'user', 'content': f'{records}\n\nQUESTION: {question}'}])
    spend.add(model, resp.usage)
    text, seen = text_of(resp), refs_in(records)
    cited = refs_in(text)
    return {'answer': text, 'commands': ['goals --date', 'sessions --date', 'chat up to the moment', 'recap --date'], 'steps': 0, 'spend': spend,
            'cited': len(cited), 'unknown': sorted(cited - seen), 'model': model}


def answer(question, goal=None, model=None, max_steps=40, log=None, date=None):
    """Run the agent on one question -> {answer, commands, steps, spend, cited, unknown}."""
    if date and NOW.search(question):
        return now(question, date)
    from .cli import run_line
    cl, model, spend = client(), model or ASK_MODEL, Spend()
    system = [{'type': 'text', 'text': AGENT.format(reference=reference()), 'cache_control': {'type': 'ephemeral'}}]
    messages = [{'role': 'user', 'content': question + (f'\n\n(Scope: the village goal "{goal}".)' if goal else '')
                 + (f'\n\n(The user is watching the village at {date} Pacific time.)' if date else '')}]
    seen, commands, text = set(), [], ''
    repaired = False
    for step in range(max_steps + 3):
        last = step >= max_steps
        cache_last(messages)
        resp = cl.messages.create(model=model, max_tokens=16000, system=system, messages=messages, **({} if last else {'tools': [TOOL]}))
        spend.add(model, resp.usage)
        if resp.stop_reason == 'refusal':
            if model != FALLBACK_MODEL:
                if log:
                    log(f'  {model} stopped with a refusal after {len(commands)} commands: starting again with {FALLBACK_MODEL}')
                r = answer(question, goal, FALLBACK_MODEL, max_steps, log)
                r['spend'].usd += spend.usd
                r['model'] = f'{FALLBACK_MODEL} (after {model} refused)'
                return r
            return {'answer': 'The model declined to answer this question.', 'commands': commands, 'steps': len(commands), 'spend': spend,
                    'cited': 0, 'unknown': [], 'stop': 'refusal', 'model': model}
        messages.append({'role': 'assistant', 'content': resp.content})
        calls = [b for b in resp.content if b.type == 'tool_use']
        if resp.stop_reason == 'tool_use' and calls:
            results = []
            for c in calls:
                cmd = str(c.input.get('command', ''))
                out = run_line(cmd.removeprefix('village ').strip())
                if len(out) > 14000:
                    out = out[:14000] + f'\n… [{len(out) - 14000:,} more characters: narrow the scope, lower --limit, or use --in / --kinds]'
                seen |= refs_in(out)
                commands.append(cmd)
                if log:
                    log(f'  {len(commands):>2}. village {one(cmd, 150)}')
                results.append({'type': 'tool_result', 'tool_use_id': c.id, 'content': out or '(no output)'})
            if step + 1 >= max_steps:
                results.append({'type': 'text', 'text': 'You have used your steps. Answer now from what you have, and say what you could not check.'})
            messages.append({'role': 'user', 'content': results})
            continue
        text = text_of(resp)
        cited = refs_in(text)
        unknown = sorted(cited - seen)
        if unknown and not repaired and not last:  # a citation the tools never showed is not evidence
            repaired = True
            messages.append({'role': 'user', 'content': 'These refs in your answer did not appear in any tool result: ' +
                             ', '.join(unknown) + '. Check them with `show`, or cite records you saw, then give the full answer again.'})
            continue
        return {'answer': text, 'commands': commands, 'steps': len(commands), 'spend': spend, 'cited': len(cited), 'unknown': unknown,
                'stop': resp.stop_reason, 'model': model}
    return {'answer': text, 'commands': commands, 'steps': len(commands), 'spend': spend, 'cited': 0, 'unknown': [], 'stop': 'max_steps', 'model': model}


def ask(a):
    r = answer(a.question, a.goal, a.model, a.max_steps, None if a.quiet else lambda s: print(s, file=sys.stderr, flush=True), a.date)
    return [('text', a.question, r['answer']),
            ('table', 'the commands it ran', ['#', 'command'], [(i + 1, c) for i, c in enumerate(r['commands'])]),
            ('note', f'{r["model"]}: {r["steps"]} commands, {r["spend"]}. Citations: {r["cited"]} refs, ' +
             ('all shown by the tools.' if not r['unknown'] else f'{len(r["unknown"])} NOT shown by any tool result: {", ".join(r["unknown"])}.'))]


# ---- eval ------------------------------------------------------------------------------------------------------------

JUDGE = '''You grade an answer about the AI Village dataset against a ground truth that was verified by hand against the raw records.
Pass only if the answer states the ground truth's key facts and contradicts none of them. Extra correct detail is fine. A hedge that
avoids the key fact, a different name or number, or "could not determine" fails. Judge the facts, not the style.
Return JSON: {"pass": true|false, "why": "one sentence"}.'''


def grade(cl, q, text, spend):
    """One answer against one question's ground truth -> (passed, why). Rules first, then a judge model if the question asks for one."""
    short = (re.findall(r'ANSWER:\s*(.+)', text) or [text])[-1]
    c, why = q.get('check') or {}, []
    if 'number' in c:
        nums = [float(x.replace(',', '')) for x in re.findall(r'(?<![\w:.])-?\d[\d,]*\.?\d*', short)]
        if not any(abs(n - c['number']) <= c.get('tol', 0) for n in nums):
            why.append(f'expected {c["number"]}' + (f' ±{c["tol"]}' if c.get('tol') else '') + f', the ANSWER line has {nums or "no number"}')
    for rx in c.get('all', []):
        if not re.search(rx, text, re.I):
            why.append(f'missing /{rx}/')
    if c.get('any') and not any(re.search(rx, text, re.I) for rx in c['any']):
        why.append('none of ' + ' | '.join(c['any']))
    for rx in c.get('none', []):
        if re.search(rx, short, re.I):
            why.append(f'the ANSWER line must not say /{rx}/')
    if not why and (q.get('judge') or not c):
        resp = cl.messages.create(model=ASK_MODEL, max_tokens=4000, system=JUDGE, messages=[{'role': 'user', 'content':
                                  f'QUESTION: {q["question"]}\n\nGROUND TRUTH: {q["truth"]}\n\nANSWER TO GRADE:\n{text}'}],
                                  output_config={'format': {'type': 'json_schema', 'schema': {
                                      'type': 'object', 'additionalProperties': False, 'required': ['pass', 'why'],
                                      'properties': {'pass': {'type': 'boolean'}, 'why': {'type': 'string'}}}}})
        spend.add(ASK_MODEL, resp.usage)
        d = json.loads(text_of(resp))
        if not d['pass']:
            why.append('judge: ' + d['why'])
    return not why, '; '.join(why)


def eval(a):  # noqa: A001 (the command's name)
    qs = json.loads(Path(a.file).read_text())
    if a.ids:
        qs = [q for q in qs if q['id'] in a.ids.split(',')]
    cl, judge_spend, t0 = client(), Spend(), time.time()

    def work(q):
        t = time.time()
        try:
            if a.agent_cmd:
                r = {'answer': subprocess.run(a.agent_cmd.replace('{question}', q['question'].replace("'", "’")), shell=True, capture_output=True,
                                              text=True, timeout=1800).stdout, 'steps': '', 'spend': None, 'unknown': [], 'commands': []}
            else:
                r = answer(q['question'], q.get('goal'), a.model)
            ok, why = grade(cl, q, r['answer'], judge_spend)
        except Exception as e:
            r, ok, why = {'answer': '', 'steps': '', 'spend': None, 'unknown': [], 'commands': []}, False, f'{type(e).__name__}: {e}'
        print(f'  {q["id"]}: {"pass" if ok else "FAIL"} ({time.time() - t:.0f}s)', file=sys.stderr, flush=True)
        return q, r, ok, why, time.time() - t

    with ThreadPoolExecutor(a.jobs) as pool:
        done = list(pool.map(work, qs))
    usd = sum(r['spend'].usd for _, r, *_ in done if r['spend']) + judge_spend.usd
    runs = Path(a.file).resolve().parent / 'runs'
    runs.mkdir(exist_ok=True)
    out = runs / f'{datetime.now():%Y%m%d-%H%M%S}.json'
    out.write_text(json.dumps([{'id': q['id'], 'pass': ok, 'why': why, 'seconds': round(s), 'usd': round(r['spend'].usd, 3) if r['spend'] else None,
                                'model': r.get('model'), 'steps': r['steps'], 'cited': r.get('cited', 0), 'unknown_refs': r.get('unknown', []), 'commands': r['commands'], 'answer': r['answer'], 'truth': q['truth']} for q, r, ok, why, s in done], ensure_ascii=False, indent=1))
    kinds = {}
    for q, r, ok, why, s in done:
        kinds.setdefault(q.get('kind', 'other'), []).append(ok)
    short = lambda t: one((re.findall(r'ANSWER:\s*(.+)', t) or [t[-200:]])[-1], 110)
    return [('table', f'{sum(d[2] for d in done)} of {len(done)} passed · {a.agent_cmd or (a.model or ASK_MODEL)} · {time.time() - t0:.0f}s · about ${usd:.2f}',
             ['id', 'kind', 'result', 'steps', 'secs', '$', 'answer given', 'why it failed'],
             [(q['id'], q.get('kind', ''), 'pass' if ok else 'FAIL', r['steps'], round(s), f'{r["spend"].usd:.2f}' if r['spend'] else '', short(r['answer']), one(why, 160))
              for q, r, ok, why, s in done]),
            ('table', 'by kind of question', ['kind', 'passed'], [(k, f'{sum(v)} of {len(v)}') for k, v in kinds.items()]),
            ('note', f'Full answers and the commands each run used: {out}')]
