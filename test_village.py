from village_graph.mentions import extractor

agents = {'a': 'GPT-5', 'b': 'GPT-5.1', 'c': 'Fine-Tuned Leader', 'd': '[Temporary] Fine-tuned Leader',
          'e': 'o3', 'f': 'DeepSeek-V3.2', 'g': 'Claude Opus 4.8'}
m = extractor(agents, humans={'zak', 'claude'})

assert m('I agree with GPT-5.1 here', 'x') == {'b': 'named'}
assert m('GPT-5, thanks.', 'x') == {'a': 'named'}
assert m('GPT-5.6 Sol said so', 'x') == {}                                  # unknown 5.x doesn't fall back to GPT-5
assert m('[Temporary] Fine-tuned Leader wins', 'x') == {'d': 'named'}
assert m('Fine-Tuned Leader wins', 'x') == {'c': 'named'}
assert m('@DeepSeek‑V3.2 ok', 'x') == {'f': 'addressed'}               # non-breaking hyphen
assert m('see https://x.com/o3/page', 'x') == {}
assert m('o3 is right', 'x') == {'e': 'named'}
assert m('Claude Opus 4.8 said, so @Claude Opus 4.8 do it', 'x') == {'g': 'addressed'}
assert m('thanks @zak.', 'x') == {'human': 'addressed'}
assert m('@Claude Opus 4.8 hi', 'x') == {'g': 'addressed'}                  # "@Claude" is not human "claude"
assert m('@GPT-5 hi @zak', 'human') == {'a': 'addressed'}                   # no Human -> Human
assert m('I am GPT-5', 'a') == {}                                           # self-mention dropped

# Everything below runs on a tiny hand-made database: Alpha @Beta twice (Beta answers the first after 60 s, the second
# only after 30 min), Alpha @Gamma once (Gamma only speaks in another room), Beta names Alpha once. Alpha has one
# session with three actions and a consolidation; times are Pacific.
import json, sqlite3, tempfile
from pathlib import Path
from village_graph import cli, core, db, evidence, llm

assert db.pt('2026-05-13 19:33:26.219018') == '2026-05-13 12:33:26.219018'          # UTC -> Pacific (PDT)
assert db.pt('2026-01-05 17:34:00') == '2026-01-05 09:34:00.000000'                 # PST
assert db.cut('x' * 50, 20).count('x') == 20 and 'cut' in db.cut('x' * 50, 20)
assert db.thought({'content': [{'type': 'thinking', 'thinking': 'plan'}, {'type': 'text', 'text': 'note'}]}) == 'plan'
assert db.thought({'role': 'assistant', 'content': 'Let me check', 'reasoning': None}) == 'Let me check'   # a note when no reasoning
assert db.thought([{'type': 'reasoning', 'summary': [{'text': 'sum'}]}]) == 'sum'
assert db.action_of({'command': 'ls'}) == ('bash', 'ls')
assert db.action_of({'action': 'send_message_back_to_chat', 'content': 'hi'}) == ('chat', 'hi')
assert db.action_of({'action': 'left_click', 'coordinate': [1, 2]}) == ('gui', 'left_click coordinate=[1, 2]')
assert db.near('2026-05-11', '2026-05-18')(b'{"created_at": "2026-05-12 10:00:00"}') and not db.near('2026-05-11', '2026-05-18')(b'"2026-06-01 x"')
assert db.near('', db.END) is None
assert evidence.match('run_judging.py "a phrase" OR codex*') == '"run_judging.py" "a phrase" OR codex*'
assert llm.quoted('Scored  natively', 'x scored natively y') and not llm.quoted('scored by hand', 'scored natively')
assert core.ref('t', '0a1b2c3d-4e5f-4000-8000-000000000000') == 't:0a1b2c3d4e5f' and core.ref('t', 'toolu_01A') == 't:toolu_01A'

db.DB = Path(tempfile.mkdtemp()) / 'test.db'
con = sqlite3.connect(db.DB)
con.executescript(db.SCHEMA)
uid = lambda n: f'{n:08x}-0000-4000-8000-000000000000'
con.executemany('INSERT INTO nodes VALUES (?,?,?)', [('a', 'Alpha', 'claude-x'), ('b', 'Beta', 'gpt-x'), ('c', 'Gamma', 'm-c')])
con.execute("INSERT INTO goals VALUES (1, 'Do research!', '2026-09-01 00:00:00', '2026-09-02 00:00:00')")
con.execute("INSERT INTO goals VALUES (2, 'Rest', '2026-09-02 00:00:00', NULL)")
con.executemany('INSERT INTO days VALUES (?,?)', [('2026-09-01', 518), ('2026-09-02', 519)])
msgs = [(1, 'a', 'general', '2026-09-01 10:00:00.000000', '@Beta hi', 'I will greet Beta'),
        (2, 'b', 'general', '2026-09-01 10:01:00.000000', 'Alpha: yes', ''),
        (3, 'a', 'general', '2026-09-01 11:00:00.000000', '@Beta again', ''),
        (4, 'b', 'general', '2026-09-01 11:30:00.000000', 'late', ''),
        (5, 'a', 'general', '2026-09-01 12:00:00.000000', '@Gamma hi, all scores verified', ''),
        (6, 'c', 'rest', '2026-09-01 12:00:30.000000', 'elsewhere', '')]
con.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?)', [(uid(i), *r) for i, *r in msgs])
con.executemany('INSERT INTO edges VALUES (?,?,?,?,?,?)', [(uid(i), s, d, k, 'general', msgs[i - 1][3]) for i, s, d, k in
                [(1, 'a', 'b', 'addressed'), (2, 'b', 'a', 'named'), (3, 'a', 'b', 'addressed'), (5, 'a', 'c', 'addressed')]])
con.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)', (uid(100), 'a', '2026-09-01 10:30:00.000000', '2026-09-01 10:40:00.000000',
                                                                   'Score the 40 items by reading them', 'Score items', 3, 2, 0, 1, 1))
turns = [(201, '2026-09-01 10:31:00.000000', 'bash', 'python3 fill_scores.py  # random.randint(7, 10)', 'Filled scores', '', 0, 'no time to read them'),
         (202, '2026-09-01 10:32:00.000000', 'bash', 'git push', '', 'fatal: rejected', 1, ''),
         (203, '2026-09-01 10:33:00.000000', 'chat', 'all scores verified', 'Message successfully sent back to chat', '', 0, '')]
con.executemany('INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?)', [(uid(i), uid(100), 'a', ts, k, act, out, err, f, why, 0) for i, ts, k, act, out, err, f, why in turns])
con.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)', (uid(300), 'a', '2026-09-01 10:41:00.000000', 'CONSOLIDATE', 'next goal: publish the scores', uid(100), ''))
con.execute('INSERT INTO memories VALUES (?,?,?,?,?,?)', (uid(400), 'a', '2026-09-01 10:41:00.000000', 30, 'Scored all 40 items natively', 0))
con.execute('INSERT INTO memory_days VALUES (?,?,?,?)', ('a', '2026-09-01', '2026-09-01 10:41:00.000000', 'Scored all 40 items natively\nNext: publish'))
con.execute("INSERT INTO terms VALUES ('lambda-lang', '2026-09-01 10:00:00', 'a', ?, 5, 2)", (uid(1),))
con.executemany('INSERT INTO meta VALUES (?,?)', [('actions_from', '2026-09-01 10:31'), ('actions_to', '2026-09-01 10:33'), ('window_from', '2026-09-01'), ('window_to', '2026-09-02')])
for t in db.FTS:
    con.execute(f"INSERT INTO {t}_fts({t}_fts) VALUES ('rebuild')")
con.commit()
con.close()
run = lambda *args: cli.run(cli.parser().parse_args(args))
q = lambda *args: next(b for b in run(*args) if b[0] == 'table')[3]

# who talks to whom
assert q('replies') == [['Beta', 2, 1, '50%', 60], ['Gamma', 1, 0, '0%', None]]
assert q('replies', 'beta') == [['Alpha', 2, 1, '50%', 60]]
assert q('replies', '--within', '31') == [['Beta', 2, 2, '100%', 930], ['Gamma', 1, 0, '0%', None]]
ignored = q('ignored')
assert sorted(ignored[:2]) == [['Alpha', 'Beta', 2, 1, '50%'], ['Alpha', 'Gamma', 1, 0, '0%']]
assert ignored[2] == ['Beta', 'Alpha', 1, 2, '200%']
assert [r[4] for r in q('examples', 'alpha', 'beta')] == ['@Beta again', '@Beta hi']
assert q('agents')[0] == ['Alpha', 'claude-x', 3, 2, 3, 1, '2026-09-01 10:00', '2026-09-01 12:00']
assert [r[4] for r in run('pair', 'alpha', 'beta')[-1][3]] == ['@Beta again', 'Alpha: yes', '@Beta hi']   # samples: both directions, newest first
assert len(run('pair', 'alpha', 'beta', '--samples', '0')) == 2
assert [r[4] for r in run('top-pairs', '--samples', '2')[-1][3]] == ['@Beta again', 'Alpha: yes']   # the top pair's, not the newest overall
assert q('families')[-1] == ['all', 2, 4, 0, '0%', '0%', '']                                          # one agent per maker: no own-family target exists
assert q('families', '--by', 'goal') == [['1: Do research!', 2, 4, 0, '0%', '0%', '']]
lim = lambda *args: cli.parser().parse_args(args).limit                                                # each command keeps its own default
assert (lim('goals'), lim('find', 'x'), lim('timeline', 'a'), lim('examples', 'a', 'b')) == (100, 20, 80, 10)
assert cli.parser().parse_args(['pair', 'a', 'b']).samples == 5 and cli.parser().parse_args(['families']).samples == 0
assert q('agents', '--goal', '2') == [] and len(q('agents', '--day', '518')) == 3                      # scope: goal and village day

# evidence
hits = q('find', 'random', '--in', 'action,reasoning,chat')
assert [(h[1], h[3]) for h in hits] == [('t:000000c90000', 'action·truth')] and '«random»' in hits[0][4]
assert q('find', 'fill_scores.py')[0][1] == 't:000000c90000'                                           # dots need no quoting
assert q('find', 'publish', '--in', 'event')[0][3] == 'consolidate·claim'                              # an event's text is the agent's own
assert q('find', 'verified', '--agent', 'beta') == []
text = run('session', 's:000000640000')[0][2]
assert 'STATED INTENT' in text and 'FAILED: fatal: rejected' in text and 'k:000001900000' in text and 'e:0000012c0000' in text
assert run('session', 't:000000ca0000')[0][2] == text                                                  # an action opens its session
assert 'random.randint' in run('show', 't:000000c90000')[0][2] and '[output from the system · ground truth]' in run('show', 't:000000c90000')[0][2]
assert [r[2] for r in q('timeline', 'alpha', '--kinds', 'action,event')] == ['bash·truth', 'bash·truth', 'consolidate·claim']
assert q('said', 'alpha') == [('2026-09-01 10:00:00', 'm:000000010000', 'I will greet Beta', '@Beta hi')]
assert 'Next: publish' in run('memory', 'alpha')[0][2] and run('memory', 'alpha', '--grep', 'natively')[0][2] == 'Scored all 40 items natively'
assert q('count', 'verified', '--by', 'agent')[0][:5] == ('Alpha', 3, 1, '33.3%', 1)
assert q('terms', '--goal', '1')[0][:3] == ('lambda-lang', '2026-09-01 10:00', 'Alpha')
assert q('first-use', 'hi')[0][1:3] == ('Alpha', 2)
assert q('sessions')[0][:1] == ('s:000000640000',) and q('goals')[0][0] == 2
assert q('sql', 'SELECT count(*) FROM turns WHERE failed')[0] == [1]
assert 'not a ref' in cli.run_line('show nonsense') and 'read-only' in cli.run_line('sql "DELETE FROM turns"')
assert 'is not available here' in cli.run_line('build')
assert 'Actions, reasoning and memories are loaded only' in cli.run_line('timeline alpha --since 2026-08-01')   # outside the window: say so

# the web page's server: runs a command, remembers it, refuses what is terminal-only
import contextlib, io, threading, urllib.request
from http.server import ThreadingHTTPServer
from village_graph import web
srv = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
get = lambda path: json.loads(urllib.request.urlopen(f'http://127.0.0.1:{srv.server_port}{path}').read())
rec = get('/api/run?cmd=find%20random%20--in%20action')
assert rec['blocks'][0][0] == 'table' and rec['blocks'][0][3][0][1] == 't:000000c90000' and rec['source'] == 'web'
assert 'not available' in get('/api/run?cmd=build')['error'] and 'not a ref' in get('/api/run?cmd=show%20nope')['error']
with contextlib.redirect_stdout(io.StringIO()):
    cli.main(['sessions'])                                                                             # a terminal run is remembered too
hist = get('/api/history')
assert [h['source'] for h in hist[:2]] == ['terminal', 'web'] and get(f"/api/history?id={hist[0]['id']}")['blocks'][0][0] == 'table'
assert {'find', 'ask'} <= {c['name'] for c in get('/api/meta')['commands']} and 'Alpha' in get('/api/meta')['agents']
assert b'<title>village</title>' in urllib.request.urlopen(f'http://127.0.0.1:{srv.server_port}/').read()
# research tools stay off the public page; a long command can run as a job and be polled
assert 'not available' in get('/api/run?cmd=py%20print(1)')['error'] and 'not available' in get('/api/run?cmd=ask%20hi%20--deep')['error']
job = get('/api/run?cmd=sessions&async=1')['job']
for _ in range(50):
    r = get(f'/api/job?id={job}')
    if r['done']:
        break
    __import__('time').sleep(0.1)
assert r['done'] and r['run']['blocks'][0][0] == 'table'
srv.shutdown()

# sample: a seeded sample of a pattern's matches; py: read-only code over the same database
blocks, _ = cli.run_cmd('sample "random|again" --in chat,action --n 1')
assert '1 of 2 matches' in blocks[0][1] and blocks[0][3] == cli.run_cmd('sample "random|again" --in chat,action --n 1')[0][0][3]  # same seed, same sample
from village_graph import pyrun
assert pyrun.run("print(q('SELECT count(*) FROM messages')[0][0], names['a'])") == '6 Alpha'
for bad in ("open('x.txt', 'w')", "import socket; socket.socket()", "import os; os.system('true')", "db.execute('CREATE TABLE z (a)')",
            "open('/etc/hostname').read()"):
    assert pyrun.run(bad).startswith('error:'), bad
assert [x for x in llm.QUOTE.findall('It said "finished scoring the packets" [m:1] and "ok".') if len(x.split()) >= 3] == ['finished scoring the packets']

# the labeller's unit text carries only citable refs; grading rules
con = core.connect()
unit = llm.unit_text(con, {'unit': 'session', 'shows': 'full'}, uid(100))
assert llm.refs_in(unit) >= {'s:000000640000', 't:000000c90000', 'e:0000012c0000', 'k:000001900000'}
assert 'ACTIONS' not in llm.unit_text(con, {'unit': 'session', 'shows': 'intent'}, uid(100))
assert 'THE MESSAGE TO LABEL · m:000000050000' in llm.unit_text(con, {'unit': 'message', 'context': '2'}, uid(5))
# ground-truth files: a quote is checked against the record it cites, and the review page shows the miss
import sys
sys.path.insert(0, str(Path(__file__).parent / 'evals'))
import check_citations, review_page
gt = db.DB.parent / 'gt.json'
gt.write_text(json.dumps({'question': 'Q?', 'answer': 'A.', 'confidence': 'high', 'tables': [{'title': 'Per agent', 'columns': ['Agent', 'n'], 'rows': [['Alpha', 3]]}], 'findings': [
    {'claim': 'scores came from a script', 'kind': 'ground truth', 'citations': [{'ref': 't:000000c90000', 'field': 'action', 'quote': 'random.randint(7,  10)'}]},
    {'claim': 'it was read by hand', 'kind': 'claim', 'citations': [{'ref': 't:000000c90000', 'field': 'action', 'quote': 'scored by hand'}]}]}))
with contextlib.redirect_stdout(io.StringIO()):
    assert not check_citations.check(con, gt)
assert [f['verified'] for f in json.loads(gt.read_text())['findings']] == [True, False]
sys.argv = ['review_page', str(db.DB.parent / 'gt.html'), f'Group={gt}']
with contextlib.redirect_stdout(io.StringIO()):
    review_page.main()
page = (db.DB.parent / 'gt.html').read_text()
assert 'quote NOT found in the record' in page and '<td class="num">3</td>' in page
con.close()
g = lambda check, text: llm.grade(None, {'check': check, 'question': '', 'truth': ''}, text, None)[0]
assert g({'number': 22}, 'It ran many.\nANSWER: 22 sessions') and not g({'number': 22}, 'ANSWER: 21 sessions [t:000000c90000]')
assert g({'number': 1014, 'tol': 5}, 'ANSWER: about 1,012') and g({'all': ['gemini', r'gpt-5\.5']}, 'Gemini was caught by GPT-5.5')
assert not g({'all': ['gemini'], 'none': ['o3 did']}, 'gemini\nANSWER: o3 did it')
for name in (p.stem for p in (Path(__file__).parent / 'rubrics').glob('*.md')):
    assert llm.rubric(name)['labels']
for qn in json.loads((Path(__file__).parent / 'evals' / 'questions.json').read_text()):
    assert {'id', 'question', 'truth', 'kind', 'source'} <= qn.keys() and (qn.get('check') or qn.get('judge')), qn['id']
assert llm.NOW.search('What is happening in the village?') and not llm.NOW.search('Which agent ran the most commands?')
for qn in json.loads((Path(__file__).parent / 'evals' / 'ground_truth_questions.json').read_text()):
    assert qn.keys() == {'id', 'goal', 'question', 'answer'} and qn['answer'], qn['id']
print('ok')
