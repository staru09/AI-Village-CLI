"""village rlm: answer a whole-scope question with a Recursive Language Model (github.com/alexzhang13/rlm).

`ask` pastes each command's output into the model's context. That is cheap for a lookup and wasteful for a question
that needs hundreds of records read and combined. Here the scope's records are exported as one object and loaded into
a sandboxed Python REPL as `context`. The root model never reads it whole: it writes code to slice it, sends slices to
a cheaper model (llm_query_batched), keeps what comes back in variables, and prints only what it needs.

Needs `uv sync --extra rlm`, ANTHROPIC_API_KEY and Docker (the REPL runs in a container: the code is written by a
model that has read text written by other models, so it does not run on this machine's Python).
"""
import os, sys, time

from . import db, evidence
from .core import connect, maker, ref, scope
from .llm import Spend, refs_in

ROOT_MODEL = os.environ.get('VILLAGE_RLM_MODEL', 'claude-sonnet-5-5')
SUB_MODEL = os.environ.get('VILLAGE_RLM_SUB_MODEL', 'claude-haiku-4-5')

ABOUT = '''The AI Village: frontier AI agents share a group chat, each with its own computer, pursuing goals set by AI Digest.
This object holds every record of one scope. All times are Pacific time. Every record has a `ref` you must cite.

Keys:
- goals: the village goal(s) in scope: n, goal, start, end. agent_goals: per-agent goals, if any were assigned.
- agents: name, model, maker (the model family), and counts for the scope.
- messages: chat in time order: ref (m:…), time, speaker, room, text, to (names it @-addresses), named (names it mentions
  without @), thought (its reasoning before sending, when recorded), labels (rubric -> label, when a rubric was run).
- sessions: computer sessions in time order: ref (s:…), agent, start, end, intent (the goal the agent stated for the session),
  actions, commands, failed (counts), report (what it wrote when the session ended), labels (rubric -> label).
- actions: every computer action: ref (t:…), session, agent, time, kind (bash, gui, chat, other), action, output, failed.
  Present only when the scope was exported with actions.
- rubrics: for each rubric that was run, its labels and what the rubric asked. A label is a model's judgement, checked
  against hand-labelled cases; it is not a rule.

Trust: actions, outputs and events are recorded by the system (ground truth). Chat text, intent, thought, report and
memory are an agent's own words (claims): they show what it said or believed, not what happened.'''

RULES = '''Answer the question below about the AI Village from the `context` object in the REPL (read context["about"] first).

How to work
- Never print large parts of `context`. Count and filter with Python; read only small samples.
- For judgements over many records, send compact batches to the sub-model with llm_query_batched and keep the results
  in variables. Use the stored `labels` where a rubric already judged what you need, and say that you did.
- Check a pattern against its base ("12 of the 40 sessions"), and look for evidence against your answer before settling.

The answer
- Plain English, short: the answer first, then the evidence. Define any score you compute in one sentence.
- After each factual sentence cite the records that show it as refs in square brackets, e.g. [m:0a1b2c3d4e5f] [s:…].
  Cite only refs that exist in `context`.
- Say "X reported that …" for claims; only actions and outputs show what happened. Mark your own interpretation as such.
- Say what you could not check. End with one line: ANSWER: <the answer in one short sentence>.

QUESTION: '''


def export(con, a, actions=True):
    """The scope as one JSON-able object (see ABOUT). Texts are cut so one goal stays loadable."""
    lo, hi = scope(con, a)
    if not lo and hi == db.END:
        sys.exit('give a scope: --goal, --day, --date or --since/--until (a whole history does not fit).')
    N, models = evidence.names_of(con), dict(con.execute('SELECT id, model FROM nodes'))
    r = (lo, hi)
    labels = {}
    try:
        for rf, rubric, label in con.execute('SELECT ref, rubric, coalesce(verdict, label) FROM L.labels WHERE ts >= ? AND ts < ?', r):
            labels.setdefault(rf, {})[rubric] = label
    except Exception:  # no labels.db yet
        pass
    to = {}
    for mid, dst, kind in con.execute('SELECT msg_id, dst, kind FROM edges WHERE ts >= ? AND ts < ?', r):
        to.setdefault(mid, {'addressed': [], 'named': []})[kind].append(N.get(dst, dst))
    messages = [{'ref': ref('m', i), 'time': ts[:19], 'speaker': N.get(s, s), 'room': room, 'text': db.cut(text, 3000),
                 'to': to.get(i, {}).get('addressed', []), 'named': to.get(i, {}).get('named', []),
                 **({'thought': db.cut(why, 700)} if why else {}), **({'labels': labels[ref('m', i)]} if ref('m', i) in labels else {})}
                for i, s, room, ts, text, why in con.execute('SELECT id, src, room, ts, content, reasoning FROM messages WHERE ts >= ? AND ts < ? ORDER BY ts', r)]
    reports = {}
    for sid, typ, text in con.execute(f"SELECT session, type, text FROM events WHERE ts >= ? AND ts < ? AND type = 'CONSOLIDATE' AND session IS NOT NULL", r):
        reports[sid] = text
    sessions = [{'ref': ref('s', i), 'agent': N.get(w, w), 'start': ts[:19], 'end': (e or '')[:19], 'intent': f'{short} — {db.cut(goal, 1500)}',
                 'actions': t or 0, 'commands': b or 0, 'failed': f or 0, 'report': db.cut(reports.get(i, ''), 900),
                 **({'labels': labels[ref('s', i)]} if ref('s', i) in labels else {})}
                for i, w, ts, e, goal, short, t, b, f in con.execute(
                    'SELECT id, agent, ts, end_ts, goal, short, turns, bash, failed FROM sessions WHERE ts >= ? AND ts < ? ORDER BY ts', r)]
    present = {m['speaker'] for m in messages} | {s['agent'] for s in sessions}
    out = {'about': ABOUT,
           'goals': [{'n': n, 'goal': g, 'start': s[:16], 'end': (e or 'running')[:16]} for n, g, s, e in con.execute(
               "SELECT n, goal, start_time, end_time FROM goals WHERE start_time < ? AND coalesce(end_time, '9999') > ? ORDER BY start_time", (hi, lo))],
           'agent_goals': [{'agent': N.get(w, w), 'role': short, 'goal': name} for w, name, short in con.execute(
               "SELECT agent, name, short FROM agent_goals WHERE start_time < ? AND coalesce(end_time, '9999') > ?", (hi, lo))],
           'agents': [{'name': n, 'model': models[i], 'maker': maker(models[i]), 'messages': sum(m['speaker'] == n for m in messages),
                       'sessions': sum(s['agent'] == n for s in sessions)} for i, n in sorted(N.items(), key=lambda kv: kv[1]) if n in present and i != 'human'],
           'messages': messages, 'sessions': sessions, 'rubrics': {}}
    try:
        from .llm import rubric
        for (name,) in con.execute('SELECT DISTINCT rubric FROM L.labels WHERE ts >= ? AND ts < ?', r).fetchall():
            rub = rubric(name)
            out['rubrics'][name] = {'unit': rub['unit'], 'labels': rub['labels'], 'asks': rub['body']}
    except Exception:
        pass
    if actions:
        out['actions'] = [{'ref': ref('t', i), 'session': ref('s', s), 'agent': N.get(w, w), 'time': ts[:19], 'kind': k, 'action': db.cut(act, 400),
                           'output': db.cut(o, 300), 'failed': bool(f)}
                          for i, s, w, ts, k, act, o, f in con.execute(
                              'SELECT id, session, agent, ts, kind, action, output, failed FROM turns WHERE ts >= ? AND ts < ? ORDER BY ts', r)]
    return out


def patch_client(spend):
    """The library reads `content[0].text`, which is a thinking block on current Claude models. Read the text blocks,
    cache the growing conversation (the root model re-sends it every step), and count tokens with cache reads."""
    from rlm.clients.anthropic import AnthropicClient

    def prepared(self, prompt, model):
        messages, system = self._prepare_messages(prompt)
        messages = [dict(m) for m in messages]
        if messages and messages[-1]['role'] == 'assistant':  # current Claude models take no prefill: the last turn must be the user's
            messages.append({'role': 'user', 'content': 'Continue.'})
        if messages and isinstance(messages[-1].get('content'), str):
            messages[-1]['content'] = [{'type': 'text', 'text': messages[-1]['content'], 'cache_control': {'type': 'ephemeral'}}]
        kw = {'model': model or self.model_name, 'max_tokens': self.max_tokens, 'messages': messages}
        if system:
            kw['system'] = [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}]
        return kw

    def done(self, resp, model):
        self._track_cost(resp, model)
        spend.add(model, resp.usage)
        calls[model] = calls.get(model, 0) + 1
        if resp.stop_reason == 'refusal':
            return '(the model declined this request)'
        return ''.join(b.text for b in resp.content if b.type == 'text')

    calls = {}

    def completion(self, prompt, model=None):
        kw = prepared(self, prompt, model)
        return done(self, self.client.messages.create(**kw), kw['model'])

    async def acompletion(self, prompt, model=None):
        kw = prepared(self, prompt, model)
        return done(self, await self.async_client.messages.create(**kw), kw['model'])

    AnthropicClient.completion, AnthropicClient.acompletion = completion, acompletion
    return calls


def answer(question, a, model=None, sub=None, actions=True, env='docker', max_iterations=25, log=None):
    """Run the RLM on one question over the scope in `a` -> {answer, spend, calls, seconds, size, cited, unknown}."""
    try:
        from rlm import RLM
    except ImportError:
        sys.exit('`village rlm` needs the RLM library: `uv sync --extra rlm`.')
    if not os.environ.get('ANTHROPIC_API_KEY'):
        sys.exit('set ANTHROPIC_API_KEY to use this command.')
    con = connect(600)
    payload = export(con, a, actions)
    con.close()
    import json
    size = len(json.dumps(payload, ensure_ascii=False))
    known = {m['ref'] for m in payload['messages']} | {s['ref'] for s in payload['sessions']} | {t['ref'] for t in payload.get('actions', [])}
    spend, t0 = Spend(), time.time()
    calls = patch_client(spend)
    model, sub = model or ROOT_MODEL, sub or SUB_MODEL
    if log:
        log(f'  context: {len(payload["messages"]):,} messages, {len(payload["sessions"]):,} sessions, {len(payload.get("actions", [])):,} actions '
            f'({size / 1e6:.1f} MB), in a {env} REPL; root {model}, sub-calls {sub}')
    key = os.environ['ANTHROPIC_API_KEY']  # the library's Anthropic client wants it passed, not read from the environment
    rlm = RLM(backend='anthropic', backend_kwargs={'model_name': model, 'api_key': key}, other_backends=['anthropic'],
              other_backend_kwargs=[{'model_name': sub, 'api_key': key}],
              environment=env, max_depth=1, max_iterations=max_iterations, max_timeout=1500, verbose=bool(os.environ.get('VILLAGE_RLM_VERBOSE')),
              on_iteration_complete=(lambda *x, **k: log(f'  step done · {spend}')) if log else None)
    out = rlm.completion(payload, root_prompt=RULES + question)
    text = str(out.response)
    cited = refs_in(text)
    return {'answer': text, 'spend': spend, 'calls': calls, 'seconds': time.time() - t0, 'size': size, 'cited': len(cited),
            'unknown': sorted(cited - known), 'model': model, 'sub': sub}


def rlm(a):
    if a.env == 'local' and not a.unsafe:
        sys.exit('--env local runs model-written code in this Python process, with your files and keys in reach. Pass --unsafe to accept that, or use Docker.')
    r = answer(a.question, a, a.model, a.sub_model, not a.no_actions, a.env, a.max_steps, None if a.quiet else lambda s: print(s, file=sys.stderr, flush=True))
    return [('text', a.question, r['answer']),
            ('table', 'model calls', ['model', 'calls', 'role'], [(m, n, 'root' if m == r['model'] else 'sub-calls') for m, n in r['calls'].items()]),
            ('note', f'Recursive Language Model over a {r["size"] / 1e6:.1f} MB context that never entered a prompt whole: {r["spend"]}, {r["seconds"]:.0f}s. '
                     f'Citations: {r["cited"]} refs, ' + ('all exist in the scope.' if not r['unknown'] else
                                                         f'{len(r["unknown"])} do NOT exist in the scope: {", ".join(r["unknown"][:8])}.'))]
