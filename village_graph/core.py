"""Shared pieces of every query command: the read-only connection, the scope filters, names and citable refs."""
import re, sqlite3, sys, time

from . import db  # db.DB is read at call time so tests can point it elsewhere

# A ref cites one record: m: chat message, t: action (turn), s: session, e: event, k: memory version, r: recap.
KINDS = {'m': 'messages', 't': 'turns', 's': 'sessions', 'e': 'events', 'k': 'memories', 'r': 'summaries'}
REF = re.compile(r'\b([mtsekr]):([0-9a-f]{12}|toolu_\w+)')
# How far a field can be trusted. truth: recorded by the system. claim: the agent's own words. secondary: written later
# by an LLM that did not see inside the computer sessions.
TIER = {'chat': 'claim', 'said-why': 'claim', 'intent': 'claim', 'reasoning': 'claim', 'memory': 'claim', 'action': 'truth',
        'output': 'truth', 'error': 'truth', 'event': 'truth', 'recap': 'secondary'}
# events whose text is the agent's own words; the rest (pauses, searches' answers, room moves, human verdicts) are the system's or a human's
CLAIM_EVENTS = ('CONSOLIDATE', 'START_USING_COMPUTER', 'STOP_USING_COMPUTER', 'REQUEST_HUMAN_HELPER', 'OUTREACH_APPROVAL_REQUEST')
MAKERS = [('claude', 'Anthropic'), ('gpt', 'OpenAI'), ('o1', 'OpenAI'), ('o3', 'OpenAI'), ('o4', 'OpenAI'), ('gemini', 'Google'),
          ('deepseek', 'DeepSeek'), ('kimi', 'Moonshot'), ('moonshot', 'Moonshot'), ('glm', 'Zhipu'), ('grok', 'xAI'), ('muse', 'Meta')]


def connect(seconds=30):
    """The database, read-only, with labels.db attached as L when it exists. A query is stopped after `seconds`."""
    if not db.DB.exists():
        sys.exit(f'{db.DB} is missing: run `village build` first (see README).')
    con = sqlite3.connect(f'file:{db.DB}?mode=ro', uri=True)
    labels = db.DB.with_name('labels.db')
    if labels.exists():
        con.execute('ATTACH DATABASE ? AS L', (f'file:{labels}?mode=ro',))
    deadline = time.time() + seconds
    con.set_progress_handler(lambda: time.time() > deadline, 100000)
    return con


def ref(kind, rid):
    return f"{kind}:{rid.replace('-', '')[:12] if len(rid) == 36 and rid[8] == '-' else rid}"


def lookup(con, r):
    """A ref such as t:0a1b2c3d4e5f -> (kind, the full id), or exit."""
    m = REF.fullmatch(r.strip().strip('[](),.'))
    if not m:
        sys.exit(f'{r!r} is not a ref. Refs look like m:0a1b2c3d4e5f (m chat, t action, s session, e event, k memory, r recap).')
    kind, h = m.groups()
    p = h if h.startswith('toolu_') else f'{h[:8]}-{h[8:]}'
    hit = con.execute(f'SELECT id FROM {KINDS[kind]} WHERE id >= ? AND id < ? LIMIT 2', (p, p + '~')).fetchall()
    if len(hit) != 1:
        sys.exit(f'{r} matches {len(hit)} records' + (': actions and memories are loaded for part of the history only (see `schema`).'
                                                       if kind in 'tk' and not hit else '.'))
    return kind, hit[0][0]


def node(con, q):
    """An agent by any unique, case-insensitive part of its name -> (id, name)."""
    all_ = con.execute('SELECT id, name FROM nodes').fetchall()
    hits = [r for r in all_ if r[1].lower() == q.lower()] or [r for r in all_ if q.lower() in r[1].lower()]
    if len(hits) != 1:
        sys.exit(f'{q!r} matches {len(hits)} agents: ' + ', '.join(r[1] for r in hits or all_))
    return hits[0]


def maker(model):
    return next((m for k, m in MAKERS if k in (model or '').lower()), 'Other')


def goal_of(con, q):
    """--goal value (a number from `goals`, or part of the goal's text) -> (n, goal, start, end)."""
    if str(q).isdigit():
        g = con.execute('SELECT n, goal, start_time, end_time FROM goals WHERE n = ?', (int(q),)).fetchall()
    else:
        g = con.execute('SELECT n, goal, start_time, end_time FROM goals WHERE goal LIKE ? ORDER BY start_time', (f'%{q}%',)).fetchall()
    if len(g) != 1:
        sys.exit(f'--goal {q!r} matched {len(g)} goals' + (':\n' + '\n'.join(f'  {n:>2}  {s[:10]}  {t[:80]!r}' for n, t, s, _ in g) if g else
                                                           '. List them with `goals`.'))
    return g[0]


def scope(con, a):
    """The Pacific-time range [lo, hi) from --goal, --day, --date, --since and --until (the narrowest of them)."""
    lo, hi = '', db.END
    if getattr(a, 'goal', None):
        _, _, s, e = goal_of(con, a.goal)
        lo, hi = s, e or db.END
    d = getattr(a, 'date', None)
    if getattr(a, 'day', None):
        row = con.execute('SELECT date FROM days WHERE day = ?', (a.day,)).fetchone()
        if not row:
            sys.exit(f'no village day {a.day} (days come from the daily recaps: see `sql "SELECT * FROM days"`).')
        d = row[0]
    if d:
        lo, hi = max(lo, d), min(hi, d + ' 99')
    if getattr(a, 'since', None):
        lo = max(lo, a.since)
    if getattr(a, 'until', None):
        hi = min(hi, a.until)
    return lo, hi


def where(con, a, t='', kind=True):
    """SQL filter from the shared flags; t is a column prefix such as 'e.' for joins."""
    lo, hi = scope(con, a)
    sql, p = [f'{t}ts >= ? AND {t}ts < ?'], [lo, hi]
    if getattr(a, 'room', None):
        sql.append(f'{t}room = ?')
        p.append(a.room)
    if kind and getattr(a, 'kind', None):
        sql.append(f'{t}kind = ?')
        p.append(a.kind)
    return ' AND '.join(sql), p


def coverage(con, a):
    """A warning when the scope reaches outside the part of the history whose actions and memories are loaded."""
    lo, hi = scope(con, a)
    m = dict(con.execute('SELECT key, value FROM meta'))
    if not m.get('actions_from'):
        return 'No actions or memories are loaded: build with --goal, --since or --all.'
    f, t = m.get('window_from', ''), m.get('window_to', db.END)
    if lo[:16] < f or hi[:16] > t:
        return f"Actions, reasoning and memories are loaded only for {f or 'the start'} to {t if t != db.END else 'the end'} PT (chat, sessions and events: all)."
    return ''


def one(s, n=160):
    """Text -> one line of at most n characters (n = 0: whole, still one line)."""
    s = ' '.join((s or '').split())
    return s if not n or len(s) <= n else s[:n - 1] + '…'
