# village usage

## The idea

A village goal is the unit: every record belongs to the goal running when it happened. Inside a goal, each computer
session is a chain you can check:

```
village goal (+ agent goal)  ->  stated intent  ->  reasoning  ->  actions  ->  outputs  ->  self-report
      ground truth                  claim            claim      ground truth  ground truth     claim
```

Three checks follow from it, and most questions about misalignment are one of them:

1. **Intent vs goal:** does what the agent set out to do serve the goal? (`goal_fit`)
2. **Action vs intent:** did it do what it said it would? (`did_what_it_said`)
3. **Claim vs outcome:** does what it reported match what the outputs show? (`over_report`, `made_up_data`)

## Scope

Every query command takes the same scope flags. They combine (the narrowest wins).

| Flag | Meaning |
|---|---|
| `--goal 41` or `--goal "novel research"` | one village goal, by its number in `goals` or part of its text |
| `--day 407` | one village day (Day 1 = 2 April 2025; weekends count) |
| `--date 2026-05-13` | one Pacific-time day |
| `--since`, `--until` | a date or `"YYYY-MM-DD HH:MM"`, Pacific time; `--until` is exclusive |
| `--agent NAME` | one agent, by any unique part of its name (where the command takes it) |
| `--limit N`, `--wide` | more rows; whole texts instead of cut ones |
| `--json` | the result as JSON |

## Commands

**Orient**

| Command | Answers |
|---|---|
| `goals` | the village goals: dates, day numbers, agents, messages, sessions, and how many actions are loaded |
| `overview` | the goals in scope, the chat rooms, and per agent: messages, sessions, actions, commands, failures, share of actions with reasoning |
| `recap` | AI Digest's own daily recap or goal story. Secondary: for deciding where to look |
| `schema` | tables, columns, row counts, and which part of the history has actions loaded |

**Search and count** (no model)

| Command | Answers |
|---|---|
| `find TEXT [--in FIELDS] [--order time]` | full-text search with snippets. Fields: `chat`, `said-why`, `action`, `output`, `error`, `reasoning`, `intent`, `memory`, `event`, `recap`. Plain words must all match; `"a phrase"`, `OR` and `prefix*` work |
| `count REGEX [--in FIELDS] [--by agent\|model\|maker\|day\|room]` | how often a pattern occurs, per 1,000 words, with its base |
| `terms` | words and names first used in chat inside the scope (candidates for coined terms), by how many agents adopted them |
| `first-use TERM` | who used a term first and who picked it up when |

**Read**

| Command | Shows |
|---|---|
| `show REF… [--context N]` | records in full: a message with its reasoning, an action with its reasoning, output and error |
| `sessions [--agent A]` | sessions with their stated goal, actions, commands and failures |
| `session REF` | one session as a chain: goals, stated intent, every action with its result, and the consolidation and memory lines that closed it |
| `timeline AGENT [--kinds …]` | one agent's chat, session goals, actions, events and memory updates in time order |
| `said AGENT` | thought vs said: its chat messages next to the reasoning recorded just before each |
| `memory AGENT [--diff] [--grep REGEX]` | its notes at the end of the scope, or what each rewrite added |
| `shot REF [--save PATH]` | an action's screenshot (needs the dataset's `images/` tars, or `VILLAGE_IMAGES`) |
| `sql "SELECT …"` | one read-only query |

**Who talks to whom** (from `@Name` and plain name mentions in chat; there is no reply-to field in the dataset)

`pair A B`, `neighbors A`, `top-pairs`, `hubs`, `agents`, `examples A B`, `ignored`, `replies [A]`. They also take
`--room` and `--kind addressed|named`. "Replied" in `replies` means the agent posted anything in the same room within
`--within` minutes.

**With a model** (`uv sync --extra llm`, `ANTHROPIC_API_KEY`)

| Command | Does |
|---|---|
| `label RUBRIC [scope] [--match TEXT] [--within RUBRIC=LABEL] [--limit N]` | applies a rubric to each session, message or action in scope and stores label, confidence, quote, evidence refs and a reason. The default is a sample of 20 spread over the scope; `--limit 0` runs them all |
| `labels RUBRIC [--by agent\|model\|maker\|day] [--rows LABEL]` | counts per group with their base, or the rows behind a count |
| `verdict RUBRIC REF LABEL [note]` | your own verdict on one unit; it overrides the model's label in every count |
| `check RUBRIC CASES.jsonl` | runs the rubric on cases with known answers and reports agreement |
| `look REF "question"` | a vision model reads one screenshot |
| `ask "question"` | an agent answers by running these commands, and cites refs |
| `eval [FILE]` | grades the agent on questions with known answers |

Models: `label` uses `$VILLAGE_LABEL_MODEL` (default `claude-haiku-4-5`), `ask` uses `$VILLAGE_ASK_MODEL` (default
`claude-opus-5-5`). If the asking model stops with a safety refusal, the question starts again with
`$VILLAGE_FALLBACK_MODEL` (default `claude-sonnet-5-5`).

## Refs

`m:` chat message, `t:` action, `s:` session, `e:` event, `k:` memory version, `r:` recap. A ref is the first 12 hex
digits of the record's UUID in the dataset, so it stays the same across rebuilds.

## Rubrics

A rubric is a text file in `rubrics/`: a few header lines, `---`, then the instructions the model follows.

```
unit: session                  # session | message | action
labels: fabricated, disclosed_placeholder, none
shows: full                    # session only: full (actions and self-report) or intent (goal and intent only)
---
Did the agent, in this session, produce data by making it up …
```

| Rubric | Unit | Question |
|---|---|---|
| `goal_fit` | session | does the stated intent serve the goal? (check 1) |
| `did_what_it_said` | session | do the actions do what the intent says? (check 2) |
| `over_report` | session | do the claims match the outputs? "done" with no check run, "done" when the check failed, overstated (check 3) |
| `made_up_data` | session | did it generate data and present it as real? |
| `deception_plan` | action | does the reasoning before an action choose to mislead? |
| `callout` | message | does it call out another agent's work, or admit its own mistake? |
| `credit` | message | whose success or failure does it say this is? |
| `delegation` | message | is one agent directing another? |
| `mood` | message | the tone expressed |

What keeps labels honest:

- **The quote is checked in code.** The model must copy the deciding words from the unit; a quote that is not in the
  unit is marked `✗`.
- **Evidence must be shown.** Only refs that appear in the unit are kept.
- **Try before you run.** `label` samples 20 units by default, and refuses more than 500 without `--yes`.
- **Known cases first.** `check` runs a rubric on cases you verified by hand, including cases it must leave alone.
- **Your verdict wins.** `verdict` overrides a label, and `labels` counts the overridden value.
- **Counts carry their base.** `labels` says how many units in scope were labelled, by which model.
- **A changed rubric is a new version.** Labels made with an older text are reported as such.

Reasoning is missing for some models (Claude Opus 4.7 and DeepSeek-V3.2 return almost none; OpenAI and Gemini 3.x
return summaries). `overview` shows the share per agent. A rubric that reads reasoning says nothing about an agent
with none.

## The agent (`ask`)

`ask` gives Claude one tool: this CLI. It orients (`goals`, `overview`), searches, reads the records, counts with the
tool, and writes a short answer with refs. After it answers, the code checks that every ref it cited appeared in a
tool result; if not, it must fix the answer. It ends with one `ANSWER:` line. The cost and the commands it ran are
printed with the answer.

The same loop can sit behind a web page: `village_graph.llm.answer(question)` returns the answer, the commands, the
cost and the citation check. The database is opened read-only, `sql` accepts only `SELECT`, and a query is stopped
after 30 seconds.

## Eval

`evals/questions.json` holds 22 questions with known answers, on "Perform novel research!" (11 to 15 May 2026) plus
a few on chat from other goals. Build the database with `village build --goal "novel research"` first.

| Kind | Tests | Graded by |
|---|---|---|
| lookup, count, social | facts and counts | a number or a name in the answer |
| investigate | finding and reading the right records | names and facts, then a judge model against the ground truth |
| claim-vs-record | telling what an agent said from what it did | a judge model |
| absence | not inventing: an agent that was not there, reasoning that was not recorded, actions that are not loaded | a judge model |

Where the truths come from: `evals/verify.py` recomputes every countable one from the raw tables without this tool's
code; the others were read by hand in the raw actions, and each question's `source` says where.

```bash
uv run village eval                                   # all questions; about 3 minutes and $2
uv run village eval --ids I1-fabricated-who,V2-native-claim
uv run village eval --agent-cmd 'my-agent "{question}"'   # grade another agent: it must print its answer
```

Result on 2026-10-04 with `claude-opus-5-5`: 21 of 22, about $2.10 and 3.5 minutes in all ($0.02 to $0.28 per
question). The one failure, `A2-no-reasoning`, is a refusal: Claude's API declines questions that ask for a Claude
model's private reasoning, before any command runs. Ask what the agent did or said instead.

A question is `{id, kind, question, truth, source}` plus `check` (`number` with optional `tol`, `all`, `any`, `none`:
regular expressions) and/or `"judge": true`. Add your own the same way.

## Database

`village.db` (see `village schema` for the live list). Times are Pacific. `agent`, `src` and `dst` hold `nodes.id`.

```text
nodes(id, name, model)                      goals(n, goal, start_time, end_time)        days(date, day)
agent_goals(agent, name, short, description, start_time, end_time)
messages(id, src, room, ts, content, reasoning)        edges(msg_id, src, dst, kind, room, ts)
sessions(id, agent, ts, end_ts, goal, short, turns, bash, gui, chat, failed)
turns(id, session, agent, ts, kind, action, output, error, failed, reasoning, shot)
events(id, agent, ts, type, text, session, reasoning)
memories(id, agent, ts, chars, added, dropped)         memory_days(agent, date, ts, content)
summaries(id, type, date, target, ts, content)         terms(term, first_ts, first_agent, first_msg, uses, agents)
labels.db: labels(rubric, ref, rev, unit, agent, ts, label, confidence, quote, quote_ok, evidence, why, model, made, verdict, note)
```

Known limits:

- **Long texts are cut** to their head and tail: commands at 12,000 characters, outputs at 6,000, reasoning at 8,000.
- **A failed command is a guess.** A shell command's `error` is its stderr, which successful commands also write; it
  counts as failed only when the text looks like a failure.
- **Memories are stored as differences.** Each version keeps the lines it added; the whole text is kept once per
  agent and day (the day's last version).
- **Mentions use exact full names.** Nicknames such as "Opus" are skipped.
- **Claude Code agents** set no session goal; their tool calls are loaded as actions.
