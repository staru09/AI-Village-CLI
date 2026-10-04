"""Recompute the eval set's countable ground truths straight from the raw dataset tables, without the CLI's code.

    VILLAGE_DATA=/path/to/tables python3 evals/verify.py     # about 3 minutes; prints each fact

Run it after a new dataset export: if a number here changes, update evals/questions.json to match.
"""
import gzip, json, os, re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

D = Path(os.environ['VILLAGE_DATA'])
PT = ZoneInfo('America/Los_Angeles')
pt = lambda s: datetime.fromisoformat(s[:26]).replace(tzinfo=timezone.utc).astimezone(PT).strftime('%Y-%m-%d %H:%M:%S') if s else None
rows = lambda n: map(json.loads, gzip.open(D / n, 'rt'))

agents = {a['id']: a['name'] for a in rows('agents.jsonl.gz')}
goals = sorted(((pt(g['start_time']), pt(g['end_time']) or '9999', g['goal'].strip()) for g in rows('village_goals.jsonl.gz')))
span = lambda text: next((s, e) for s, e, g in goals if text in g)
NR, BA = span('Perform novel research'), span('best AI Assistant')
print('village goals:', len(goals))
print('goal on 2025-08-19 (village day 140):', next(g for s, e, g in goals if s <= '2025-08-19 12:00:00' < e))
print("Claude Opus 4.8's agent goal:", [(g['short_name'], g['name']) for g in rows('agent_goals.jsonl.gz') if agents[g['agent_id']] == 'Claude Opus 4.8'])

automated, pauses = set(), Counter()
for e in rows('events.jsonl.gz'):
    d = e['data'] or {}
    if d.get('actionType') == 'USER_TALK' and d.get('speakerName') == 'automated':
        automated.add(d.get('messageId'))
    if d.get('actionType') == 'PAUSE' and NR[0] <= pt(e['created_at']) < NR[1]:
        pauses[agents.get(d.get('agentId'))] += 1
print('PAUSE events in novel research, top 3:', pauses.most_common(3), '| Gemini 2.5 Pro:', pauses['Gemini 2.5 Pro'])

sent_ba, sent_nr, humans_nr, first_ls = Counter(), Counter(), 0, None
for m in sorted(rows('chat_messages.jsonl.gz'), key=lambda m: m['created_at']):
    ts, who = pt(m['created_at']), agents.get(m['agent_speaker_id'])
    if BA[0] <= ts < BA[1] and m['speaker_type'] == 'agent':
        sent_ba[who] += 1
    if NR[0] <= ts < NR[1]:
        if m['speaker_type'] == 'agent':
            sent_nr[who] += 1
        elif m['id'] not in automated:
            humans_nr += 1
    if not first_ls and m['speaker_type'] == 'agent' and re.search(r'label[- ]swap', m['content'] or '', re.I):
        first_ls = (who, ts)
print('chat messages in "best AI Assistant", top 3:', sent_ba.most_common(3))
print('chat messages in novel research: agents', sum(sent_nr.values()), '| by humans (not the automated system):', humans_nr)
print('o3 in novel research: messages', sent_nr['o3'])
print('first chat use of "label-swap":', first_ls)

sess, per_day, o3_sessions, named = {}, Counter(), 0, {'Persistence Garden': Counter(), 'Drift': Counter()}
for s in rows('computer_use_sessions.jsonl.gz'):
    ts, who = pt(s['created_at']), agents[s['agent_id']]
    sess[s['id']] = who
    if who == 'Gemini 3.1 Pro' and ts[:10] == '2026-05-13':
        per_day[who] += 1
    if NR[0] <= ts < NR[1]:
        o3_sessions += who == 'o3'
        for k in named:
            if k.lower() in (s['session_goal'] or '').lower() + (s['short_displayed_session_goal'] or '').lower():
                named[k][who] += 1
print('Gemini 3.1 Pro sessions on 2026-05-13 (day 407):', per_day['Gemini 3.1 Pro'], '| o3 sessions in novel research:', o3_sessions)
for k, c in named.items():
    print(f'sessions in novel research whose stated goal names "{k}":', c.most_common(3))

bash, total, commit = Counter(), Counter(), None
with gzip.open(D / 'computer_use_turns.jsonl.gz', 'rb') as f:
    for line in f:
        if b'"2026-05-1' not in line:
            continue
        t = json.loads(line)
        ts = pt(t['created_at'])
        if not (NR[0] <= ts < NR[1]) or t['session_id'] not in sess:
            continue
        who, a = sess[t['session_id']], t['agent_action'] or {}
        total[who] += 1
        bash[who] += 'command' in a or a.get('action') == 'bash'
        if who == 'Gemini 3.1 Pro' and ts[:16] == '2026-05-13 10:30' and 'add gemini-3.1-pro judgments' in (t['output'] or ''):
            commit = re.search(r'\[feature/replication-wave (\w+)\]', t['output'])[1]
print('bash commands in novel research, top 3:', bash.most_common(3))
print('actions in novel research:', sum(total.values()), '| by agent, top 3:', total.most_common(3))
print('commit that added the random scores (from git output, 13 May 10:30 PT):', commit)
