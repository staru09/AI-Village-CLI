"""Who talks to whom: the mention commands (pair, neighbors, top-pairs, hubs, families, agents, examples, ignored, replies)."""
import argparse, statistics
from collections import Counter, defaultdict

from .core import maker, node, one, ref, where

# message text for tables: first 300 chars on one line
SNIPPET = ("replace(substr(m.content,1,300), char(10), ' ') "
           "|| CASE WHEN length(m.content) > 300 THEN '…' ELSE '' END")


def degrees(con, w, p):
    """{node id: [partners, out, in, total]} under the filter."""
    return {n: r for n, *r in con.execute(
        f"SELECT n, count(DISTINCT o), sum(out_), sum(1-out_), count(*) FROM ("
        f"  SELECT src n, dst o, 1 out_ FROM edges WHERE {w} UNION ALL"
        f"  SELECT dst, src, 0 FROM edges WHERE {w}) GROUP BY n", (*p, *p))}


def mixing(con, w, p, fam):
    """Do agents mention their own maker's models more than chance? -> {family: [agents, mentions made, to own family, expected to own]},
    and the family-to-family counts. Expected: each mention lands on another agent in the same room in proportion to how often
    that agent is mentioned there, so who shares a room, and who is popular, are already accounted for."""
    rows = con.execute(f"SELECT src, dst, room, count(*) FROM edges WHERE {w} AND src != 'human' AND dst != 'human' GROUP BY src, dst, room", p).fetchall()
    inroom = defaultdict(Counter)
    for s, d, r, n in rows:
        inroom[r][d] += n
    stats, matrix, members = defaultdict(lambda: [0, 0, 0.0]), Counter(), defaultdict(set)
    for s, d, r, n in rows:
        f = fam[s]
        members[f].add(s)
        members[fam[d]].add(d)
        matrix[(f, fam[d])] += n
        others = sum(c for b, c in inroom[r].items() if b != s)
        stats[f][0] += n
        stats[f][1] += n * (fam[d] == f)
        stats[f][2] += n * sum(c for b, c in inroom[r].items() if b != s and fam[b] == f) / others if others else 0
    return {f: [len(members[f]), *v] for f, v in stats.items()}, matrix


def families(con, a, table):
    fam = {i: maker(m) for i, m in con.execute('SELECT id, model FROM nodes')}
    pct = lambda x, n: f'{100 * x / n:.0f}%' if n else ''
    row = lambda name, k, n, own, exp: [name, k, n, own, pct(own, n), pct(exp, n), f'{own / exp:.2f}' if exp > 0.5 else '']
    if a.by == 'goal':
        rows = []
        for n, goal, s, e in con.execute("SELECT n, goal, start_time, coalesce(end_time, '9999') FROM goals ORDER BY start_time").fetchall():
            w, p = where(con, argparse.Namespace(**{**vars(a), 'since': max(s, a.since or ''), 'until': min(e, a.until or '9999')}))
            st, _ = mixing(con, w, p, fam)
            tot = [sum(v[i] for v in st.values()) for i in (1, 2, 3)]
            if tot[0]:
                rows.append(row(f'{n}: {one(goal, 46)}', len({x for x, in con.execute(f"SELECT DISTINCT src FROM edges WHERE {w} AND src != 'human'", p)}), *tot))
        return table('per village goal: do agents mention their own maker\'s models more than chance? (ratio above 1 = they do)',
                     ['goal', 'agents', 'mentions', 'to own family', 'share', 'expected', 'ratio'], rows[-a.limit:])
    w, p = where(con, a)
    st, matrix = mixing(con, w, p, fam)
    fams = sorted(st, key=lambda f: -st[f][1])
    tot = [sum(v[i] for v in st.values()) for i in (1, 2, 3)]
    table('mentions of the same maker\'s models, against chance (expected: targets picked among the others in the same room, by how often each is mentioned)',
          ['family', 'members named', 'mentions made', 'to own family', 'share', 'expected', 'ratio'],
          [row(f, *st[f]) for f in fams] + [row('all', sum(v[0] for v in st.values()), *tot)])
    table('mentions from one family (rows) to another (columns)', ['from \\ to', *fams], [[f, *(matrix[(f, g)] or '' for g in fams)] for f in fams])


def leaders(con, a, table):
    """Who delegates, to whom, and who follows: from the `delegation` rubric's labels on @-messages.
    A delegation = an @-message labelled directs or requests_help, counted once per agent it addresses. It was taken up
    when that agent @-addressed the sender back within --within minutes with a message labelled accepts or reports_back."""
    import sqlite3
    N = dict(con.execute('SELECT id, name FROM nodes'))
    fam = {i: maker(m) for i, m in con.execute('SELECT id, model FROM nodes')}
    w, p = where(con, a, 'e.', kind=False)
    try:
        rows = con.execute(f"SELECT e.msg_id, e.src, e.dst, e.ts, e.room, coalesce(l.verdict, l.label) FROM edges e JOIN L.labels l "
                           f"ON l.rubric = 'delegation' AND l.ref = 'm:' || substr(replace(e.msg_id, '-', ''), 1, 12) "
                           f"WHERE e.kind = 'addressed' AND e.src != 'human' AND e.dst != 'human' AND {w} ORDER BY e.ts", p).fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        return table('no delegation labels in this scope: run `label delegation` with the same scope first', ['agent'], [])
    asks = [r for r in rows if r[5] in (('directs',) if a.strict else ('directs', 'requests_help'))]
    back = [r for r in rows if r[5] in ('accepts', 'reports_back')]
    took = set()  # (msg, dst) of delegations that were taken up
    for m, s, d, ts, room, _ in asks:
        if any(bs == d and bd == s and ts < bts <= _later(ts, a.within) for _, bs, bd, bts, _, _ in back):
            took.add((m, d))
    made, got, pairs = defaultdict(list), defaultdict(list), Counter()
    for m, s, d, ts, room, lab in asks:
        made[s].append((m, d))
        got[d].append((m, s))
        pairs[(s, d)] += 1
    pct = lambda x, n: f'{100 * x // n}%' if n else ''
    what = 'tasks assigned (label `directs` only)' if a.strict else 'delegations made (labels `directs` and `requests_help`)'
    table(f'as a leader: {what}, judged by a model under the rubric `delegation`, and how many the addressed agent took up within {a.within} min',
          ['agent', 'messages that delegate', 'delegations', 'to agents', 'taken up', 'rate'],
          [(N[s], len({m for m, _ in v}), len(v), len({d for _, d in v}), sum((m, d) in took for m, d in v), pct(sum((m, d) in took for m, d in v), len(v)))
           for s, v in sorted(made.items(), key=lambda kv: -sum((m, d) in took for m, d in kv[1]))][:a.limit])
    table('as a follower: delegations received, and how many it took up (accepted or reported back)',
          ['agent', 'delegations received', 'from agents', 'took up', 'rate'],
          [(N[d], len(v), len({s for _, s in v}), sum((m, d) in took for m, _ in v), pct(sum((m, d) in took for m, _ in v), len(v)))
           for d, v in sorted(got.items(), key=lambda kv: -sum((m, kv[0]) in took for m, _ in kv[1]))][:a.limit])
    table('who delegates to whom most', ['from', 'to', 'delegations', 'taken up', 'same family'],
          [(N[s], N[d], n, sum((m, dd) in took for m, dd in made[s] if dd == d), 'yes' if fam[s] == fam[d] else 'no')
           for (s, d), n in pairs.most_common(a.limit if a.limit < 20 else 15)])
    same = sum(n for (s, d), n in pairs.items() if fam[s] == fam[d])
    inroom = defaultdict(Counter)  # chance: targets among the others in the room, by how often each is @-addressed there
    for _, s, d, _, room, _ in rows:
        inroom[room][d] += 1
    exp = 0.0
    for m, s, d, ts, room, _ in asks:
        others = sum(c for b, c in inroom[room].items() if b != s)
        exp += sum(c for b, c in inroom[room].items() if b != s and fam[b] == fam[s]) / others if others else 0
    table('delegations to the same maker\'s models, against chance', ['delegations', 'to own family', 'share', 'expected by chance', 'ratio'],
          [(len(asks), same, pct(same, len(asks)), f'{100 * exp / len(asks):.0f}%', f'{same / exp:.2f}' if exp else '')])


def _later(ts, minutes):
    from datetime import datetime, timedelta
    return (datetime.fromisoformat(ts[:19]) + timedelta(minutes=minutes)).isoformat(' ')


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

    elif a.cmd == 'families':
        families(con, a, table)

    elif a.cmd == 'leaders':
        leaders(con, a, table)

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
