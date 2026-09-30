import gzip, json, os, sqlite3, sys
from datetime import datetime, timedelta
from pathlib import Path

from .mentions import extractor

DB = Path(__file__).resolve().parents[1] / 'village.db'
NOT_HUMAN = {'automated', 'all', 'team', 'everyone', 'agents'}


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


SCHEMA = '''
    CREATE TABLE nodes(id TEXT PRIMARY KEY, name TEXT UNIQUE, model TEXT);
    CREATE TABLE edges(msg_id TEXT, src TEXT, dst TEXT, kind TEXT, room TEXT, ts TEXT, PRIMARY KEY(msg_id, dst));
    CREATE TABLE messages(id TEXT PRIMARY KEY, src TEXT, room TEXT, ts TEXT, content TEXT);
    CREATE INDEX messages_by_speaker ON messages(src, room, ts);  -- reply lookups in `replies`
    CREATE TABLE goals(goal TEXT, start_time TEXT, end_time TEXT);'''


def build(days):
    snap = snapshot()
    roster = list(rows(snap, 'agents.jsonl.gz'))
    agents = {r['id']: r['name'] for r in roster}
    rooms = {r['id']: r['name'] for r in rows(snap, 'chat_rooms.jsonl.gz')}
    goals = [(r['goal'], r['start_time'], r['end_time']) for r in rows(snap, 'village_goals.jsonl.gz')]

    speaker = {}  # chat message id -> human display name
    with gzip.open(snap / 'events.jsonl.gz', 'rb') as f:
        for line in f:
            if b'"USER_TALK"' in line:
                d = json.loads(line)['data']
                if d.get('actionType') == 'USER_TALK':
                    speaker[d['messageId']] = d.get('speakerName') or ''
    agent_names = {n.lower() for n in agents.values()}
    humans = {n.lower() for n in speaker.values() if len(n) >= 3} - NOT_HUMAN - agent_names
    mentions = extractor(agents, humans)

    msgs = list(rows(snap, 'chat_messages.jsonl.gz'))
    cutoff = ''
    if days:
        latest = datetime.fromisoformat(max(m['created_at'] for m in msgs))
        cutoff = (latest - timedelta(days=days)).isoformat(' ')
    msgs = [m for m in msgs if m['created_at'] >= cutoff]

    edges, messages = [], []
    for m in msgs:
        if m['speaker_type'] == 'agent':
            src = m['agent_speaker_id']
        elif speaker.get(m['id']) == 'automated':
            continue
        else:
            src = 'human'
        room = rooms.get(m['room_id'])
        messages.append((m['id'], src, room, m['created_at'], m['content'] or ''))
        for dst, kind in mentions(m['content'] or '', src).items():
            edges.append((m['id'], src, dst, kind, room, m['created_at']))

    tmp = DB.with_suffix('.tmp')
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    con.executemany('INSERT INTO nodes VALUES (?,?,?)',
                    [*((r['id'], r['name'], r['model_string']) for r in roster), ('human', 'Human', '')])
    con.executemany('INSERT INTO edges VALUES (?,?,?,?,?,?)', edges)
    con.executemany('INSERT INTO messages VALUES (?,?,?,?,?)', messages)
    con.executemany('INSERT INTO goals VALUES (?,?,?)', goals)
    con.commit()
    con.close()
    tmp.replace(DB)  # swap only after a complete build

    ts = [m['created_at'] for m in msgs] or ['-']
    print(f'window: {min(ts)[:19]} -> {max(ts)[:19]}  '
          f'({len(msgs)} messages, {"last %d days" % days if days else "full history"})')
    kinds = {}
    for e in edges:
        kinds[e[3]] = kinds.get(e[3], 0) + 1
    print(f'edges: {len(edges)}  ' + '  '.join(f'{k}={v}' for k, v in sorted(kinds.items())))
