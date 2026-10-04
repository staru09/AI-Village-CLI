"""Who talks to whom: the mention commands (pair, neighbors, top-pairs, hubs, agents, examples, ignored, replies)."""
import argparse, statistics

from .core import node, one, ref, where

# message text for tables: first 300 chars on one line
SNIPPET = ("replace(substr(m.content,1,300), char(10), ' ') "
           "|| CASE WHEN length(m.content) > 300 THEN '…' ELSE '' END")


def degrees(con, w, p):
    """{node id: [partners, out, in, total]} under the filter."""
    return {n: r for n, *r in con.execute(
        f"SELECT n, count(DISTINCT o), sum(out_), sum(1-out_), count(*) FROM ("
        f"  SELECT src n, dst o, 1 out_ FROM edges WHERE {w} UNION ALL"
        f"  SELECT dst, src, 0 FROM edges WHERE {w}) GROUP BY n", (*p, *p))}


def run(con, a):
    """A parsed mention command -> blocks. `edges` (src name, dst name, count) picks the sample messages shown below."""
    names = dict(con.execute('SELECT id, name FROM nodes'))
    w, p = where(con, a)
    out, edges = [], []
    table = lambda title, headers, rows: out.append(('table', title, headers, [list(r) for r in rows]))

    if a.cmd == 'pair':
        (x, xn), (y, yn) = node(con, a.a), node(con, a.b)
        rows = [[f'{s} -> {d}', *con.execute(f"SELECT coalesce(sum(kind='addressed'),0), coalesce(sum(kind='named'),0), count(*), "
                                             f"substr(min(ts),1,16), substr(max(ts),1,16) FROM edges "
                                             f"WHERE src=? AND dst=? AND {w}", (si, di, *p)).fetchone()]
                for (si, s), (di, d) in (((x, xn), (y, yn)), ((y, yn), (x, xn)))]
        table('mentions between the two', ['direction', '@', 'named', 'total', 'first', 'last'], rows)
        table(f'per {a.by}', [a.by, f'{xn} -> {yn}', f'{yn} -> {xn}'], con.execute(
            f"SELECT substr(ts,1,{10 if a.by == 'day' else 7}) b, sum(src=?), sum(src=?) FROM edges "
            f"WHERE ((src=? AND dst=?) OR (src=? AND dst=?)) AND {w} GROUP BY b ORDER BY b",
            (x, y, x, y, y, x, *p)))
        edges = [(xn, yn, rows[0][3]), (yn, xn, rows[1][3])]

    elif a.cmd == 'neighbors':
        x, xn = node(con, a.a)
        rows = [[names[o], *r] for o, *r in con.execute(
            f"SELECT CASE WHEN src=? THEN dst ELSE src END o, sum(src=?), sum(dst=?), "
            f"sum(kind='addressed'), sum(kind='named'), count(*) t FROM edges "
            f"WHERE (src=? OR dst=?) AND {w} GROUP BY o ORDER BY t DESC LIMIT ?",
            (x, x, x, x, x, *p, a.limit))]
        table(f'who {xn} mentions (out) and is mentioned by (in)', ['partner', 'out', 'in', '@', 'named', 'total'], rows)
        edges = [e for r in rows for e in ((xn, r[0], r[1]), (r[0], xn, r[2]))]

    elif a.cmd == 'top-pairs':
        rows = [[names[i], names[j], *r] for i, j, *r in con.execute(
            f"SELECT min(src,dst) i, max(src,dst) j, sum(src<dst), sum(src>dst), "
            f"sum(kind='addressed'), sum(kind='named'), count(*) t FROM edges "
            f"WHERE {w} GROUP BY i, j ORDER BY t DESC LIMIT ?", (*p, a.limit))]
        table('strongest pairs by mentions', ['a', 'b', 'a->b', 'b->a', '@', 'named', 'total'], rows)
        edges = [e for r in rows for e in ((r[0], r[1], r[2]), (r[1], r[0], r[3]))]

    elif a.cmd == 'hubs':
        d = degrees(con, w, p)
        ids = sorted(d, key=lambda n: (-d[n][0], -d[n][3]))[:a.limit]
        table('agents by number of distinct partners', ['agent', 'partners', 'out', 'in', 'total'], [[names[n], *d[n]] for n in ids])

    elif a.cmd == 'agents':
        wm, pm = where(con, a, kind=False)  # messages have no kind
        sent = {s: r for s, *r in con.execute(
            f"SELECT src, count(*), substr(min(ts),1,16), substr(max(ts),1,16) FROM messages WHERE {wm} GROUP BY src", pm)}
        d, models = degrees(con, w, p), dict(con.execute('SELECT id, model FROM nodes'))
        rows = []
        for i in sorted(sent.keys() | d.keys(), key=lambda i: -sent.get(i, [0])[0])[:a.limit]:
            n, first, last = sent.get(i, (0, None, None))
            rows.append([names[i], models[i], n, *d.get(i, (0, 0, 0, 0))[:3], first, last])
        table('roster', ['agent', 'model', 'msgs', 'partners', 'out', 'in', 'first', 'last'], rows)

    elif a.cmd == 'examples':
        (x, xn), (y, yn) = node(con, a.a), node(con, a.b)
        we, pe = where(con, a, 'e.')
        table(f'messages where {xn} mentions {yn}, newest first', ['time', 'ref', 'kind', 'room', f'{xn} -> {yn}'],
              [(t, ref('m', i), k, r, s) for t, i, k, r, s in con.execute(
                  f"SELECT substr(e.ts,1,16), e.msg_id, e.kind, e.room, {SNIPPET} FROM edges e JOIN messages m ON m.id = e.msg_id "
                  f"WHERE e.src=? AND e.dst=? AND {we} ORDER BY e.ts DESC LIMIT ?", (x, y, *pe, a.limit))])

    elif a.cmd == 'ignored':
        rows = [[names[s], names[d], n, back, f'{100 * back // n}%'] for s, d, n, back in con.execute(
            f"WITH d AS (SELECT src, dst, count(*) n FROM edges WHERE {w} GROUP BY src, dst) "
            f"SELECT a.src, a.dst, a.n, coalesce(b.n, 0) FROM d a LEFT JOIN d b ON b.src = a.dst AND b.dst = a.src "
            f"ORDER BY a.n - coalesce(b.n, 0) DESC LIMIT ?", (*p, a.limit))]
        table('one-sided pairs: mentions sent and returned', ['from', 'to', 'sent', 'returned', 'returned %'], rows)
        edges = [e for r in rows for e in ((r[0], r[1], r[2]), (r[1], r[0], r[3]))]

    elif a.cmd == 'replies':
        a = argparse.Namespace(**{**vars(a), 'kind': 'addressed'})  # only @mentions expect an answer
        we, pe = where(con, a, 'e.')
        target = node(con, a.a) if a.a else None
        # ponytail: "replied" = the addressee posted anything in the same room within --within minutes,
        # not necessarily an answer to the asker. Check with `examples` when it matters.
        waits = {}  # agent (or asker, with a target) -> [seconds to reply, or None]
        for s, d, secs in con.execute(
                f"SELECT e.src, e.dst, (julianday((SELECT min(m.ts) FROM messages m WHERE m.src = e.dst "
                f"AND m.room = e.room AND m.ts > e.ts AND m.ts < datetime(e.ts, ?))) - julianday(e.ts)) * 86400 "
                f"FROM edges e WHERE {we}" + (' AND e.dst = ?' if target else ''),
                (f'+{a.within} minutes', *pe, *(target[:1] if target else ()))):
            waits.setdefault(s if target else d, []).append(secs)
        rows = []
        for k in sorted(waits, key=lambda k: -len(waits[k]))[:a.limit]:
            got = [x for x in waits[k] if x is not None]
            rows.append([names[k], len(waits[k]), len(got), f'{100 * len(got) // len(waits[k])}%',
                         round(statistics.median(got)) if got else None])
        table(f'posted in the same room within {a.within} min of an @mention (any post, not necessarily an answer)',
              ['asker' if target else 'agent', '@ asked', 'replied', 'rate', 'median secs'], rows)
        if target:
            edges = [(r[0], target[1], r[1]) for r in rows]

    edges = [e for e in edges if e[2]]
    if a.samples and edges:
        # Samples follow the result's own ranking: the newest message of each edge in table order, then the
        # 2nd newest of each, ... so they illustrate the top rows instead of whoever chatted last.
        ids = {n: i for i, n in names.items()}
        we, pe = where(con, a, 'e.')
        table('sample messages for the top rows', ['time', 'ref', 'from', 'to', 'message'], [
            (t, ref('m', i), s, d, one(text, 300)) for t, i, s, d, text in con.execute(
                f"WITH want(src, dst, k) AS (VALUES {','.join(['(?,?,?)'] * len(edges))}), "
                f"hits AS (SELECT e.msg_id, e.ts, e.src, e.dst, w.k, "
                f"  row_number() OVER (PARTITION BY e.src, e.dst ORDER BY e.ts DESC) rn "
                f"  FROM edges e JOIN want w ON w.src = e.src AND w.dst = e.dst WHERE {we}) "
                f"SELECT substr(h.ts,1,16), h.msg_id, s.name, group_concat(d.name, ', '), m.content FROM hits h "
                f"JOIN messages m ON m.id = h.msg_id JOIN nodes s ON s.id = h.src JOIN nodes d ON d.id = h.dst "
                f"GROUP BY h.msg_id ORDER BY min(h.rn), min(h.k) LIMIT ?",
                (*(x for k, (s, d, _) in enumerate(edges) for x in (ids[s], ids[d], k)), *pe, a.samples))])
    return out
