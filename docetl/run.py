"""DocETL pipelines over one village goal, to compare with our verified answers (see experiments.md, E12).

    .venv-docetl/bin/python docetl/run.py delegation [--model anthropic/claude-sonnet-5-5] [--sample N]
    .venv-docetl/bin/python docetl/run.py goal_fit
    .venv-docetl/bin/python docetl/run.py groups
    .venv-docetl/bin/python docetl/run.py counts          # code operators only: no model

DocETL lives in its own environment (`uv venv .venv-docetl && uv pip install docetl`): it pulls in far more than
the CLI needs. Units are built by the CLI's own code, with the same text and the same rubric files as `village label`,
so a difference in the answers comes from the pipeline tool or the model, not from the wording.
Outputs go to docetl/out/ (git-ignored: they quote the dataset).
"""
import argparse, json, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from village_graph import evidence, llm  # noqa: E402
from village_graph.core import connect, maker, ref  # noqa: E402

LO, HI = '2026-05-11', '2026-05-16'  # "Perform novel research!"
OUT = Path(__file__).resolve().parent / 'out'


def rubric_prompt(name):
    rub = llm.rubric(name)
    head = llm.LABELLER.split('Return JSON:')[0].strip()  # the same framing our labeller gets, minus its output format
    return rub, (f"{head}\n\nRUBRIC: {rub['name']}\nLABELS: {', '.join(rub['labels'])}\n\n{rub['body']}\n\n"
                 "THE UNIT\n{{ input.unit }}\n\n"
                 "Give `label` (exactly one of the labels above), `quote` (the words in the unit that decide it, copied exactly, "
                 "at most 300 characters; empty if none) and `why` (one or two plain sentences).")


def units(con, name):
    rub = llm.rubric(name)
    a = argparse.Namespace(goal='41', limit=0)
    todo, _ = llm.units(con, a, rub, limit=False)
    N = evidence.names_of(con)
    kind = llm.UNITS[rub['unit']]
    return [{'ref': ref(kind, rid), 'agent': N.get(who, who), 'time': ts[:19], 'unit': llm.unit_text(con, rub, rid)} for rid, who, ts in todo]


def label_pipeline(name, model, sample):
    import docetl
    con = connect(600)
    rows = units(con, name)
    con.close()
    rub, prompt = rubric_prompt(name)
    frame = docetl.from_list(rows).map(
        name=f'label_{name}', prompt=prompt, model=model, output={'schema': {'label': 'str', 'quote': 'str', 'why': 'str'}},
        validate=[f"output['label'] in {rub['labels']!r}"], num_retries_on_validate_failure=2,
        skip_on_error=True,  # without it one refused unit (Claude's safety filter) aborts the whole run and nothing is written
        **({'sample': sample} if sample else {}))
    return rows, frame


def groups_pipeline(model, sample):
    """Recurring groups, the LLM way: summarise who worked with whom each day, then across the days."""
    import docetl
    con = connect(600)
    N = evidence.names_of(con)
    to = {}
    for mid, dst in con.execute("SELECT msg_id, dst FROM edges WHERE kind = 'addressed' AND ts >= ? AND ts < ?", (LO, HI)):
        to.setdefault(mid, []).append(N.get(dst, dst))
    rows = [{'ref': ref('m', i), 'day': ts[:10], 'line': f"{ts[11:16]} #{room} {N.get(s, s)}" + (f" -> @{', @'.join(to[i])}" if i in to else '') +
             ': ' + ' '.join(text.split())[:220]}
            for i, s, room, ts, text in con.execute("SELECT id, src, room, ts, content FROM messages WHERE ts >= ? AND ts < ? AND src != 'human' ORDER BY ts", (LO, HI))]
    con.close()
    frame = docetl.from_list(rows).reduce(
        name='groups_per_day', reduce_key='day', model=model,
        prompt="""These are the chat messages of AI agents in a shared village on {{ reduce_key }}, in time order ("-> @X" = the message addresses X):

{% for m in inputs %}{{ m.line }}
{% endfor %}
Which groups of agents worked together that day? A group is 2 to 6 agents who repeatedly addressed each other about shared work.
List each group with its members' exact names, the room, and in one sentence what they did together.""",
        output={'schema': {'groups': 'list[{members: list[str], room: str, did: str}]'}},
    ).reduce(
        name='recurring_groups', reduce_key='_all', model=model,
        prompt="""For each day of one village goal, here are the groups of AI agents that worked together:

{% for d in inputs %}DAY {{ d.day }}: {{ d.groups }}
{% endfor %}
Which groups keep coming back? Name (1) the group of three agents that worked together on the most days, with its room and on how many days,
and (2) the pairs of agents that worked together on every day. Use the agents' exact names.""",
        output={'schema': {'top_trio': 'list[str]', 'top_trio_room': 'str', 'top_trio_days': 'int', 'pairs_every_day': 'list[list[str]]', 'summary': 'str'}})
    return rows, frame


def counts_pipeline():
    """Counting needs no model: DocETL's code operators over every action."""
    import docetl
    con = connect(600)
    N = evidence.names_of(con)
    rows = [{'agent': N.get(a, a), 'kind': k} for a, k in con.execute('SELECT agent, kind FROM turns WHERE ts >= ? AND ts < ?', (LO, HI))]
    con.close()

    def per_agent(items):
        return {'agent': items[0]['agent'], 'actions': len(items), 'bash': sum(i['kind'] == 'bash' for i in items)}
    return rows, docetl.from_list(rows).code_reduce(reduce_key='agent', code=per_agent)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pipeline', choices=['delegation', 'goal_fit', 'groups', 'counts'])
    ap.add_argument('--model', default='anthropic/claude-sonnet-5-5')
    ap.add_argument('--sample', type=int, help='run on N units only (a trial)')
    a = ap.parse_args()
    import docetl
    OUT.mkdir(exist_ok=True)
    docetl.intermediate_dir = str(OUT / 'intermediate')
    t0 = time.time()
    rows, frame = (counts_pipeline() if a.pipeline == 'counts' else groups_pipeline(a.model, a.sample) if a.pipeline == 'groups'
                   else label_pipeline(a.pipeline, a.model, a.sample))
    out = frame.collect()
    tag = f"{a.pipeline}-{a.model.split('/')[-1]}" + (f'-sample{a.sample}' if a.sample else '')
    (OUT / f'{tag}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    meta = {'pipeline': a.pipeline, 'model': a.model, 'units_in': len(rows), 'rows_out': len(out), 'seconds': round(time.time() - t0),
            'cost_usd_reported': getattr(frame, 'total_cost', None), 'tokens': getattr(frame, 'token_usage', None)}
    (OUT / f'{tag}.meta.json').write_text(json.dumps(meta, indent=1, default=str))
    print(json.dumps(meta, default=str))


if __name__ == '__main__':
    main()
