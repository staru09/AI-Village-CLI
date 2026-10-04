"""The evidence commands: orient (overview, goals, recap), search (find, first-use, terms, count), and read
(show, timeline, sessions, session, said, memory). Every row carries a ref that `show` opens, so an answer can cite it."""
import re, sqlite3, sys
from collections import Counter, defaultdict

from . import db
from .core import CLAIM_EVENTS, KINDS, TIER, coverage, goal_of, lookup, maker, node, one, ref, scope

# find --in NAME -> (table, column, ref kind, agent column)
FIELDS = {'chat': ('messages', 'content', 'm', 'src'), 'said-why': ('messages', 'reasoning', 'm', 'src'),
          'action': ('turns', 'action', 't', 'agent'), 'output': ('turns', 'output', 't', 'agent'),
          'error': ('turns', 'error', 't', 'agent'), 'reasoning': ('turns', 'reasoning', 't', 'agent'),
          'intent': ('sessions', 'goal', 's', 'agent'), 'memory': ('memories', 'added', 'k', 'agent'),
          'event': ('events', 'text', 'e', 'agent'), 'recap': ('summaries', 'content', 'r', None)}
DEFAULT_IN = 'chat,action,output,reasoning,intent,memory,event'


def names_of(con):
    return dict(con.execute('SELECT id, name FROM nodes'))


def agent_filter(con, a, col):
    if getattr(a, 'agent', None):
        return f' AND {col} = ?', [node(con, a.agent)[0]]
    return '', []


def notes(con, a, *more):
    return [('note', n) for n in (*more, coverage(con, a)) if n]


def fields(a, default=DEFAULT_IN):
    got = [f.strip() for f in (a.where or default).split(',') if f.strip()]
    if bad := [f for f in got if f not in FIELDS]:
        sys.exit(f"--in {', '.join(bad)}: choose from {', '.join(FIELDS)}")
    return got


# ---- orient ----------------------------------------------------------------------------------------------------------

def goals(con, a):
    rows = []
    for n, goal, s, e in con.execute('SELECT n, goal, start_time, end_time FROM goals ORDER BY start_time DESC LIMIT ?', (a.limit,)):
        r = (s, e or db.END)
        days = con.execute('SELECT min(day), max(day) FROM days WHERE date >= ? AND date < ?', (s[:10], (e or db.END)[:10] + '~')).fetchone()
        rows.append([n, s[:16], (e or 'running')[:16], f'{days[0]}–{days[1]}' if days[0] else '', one(goal, 70),
                     *con.execute("SELECT count(DISTINCT src), count(*) FROM messages WHERE src != 'human' AND ts >= ? AND ts < ?", r).fetchone(),
                     con.execute('SELECT count(*) FROM sessions WHERE ts >= ? AND ts < ?', r).fetchone()[0],
                     con.execute('SELECT count(*) FROM turns WHERE ts >= ? AND ts < ?', r).fetchone()[0]])
    return [('table', 'village goals, newest first (times in Pacific time; use the number or part of the text with --goal)',
             ['n', 'start', 'end', 'days', 'goal', 'agents', 'msgs', 'sessions', 'actions loaded'], rows)]


def overview(con, a):
    lo, hi = scope(con, a)
    N = names_of(con)
    models = dict(con.execute('SELECT id, model FROM nodes'))
    r = (lo, hi)
    out = []
    gs = con.execute("SELECT n, goal, start_time, end_time FROM goals WHERE start_time < ? AND coalesce(end_time, '9999') > ? ORDER BY start_time",
                     (hi, lo)).fetchall()
    days = con.execute('SELECT min(day), max(day), min(date), max(date) FROM days WHERE date >= ? AND date < ?', (lo[:10], hi[:10] + '~')).fetchone()
    head = [f'Scope: {lo[:16] or "start"} to {hi[:16] if hi != db.END else "end"} PT' + (f', village days {days[0]}–{days[1]}' if days[0] else '')]
    head += [f'Village goal {n}: "{one(g, 200)}" ({s[:16]} to {(e or "running")[:16]})' for n, g, s, e in gs[:6]]
    if len(gs) > 6:
        head.append(f'… and {len(gs) - 6} more goals (see `goals`)')
    for agent, name, short, s, e in con.execute("SELECT agent, name, short, start_time, end_time FROM agent_goals WHERE start_time < ? "
                                                "AND coalesce(end_time, '9999') > ? ORDER BY start_time", (hi, lo)).fetchall()[:40]:
        head.append(f'Agent goal · {N.get(agent, agent)}: {short}: {one(name, 160)}')
    rooms = con.execute('SELECT room, count(*) FROM messages WHERE ts >= ? AND ts < ? GROUP BY room ORDER BY 2 DESC', r).fetchall()
    head.append('Chat rooms: ' + ', '.join(f'#{room} ({n})' for room, n in rooms))
    out.append(('text', 'overview', '\n'.join(head)))
    msgs = {s: v for s, *v in con.execute('SELECT src, count(*), substr(min(ts),1,16), substr(max(ts),1,16) FROM messages '
                                          'WHERE ts >= ? AND ts < ? GROUP BY src', r)}
    sess = dict(con.execute('SELECT agent, count(*) FROM sessions WHERE ts >= ? AND ts < ? GROUP BY agent', r))
    turns = {s: v for s, *v in con.execute("SELECT agent, count(*), sum(kind='bash'), sum(kind='gui'), sum(failed), sum(reasoning != '') "
                                           "FROM turns WHERE ts >= ? AND ts < ? GROUP BY agent", r)}
    rows = []
    for i in sorted(msgs.keys() | sess.keys() | turns.keys(), key=lambda i: -(turns.get(i, [0])[0] + msgs.get(i, [0])[0])):
        m, t = msgs.get(i, (0, '', '')), turns.get(i, (0, 0, 0, 0, 0))
        rows.append([N.get(i, i), models.get(i, ''), m[0], sess.get(i, 0), t[0], t[1], t[2], t[3], f'{100 * t[4] // t[0]}%' if t[0] else '', m[1], m[2]])
    out.append(('table', 'per agent (commands and screen are kinds of action; failed counts failure-looking errors; '
                         'reasoning = share of actions with readable reasoning or a note)',
                ['agent', 'model', 'msgs', 'sessions', 'actions', 'commands', 'screen', 'failed', 'reasoning', 'first msg', 'last msg'], rows))
    return out + notes(con, a)


def recap(con, a):
    """AI Digest's own summaries: SECONDARY (written by an LLM that never saw inside computer sessions)."""
    lo, hi = scope(con, a)
    out = []
    if getattr(a, 'goal', None):
        n, goal, s, e = goal_of(con, a.goal)
        words = set(re.findall(r'[a-z]+', goal.lower()))
        d = [r[0] for r in con.execute('SELECT day FROM days WHERE date >= ? AND date < ?', (s[:10], (e or db.END)[:10] + '~'))]
        for rid, typ, target, ts, text in con.execute("SELECT id, type, target, ts, content FROM summaries WHERE type IN ('goal', 'goal-checkpoint') ORDER BY ts"):
            rng = re.fullmatch(r'(\d+)-(\d+)', target or '')
            if (rng and d and set(range(int(rng[1]), int(rng[2]) + 1)) & set(d)) or \
                    ((w := set(re.findall(r'[a-z]+', (target or '').lower()))) and w <= words):
                out.append(('text', f'{ref("r", rid)} · {typ} story "{target}", written {ts[:10]} · SECONDARY SOURCE', text if a.wide else db.cut(text, 7000)))
    else:
        for rid, date, target, ts, text in con.execute("SELECT id, date, target, max(ts), content FROM summaries WHERE type = 'daily' AND date >= ? AND date < ? "
                                                       "GROUP BY date ORDER BY date LIMIT ?", (lo[:10], hi[:10] + '~', a.limit)):
            out.append(('text', f'{ref("r", rid)} · daily recap, Day {target}, {date} · SECONDARY SOURCE', text if a.wide else db.cut(text, 5000)))
    return out + [('note', 'Recaps are AI Digest\'s LLM summaries, written without seeing inside computer sessions: use them to decide where to '
                           'look, never as evidence.' if out else 'No recap in this scope: give --goal, --day or --date.')]


# ---- search ----------------------------------------------------------------------------------------------------------

def match(q):
    """A user's search text -> an FTS5 query. Plain words are ANDed; "quoted phrases", OR and prefix* work.
    Anything FTS5 would choke on (dots, slashes, colons) is quoted, so `run_judging.py` just works."""
    out = []
    for tok in re.findall(r'"[^"]+"|\S+', q):
        if tok in ('OR', 'AND', 'NOT') or tok.startswith('"'):
            out.append(tok)
        elif re.fullmatch(r'\w+\*?', tok):
            out.append(tok)
        else:
            out.append('"' + tok.replace('"', ' ') + '"')
    return ' '.join(out)


def find(con, a):
    lo, hi = scope(con, a)
    N = names_of(con)
    q, rows = match(a.text), []
    for f in fields(a):
        table, col, kind, who = FIELDS[f]
        cols = [c[1] for c in con.execute(f'PRAGMA table_info({table}_fts)')]
        aw, ap = agent_filter(con, a, f'x.{who}') if who else ('', [])
        time_col = 'x.ts'
        try:
            hits = con.execute(
                f"SELECT x.id, {time_col}, {f'x.{who}' if who else 'NULL'}, snippet({table}_fts, {cols.index(col)}, '«', '»', '…', {a.words}), "
                f"bm25({table}_fts) FROM {table}_fts JOIN {table} x ON x.rowid = {table}_fts.rowid "
                f"WHERE {table}_fts MATCH ? AND {time_col} >= ? AND {time_col} < ?{aw} ORDER BY {'x.ts' if a.order == 'time' else 'bm25(' + table + '_fts)'} LIMIT ?",
                (f'{col} : ({q})', lo, hi, *ap, a.limit)).fetchall()
        except sqlite3.OperationalError as e:
            sys.exit(f'search syntax: {e}. Use plain words, "a phrase", OR, or a prefix*.')
        if f == 'event':  # an event happened for sure, but its text may be the agent's own words
            types = dict(con.execute(f"SELECT id, type FROM events WHERE id IN ({','.join('?' * len(hits))})", [h[0] for h in hits]))
        tag = lambda i: f'{types[i].lower()}·{"claim" if types[i] in CLAIM_EVENTS else "truth"}' if f == 'event' else f'{f}·{TIER[f]}'
        rows += [(rank, ts[:19], ref(kind, i), N.get(w, w or ''), tag(i), one(snip, 0)) for i, ts, w, snip, rank in hits]
    rows.sort(key=(lambda r: r[1]) if a.order == 'time' else (lambda r: r[0]))
    total = len(rows)
    rows = [r[1:] for r in rows[:a.limit]]
    return [('table', f'{len(rows)} hits for {a.text!r}' + (f' (of at least {total}; raise --limit or narrow --in)' if total > len(rows) else '') +
             ' · «…» marks the match · open any ref with `show`', ['time PT', 'ref', 'agent', 'field·trust', 'snippet'], rows)] + \
        notes(con, a, 'No hits. Try fewer words, a prefix* or OR; check the scope.' if not rows else '')


def first_use(con, a):
    """Per agent: when it first used a term in chat and how often since. The order shows how a term spread."""
    lo, hi = scope(con, a)
    N = names_of(con)
    rows = con.execute("SELECT x.src, min(x.ts), count(*), min(x.ts || ' ' || x.id) FROM messages_fts JOIN messages x ON x.rowid = messages_fts.rowid "
                       "WHERE messages_fts MATCH ? AND x.ts >= ? AND x.ts < ? GROUP BY x.src ORDER BY 2 LIMIT ?",
                       (f'content : ({match(a.text)})', lo, hi, a.limit)).fetchall()
    out = [(ts[:16], N.get(s, s), n, ref('m', key.rsplit(' ', 1)[1])) for s, ts, n, key in rows]
    return [('table', f'chat use of {a.text!r} per speaker, in order of first use (exact word match; a human counts as one speaker)',
             ['first use PT', 'speaker', 'messages', 'first message'], out)]


def terms(con, a):
    """Words and names first used in chat inside the scope: candidates for coined terms."""
    lo, hi = scope(con, a)
    N = names_of(con)
    aw, ap = agent_filter(con, a, 'first_agent')
    rows = con.execute(f'SELECT term, first_ts, first_agent, uses, agents, first_msg FROM terms WHERE first_ts >= ? AND first_ts < ? AND agents >= ? '
                       f'AND uses >= ?{aw} ORDER BY agents DESC, uses DESC LIMIT ?', (lo, hi, a.min_agents, a.min_uses, *ap, a.limit)).fetchall()
    return [('table', 'terms first used in chat inside the scope, most widely adopted first (uses and agents count the whole history after it)',
             ['term', 'first used PT', 'by', 'messages', 'agents', 'first message'],
             [(t, ts[:16], N.get(w, w), u, n, ref('m', m)) for t, ts, w, u, n, m in rows]),
            ('note', 'A candidate list: it includes ordinary words that happened to appear late. Check a term with `first-use TERM`.')]


def count(con, a):
    """Count a regular expression per agent, model, maker, day or room: a rate per 1,000 words, with its base."""
    lo, hi = scope(con, a)
    N, models = names_of(con), dict(con.execute('SELECT id, model FROM nodes'))
    try:
        rx = re.compile(a.pattern, 0 if a.case else re.I)
    except re.error as e:
        sys.exit(f'bad regular expression: {e}')
    key = {'agent': lambda w, ts, room: N.get(w, w), 'model': lambda w, ts, room: models.get(w, w), 'maker': lambda w, ts, room: maker(models.get(w)),
           'day': lambda w, ts, room: ts[:10], 'room': lambda w, ts, room: room or '', 'all': lambda w, ts, room: 'all'}[a.by]
    units, hit, matches, words = Counter(), Counter(), Counter(), Counter()
    for f in fields(a, 'chat'):
        table, col, _, who = FIELDS[f]
        if not who:
            sys.exit('count works on the agents\' own fields, not recap')
        aw, ap = agent_filter(con, a, who)
        room = 'room' if table == 'messages' else 'NULL'
        for w, ts, rm, text in con.execute(f"SELECT {who}, ts, {room}, {col} FROM {table} WHERE ts >= ? AND ts < ? AND {col} != '' AND {who} != 'human'{aw}",
                                           (lo, hi, *ap)):
            k = key(w, ts, rm)
            n = sum(1 for _ in rx.finditer(text))
            units[k] += 1
            hit[k] += n > 0
            matches[k] += n
            words[k] += text.count(' ') + 1
    rows = [(k, units[k], hit[k], f'{100 * hit[k] / units[k]:.1f}%', matches[k], words[k], f'{1000 * matches[k] / max(words[k], 1):.2f}')
            for k in sorted(units, key=(lambda k: k) if a.by == 'day' else (lambda k: -matches[k] / max(words[k], 1)))][:a.limit]
    return [('table', f'/{a.pattern}/ in {a.where or "chat"}, by {a.by} (a rule-based count, not a model\'s judgement)',
             [a.by, 'texts', 'texts with a match', 'share', 'matches', 'words', 'matches per 1,000 words'], rows)] + notes(con, a)


# ---- read ------------------------------------------------------------------------------------------------------------

def context(con, agent, ts):
    """The goals in force for an agent at a time: (village goal, agent goal or '', the village goal before it or '')."""
    g = con.execute("SELECT n, goal, start_time FROM goals WHERE start_time <= ? AND coalesce(end_time, '9999') > ?", (ts, ts)).fetchone()
    ag = con.execute("SELECT short, name FROM agent_goals WHERE agent = ? AND start_time <= ? AND coalesce(end_time, '9999') > ?", (agent, ts, ts)).fetchone()
    prev = con.execute('SELECT goal, end_time FROM goals WHERE start_time < ? ORDER BY start_time DESC LIMIT 1', (g[2] if g else ts,)).fetchone()
    day = g and con.execute('SELECT day FROM days WHERE date = ?', (g[2][:10],)).fetchone()
    return ((f'{g[0]}: {g[1]} (set on {g[2][:10]}' + (f', village day {day[0]}' if day else '') + ')') if g else 'between goals',
            f'{ag[0]}: {ag[1]}' if ag else '', f'{prev[0]} (ended {prev[1][:10]})' if prev else '')


def show(con, a):
    out, N = [], names_of(con)
    for r in a.refs:
        kind, rid = lookup(con, r)
        row = con.execute(f'SELECT * FROM {KINDS[kind]} WHERE id = ?', (rid,))
        d = dict(zip([c[0] for c in row.description], row.fetchone()))
        who = N.get(d.get('agent') or d.get('src'), d.get('agent') or d.get('src') or '')
        big = lambda s: s if a.wide else db.cut(s, 6000)
        extra = []
        if kind == 'm':
            body = [f'{who} in #{d["room"]} at {d["ts"][:19]} PT', '', '[chat · claim]', d['content']]
            if d['reasoning']:
                body += ['', '[reasoning before it · claim]', big(d['reasoning'])]
            if a.context:
                near = con.execute('SELECT * FROM (SELECT ts, id, src, content FROM messages WHERE room = ? AND ts < ? ORDER BY ts DESC LIMIT ?) '
                                   'UNION ALL SELECT * FROM (SELECT ts, id, src, content FROM messages WHERE room = ? AND ts > ? ORDER BY ts LIMIT ?) '
                                   'ORDER BY 1', (d['room'], d['ts'], a.context, d['room'], d['ts'], a.context)).fetchall()
                extra.append(('table', f'the {a.context} messages before and after {ref("m", rid)} in #{d["room"]}', ['time PT', 'ref', 'speaker', 'message'],
                            [(t[:19], ref('m', i), N.get(s, s), one(c, 300)) for t, i, s, c in near]))
        elif kind == 't':
            s = con.execute('SELECT short, goal FROM sessions WHERE id = ?', (d['session'],)).fetchone() or ('', '')
            body = [f'{who} at {d["ts"][:19]} PT · {d["kind"]} action in session {ref("s", d["session"])} ("{one(s[0], 100)}")']
            if d['reasoning']:
                body += ['', '[reasoning before it · claim]', big(d['reasoning'])]
            body += ['', '[action · ground truth]', big(d['action'])]
            if d['output']:
                body += ['', '[output from the system · ground truth]', big(d['output'])]
            if d['error']:
                body += ['', f'[error / stderr from the system · ground truth{" · looks like a failure" if d["failed"] else ""}]', big(d['error'])]
            if d['shot'] and d['kind'] in ('gui', 'other'):
                body += ['', f'[screenshot] {d["id"]}.png in images/computer-use-turns/<day>.tar (see `shot {ref("t", rid)}`)']
            if a.context:
                near = con.execute('SELECT * FROM (SELECT ts, id, kind, action, output, error FROM turns WHERE session = ? AND ts < ? ORDER BY ts DESC LIMIT ?) '
                                   'UNION ALL SELECT * FROM (SELECT ts, id, kind, action, output, error FROM turns WHERE session = ? AND ts > ? ORDER BY ts LIMIT ?) '
                                   'ORDER BY 1', (d['session'], d['ts'], a.context, d['session'], d['ts'], a.context)).fetchall()
                extra.append(('table', f'the {a.context} actions before and after {ref("t", rid)} in its session', ['time PT', 'ref', 'kind', 'action', 'result'],
                            [(t[:19], ref('t', i), k, one(act, 200), one(o or (e and 'ERR: ' + e), 160)) for t, i, k, act, o, e in near]))
        elif kind == 's':
            out += session(con, a, rid)
            continue
        elif kind == 'e':
            body = [f'{who} at {d["ts"][:19]} PT · event {d["type"]}' + (f' · session {ref("s", d["session"])}' if d['session'] else ''),
                    '', '[event · recorded by the system; the texts inside are the agent\'s own]', big(d['text'])]
            if d['reasoning']:
                body += ['', '[reasoning · claim]', big(d['reasoning'])]
        elif kind == 'k':
            body = [f'{who} rewrote its memory at {d["ts"][:19]} PT · {d["chars"]:,} characters · {d["dropped"]} lines dropped',
                    '', '[lines added in this version · claim]', big(d['added'])]
        else:
            body = [f'{d["type"]} recap "{d["target"]}" {d["date"] or ""}, written {d["ts"][:10]} · SECONDARY SOURCE', '', big(d['content'])]
        out += [('text', ref(kind, rid), '\n'.join(body)), *extra]
    return out


def sessions(con, a):
    lo, hi = scope(con, a)
    N = names_of(con)
    aw, ap = agent_filter(con, a, 'agent')
    rows = con.execute(f'SELECT id, ts, end_ts, agent, turns, bash, failed, short FROM sessions WHERE ts >= ? AND ts < ?{aw} ORDER BY ts LIMIT ?',
                       (lo, hi, *ap, a.limit + 1)).fetchall()
    out = [(ref('s', i), ts[:16], (e or '')[11:16], N.get(w, w), t or '', b or '', f or '', one(short, 90)) for i, ts, e, w, t, b, f, short in rows[:a.limit]]
    return [('table', 'computer sessions in time order · the goal is the agent\'s own stated intent (a claim) · open one with `session REF`',
             ['ref', 'start PT', 'last action', 'agent', 'actions', 'commands', 'failed', 'short goal'], out)] + \
        notes(con, a, f'More than {a.limit} sessions: narrow with --agent, --day or --date, or raise --limit.' if len(rows) > a.limit else '')


def session_parts(con, sid):
    """A session's chain: its row, its actions, the consolidation or report that closed it, and the memory version written then."""
    s = con.execute('SELECT id, agent, ts, end_ts, goal, short, turns, bash, gui, chat, failed FROM sessions WHERE id = ?', (sid,)).fetchone()
    turns = con.execute('SELECT ts, id, kind, action, output, error, failed, reasoning FROM turns WHERE session = ? ORDER BY ts', (sid,)).fetchall()
    nxt = con.execute('SELECT ts FROM sessions WHERE agent = ? AND ts > ? ORDER BY ts LIMIT 1', (s[1], s[2])).fetchone()
    close = con.execute("SELECT id, ts, type, text, reasoning FROM events WHERE session = ? AND type = 'CONSOLIDATE' ORDER BY ts LIMIT 1", (sid,)).fetchone() or \
        con.execute("SELECT id, ts, type, text, reasoning FROM events WHERE agent = ? AND type = 'STOP_USING_COMPUTER' AND ts > ? AND ts < ? ORDER BY ts LIMIT 1",
                    (s[1], s[2], nxt[0] if nxt else db.END)).fetchone()
    mem = close and con.execute("SELECT id, ts, added, dropped FROM memories WHERE agent = ? AND ts BETWEEN datetime(?, '-3 minutes') AND datetime(?, '+3 minutes') "
                                "ORDER BY ts DESC LIMIT 1", (s[1], close[1][:19], close[1][:19])).fetchone()
    return s, turns, close, mem


def session_text(con, sid, budget=14000, why=300):
    """One session as plain text for a reader or a labeller: goals, stated intent, actions with results, self-report.
    Long sessions keep every action but shorten each one, so the text stays near `budget` characters."""
    s, turns, close, mem = session_parts(con, sid)
    N = names_of(con)
    vg, ag, before = context(con, s[1], s[2])
    model = con.execute('SELECT model FROM nodes WHERE id = ?', (s[1],)).fetchone()
    head = [f'SESSION {ref("s", sid)} · {N.get(s[1], s[1])} ({model[0] if model else "?"}) · {s[2][:19]} to {(s[3] or "?")[11 if (s[3] or "")[:10] == s[2][:10] else 0:19]} PT',
            f'VILLAGE GOAL (ground truth): {vg}', f'AGENT GOAL (ground truth): {ag or "none assigned at that time"}',
            f'PREVIOUS VILLAGE GOAL: {before or "none"}',
            f'STATED INTENT (claim, written by the agent before the session): {s[5]}', s[4], '',
            f'ACTIONS (ground truth: what it did and what the system answered; {len(turns)} in all, {s[10] or 0} look failed)']
    per = max(120, min(700, (budget - 2500) // max(len(turns), 1)))
    lines = []
    for ts, tid, kind, act, out, err, failed, reason in turns:
        line = f'{ts[11:19]} {ref("t", tid)} [{kind}] {one(act, per)}'
        if out:
            line += f'\n    -> {one(out[-per:] if len(out) > per else out, per)}'
        if err and (failed or not out):
            line += f'\n    {"FAILED" if failed else "stderr"}: {one(err, per // 2)}'
        if reason and why:
            line += f'\n    (its reasoning: {one(reason, min(why, per))})'
        lines.append(line)
    tail = ['', 'SELF-REPORT (claim: what the agent wrote when the session ended)']
    if close:
        tail.append(f'{close[1][11:19]} {ref("e", close[0])} {close[2].lower()}: {db.cut(close[3], 2500)}')
    if mem:
        tail.append(f'{mem[1][11:19]} {ref("k", mem[0])} lines it added to its memory ({mem[3]} dropped):\n{db.cut(mem[2], 3500)}')
    if not close and not mem:
        tail.append('(none found)')
    return '\n'.join(head + lines + tail)


def session(con, a, sid=None):
    if not sid:
        kind, sid = lookup(con, a.ref)
        if kind == 't':  # an action: open the session it belongs to
            sid = con.execute('SELECT session FROM turns WHERE id = ?', (sid,)).fetchone()[0]
        elif kind != 's':
            sys.exit('`session` takes a session ref (s:…) or an action ref (t:…): list sessions with `sessions`.')
    n = con.execute('SELECT turns FROM sessions WHERE id = ?', (sid,)).fetchone()[0]
    return [('text', f'session {ref("s", sid)}', session_text(con, sid, 10 ** 7 if a.wide else max(14000, a.limit * 200), why=10 ** 6 if a.wide else 300))] + \
        ([] if n else notes(con, a, 'This session has no actions loaded.'))


def timeline(con, a):
    """One agent's chat, actions, session goals, events and memory updates, interleaved in time."""
    lo, hi = scope(con, a)
    x, name = node(con, a.name)
    kinds = set((a.kinds or 'chat,intent,action,event,memory').replace('action', 'bash,gui,other').split(','))
    if a.session:
        sid = lookup(con, a.session)[1]
        s = con.execute('SELECT ts, end_ts FROM sessions WHERE id = ?', (sid,)).fetchone()
        lo, hi = max(lo, s[0]), min(hi, (s[1] or s[0]) + '~')
    n = 0 if a.wide else 150
    q, p = [], []
    if 'chat' in kinds:
        q.append("SELECT ts, 'm', id, 'chat·claim', '#' || room || ': ' || content FROM messages WHERE src = ? AND ts >= ? AND ts < ?")
    if 'heard' in kinds:
        q.append("SELECT m.ts, 'm', m.id, 'heard', (SELECT name FROM nodes WHERE id = m.src) || ': ' || m.content FROM edges e JOIN messages m ON m.id = e.msg_id "
                 "WHERE e.dst = ? AND e.ts >= ? AND e.ts < ?")
    if 'intent' in kinds:
        q.append("SELECT ts, 's', id, 'intent·claim', short || ' — ' || goal FROM sessions WHERE agent = ? AND ts >= ? AND ts < ?")
    acts = [k for k in ('bash', 'gui', 'other') if k in kinds]
    if acts:
        q.append("SELECT ts, 't', id, kind || '·truth', action || CASE WHEN failed THEN '  ✗ ' || error WHEN output != '' THEN '  → ' || substr(output, 1, 300) ELSE '' END "
                 f"FROM turns WHERE agent = ? AND ts >= ? AND ts < ? AND kind IN ({','.join(repr(k) for k in acts)})")
    if 'event' in kinds:
        q.append(f"SELECT ts, 'e', id, lower(type) || CASE WHEN type IN {CLAIM_EVENTS} THEN '·claim' ELSE '·truth' END, text "
                 "FROM events WHERE agent = ? AND ts >= ? AND ts < ?")
    if 'memory' in kinds:
        q.append("SELECT ts, 'k', id, 'memory·claim', '+' || (length(added) - length(replace(added, char(10), '')) + 1) || ' lines, -' || dropped || ': ' || added "
                 "FROM memories WHERE agent = ? AND ts >= ? AND ts < ?")
    if not q:
        sys.exit('--kinds: choose from chat, heard, intent, bash, gui, other, event, memory')
    rows = con.execute(' UNION ALL '.join(q) + ' ORDER BY 1 LIMIT ?', (*(v for _ in q for v in (x, lo, hi)), a.limit + 1)).fetchall()
    out = [(ts[:19], ref(k, i), kind, one(text, n)) for ts, k, i, kind, text in rows[:a.limit]]
    more = f'Stopped at {a.limit} rows ({out[-1][0]}): continue with --since "{out[-1][0]}", or filter with --kinds.' if len(rows) > a.limit else ''
    return [('table', f'{name}: timeline', ['time PT', 'ref', 'what·trust', 'text'], out)] + notes(con, a, more)


def said(con, a):
    """Thought vs said: each chat message of an agent next to the reasoning recorded just before it."""
    lo, hi = scope(con, a)
    x, name = node(con, a.name)
    n = 0 if a.wide else 400
    rows = con.execute("SELECT ts, id, reasoning, content FROM messages WHERE src = ? AND ts >= ? AND ts < ? AND reasoning != '' ORDER BY ts LIMIT ?",
                       (x, lo, hi, a.limit)).fetchall()
    have, base = con.execute("SELECT sum(reasoning != ''), count(*) FROM messages WHERE src = ? AND ts >= ? AND ts < ?", (x, lo, hi)).fetchone()
    return [('table', f'{name}: {have or 0} of its {base} chat messages in scope have reasoning recorded before them (both columns are claims)'
             + (f'; showing the first {len(rows)}' if (have or 0) > len(rows) else ''),
             ['time PT', 'ref', 'thought before it', 'said in chat'], [(ts[:19], ref('m', i), one(r, n), one(c, n)) for ts, i, r, c in rows])] + notes(con, a)


def memory(con, a):
    lo, hi = scope(con, a)
    x, name = node(con, a.name)
    if a.diff:
        rows = con.execute('SELECT ts, id, chars, added, dropped FROM memories WHERE agent = ? AND ts >= ? AND ts < ? ORDER BY ts LIMIT ?', (x, lo, hi, a.limit)).fetchall()
        return [('table', f'{name}: memory versions and the lines each added (its own notes: claims)', ['time PT', 'ref', 'chars', 'dropped', 'added'],
                 [(ts[:19], ref('k', i), c, d, one(add, 0 if a.wide else 400)) for ts, i, c, add, d in rows])] + notes(con, a)
    row = con.execute('SELECT date, ts, content FROM memory_days WHERE agent = ? AND date < ? ORDER BY date DESC LIMIT 1',
                      (x, hi[:10] + '~' if hi != db.END else db.END)).fetchone()
    if not row:
        return notes(con, a, f'No memory of {name} is loaded at or before this scope.')
    text = row[2]
    if a.grep:
        rx = re.compile(a.grep, re.I)
        text = '\n'.join(l for l in text.splitlines() if rx.search(l))
    return [('text', f'{name}: its memory as of {row[1][:19]} PT (the last version of {row[0]}; {len(row[2]):,} characters; its own notes: claims)',
             text if a.wide else db.cut(text, 8000))] + notes(con, a)


def png(rid, ts):
    """An action's screenshot -> (PNG bytes, the tar it came from), or exit with what is missing."""
    import tarfile
    tar = images() / f'{ts[:10]}.tar'
    if not tar.exists():
        sys.exit(f'{tar} is missing: download images/computer-use-turns/{ts[:10]}.tar from the dataset, or set VILLAGE_IMAGES to its folder.')
    with tarfile.open(tar) as t:
        try:
            return t.extractfile(f'{rid}.png').read(), tar
        except KeyError:
            sys.exit(f'{ref("t", rid)} has no screenshot in {tar.name} (commands and chat-only actions have none).')


def shot(con, a):
    """Where a turn's screenshot is; --save writes the PNG."""
    kind, rid = lookup(con, a.ref)
    if kind != 't':
        sys.exit('`shot` takes an action ref (t:…).')
    data, tar = png(rid, con.execute('SELECT ts FROM turns WHERE id = ?', (rid,)).fetchone()[0])
    if a.save:
        open(a.save, 'wb').write(data)
    return [('text', ref('t', rid), f'screenshot {rid}.png in {tar} ({len(data):,} bytes)' + (f', saved to {a.save}' if a.save else ''))]


def images():
    import os
    from pathlib import Path
    if os.environ.get('VILLAGE_IMAGES'):
        return Path(os.environ['VILLAGE_IMAGES'])
    cache = Path(os.environ.get('HF_HUB_CACHE') or Path.home() / '.cache/huggingface/hub') / 'datasets--aidigestorg--ai-village'
    try:
        return cache / 'snapshots' / (cache / 'refs' / 'main').read_text().strip() / 'images' / 'computer-use-turns'
    except FileNotFoundError:
        return db.snapshot() / 'images' / 'computer-use-turns'


# ---- escape hatch ----------------------------------------------------------------------------------------------------

def sql(con, a):
    if not re.match(r'\s*(select|with)\b', a.query, re.I):
        sys.exit('sql runs one read-only SELECT (or WITH … SELECT).')
    try:
        cur = con.execute(a.query)
        rows = cur.fetchmany(a.limit + 1)
    except sqlite3.Error as e:
        sys.exit(f'sql: {e}. See `schema` for tables and columns.')
    return [('table', 'sql', [c[0] for c in cur.description], [[one(v, 0 if a.wide else 300) if isinstance(v, str) else v for v in r] for r in rows[:a.limit]])] + \
        ([('note', f'Stopped at {a.limit} rows: add LIMIT or raise --limit.')] if len(rows) > a.limit else [])


def schema(con, a):
    m = dict(con.execute('SELECT key, value FROM meta'))
    out = [('text', 'coverage', f"Built {m.get('built')} from the export of {m.get('exported', '')[:10]}. All times are Pacific time (the village clock).\n"
                                f"Chat, mentions, sessions, events, goals: {m.get('chat_from')} to {m.get('chat_to')} (full history).\n"
                                f"Actions (turns) and memories: {m.get('actions_from') or 'none'} to {m.get('actions_to') or 'none'}.")]
    rows = []
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE '%\\_fts%' ESCAPE '\\' AND name != 'meta' ORDER BY name").fetchall():
        rows.append((t, con.execute(f'SELECT count(*) FROM {t}').fetchone()[0], ', '.join(c[1] for c in con.execute(f'PRAGMA table_info({t})'))))
    try:
        rows.append(('L.labels', con.execute('SELECT count(*) FROM L.labels').fetchone()[0], ', '.join(c[1] for c in con.execute('PRAGMA L.table_info(labels)'))))
    except sqlite3.OperationalError:
        pass
    out.append(('table', 'tables (ids are UUIDs; agent, src and dst hold nodes.id; join names through nodes)', ['table', 'rows', 'columns'], rows))
    out.append(('note', 'Full-text tables: messages_fts, turns_fts, sessions_fts, events_fts, memories_fts, summaries_fts (join on rowid). '
                        'Trust: turns.action/output/error and events are ground truth; chat, reasoning, sessions.goal and memories are the agents\' claims; '
                        'summaries are secondary.'))
    return out
