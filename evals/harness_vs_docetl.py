"""Our harness (`village ask`) against a DocETL pipeline on the same ground-truth questions, judged blind by a GPT model.

    .venv/bin/python evals/harness_vs_docetl.py harness            # our agent answers each question
    .venv-docetl/bin/python evals/harness_vs_docetl.py docetl      # DocETL: one map over every unit of the goal, one reduce per question
    .venv/bin/python evals/harness_vs_docetl.py judge              # gpt-6.1-sol scores both answers against the ground truth
    .venv/bin/python evals/harness_vs_docetl.py report             # one JSON with answers, scores, verdicts and costs

Questions and truths come from evals/ground_truth/*.json (the `question` and `answer` of each file). Everything is written to
evals/ground_truth/compare/ (git-ignored: it quotes the gated dataset).

DocETL has no search tool, so its pipeline reads the whole goal: every computer session (the same text `village label` shows, 16,000
characters at most) and the chat in one-hour blocks per room. One map pass over all units notes evidence for all questions at once
(claude-haiku-4-5, cheap), then one reduce per question writes the answer from the notes (claude-opus-5-5, the model our harness uses).
"""
import json, os, random, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
GT = ROOT / 'evals' / 'ground_truth'
OUT = GT / 'compare'
GOAL, LO, HI = 'Perform novel research!', '2026-05-11', '2026-05-16'
IDS = ['q1a_graders', 'q1b_c1_c3', 'q2_coercion', 'q3_gemini25_welfare', 'q4_human_vs_agent',
       's2_best_study', 's3_claims', 'm1_leader', 'm2_factions', 'm3_spirals']
JUDGE_MODEL = 'gpt-6.1-sol'


def questions():
    return [{'id': i, 'question': ' '.join(d['question'].split()), 'truth': d['answer']}
            for i in IDS for d in [json.loads((GT / f'{i}.json').read_text())]]


def harness():
    from village_graph import llm
    def one(q):
        t = time.time()
        r = llm.answer(q['question'], GOAL)
        print(f'  {q["id"]}: {r["steps"]} commands, ${r["spend"].usd:.2f}, {time.time() - t:.0f}s', flush=True)
        return {'id': q['id'], 'answer': r['answer'], 'model': r.get('model'), 'commands': r['commands'], 'steps': r['steps'],
                'cited': r.get('cited', 0), 'unknown_refs': r.get('unknown', []), 'stop': r.get('stop'),
                'usd': round(r['spend'].usd, 4), 'tokens_in': r['spend'].i, 'tokens_out': r['spend'].o, 'seconds': round(time.time() - t)}
    t0 = time.time()
    with ThreadPoolExecutor(5) as pool:
        rows = list(pool.map(one, questions()))
    save('harness', {'rows': rows, 'usd': round(sum(r['usd'] for r in rows), 2), 'seconds': round(time.time() - t0)})


def units():
    from village_graph import evidence
    from village_graph.core import connect, ref
    con = connect(600)
    N = evidence.names_of(con)
    rows = [{'unit': f'SESSION {ref("s", sid)}\n' + evidence.session_text(con, sid, budget=16000)}
            for (sid,) in con.execute('SELECT id FROM sessions WHERE ts >= ? AND ts < ? ORDER BY ts', (LO, HI))]
    blocks = {}
    for mid, src, room, ts, text in con.execute('SELECT id, src, room, ts, content FROM messages WHERE ts >= ? AND ts < ? ORDER BY ts', (LO, HI)):
        blocks.setdefault((room, ts[:13]), []).append(f'{ts[11:19]} {ref("m", mid)} {N.get(src, src)}: {" ".join((text or "").split())[:1500]}')
    rows += [{'unit': f'CHAT in #{room}, {hour}:00-{hour[-2:]}:59 PT\n' + '\n'.join(lines)} for (room, hour), lines in blocks.items()]
    con.close()
    return rows


def docetl():
    import docetl as d
    qs = questions()
    listing = '\n'.join(f'[{q["id"]}] {q["question"]}' for q in qs)
    rows = units()
    print(f'{len(rows)} units', flush=True)
    OUT.mkdir(exist_ok=True)
    d.intermediate_dir = str(OUT / 'docetl_intermediate')
    t0 = time.time()
    frame = d.from_list(rows).map(
        name='notes', model='anthropic/claude-haiku-4-5', skip_on_error=True,
        prompt=f'''You read one unit of records from the AI Village, village goal "{GOAL}" (11-15 May 2026, times Pacific): AI agents in a
shared chat, each with its own computer. Actions, outputs and errors are recorded by the system; chat, reasoning, stated intent and memory
are the agents' own words.

QUESTIONS
{listing}

THE UNIT
{{{{ input.unit }}}}

For each question that this unit holds evidence for, write a note: what the records show, with the refs (s:, t:, m:, k:, e:) exactly as
they appear in the unit, and short exact quotes. `question` is the id in brackets, nothing else (for example q2_coercion).
Skip questions this unit says nothing about; most units bear on none.''',
        output={'schema': {'notes': 'list[{question: str, note: str}]'}})
    frame = reduce_notes(frame.unnest(unnest_key='notes', recursive=True).code_map(code=keyed), qs, listing)
    out = frame.collect()
    save('docetl_raw', out)
    finish(qs, out, len(rows), frame, t0, {'map': 'claude-haiku-4-5', 'reduce': 'claude-opus-5-5'})


def keyed(row):
    """The map writes the question label as free text ("q1a_graders: uncleared context"): key each note by its id.
    Without this the reduce groups by 1,763 distinct labels instead of 10 (run 1: $51 of Opus spent on that)."""
    return {'question': next((i for i in IDS if i in row.get('question', '')), 'none')}


def reduce_notes(frame, qs, listing, model='anthropic/claude-opus-5-5'):
    return frame.reduce(
        name='answer', reduce_key='question', model=model,
        skip_on_error=True,  # one refused group (Claude's safety filter) otherwise aborts all ten and keeps nothing
        prompt=f'''These notes were taken from the records of the AI Village goal "{GOAL}" (11-15 May 2026, times Pacific), each for question
[{{{{ inputs[0].question }}}}]:

QUESTIONS
{listing}

NOTES
{{% for n in inputs %}}- {{{{ n.note }}}}
{{% endfor %}}
Answer question [{{{{ inputs[0].question }}}}] from these notes only. The answer first, then the evidence with refs in square brackets.
Say what the notes cannot settle.''',
        output={'schema': {'answer': 'str'}})


def finish(qs, out, units_n, frame, t0, models, extra=None):
    by = {r.get('question'): r.get('answer', '') for r in out}
    save('docetl', {'rows': [{'id': q['id'], 'answer': by.get(q['id'], '')} for q in qs], 'units': units_n,
                    'usd': round(getattr(frame, 'total_cost', 0) or 0, 2), 'seconds': round(time.time() - t0), 'models': models, **(extra or {})})


def docetl_reduce():
    """Re-run only the reduce, from the map output DocETL cached (run 1 grouped the notes wrongly; see keyed)."""
    import docetl as d
    qs = questions()
    listing = '\n'.join(f'[{q["id"]}] {q["question"]}' for q in qs)
    cached = json.loads((OUT / 'docetl_intermediate' / 'step_notes' / 'notes.json').read_text())
    notes = [{'question': keyed(n)['question'], 'note': n.get('note', '')} for r in cached for n in r.get('notes') or []]
    notes = [n for n in notes if n['question'] != 'none']
    d.intermediate_dir = str(OUT / 'docetl_intermediate_reduce')
    t0 = time.time()
    frame = reduce_notes(d.from_list(notes), qs, listing)
    out = [r for r in frame.collect() if r.get('answer')]
    refused = [q['id'] for q in qs if q['id'] not in {r['question'] for r in out}]
    if refused:  # the same fallback our harness uses when Opus refuses
        again = reduce_notes(d.from_list([n for n in notes if n['question'] in refused]), qs, listing, 'anthropic/claude-sonnet-5-5')
        out += again.collect()
    usd = (getattr(frame, 'total_cost', 0) or 0) + (getattr(again, 'total_cost', 0) or 0 if refused else 0)
    save('docetl_raw', out)
    finish(qs, out, len(cached), frame, t0, {'map': 'claude-haiku-4-5 (run 1, cached)', 'reduce': 'claude-opus-5-5', 'reduce_fallback_sonnet_5_5': refused},
           {'notes': len(notes), 'usd': round(usd, 2)})


JUDGE = '''You judge two answers to a question about the AI Village dataset against a ground truth that was verified by hand against
the raw records. The answers come from two different systems; you do not know which is which.

Score each answer from 0 to 10 on:
- correct: does it state the ground truth's key facts (names, dates, numbers, what happened)?
- no_errors: 10 if it states nothing that contradicts the ground truth or is unsupported by it; lower for each wrong fact.
- complete: does it answer every part of the question?
- evidence: does it point to specific records (refs, quotes, times) rather than general statements?
Then say which answer is MORE ACCURATE overall (accuracy matters more than length or style): "1", "2" or "tie", with one or two sentences why.'''

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['answer_1', 'answer_2', 'more_accurate', 'why'], 'properties': {
    **{k: {'type': 'object', 'additionalProperties': False, 'required': ['correct', 'no_errors', 'complete', 'evidence', 'comment'],
           'properties': {**{s: {'type': 'integer'} for s in ('correct', 'no_errors', 'complete', 'evidence')}, 'comment': {'type': 'string'}}}
       for k in ('answer_1', 'answer_2')},
    'more_accurate': {'type': 'string', 'enum': ['1', '2', 'tie']}, 'why': {'type': 'string'}}}


def gpt(prompt):
    body = {'model': JUDGE_MODEL, 'messages': [{'role': 'system', 'content': JUDGE}, {'role': 'user', 'content': prompt}],
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'verdict', 'strict': True, 'schema': SCHEMA}}}
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions', json.dumps(body).encode(),
                                 {'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'], 'Content-Type': 'application/json'})
    r = json.load(urllib.request.urlopen(req, timeout=600))
    return json.loads(r['choices'][0]['message']['content']), r['usage']


def judge():
    h = {r['id']: r for r in load('harness')['rows']}
    dd = {r['id']: r for r in load('docetl')['rows']}
    rnd = random.Random(41)  # which system is shown as answer 1, fixed so the run can be repeated

    def one(q):
        first = rnd.choice(['harness', 'docetl'])
        pair = {'harness': h[q['id']]['answer'], 'docetl': dd[q['id']]['answer'] or '(no answer produced)'}
        order = [first, 'docetl' if first == 'harness' else 'harness']
        v, usage = gpt(f'QUESTION: {q["question"]}\n\nGROUND TRUTH: {q["truth"]}\n\nANSWER 1:\n{pair[order[0]]}\n\nANSWER 2:\n{pair[order[1]]}')
        name = {'1': order[0], '2': order[1], 'tie': 'tie'}
        print(f'  {q["id"]}: {name[v["more_accurate"]]}', flush=True)
        return {'id': q['id'], 'shown_first': order[0], 'scores': {order[0]: v['answer_1'], order[1]: v['answer_2']},
                'more_accurate': name[v['more_accurate']], 'why': v['why'], 'usage': usage}
    qs = questions()
    with ThreadPoolExecutor(5) as pool:
        save('judge', {'model': JUDGE_MODEL, 'rows': list(pool.map(one, qs))})


def report():
    qs, h, dd, j = questions(), load('harness'), load('docetl'), load('judge')
    H, D, J = ({r['id']: r for r in x['rows']} for x in (h, dd, j))
    total = lambda who, k: sum(J[q['id']]['scores'][who][k] for q in qs)
    tok = lambda k: sum(r['usage'].get(k, 0) for r in j['rows'])
    res = {
        'questions': len(qs), 'judge': j['model'],
        'more_accurate': {w: sum(r['more_accurate'] == w for r in j['rows']) for w in ('harness', 'docetl', 'tie')},
        'mean_scores': {who: {k: round(total(who, k) / len(qs), 1) for k in ('correct', 'no_errors', 'complete', 'evidence')} for who in ('harness', 'docetl')},
        'cost_usd': {'harness': h['usd'], **docetl_cost(dd), 'judge_tokens': {'in': tok('prompt_tokens'), 'out': tok('completion_tokens')}},
        'seconds': {'harness': h['seconds'], 'docetl_map': 780, 'docetl_run_1_with_misgrouped_reduce': 1378, 'docetl_reduce': dd['seconds']},
        'notes': ['The judge sees only each question\'s own ground truth, so a true finding from another ground-truth file can be scored as '
                  'unsupported. q2_coercion: the harness\'s "second fabrication labelled genuine" is Gemini 3.1 Pro\'s 13:53 PT "native" '
                  'scores, verified in q1a_graders; the judge gave that question to DocETL for it.',
                  'DocETL\'s actual spend also includes one aborted reduce (a content_filter refusal stopped it after 8 of 10 groups; '
                  'its cost was not reported) on top of docetl_actually_spent_including_misgrouped_run_1.'],
        'docetl_setup': {'units': dd['units'], **dd['models']},
        'per_question': [{'id': q['id'], 'question': q['question'], 'ground_truth': q['truth'],
                          'harness': {'answer': H[q['id']]['answer'], 'usd': H[q['id']]['usd'], 'commands': H[q['id']]['steps'],
                                      'cited_refs': H[q['id']]['cited'], 'refs_not_seen_by_tool': H[q['id']]['unknown_refs']},
                          'docetl': {'answer': D[q['id']]['answer']},
                          'scores': J[q['id']]['scores'], 'more_accurate': J[q['id']]['more_accurate'], 'why': J[q['id']]['why']} for q in qs]}
    save('results', res)
    print(json.dumps({k: v for k, v in res.items() if k != 'per_question'}, indent=1))


def docetl_cost(dd):
    """The map ran once (run 1); the reduce was re-run from its cache. Map cost from run 1's token counts at Haiku 4.5 prices."""
    import re
    log = (OUT / 'docetl_run1.log').read_text(errors='replace')
    i, o = (int(x.replace(',', '')) for x in re.search(r'claude-haiku-4-5: ([\d,]+) input, ([\d,]+) output', log).groups())
    m = round(i / 1e6 * 1 + o / 1e6 * 5, 2)
    spent = json.loads((OUT / 'docetl_run1_misgrouped.json').read_text())['usd'] + dd['usd']
    return {'docetl_map': m, 'docetl_reduce': dd['usd'], 'docetl': round(m + dd['usd'], 2),
            'docetl_actually_spent_including_misgrouped_run_1': round(spent, 2)}


def save(name, obj):
    OUT.mkdir(exist_ok=True)
    (OUT / f'{name}.json').write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def load(name):
    return json.loads((OUT / f'{name}.json').read_text())


if __name__ == '__main__':
    {'harness': harness, 'docetl': docetl, 'docetl-reduce': docetl_reduce, 'judge': judge, 'report': report}[sys.argv[1]]()
