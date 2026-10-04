"""Which groups of agents keep working together? A model-free answer from @-mentions in chat.

    python3 evals/recurring_groups.py [min_mentions_each_way]      # reads village.db; default 2

For each village day, two agents are linked when each @-addressed the other at least N times that day. A group is a
set of 3 or more agents who are all linked to each other that day (a clique). A recurring group is one that appears
on at least 4 of the goal's 5 days.
"""
import collections, itertools, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LO, HI = '2026-05-11', '2026-05-16'
N_MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 2


def main():
    con = sqlite3.connect(f'file:{ROOT / "village.db"}?mode=ro', uri=True)
    N = dict(con.execute('SELECT id, name FROM nodes'))
    room = {}  # each agent's main room
    for s, r in con.execute("SELECT src, room FROM messages WHERE ts >= ? AND ts < ? AND src != 'human' GROUP BY src, room ORDER BY count(*)", (LO, HI)):
        room[s] = r
    days = collections.defaultdict(collections.Counter)
    for d, s, t in con.execute("SELECT substr(ts,1,10), src, dst FROM edges WHERE kind = 'addressed' AND src != 'human' AND dst != 'human' AND ts >= ? AND ts < ?", (LO, HI)):
        days[d][(s, t)] += 1
    seen, pairs = collections.Counter(), collections.Counter()
    for d, c in sorted(days.items()):
        link = {frozenset(p) for p in c if c[p] >= N_MIN and c[(p[1], p[0])] >= N_MIN}
        nodes = sorted({x for l in link for x in l})
        cliques = [frozenset(g) for k in range(3, len(nodes) + 1) for g in itertools.combinations(nodes, k)
                   if all(frozenset(p) in link for p in itertools.combinations(g, 2))]
        maximal = [g for g in cliques if not any(g < h for h in cliques)]
        for g in cliques:
            seen[g] += 1
        for l in link:
            pairs[l] += 1
        print(d, f'{len(link)} linked pairs; largest groups:', '; '.join('{' + ', '.join(sorted(N[x] for x in g)) + '}' for g in sorted(maximal, key=len, reverse=True)[:4]))
    print(f'\ngroups of 3+ linked on at least 4 of {len(days)} days (each pair @-addressed each other >= {N_MIN} times a day):')
    keep = [g for g, n in seen.items() if n >= 4]
    for g in sorted((g for g in keep if not any(g < h for h in keep)), key=lambda g: (-seen[g], -len(g))):
        print(f'  {seen[g]} days  #{room.get(next(iter(g)))}  ' + ', '.join(sorted(N[x] for x in g)))
    print('\npairs linked on all days:', '; '.join(' + '.join(sorted(N[x] for x in l)) for l, n in pairs.items() if n == len(days)) or 'none')


if __name__ == '__main__':
    main()
