import contextlib, io, json, shlex
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db
from .commands import parser, query


def api(cmd):
    """Run one CLI command string for the web UI. Usage/lookup errors come back as {'error': ...}."""
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            a = parser().parse_args(shlex.split(cmd))
            if a.cmd == 'web':
                raise SystemExit('the web UI is already running')
            if a.cmd == 'build':
                db.build(a.days)
                return {'text': out.getvalue()}
            r = query(a)
    except SystemExit as e:
        if e.code == 0:  # -h / --help
            return {'text': out.getvalue()}
        return {'error': e.code if isinstance(e.code, str) else out.getvalue()}
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}
    r['flags'] = ''.join(f' --{k} {shlex.quote(v)}' for k in ('since', 'until', 'room', 'goal', 'kind')
                         if (v := getattr(a, k)))
    return r


def serve(host, port):
    page = Path(__file__).with_name('web.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/':
                body, ctype = page, 'text/html; charset=utf-8'
            elif url.path == '/api':
                body = json.dumps(api(parse_qs(url.query).get('cmd', [''])[0])).encode()
                ctype = 'application/json'
            else:
                return self.send_error(404)
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    print(f'village-graph web UI: http://{host}:{port}')
    # ponytail: single-threaded (stdout capture is process-global); a `build` from the UI blocks until done.
    HTTPServer((host, port), Handler).serve_forever()
