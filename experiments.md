# Experiments

A running log of what we tried on the AI Village data with this tool: what was run, how, what came out, what it cost.
Newest first. Costs are API estimates printed by the tool. Unless a line says otherwise, the scope is the village goal
"Perform novel research!" (goal 41, 11–15 May 2026: 15 agents, 2,146 agent chat messages, 1,014 sessions, 35,898 actions),
built with `village build --goal "novel research"`.

How to read an entry: **Question** (what we wanted to know), **Run** (the command or method), **Result**, **Cost**,
**Verdict** (what we decided), **Where** (files, commits).

---

## 2026-10-04

### E17. DocETL against the ground truth
- **Question:** do DocETL pipelines give the same answers as the verified ones, and what do they cost?
- **Run:** `docetl/run.py` (DocETL 0.3.0 in `.venv-docetl`, Claude Sonnet 5.5 through LiteLLM), four pipelines over goal 41:
  `counts` (code operators only), `delegation` (map over the 652 @-messages), `goal_fit` (map over the 1,014 sessions),
  `groups` (reduce per day, then across days). The units and rubric texts are the ones `village label` uses.
  `docetl/compare.py` checks the outputs against the ground truth.
- **Result:**

  | Pipeline | Against the ground truth | Units returned | Time | Cost | Our own run |
  |---|---|---|---|---|---|
  | `counts` (code only) | exact: Gemini 3.1 Pro 2,785 commands; 35,898 actions | all | under 1 s | $0 | same numbers by SQL |
  | `goal_fit` (map) | G10, G11, G12 match | 1,014 of 1,014 | 104 s | $7.40 | `village label`: $3.90, 339 s |
  | `delegation` (map) | G7, G9 match; G6, G8 match once one borderline message each for GPT-5.5 and Gemini 2.5 Pro is allowed | 647 of 652 | 66 s | $6.89 | `village label`: $4.94, 221 s |
  | `groups` (two reduces) | names the right trio but says 5 days (truth: 4); lists 18 pairs "every day" (truth: 2, both among the 18) | 1 row | 36 s | $0.61 | `evals/recurring_groups.py`: exact, $0 |

  - **Same labels as ours?** `goal_fit`: 926 of 1,014 (91%). `delegation`: 509 of 646 on the exact label (79%), 616 of
    646 on assigns-a-task-or-not (95%). Same model and rubric text, so this is run-to-run variation plus the different
    output format.
  - **It changed one ground-truth answer.** DocETL labelled one message each by GPT-5.5 and Gemini 2.5 Pro as a task
    assignment. Read by hand, both are borderline (a soft suggestion; "the floor is yours"). G6 and G8 now say "no clear
    assignment, at most one borderline message" for those two.
  - **One refused unit aborted the first `delegation` run** (Claude's safety filter returned no output; DocETL raised
    and wrote nothing). With `skip_on_error=True` it finishes but returns 647 of 652 with no list of what was dropped;
    one of the 5 is a real task assignment. `village label` records the failed units and keeps going.
  - **Why it costs more:** no Anthropic prompt caching (2.4M and 2.6M prompt tokens, all at full price; our runs read
    1.4M of 2.3M and 0.8M of 2.6M from cache) and longer outputs. **Why it is faster:** more parallel calls.
- **Cost:** about $15 for the runs above, plus the aborted `delegation` run (up to about $7 more).
- **Verdict:** DocETL's map gives the same answers as `village label` at 1.4 to 1.9 times the cost and a third of the
  time, without our quote check, evidence refs, failure record or verdicts. Its LLM reduce over-claims on a question
  that a counting script answers exactly. Not adopted as a dependency. Worth taking from it: more parallel calls in
  `label`. Not yet tried: reduce for summaries, resolve for names and terms.

### E16. Recurring groups ("swarms"), without a model
- **Run:** `python3 evals/recurring_groups.py 1` (and `2`). Per day, two agents are linked when each @-addressed the
  other at least N times; a group is 3 or more agents all linked to each other.
- **Result:** one trio recurs: Claude Opus 4.7, GPT-5.5 and Gemini 3.1 Pro (#best), on 4 of 5 days. Two pairs are
  linked on all 5 days: Claude Haiku 4.5 + DeepSeek-V3.2 and Claude Opus 4.5 + GPT-5.4 (#rest). At N = 2 no trio
  reaches 4 days. Recounted from the raw chat table with a plain regular expression (`evals/verify.py`): same.
- **Cost:** none.

### E15. Goal alignment from what the commands touched, without a model
- **Question:** an independent check of the `goal_fit` labels (E7), and ground truth for "how aligned is model X".
- **Run:** `python3 evals/alignment_by_repo.py`. Each bash action names folders and repositories; the names are sorted
  by hand into research, worlds (earlier goals' projects) and analysis projects; a session takes the kind most of its
  commands touch.
- **Result:** research share of classified sessions: Claude Opus 4.7 100% (66 of 66), Kimi K2.6 97%, GPT-5.5 96%,
  Gemini 3.1 Pro 85%; Claude Opus 4.6 41% (28 research, 40 world); Claude Sonnet 4.5 and 4.6 9% each. Per day: 89%,
  80%, 38%, 26%, 41%. GPT-5 ran no commands (47 sessions unclassified). The `goal_fit` labels agree with this measure
  on 608 of 664 sessions (92%).
- **Cost:** none.
- **Verdict:** two independent measures agree, so alignment answers for this goal can be treated as ground truth.

### E14. "Taken up" as a measure of following: rejected
- **Run:** `village leaders --goal 41 --strict`: an assignment counts as taken up when the addressed agent @-answers
  the sender within 60 minutes with a message labelled `accepts` or `reports_back`. Then 4 "taken up" (Claude Opus 4.7)
  and 4 "not taken up" (Claude Haiku 4.5) assignments read by hand.
- **Result:** the 4 "taken up" were real, except one where the reply an hour later was about something else. All 4
  "not taken up" were in fact followed: the agent did the task or confirmed, without @-addressing the sender.
- **Verdict:** the rate measures explicit acknowledgement, not compliance. It is not used as ground truth, so "best
  leader" and "best follower" by follow-through are still open. A better measure has to look at what the addressed
  agent did next.

### E13. Blind check of the `delegation` labels
- **Run:** 40 @-messages drawn at random from the 637 not used to tune the rubric (20 the model called a delegation,
  20 it did not), labelled by hand without seeing the model's labels, then compared.
- **Result:** 37 of 40 agree. All 3 disagreements are messages the model called `requests_help` (questions put to
  another agent); none was a missed delegation, and every `directs` label was confirmed.
- **Verdict:** `directs` is reliable; `requests_help` is fuzzy. Leadership answers use `directs` only (`leaders --strict`).

### E12. Ground-truth questions for the research goal
- **Question:** 10–15 questions on goal 41 with answers we have verified ourselves, to grade any tool against.
- **Result:** 12 questions added to `evals/questions.json` (ids G1–G12; 34 in all):
  - counts (G1, G2) and mention pairs and groups (G3–G5): computed by SQL and recounted from the raw tables by
    `evals/verify.py`;
  - who assigns tasks (G6–G9): `delegation` labels restricted to `directs`, with E13 and hand-reading of the rows
    behind each answer (all 16 task-assigning messages of Claude Opus 4.7, all 19 of DeepSeek-V3.2, and every
    directive-like sentence of the five agents that never assign);
  - alignment (G10–G12): E15 and the `goal_fit` labels together.
- **Not included:** "best leader" and "best follower" by follow-through (E14).

### E11. `leaders`: who delegates to whom, who follows
- **Run:** `village leaders --goal 41`, computed from the E9 labels. A delegation = an @-message labelled `directs` or
  `requests_help`, once per agent addressed (350 in all). Taken up = the addressed agent @-answers the sender within
  60 minutes with a message labelled `accepts` or `reports_back`.
- **Result (a model's labels, not yet hand-verified):** most delegations taken up: DeepSeek-V3.2 (29 of 75), Claude
  Opus 4.7 (23 of 40, the highest rate among the active ones, 57%). Claude Haiku 4.5 delegated 73 times, 7 taken up.
  Top pair: Claude Opus 4.7 → GPT-5.5 (20, 12 taken up). Same-family share 21% against 20% expected (ratio 1.06).
- **Cost:** none (SQL over stored labels).

### E10. Recursive Language Model (`village rlm`), parked
- **Question:** is an RLM (github.com/alexzhang13/rlm) a cheaper way to answer questions than `ask`?
- **Run:** `village rlm "Which agent sent the most chat messages in this scope, and how many?" --goal 41 --no-actions`.
  The scope is exported as one object (4.6 MB without actions, 23.1 MB with) into a Docker REPL; root model Claude
  Sonnet 5.5, sub-calls Claude Haiku 4.5. Library pinned at commit `d04208a`.
- **Result:** correct (GPT-5.4, 387). 7 root calls, no sub-calls.
- **Cost:** $0.44, 171 s (174k tokens in, 146k of them from cache; 34k out). `ask` answers the same kind of counting
  question for $0.02–0.06 in 10–20 s.
- **Needed to make the library work with current Claude models:** pass the API key explicitly; read text blocks, not
  `content[0]` (a thinking block); no assistant prefill; prompt caching added.
- **Verdict:** more expensive than `ask` for lookups. Untested on whole-goal synthesis questions, where it should
  help. Parked at the user's request until ground truth exists.
- **Where:** `village_graph/rlm_run.py`, commit `f34f3c6`.

### E9. `delegation` rubric on every @-message
- **Run:** 15 hand-labelled cases (`evals/cases/delegation.jsonl`), `village check delegation …` with two models, then
  `village label delegation --goal 41 --limit 0 --yes` (652 messages that @-address another agent, each shown with the
  3 messages before it).
- **Result:** Haiku 4.5 agrees on 9 of 15 (it over-uses `reports_back`), Sonnet 5.5 on 14 of 15. One of Sonnet's two
  first "misses" was my own wrong hand label (fixed after reading the context). Full run with Sonnet: 652 labelled.
- **Cost:** checks $0.17; full run $4.94, 221 s.
- **Verdict:** the rubric needs Sonnet (`model: claude-sonnet-5-5` in the rubric file).

### E8. `families`: same maker or not, from mentions
- **Run:** `village families --goal 41` and `village families --by goal`. Chance = each mention lands on another agent
  in the same room in proportion to how often that agent is mentioned there.
- **Result:** goal 41: no family preference (19% own family against 20% expected, ratio 0.99). Across the 51 goals the
  ratio is mostly 1.05–1.45 from goal 18 to goal 40, then at or below 1 from goal 41 on, except goals 44–46 (1.3–1.4).
- **Cost:** none (no model).

### E7. `goal_fit` rubric: three full runs before it was right
- **Question:** does each session's stated intent serve the village goal?
- **Run 1:** Haiku 4.5, first rubric text. $2.19, 305 s. **Wrong:** GPT-5's leftover work from the previous goal
  ("Connect your worlds into a 3D universe!") was labelled research (74% on goal).
- **Run 2:** Haiku 4.5, with the previous goal shown to the labeller. $2.37, 318 s. **Wrong the other way:** real study
  work ("Finish C4 judging") was labelled as the previous goal's.
- **Cases:** 27 sessions labelled by hand (`evals/cases/goal_fit.jsonl`; 8 of them held out when the first rewording
  was made, the later ones added after seeing errors). Haiku 22 of 27, Sonnet 5.5 27 of 27.
- **Run 3:** Sonnet 5.5, rubric reworded to judge by the kind of work. $3.90, 339 s. On goal per agent: Claude Opus 4.7
  90%, GPT-5.5 85%, Kimi K2.6 78%, Gemini 3.1 Pro 68%; side project: GPT-5 95%, Claude Sonnet 4.5 87%, Claude Sonnet 4.6
  75%, Claude Opus 4.6 57%, GPT-5.1 54%. On-goal share of sessions per day: 77%, 51%, 31%, 18%, 34%.
- **Verdict:** labels from a rubric can be wrong in one direction for a whole agent. Check on hand-labelled cases that
  include the cases it must leave alone, and read the rows of any surprising number, before trusting a full run.

### E6. Web page (`village web`)
- Not an experiment on the data; see USAGE.md. Checked in a headless browser (desktop, phone, dark mode).

### E5. Eval of the `ask` agent
- **Run:** `village eval` (22 questions with ground truth in `evals/questions.json`; countable truths recomputed from
  the raw tables by `evals/verify.py`).
- **Result:** 21 of 22 with Claude Opus 5.5. The failure (`A2-no-reasoning`) is an API refusal: questions that ask for
  a Claude model's private reasoning are declined before any command runs.
- **Cost:** $2.08 and 213 s for all 22 ($0.02–0.28 per question).

### E4. `made_up_data` rubric on one agent-day
- **Run:** `village label made_up_data --agent "gemini 3.1" --day 407 --limit 0` (22 sessions, whole session text).
- **Result:** 4 labelled fabricated. Two verified by hand in the raw actions: random scores pushed as judgements
  (10:30 PT, commit `dca1d17`) and script-made scores committed as "native" (13:53 PT).
- **Check on 5 hand-verified cases:** Haiku 5 of 5, Sonnet 5 of 5, Opus 5.5 4 of 5 (one unit refused by its safety
  filter: the unit contained another model's reasoning).
- **Cost:** $0.21 for the 22 sessions; checks $0.05–0.20 each.

### E3. First question to the `ask` agent
- **Run:** `village ask "During the 'Perform novel research!' goal, did any agent submit made-up evaluation scores …"`.
- **Result:** found the incident, the admission and an earlier case on day 405; 19 commands, 24 citations, all valid.
- **Cost:** $1.61 before prompt caching was added to the loop; the same kind of question costs $0.08–0.16 after.

### E2. Research (no data touched)
- **Jev (TypeSafe AI):** a cheap decision model for per-message labels. Parked: needs its own API key.
- **DocETL (github.com/ucbepic/docetl):** LLM map/reduce pipelines. A background agent read the docs and source.
  Its risks for us: rows that fail validation are dropped silently, long inputs are truncated silently, provenance is
  only pass-through fields. To be tried against ground truth in E12.
- **Thimble, Docent, Inspect Scout, Hodoscope, MAST:** surveyed earlier the same week; thimble was installed but could
  not be run unattended from this session.

### E1. Day page for one agent
- A static page of every record for Gemini 3.1 Pro on day 407, labelled by pipeline step and trust level (throwaway
  script, published privately as an artifact). It led to the session view (`village session`).

---

## Earlier, in the AI-village-3D repo (branch `honcho`)
- **Honcho memory pilot (2026-10-03):** one day of o4-mini (448 messages, about 6 min) and of GLM-5.3 Flash (929
  messages, about 13.5 min) fed into a local Honcho. Specific answers, no peer card after one day. Paused.
