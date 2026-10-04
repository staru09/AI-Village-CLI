"""Build village.db from the AI Village dataset: chat, mentions, goals, sessions, actions, memories, events.

Light tables (chat, sessions, events, goals, summaries) always cover the full history. Heavy tables (turns: every
computer action with its output and reasoning; memories) cover a window, because the full history is several GB.
All times are stored in Pacific time (the village clock), so a date is a village day.
"""
import gzip, json, os, re, sqlite3, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .mentions import extractor

DB = Path(os.environ.get('VILLAGE_DB') or Path(__file__).resolve().parents[1] / 'village.db')
NOT_HUMAN = {'automated', 'all', 'team', 'everyone', 'agents'}
PTZ = ZoneInfo('America/Los_Angeles')
END = '9999'
# Stored text is cut to these sizes (characters). A cut keeps the head and the tail: results are usually at the end.
CUT = {'action': 12000, 'output': 6000, 'error': 2000, 'reasoning': 8000, 'added': 12000}
# a bash turn's 'error' is its stderr, also on success (git push, curl progress): only failure-looking stderr counts.
# ponytail: keyword guess, the turns keep no exit code; GUI action errors always count.
FAIL = re.compile(r"error|fatal|fail|traceback|not found|denied|timed out|returncode|no such|cannot|can't|invalid|refused|"
                  r"unable|rejected|usage:|not started", re.I)
# candidates for coined terms: compounds (lambda-lang, run_id), Capitalised Pairs, and longer plain words
TERM = re.compile(r"[A-Za-z][A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+|[A-Z][a-z]+ [A-Z][a-z]+|[A-Za-z]{5,}")
GUI = {'key', 'type', 'left_click', 'right_click', 'middle_click', 'double_click', 'triple_click', 'left_click_drag', 'mouse_move',
       'scroll', 'screenshot', 'cursor_position', 'get_pixel_coords_of_element', 'left_mouse_down', 'left_mouse_up', 'hold_key', 'zoom'}


def rows(snap, name):
    with gzip.open(snap / name, 'rb') as f:
        for line in f:
            yield json.loads(line)


def snapshot():
    if os.environ.get('VILLAGE_DATA'):
        return Path(os.environ['VILLAGE_DATA'])
    cache = Path(os.environ.get('HF_HUB_CACHE') or Path.home() / '.cache/huggingface/hub')
    root = cache / 'datasets--aidigestorg--ai-village'
    try:
        return root / 'snapshots' / (root / 'refs' / 'main').read_text().strip()
    except FileNotFoundError:
        sys.exit(f'AI Village dataset not found under {root}; download it (see README) or set VILLAGE_DATA.')


def pt(ts):
    """Dataset time (UTC, 'YYYY-MM-DD HH:MM:SS[.ffffff]') -> the same instant in Pacific time, same format.
    ponytail: the one repeated hour each November (01:00-02:00 PT) sorts ambiguously; the village is asleep then."""
    if not ts:
        return ts
    t = datetime.fromisoformat(ts[:26].replace('T', ' ')).replace(tzinfo=timezone.utc).astimezone(PTZ)
    return t.strftime('%Y-%m-%d %H:%M:%S.%f')


def cut(s, n, tail=0.35):
    """Text -> at most about n characters, keeping the head and the tail."""
    s = (s or '').strip()
    if len(s) <= n:
        return s
    t = int(n * tail)
    return f'{s[:n - t]}\n… [{len(s) - n:,} characters cut] …\n{s[-t:]}'


def thoughts(o):
    """Reasoning text anywhere in a provider-shaped model response: Anthropic thinking blocks, OpenAI reasoning
    summaries, Gemini thought parts, reasoning(_content) strings (DeepSeek, Kimi, OpenRouter)."""
    if isinstance(o, list):
        for v in o:
            yield from thoughts(v)
    elif isinstance(o, dict):
        if o.get('type') == 'thinking':
            yield o.get('thinking')
        if o.get('type') == 'reasoning':
            yield from (s.get('text') for s in o.get('summary') or [] if isinstance(s, dict))
        if o.get('thought') is True:
            yield o.get('text')
        yield o.get('reasoning_content')
        yield o.get('reasoning')
        for v in o.values():
            if isinstance(v, (dict, list)):
                yield from thoughts(v)


def notes(o):
    """Visible (non-reasoning) text in a model response: Anthropic text blocks, Gemini non-thought parts, chat content."""
    if isinstance(o, list):
        for v in o:
            yield from notes(v)
    elif isinstance(o, dict):
        if o.get('type') in ('text', 'output_text') or 'text' in o and 'type' not in o and o.get('thought') is not True:
            yield o.get('text')
        if isinstance(o.get('content'), str):
            yield o['content']
        for v in o.values():
            if isinstance(v, (dict, list)):
                yield from notes(v)


def joined(parts):
    return '\n'.join(dict.fromkeys(t.strip() for t in parts if isinstance(t, str) and t.strip()))


def thought(msg):
    """A turn's reasoning. Models that return none (DeepSeek, Claude Opus 4.7) often leave a one-line note instead."""
    return joined(thoughts(msg)) or joined(notes(msg))


def action_of(a):
    """agent_action -> (kind, text). kind: bash | chat | gui | other."""
    a = a or {}
    if 'command' in a or a.get('action') == 'bash':
        return 'bash', a.get('command') or ''
    k = a.get('action')
    if k == 'send_message_back_to_chat':
        return 'chat', a.get('content') or ''
    if not k:
        return 'other', json.dumps(a, ensure_ascii=False) if a else ''
    rest = ' '.join(f'{x}={json.dumps(y, ensure_ascii=False)}' for x, y in a.items() if x != 'action' and y not in (None, '', [], False))
    return ('gui' if k in GUI else 'other'), f'{k} {rest}'.strip()


SCHEMA = '''
    CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE nodes(id TEXT PRIMARY KEY, name TEXT UNIQUE, model TEXT);
    CREATE TABLE edges(msg_id TEXT, src TEXT, dst TEXT, kind TEXT, room TEXT, ts TEXT, PRIMARY KEY(msg_id, dst));
    CREATE TABLE messages(id TEXT PRIMARY KEY, src TEXT, room TEXT, ts TEXT, content TEXT, reasoning TEXT);
    CREATE INDEX messages_by_speaker ON messages(src, room, ts);  -- reply lookups in `replies`
    CREATE INDEX messages_by_ts ON messages(ts);
    CREATE TABLE goals(n INTEGER, goal TEXT, start_time TEXT, end_time TEXT);
    CREATE TABLE agent_goals(agent TEXT, name TEXT, short TEXT, description TEXT, start_time TEXT, end_time TEXT);
    CREATE TABLE days(date TEXT PRIMARY KEY, day INTEGER);
    CREATE TABLE sessions(id TEXT PRIMARY KEY, agent TEXT, ts TEXT, end_ts TEXT, goal TEXT, short TEXT,
                          turns INTEGER, bash INTEGER, gui INTEGER, chat INTEGER, failed INTEGER);
    CREATE INDEX sessions_by_agent ON sessions(agent, ts);
    CREATE INDEX sessions_by_ts ON sessions(ts);
    CREATE TABLE turns(id TEXT PRIMARY KEY, session TEXT, agent TEXT, ts TEXT, kind TEXT, action TEXT, output TEXT,
                       error TEXT, failed INTEGER, reasoning TEXT, shot INTEGER);
    CREATE INDEX turns_by_agent ON turns(agent, ts);
    CREATE INDEX turns_by_session ON turns(session, ts);
    CREATE INDEX turns_by_ts ON turns(ts);
    CREATE TABLE events(id TEXT PRIMARY KEY, agent TEXT, ts TEXT, type TEXT, text TEXT, session TEXT, reasoning TEXT);
    CREATE INDEX events_by_agent ON events(agent, ts);
    CREATE INDEX events_by_session ON events(session);
    CREATE TABLE memories(id TEXT PRIMARY KEY, agent TEXT, ts TEXT, chars INTEGER, added TEXT, dropped INTEGER);
    CREATE INDEX memories_by_agent ON memories(agent, ts);
    CREATE TABLE memory_days(agent TEXT, date TEXT, ts TEXT, content TEXT, PRIMARY KEY(agent, date));
    CREATE TABLE summaries(id TEXT PRIMARY KEY, type TEXT, date TEXT, target TEXT, ts TEXT, content TEXT);
    CREATE TABLE terms(term TEXT PRIMARY KEY, first_ts TEXT, first_agent TEXT, first_msg TEXT, uses INTEGER, agents INTEGER);
    CREATE VIRTUAL TABLE messages_fts USING fts5(content, reasoning, content='messages');
    CREATE VIRTUAL TABLE turns_fts USING fts5(action, output, error, reasoning, content='turns');
    CREATE VIRTUAL TABLE sessions_fts USING fts5(goal, content='sessions');
    CREATE VIRTUAL TABLE events_fts USING fts5(text, reasoning, content='events');
    CREATE VIRTUAL TABLE memories_fts USING fts5(added, content='memories');
    CREATE VIRTUAL TABLE summaries_fts USING fts5(content, content='summaries');'''
FTS = ['messages', 'turns', 'sessions', 'events', 'memories', 'summaries']

EVENT_TEXT = {
    'CONSOLIDATE': lambda d: f"next goal: {d.get('nextSessionGoal') or ''}",
    'START_USING_COMPUTER': lambda d: f"session goal: {d.get('sessionGoal') or ''}",
    'STOP_USING_COMPUTER': lambda d: f"report: {d.get('summary') or ''}",
    'PAUSE': lambda d: f"paused {d.get('seconds')} s",
    'SEARCH_HISTORY': lambda d: f"query: {d.get('query') or ''}\nanswer: {d.get('answerToQuery') or ''}",
    'ENTER_ROOM': lambda d: f"moved from #{d.get('previousRoomName')} to #{d.get('roomName')}",
    'REQUEST_HUMAN_HELPER': lambda d: f"task: {d.get('sessionGoal') or ''}\nconstraints: {d.get('humanConstraints') or ''}",
    'STOP_HUMAN_USE_SESSION': lambda d: f"ended: {d.get('endReason')}\ncomment: {d.get('endComment') or ''}\nsummary: {d.get('summary') or ''}",
    'OUTREACH_APPROVAL_REQUEST': lambda d: (f"to: {d.get('recipient')} via {d.get('medium')}\nwhy: {d.get('rationale') or ''}\n"
                                            f"message: {d.get('messageContent') or ''}"),
    'OUTREACH_APPROVAL_RESPONSE': lambda d: (f"{'approved' if d.get('approval') else 'declined'}: {d.get('recipient')} via "
                                             f"{d.get('medium')}\nreviewer: {d.get('adminComment') or ''}"),
}


def window(snap, days=None, goal=None, since=None, until=None, everything=False):
    """The Pacific-time range [lo, hi) of the heavy tables. Default: the last 7 days of the dataset."""
    if everything:
        return '', END
    if goal:
        hit = [g for g in rows(snap, 'village_goals.jsonl.gz') if any(q.lower() in g['goal'].lower() for q in goal)]
        if not hit:
            sys.exit(f'--goal {goal!r} matched no village goal')
        return pt(min(g['start_time'] for g in hit)), max(pt(g['end_time']) or END for g in hit)
    if since or until:
        return since or '', until or END
    latest = datetime.fromisoformat(pt(max(m['created_at'] for m in rows(snap, 'chat_messages.jsonl.gz')))[:10])
    return (latest - timedelta(days=(days or 7) - 1)).date().isoformat(), (latest + timedelta(days=1)).date().isoformat()


def near(lo, hi):
    """A cheap test on a raw line, 'may hold a row in [lo, hi)', so most lines are never parsed. None = parse them all.
    Rows carry created_at as UTC text, so one of the window's dates (and a day each side) must appear in the line."""
    if not lo or hi.startswith(END):
        return None
    a, b = datetime.fromisoformat(lo[:10]) - timedelta(days=1), datetime.fromisoformat(hi[:10]) + timedelta(days=1)
    if (b - a).days > 120:
        return None
    rx = re.compile(b'"(?:' + b'|'.join((a + timedelta(days=i)).date().isoformat().encode() for i in range((b - a).days + 1)) + b')[ T]')
    return lambda line: rx.search(line) is not None


def build(days=None, goal=None, since=None, until=None, everything=False, log=print):
    t0 = time.time()
    took = lambda: f'({time.time() - t0:.0f}s)'
    snap = snapshot()
    lo, hi = window(snap, days, goal, since, until, everything)
    maybe = near(lo, hi)
    roster = list(rows(snap, 'agents.jsonl.gz'))
    agents = {r['id']: r['name'] for r in roster}
    rooms = {r['id']: r['name'] for r in rows(snap, 'chat_rooms.jsonl.gz')}
    goals = sorted((pt(r['start_time']), pt(r['end_time']), r['goal'].strip()) for r in rows(snap, 'village_goals.jsonl.gz'))

    tmp = DB.with_suffix('.tmp')
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;' + SCHEMA)
    con.executemany('INSERT INTO nodes VALUES (?,?,?)',
                    [*((r['id'], r['name'], r['model_string']) for r in roster), ('human', 'Human', '')])
    con.executemany('INSERT INTO goals VALUES (?,?,?,?)', [(i + 1, g, s, e) for i, (s, e, g) in enumerate(goals)])
    con.executemany('INSERT INTO agent_goals VALUES (?,?,?,?,?,?)',
                    [(r['agent_id'], r['name'], r['short_name'], r['description'], pt(r['start_time']), pt(r['end_time']))
                     for r in rows(snap, 'agent_goals.jsonl.gz')])
    con.executemany('INSERT INTO summaries VALUES (?,?,?,?,?,?)',
                    [(r['id'], r['type'], r['summary_date'], r['summary_target'], pt(r['created_at']),
                      re.sub(r'</?[a-z_]+>', '', r['content'] or '')) for r in rows(snap, 'summaries.jsonl.gz')])

    # events: who the human speakers are, each chat message's reasoning, and every event that is not a chat message
    speaker, talk_why, ev = {}, {}, []
    for e in rows(snap, 'events.jsonl.gz'):
        d = e['data'] or {}
        k = d.get('actionType')
        if k == 'USER_TALK':
            speaker[d.get('messageId')] = d.get('speakerName') or ''
        elif k == 'AGENT_TALK':
            if (mid := d.get('messageId') or d.get('chatMessageId')) and (why := joined(thoughts(d.get('output')))):
                talk_why[mid] = cut(why, CUT['reasoning'])
        elif k and k != 'USER_NAME_CHANGE':
            ev.append((e['id'], d.get('agentId') or d.get('speakerId'), pt(e['created_at']), k,
                       cut(EVENT_TEXT.get(k, lambda d: '')(d), CUT['added']), d.get('computerUseSessionId'),
                       cut(joined(thoughts(d.get('output'))), CUT['reasoning'])))
    con.executemany('INSERT INTO events VALUES (?,?,?,?,?,?,?)', ev)
    log(f'events: {len(ev):,}  {took()}')

    humans = {n.lower() for n in speaker.values() if len(n) >= 3} - NOT_HUMAN - {n.lower() for n in agents.values()}
    mentions = extractor(agents, humans)
    edges, messages, first, uses, users = [], [], {}, Counter(), defaultdict(set)
    for m in sorted(rows(snap, 'chat_messages.jsonl.gz'), key=lambda m: m['created_at']):
        if m['speaker_type'] == 'agent':
            src = m['agent_speaker_id']
        elif speaker.get(m['id']) == 'automated':
            continue
        else:
            src = 'human'
        room, ts, text = rooms.get(m['room_id']), pt(m['created_at']), m['content'] or ''
        messages.append((m['id'], src, room, ts, text, talk_why.get(m['id'], '')))
        for dst, kind in mentions(text, src).items():
            edges.append((m['id'], src, dst, kind, room, ts))
        if src != 'human':  # coined terms: who used a word or a name first, and how far it spread
            for w in {w.lower() for w in TERM.findall(text)}:
                first.setdefault(w, (ts, src, m['id']))
                uses[w] += 1
                users[w].add(src)
    con.executemany('INSERT INTO edges VALUES (?,?,?,?,?,?)', edges)
    con.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?)', messages)
    con.executemany('INSERT INTO terms VALUES (?,?,?,?,?,?)', [(w, *first[w], n, len(users[w])) for w, n in uses.items() if n >= 3])
    # village day N = the Nth calendar day since the village opened (Day 1 = 2 April 2025), weekends included
    day1 = datetime.fromisoformat(messages[0][3][:10])
    con.executemany('INSERT INTO days VALUES (?,?)', [((day1 + timedelta(days=i)).date().isoformat(), i + 1) for i in
                                                      range((datetime.fromisoformat(messages[-1][3][:10]) - day1).days + 1)])
    log(f'chat: {len(messages):,} messages, {len(edges):,} mention edges  {took()}')

    sess = {s['id']: [s['id'], s['agent_id'], pt(s['created_at']), None, (s['session_goal'] or '').strip(),
                      (s['short_displayed_session_goal'] or '').strip(), 0, 0, 0, 0, 0]
            for s in rows(snap, 'computer_use_sessions.jsonl.gz')}

    def lines(name):  # raw lines that may fall in the window
        with gzip.open(snap / name, 'rb') as f:
            for line in f:
                if not maybe or maybe(line):
                    yield json.loads(line)

    n_turns, batch, said = 0, [], {}

    def flush():
        con.executemany('INSERT OR IGNORE INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?)', batch)
        batch.clear()

    def tally(s, ts, kind, failed):
        s[3] = max(s[3] or ts, ts)
        s[6] += 1
        s[7] += kind == 'bash'
        s[8] += kind == 'gui'
        s[9] += kind == 'chat'
        s[10] += failed

    for t in lines('computer_use_turns.jsonl.gz'):
        ts, s = pt(t['created_at']), sess.get(t['session_id'])
        if not (lo <= ts < hi) or not s:
            continue
        kind, text = action_of(t['agent_action'])
        err = (t['error'] or '').strip()
        failed = int(bool(err) and (kind != 'bash' or bool(FAIL.search(err))))
        why = cut(thought(t['agent_messages']), CUT['reasoning'])
        batch.append((t['id'], s[0], s[1], ts, kind, cut(text, CUT['action']), cut(t['output'], CUT['output']),
                      cut(err, CUT['error']), failed, why, int(t.get('screenshot_is_redacted') is not None)))
        tally(s, ts, kind, failed)
        if kind == 'chat' and why:
            said[(s[1], text.strip()[:200])] = why
        n_turns += 1
        if len(batch) >= 20000:
            flush()
            log(f'  turns: {n_turns:,}  {took()}')
    # Claude Code agents: each tool call is a turn; its result arrives in another row, sometimes before the call
    cc, results = [], {}
    for r in lines('claude_code_messages.jsonl.gz'):
        ts = pt(r['created_at'])
        if not (lo <= ts < hi) or r['message_type'] not in ('assistant', 'user') or not isinstance(r['content'], dict):
            continue
        items = (r['content'].get('message') or {}).get('content') or []
        items = [u for u in items if isinstance(u, dict)] if isinstance(items, list) else []
        if r['message_type'] == 'user':
            for u in items:
                if u.get('tool_use_id'):
                    c = u.get('content') or ''
                    results[u['tool_use_id']] = (c if isinstance(c, str) else ' '.join(i.get('text', '') for i in c if isinstance(i, dict)),
                                                 bool(u.get('is_error')))
            continue
        why = cut(joined(thoughts(r['content'])) or joined(u.get('text') for u in items if u.get('type') == 'text'), CUT['reasoning'])
        for u in items:
            if u.get('type') == 'tool_use':
                inp = u.get('input') or {}
                kind = 'bash' if u['name'] == 'Bash' else 'other'
                text = inp.get('command') or '' if kind == 'bash' else f"{u['name']} {json.dumps(inp, ensure_ascii=False)}"
                cc.append((u['id'], r['sdk_session_id'], r['agent_id'], ts, kind, cut(text, CUT['action']), why))
    for uid, sid, agent, ts, kind, text, why in cc:
        out, bad = results.get(uid, ('', False))
        batch.append((uid, sid, agent, ts, kind, text, '' if bad else cut(out, CUT['output']), cut(out, CUT['error']) if bad else '',
                      int(bad), why, 0))
        s = sess.setdefault(sid, [sid, agent, ts, ts, '(a Claude Code session: it sets no session goal)', 'Claude Code', 0, 0, 0, 0, 0])
        s[2] = min(s[2], ts)
        tally(s, ts, kind, bad)
    flush()
    n_turns += len(cc)
    con.executemany('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)', sess.values())
    con.executemany("UPDATE messages SET reasoning = ? WHERE src = ? AND reasoning = '' AND substr(trim(content),1,200) = ?",
                    [(why, a, text) for (a, text), why in said.items()])
    log(f'sessions: {len(sess):,}; actions in the window: {n_turns:,}  {took()}')

    # memories: per version, the lines it added; per agent and day, the day's last version whole.
    # They go through a temporary table so that SQLite, not Python, holds and sorts the texts (several GB for all days).
    con.execute('CREATE TEMP TABLE raw(ts TEXT, id TEXT, agent TEXT, content TEXT)')
    before = (datetime.fromisoformat(lo[:10]) - timedelta(days=1)).date().isoformat() if lo else ''
    for m in lines('agent_memories.jsonl.gz'):
        if before <= (ts := pt(m['created_at'])) < hi:  # the day before the window gives the first diff its baseline
            con.execute('INSERT INTO raw VALUES (?,?,?,?)', (ts, m['id'], m['agent_id'], m['content'] or ''))
    old, cur, day_last, n_mem = None, None, {}, 0
    for ts, mid, agent, text in con.execute('SELECT * FROM raw ORDER BY agent, ts'):
        if agent != cur:
            for k, v in day_last.items():
                con.execute('INSERT INTO memory_days VALUES (?,?,?,?)', (*k, *v))
            cur, old, day_last = agent, None, {}
        new = text.splitlines()
        if ts >= lo:
            added = [l for l in new if l.strip() and l not in old] if old is not None else ['(the first version in the database: see `memory`)']
            con.execute('INSERT INTO memories VALUES (?,?,?,?,?,?)',
                        (mid, agent, ts, len(text), cut('\n'.join(added), CUT['added']), len(old - set(new)) if old is not None else 0))
            day_last[(agent, ts[:10])] = (ts, text)
            n_mem += 1
        old = set(new)
    for k, v in day_last.items():
        con.execute('INSERT INTO memory_days VALUES (?,?,?,?)', (*k, *v))
    con.execute('DROP TABLE raw')
    log(f'memories in the window: {n_mem:,}  {took()}')

    for t in FTS:
        con.execute(f"INSERT INTO {t}_fts({t}_fts) VALUES ('rebuild')")
    span = con.execute('SELECT min(ts), max(ts) FROM turns').fetchone()
    manifest = snap / 'manifest.json'
    con.executemany('INSERT INTO meta VALUES (?,?)', {
        'built': datetime.now().isoformat(' ', 'seconds'), 'dataset': str(snap),
        'exported': json.loads(manifest.read_text()).get('exportedAt', '') if manifest.exists() else '',
        'chat_from': messages[0][3][:16] if messages else '', 'chat_to': messages[-1][3][:16] if messages else '',
        'actions_from': (span[0] or '')[:16], 'actions_to': (span[1] or '')[:16],
        'window_from': lo[:16], 'window_to': hi[:16],
    }.items())
    con.commit()
    con.close()
    tmp.replace(DB)  # swap only after a complete build
    log(f'{DB.name}: {DB.stat().st_size / 1e6:,.0f} MB {took()}. Chat, sessions and events: full history. '
        f'Actions and memories: {(span[0] or "none")[:16]} to {(span[1] or "none")[:16]} Pacific time.')
