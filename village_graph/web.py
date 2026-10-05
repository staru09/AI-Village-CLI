"""village web: the CLI in a browser. One page that runs a command on this server and renders its blocks.

Every command run in the terminal is also remembered (history.jsonl, next to village.db), so the page can show what
you just ran there. Stdlib only. It binds to localhost: there is no login, so tunnel it rather than exposing it.
"""
import json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import cli, db, evidence
from .core import connect, lookup

PAGE = Path(__file__).with_name('web.html')
NEVER = ('build', 'eval', 'web', 'py')  # long jobs, the server itself, and running code: terminal only
KEEP = 150                        # remembered runs
LOCK = threading.Lock()
JOBS = {}  # id -> the run's record once done, None while it runs (?async=1: start now, poll /api/job?id=)


def history_file():
    return db.DB.with_name('history.jsonl')


def remember(cmd, blocks, secs, source, error=None):
    """Append one run to the history -> its record. Never fails the command it records."""
    rec = {'id': round(time.time(), 3), 'cmd': cmd, 'source': source, 'secs': round(secs, 1), 'error': error, 'blocks': blocks or []}
    try:
        with LOCK:
            f = history_file()
            with f.open('a') as out:
                out.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')
            if f.stat().st_size > 40e6:  # ponytail: trim by rewriting; a real store if histories ever need to be kept
                f.write_text(''.join(f.read_text().splitlines(keepends=True)[-KEEP // 2:]))
    except OSError:
        pass
    return rec


def history():
    """The remembered runs, oldest first (the last KEEP)."""
    try:
        lines = history_file().read_text().splitlines()[-KEEP:]
    except OSError:
        return []
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except ValueError:  # a half-written line
            pass
    return out


def meta():
    """What the page needs once: the commands, the agents' names, what is loaded, and example commands that will work."""
    con = connect()
    try:
        m = dict(con.execute('SELECT key, value FROM meta'))
        g = con.execute("SELECT n, goal FROM goals WHERE start_time < ? AND coalesce(end_time, '9999') > ? ORDER BY start_time LIMIT 1",
                        (m.get('actions_to') or '', m.get('actions_from') or '9999')).fetchone() or \
            con.execute('SELECT n, goal FROM goals ORDER BY start_time DESC LIMIT 1').fetchone()
        busy = con.execute('SELECT n.name, substr(t.ts, 1, 10) FROM turns t JOIN nodes n ON n.id = t.agent GROUP BY 1, 2 ORDER BY count(*) DESC LIMIT 1').fetchone()
        day = busy and con.execute('SELECT day FROM days WHERE date = ?', (busy[1],)).fetchone()
        return {'commands': [c for c in cli.command_list() if c['name'] not in NEVER],
                'agents': [r[0] for r in con.execute("SELECT name FROM nodes WHERE id != 'human' ORDER BY name")],
                'coverage': {k: m.get(k, '') for k in ('built', 'exported', 'chat_from', 'chat_to', 'actions_from', 'actions_to')},
                'examples': ['goals', f'overview --goal {g[0]}', *([f'sessions --agent "{busy[0]}" --day {day[0]}', f'timeline "{busy[0]}" --day {day[0]}']
                                                                    if busy and day else []),
                             f'find "error OR failed" --goal {g[0]} --in output', f'count "sorry|apolog|my mistake" --goal {g[0]} --by maker',
                             f'top-pairs --goal {g[0]}', 'schema']}
    finally:
        con.close()


class Handler(BaseHTTPRequestHandler):
    llm = True

    def send(self, body, kind='application/json', status=200):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith(('text', 'application/json')) else ''))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'max-age=86400' if kind == 'image/png' else 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == '/':
                return self.send(PAGE.read_bytes(), 'text/html')
            if u.path == '/api/meta':
                return self.send(meta())
            if u.path == '/api/history':
                runs = history()
                if 'id' in q:
                    return self.send(next((r for r in runs if str(r['id']) == q['id']), {'error': 'That run is no longer in the history.', 'blocks': []}))
                return self.send([{k: r[k] for k in ('id', 'cmd', 'source', 'secs', 'error')} for r in runs[::-1]])
            if u.path == '/api/run':
                cmd = q.get('cmd', '').strip().removeprefix('village ').strip()
                if '--deep' in cmd.split():  # research mode runs model-written code and long jobs: terminal only
                    return self.send(remember(cmd, None, 0, 'web', '`--deep` is not available here: run it in a terminal.'))
                deny = NEVER + (() if self.llm else cli.SPENDS)
                if q.get('async') and cmd:  # a long question: answer at once with a job id, so no proxy timeout cuts it off
                    job = f'{time.time():.6f}'
                    JOBS[job] = None
                    def work():
                        t = time.time()
                        blocks, err = cli.run_cmd(cmd, deny=deny)
                        JOBS[job] = remember(cmd, blocks, time.time() - t, 'web', err)
                    threading.Thread(target=work, daemon=True).start()
                    return self.send({'job': job})
                t = time.time()
                blocks, err = cli.run_cmd(cmd, deny=deny) if cmd else (None, 'Type a command, for example: goals')
                return self.send(remember(cmd, blocks, time.time() - t, 'web', err))
            if u.path == '/api/job':
                if q.get('id') not in JOBS:
                    return self.send({'error': 'no such job'}, status=404)
                rec = JOBS[q['id']]
                if rec is not None:
                    JOBS.pop(q['id'])  # ponytail: results live in memory until fetched once; a restart drops running jobs
                return self.send({'done': rec is not None, **({'run': rec} if rec else {})})
            if u.path.startswith('/shot/'):
                con = connect()
                try:
                    kind, rid = lookup(con, unquote(u.path[6:]).removesuffix('.png'))
                    ts = con.execute('SELECT ts FROM turns WHERE id = ?', (rid,)).fetchone()[0] if kind == 't' else None
                finally:
                    con.close()
                return self.send(evidence.png(rid, ts)[0], 'image/png') if ts else self.send({'error': 'only actions have screenshots'}, status=404)
            self.send({'error': 'not found'}, status=404)
        except SystemExit as e:  # the CLI's way of saying "no such ref", "no screenshot"
            self.send({'error': str(e.code)}, status=404)
        except BrokenPipeError:
            pass

    def log_message(self, *args):
        pass


def serve(host, port, llm=False):
    Handler.llm = llm or host in ('127.0.0.1', 'localhost', '::1')
    server = ThreadingHTTPServer((host, port), Handler)
    print(f'village web: http://{host}:{port}  (Ctrl-C to stop)\n'
          f'  On a remote machine, tunnel it: ssh -L {port}:127.0.0.1:{port} <host>   There is no login: do not expose it.\n'
          f'  Commands that call a model (ask, label, look, check) are {"allowed" if Handler.llm else "off (start with --llm to allow them)"}.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
