from . import db, web
from .commands import parser, query


def table(headers, rows):
    rows = [['' if v is None else str(v) for v in r] for r in rows]
    widths = [max(map(len, col)) for col in zip(headers, *rows)]
    for r in [headers, *rows]:
        print('  '.join(v.ljust(w) for v, w in zip(r, widths)).rstrip())


def main():
    a = parser().parse_args()
    if a.cmd == 'build':
        return db.build(a.days)
    if a.cmd == 'web':
        return web.serve(a.host, a.port)
    r = query(a)
    print('# graph covers', r['covers'])
    for i, (headers, rows) in enumerate(r['tables']):
        if i:
            print()
        table(headers, rows)
