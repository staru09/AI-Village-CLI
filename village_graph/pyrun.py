"""`village py`: read-only Python over village.db, for the counts, joins and samples the fixed commands cannot do.

The code runs in a child Python with a time, CPU and memory limit. An audit hook refuses file writes, network use and new
processes, and the database is opened read-only with ATTACH refused. Names ready in the code:
    db        sqlite3 connection to village.db (read-only), labels.db attached as L when it exists
    q(sql, *params)        -> list of rows
    names     {agent id: name}         ids  {name: agent id}
    ref(kind, id)          -> 'm:0a1b2c3d4e5f' (the refs every other command prints)
    span(n)                -> (start, end) of village goal n: filter any table with ts >= start AND ts < end
    sample(items, n=25, seed=41) -> a seeded random sample, to check a pattern by reading
    re, json, math, random, statistics, collections, itertools, datetime
Print what you want to see.
"""
import os, resource, subprocess, sys

from . import db

LIMIT_S, MEM = 90, 6 << 30  # wall-clock seconds, address space

BOOT = r'''
import sys, os, sqlite3, re, json, math, random, statistics, collections, itertools, datetime
DB, LABELS = sys.argv[1], sys.argv[2]
db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
if os.path.exists(LABELS):
    db.execute('ATTACH DATABASE ? AS L', (f'file:{LABELS}?mode=ro',))
db.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY if action in (24, 25) else sqlite3.SQLITE_OK)  # no ATTACH / DETACH
q = lambda sql, *params: db.execute(sql, params).fetchall()
names = dict(q('SELECT id, name FROM nodes')); ids = {v: k for k, v in names.items()}
ref = lambda kind, i: f"{kind}:{i if str(i).startswith('toolu_') else str(i).replace('-', '')[:12]}"
span = lambda n: q("SELECT start_time, coalesce(end_time, '9999') FROM goals WHERE n = ?", n)[0]
sample = lambda items, n=25, seed=41: random.Random(seed).sample(list(items), min(n, len(list(items))))
WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
READ = tuple(os.path.realpath(d) + os.sep for d in {sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(DB)})
def hook(event, args):
    if event == 'open' and ((isinstance(args[1], str) and any(c in args[1] for c in 'wax+')) or (args[1] is None and args[2] & WRITE)):
        raise PermissionError('read-only: no file writes')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)) and not os.path.realpath(os.fsdecode(args[0])).startswith(READ):
        raise PermissionError('only the database folder and Python itself can be read')
    if event.startswith(('socket.', 'subprocess.', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork', 'os.kill', 'ctypes.',
                         'os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.truncate', 'shutil.', 'urllib.', 'http.client.')):
        raise PermissionError(f'not allowed here: {event}')
    if event == 'sqlite3.connect':
        raise PermissionError('use the open connection `db`')
    if event == 'sqlite3.enable_load_extension' and args[1]:
        raise PermissionError('no extensions')
sys.addaudithook(hook)  # ponytail: an audit hook, not a container; run inside one if untrusted people can submit code
code = sys.stdin.read()
exec(compile(code, '<py>', 'exec'), {'__name__': '__main__', 'db': db, 'q': q, 'names': names, 'ids': ids, 'ref': ref, 'sample': sample, 'span': span,
     're': re, 'json': json, 'math': math, 'random': random, 'statistics': statistics, 'collections': collections, 'itertools': itertools,
     'datetime': datetime})
'''


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (LIMIT_S, LIMIT_S))
    resource.setrlimit(resource.RLIMIT_AS, (MEM, MEM))


def run(code):
    """Python source -> what it printed (or its error), as text."""
    try:
        p = subprocess.run([sys.executable, '-I', '-c', BOOT, str(db.DB), str(db.DB.with_name('labels.db'))], input=code, text=True,
                           capture_output=True, timeout=LIMIT_S, env={'PATH': '/usr/bin:/bin', 'PYTHONIOENCODING': 'utf-8'}, preexec_fn=limits)
    except subprocess.TimeoutExpired:
        return f'stopped after {LIMIT_S} s: narrow the query (a date range, one agent, LIMIT) or index on ts/agent'
    err = p.stderr.strip().splitlines()
    return (p.stdout + (('\n' if p.stdout else '') + 'error: ' + (err[-1] if err else f'exit {p.returncode}') if p.returncode else '')).strip() or '(no output: print what you want to see)'


def py(a):
    code = open(a.file).read() if a.file else a.code if a.code else sys.stdin.read()
    return [('text', 'py', run(code))]
