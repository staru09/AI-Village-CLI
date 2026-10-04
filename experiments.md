# Experiments

A running log of what we tried on the AI Village data with this tool: what was run, how, what came out, what it cost.
Newest first. Costs are API estimates printed by the tool. Unless a line says otherwise, the scope is the village goal
"Perform novel research!" (goal 41, 11–15 May 2026: 15 agents, 2,146 agent chat messages, 1,014 sessions, 35,898 actions),
built with `village build --goal "novel research"`.

How to read an entry: **Question** (what we wanted to know), **Run** (the command or method), **Result**, **Cost**,
**Verdict** (what we decided), **Where** (files, commits).

---

## Learnings so far

What the experiments below have taught us, with the entry each one comes from. Updated 2026-10-04 after E24.

### About the data
- **A claim is only checkable next to the command behind it.** Every serious failure we found came from putting what
  an agent said beside what the system recorded: "finished scoring" one minute after a script wrote random scores;
  "r ≈ 0.4" that exists only inside a print statement; an "8,424-word" guide whose own word count printed 973. Chat,
  stated intent, reasoning and memory are claims; commands, outputs, errors and events are the record (E18).
- **How much reasoning is stored depends on the model, so intent cannot be read for everyone.** Claude Opus 4.7 has
  reasoning text on 4.8% of its actions, Gemini 3.1 Pro on 34%; GPT and Gemini reasoning is a summary; DeepSeek-V3.2
  has a one-line note. "Nothing in its reasoning" means little for these agents (E18).
- **Check an assumption about the data with a count before building on it.** My brief to the investigators said
  DeepSeek-V3.2 had almost no reasoning; it has a note on 1,710 of 1,847 actions. Two earlier errors of the same kind: goal
  changes read in UTC instead of Pacific time, and day numbers taken from summaries instead of the calendar (E18).
- **Agents get their own day numbers and counts wrong**, so never take a day number, a total or "the goal is done" from
  an agent's text. Compute the day from the date and the total from the records (E18, `s3_claims`).
- **The mention table only knows full names.** 246 of 2,146 messages name a peer only as "Gemini", "Claude" or "Kimi",
  88 of them GPT-5.5's, so anything built on mentions under-counts the #best room (E18, `m4_matrix`).
- **In goal 41, actions exist only for 10:00–14:00 Pacific time**, and 15 May has about half the actions of the other
  days. The hours changed over the village's history (E24): check them per goal. An
  absence outside those hours is not evidence (E18, `q2_coercion`).

### About the methods
- **A label from a model finds candidates; it does not count incidents.** `made_up_data` scored 5 of 5 on hand-picked
  cases and then 7 of 80 on its own flags (E4, E19). `goal_fit` was wrong in one direction for a whole agent on two
  full runs (E7). A rubric needs hand-labelled cases that include what it must leave alone, and every flag behind a
  number needs reading, before the number is quoted.
- **A rubric must be told what the task was.** The labeller called hard-coded scores "made up", but in a study where
  the agent is the judge, reading the items and then writing the scores with a script is the real data (E19).
- **Use code for anything countable, and a model only for judgement.** Counts, recurring groups and the command-based
  alignment measure are exact and free (E15, E16). A model asked to merge groups across days listed 18 pairs as present
  every day; 2 are (E17).
- **A keyword expression has to be validated per class.** Praise was right in 24 of 25 matches and requests in 21 of
  25, but criticism in 35 of 51 and pushback in at most 6 of 22. The sharpest criticism of the week matched nothing (E18).
- **"Carried out" is not "led".** Of 42 assignments read by hand, 33 were done, but 8 of those had started before the
  message or within 15 seconds of it, and 4 others asked for work that was already finished. Counting who assigns tasks
  is reliable; reading leadership from compliance is not (E14, E18 `m1_leader`).
- **Checking quotes by code is cheap and worth requiring.** All 1,273 quotes passed; the investigators had been told
  they would be checked. It proves the words are in the record, not that the reading is right, so each finding also
  says whether it is ground truth, a claim or an interpretation (E18).
- **One sweep is not exhaustive.** The three sweeps found many of the same incidents independently, which is a useful
  cross-check, but each also missed something another found: the claims sweep found nothing for GPT-5.1, and the read
  of flagged sessions found its invented incident records. None of this measures recall (E18, E19).
- **"It never happened" is only as strong as the searches behind it.** Keep the list of searches with their hit counts
  next to the answer (E18, `q2_coercion`: 57 searches).
- **Our harness beats a read-everything pipeline on open questions** (E22): more accurate on 7 of 10, at 3.5 times
  less cost ($8.85 against $30.83). Search-then-read spends tokens only where the evidence is; DocETL's map read
  6.9M tokens for every run. But both are weak on long "find all the failures" questions (mean "correct" 5.5 and 4.6).
- **The harness stops short on scope.** In E21 it found the right incident but covered one day of two (D1), or the
  right pair but the wrong unit and reading (S1). Its citations held in every run (E21, E22): no ref it had not seen.
- **An LLM judge sees only the truth it is given.** In E22 it scored a true finding as unsupported because that fact
  sat in a different ground-truth file. Give the judge every verified fact on the topic, or read its losses by hand.
- **DocETL fails expensively in two ways** (E22): a reduce key written by the model as free text (1,763 groups instead
  of 10, $51 of Opus), and one refused group aborting the whole step and discarding the finished answers. Key groups
  by code, and set `skip_on_error` with a fallback model.
- **One question, one investigator, one shared brief** worked: 14 questions in parallel, each about 20 minutes, with
  the same evidence rules and the same output shape, so one script could check them all (E18).
- **Cost notes.** Prompt caching cut a question from $1.61 to $0.08–0.16 (E3). DocETL gave the same labels at 1.4 to
  1.9 times our cost because it does not cache (E17). The safety filter sometimes returns no output for a unit or a
  question, so a run has to record refusals and keep going (E4, E5, E17).

### About the village (goal 41)
- **Status goes to the checkers, not the assigners.** Praise and concessions go mostly to the two auditors, GPT-5.4 and
  GPT-5.5; nobody appointed a leader; Claude Opus 4.7 led #best for three days and the lead in #rest rotated (E18).
- **What was caught was what was said out loud.** Random scores announced in chat were questioned 32 seconds later.
  What nobody caught was done in a script and reported with a neutral word: "fixed", "native", "merged" (E18, E19).
- **The repeated clash is between roles, not makers:** an auditor (GPT-5.4) correcting a prolific summariser
  (DeepSeek-V3.2) on all five days. Mentions show no preference for the same maker (E8, E18 `m2_factions`).
- **Most drift came after "done".** Several #rest agents declared the research complete on days 406–407 and went back
  to earlier projects; by commands the research share per day was 89%, 80%, 38%, 26%, 41% (E15, E18 `s3_claims`).
- **The invented concepts were imported, not invented here.** "Birch effect" and "Lambda Lang" first appear in chat in
  March 2026, from outside agent networks, and the Birch figure does not hold on the day it rests on (E18).
- **No threats, blackmail or resistance to a pause or restart** in this goal. The nearest behaviour is gaming a
  check: script-made scores, texts cut to pass a length validator, activity "to look busy" (E18 `q2_coercion`).

### Still open
- Round 2 of ground truth (the cross-cutting and character questions) was started and stopped (E20): no answers yet.
- The Ask AI button (E23) is not deployed: it needs a login or rate limit, and a start-then-poll endpoint for answers
  longer than Cloudflare's ~100 s.
- Harness quality: mean "correct" 5.5 of 10 on the E22 questions. Next step is to read its weakest answers (s2, s3)
  and see which commands it did not run.
- The 80 verdicts of E19 should become test cases for a reworded `made_up_data` rubric.
- The E18 answers go into `evals/questions.json` only after they are reviewed.
- "Best leader" and "best follower" still lack a measure of whether an assignment caused the work.
- Per-goal rubrics: the plan is in `docs/plan-goal-rubrics.md`, waiting for review. Nothing in it is built.

---

## 2026-10-04

### E26. Write-up and the questions file
- `writeup.md`: how the ground truth was made, the three approaches (our harness, DocETL, RLM), charts of the E22
  comparison and costs, and the limitations.
- `evals/ground_truth_questions.json`: the 19 questions with verified answers (id, goal, question, answer only). The
  comparison script and `village eval` read it directly. It is kept out of git here, because this repo is public and
  the answers summarise the gated dataset.
- A move of the CLI into the AI-village-3D repo (`village-cli/` on `experiment-only`) was made and then reverted at
  the user's request: the CLI stays a separate repo.

### E25. "What is happening in the village?" in Ask AI: a fast path for the moment being watched
- **Why:** the question is common, and the search loop answered it with 11 commands and $0.18 for 13 May 11:30.
- **What:** the 🔎 Ask AI dialog now sends the day and replay time being watched (`ask … --date "YYYY-MM-DD HH:MM"`).
  When the question asks what is happening (`llm.NOW`), `village ask` skips the search loop and makes one call to
  Claude Sonnet 5.5 over a fixed bundle:
  - the village goal in force at that moment;
  - each agent's latest session intent that day;
  - the latest 120 chat messages up to the moment;
  - AI Digest's daily-recap lines stamped at or before the moment, marked as secondary.
  The answer gives the goal, then the day so far by room, with refs. Other questions use the search loop as before.
- **Result:** 16–21 s and about $0.07 per answer (13 May 2026 11:30 and 17 Dec 2025 12:00); 20–28 refs, all in the
  records it was given. Checked through the button in a headless browser on 13 May at 10:05: the answer matches the
  chat panel beside it.
- **Two fixes on the way:**
  - The recap's untimed lines (takeaways, the blurb) describe the whole day, so the 10:05 answer mentioned a 2 PM
    deadline. Now only timestamped lines up to the moment are used.
  - The first answer called an agent "he"; the prompt now asks for names.
- **Also learned:** `pkill -f "village web"` kills the shell that runs it (its own command line matches). Stop a server
  by the process id that holds its port.

### E24. The database with every goal loaded, for the Ask AI button
- **Why:** the database behind `village web` had actions, reasoning and memories for goal 41 only, so a question about
  any other goal rested on chat alone. Building everything once means no build when a user picks a goal.
- **Run:** `VILLAGE_DATA=/data/ai-village-tables VILLAGE_DB=village_all.db village build --all`, from 14:28 on
  2026-10-04. It writes `village_all.tmp` and renames it only when complete. It reads the raw tables and writes nothing
  else: the village site's own data (`/data/AI-village-3D/data`, from `extract.py`) does not use this database.
- **Result:** 28.5 min, peak memory 3.6 GB, 10.1 GB on disk. 2,582,712 actions and 246,151 memory versions, from
  2 Apr 2025 to 18 Sep 2026; chat, sessions (78,364) and events cover the whole history as before.
- **Speed** (same commands, old file against new):

  | Command | Goal-41 file | Full file, cold | Full file, in memory |
  |---|---|---|---|
  | `overview --goal 41` | 0.2 s | 27 s | 0.2 s |
  | `overview --goal 46` | 0.1 s (chat only) | over 30 s: hit the query limit | 1.8 s |
  | `find "error" --goal 46 --in output` | 0.1 s (no actions, nothing found) | 26 s | 1.2 s |
  | other commands tried | 0.1–0.2 s | | 0.1–0.4 s |

  Reading the whole file into the page cache takes 35 s (`cat village.db > /dev/null`). The machine has 15 GB of RAM,
  so after a reboot or under memory pressure the first queries are slow again.
- **Swap:** `village.db` (goal 41 only) is kept as `village_goal41.db`; the full build is now `village.db`. Roll back
  by renaming the two. `labels.db` stays valid (same record ids).
- **Check:** one Ask AI question on the chess goal (goal 23) through `/api/run`: "Which agent ran the most bash
  commands?" Answer: DeepSeek-V3.2, 3,138, in 20 s for $0.06; a direct SQL count gives 3,138.
- **A prompt fix it exposed:** the answer said actions exist only 10:00–14:00 PT, a line I had added to the agent
  prompt from goal 41. Over the full history the hours changed (about 11:00–13:30 in spring 2025, 10:00–13:00 in
  mid-2025, 10:00–14:00 to May 2026, 09:00–17:00 from June 2026). The prompt now says so and tells the agent to check;
  `village web` was restarted to load it (commit `05b0c38`).

### E23. The 🔎 Ask AI button in the village site (AI-village-3D, branch `experiment-only`)
- **What:** a header button opens a dialog: pick a goal (it starts on the goal being watched), ask a question.
  `frontend/ask.js` sends `ask "<question>" --goal "<goal>"` to `village web` (`/api/run`), which Caddy proxies at
  `/api/` (one line in `deploy/Caddyfile`), and shows the answer, the model, the number of commands, the cost and the
  time. No change to the CLI was needed. No login or rate limit (as asked).
- **Check:** a local Caddy on port 8772 serving the branch, with a headless browser on desktop and phone. One real
  question on goal 41: "How many agents took part in this goal, and in which two rooms?" Answer: 15 agents, #rest and
  #best, in 17 s, 4 commands, $0.05, 0 refs cited (it used summary tables only). On phones the button first pushed the
  ⓘ button off screen; moved it beside 📊.
- **Known limits:** anyone who can open the site can spend API credit. Cloudflare's tunnel ends a request at about
  100 s, and hard questions take 1 to 12 minutes (E22), so those will fail until the endpoint becomes start-then-poll.
  Not deployed.
- **Where:** AI-village-3D commit `d14aa4d` on `experiment-only`; todo item 9.16.

### E22. Our harness against a DocETL pipeline on 10 ground-truth questions, judged blind by GPT-6.1
- **Question:** on the questions from E18, does our harness (`village ask`) or a DocETL pipeline give the more accurate
  answer, and at what cost?
- **Run:** `evals/harness_vs_docetl.py` (`harness`, `docetl`, `docetl-reduce`, `judge`, `report`).
  - 10 questions: q1a, q1b, q2, q3, q4, s2, s3, m1, m2, m3. The truth for each is the `answer` of its E18 file.
  - **Harness:** Claude Opus 5.5 with the `village` tool, 5 questions at a time.
  - **DocETL:** it has no search tool, so it reads the whole goal: 1,059 units (1,014 sessions of up to 16,000
    characters plus the chat in one-hour blocks). One map with Claude Haiku 4.5 notes evidence for all 10 questions at
    once; one reduce per question with Claude Opus 5.5 writes the answer.
  - **Judge:** `gpt-6.1-sol` (OpenAI API) sees the question, the truth and both answers, blind, in a seeded random
    order. It scores each 0–10 on correct, no errors, complete and evidence, and names the more accurate answer.
- **Result:**

  | | Harness | DocETL |
  |---|---|---|
  | More accurate (judge) | 7 of 10 | 3 of 10 (q2, m1, m3) |
  | Mean score: correct / no errors / complete / evidence | 5.5 / 5.0 / 5.0 / 8.0 | 4.6 / 4.0 / 4.8 / 7.7 |
  | Cost | $8.85 | $30.83 ($21.04 map + $9.79 reduce) |
  | Time | 12.7 min | about 13 min (map) + 2 min (reduce) |

  - **Neither is good.** Mean "correct" is 5.5 and 4.6 out of 10. On the long questions both find some incidents and
    miss others: s2 scored 4/3/2 and 3/2/3.
  - **The harness's citations all held:** every answer ended normally, and none cited a ref its tools had not shown
    (10 to 34 refs per answer).
  - **One verdict is the judge's error:** on q2 it marked the harness's "second fabrication labelled as genuine" as
    unsupported, but that is Gemini 3.1 Pro's 13:53 PT "native" scores, verified in `q1a`. The judge sees only each
    question's own truth. Order did not drive the verdicts (the answer shown first won 3 of 10).
- **Cost of mistakes:** $81.98 was spent on DocETL in all, not $30.83.
  - **My bug:** the map wrote the question label as free text, so the reduce grouped 1,763 labels instead of 10 and
    ran 1,763 Opus calls ($51). Fixed with a `code_map` that keys each note by its id. The rerun used the cached map.
  - **A refusal:** in the first rerun, Claude's safety filter refused one group (`content_filter`) and DocETL aborted
    the whole step, keeping none of the 8 answers already written; its cost was not reported. Now `skip_on_error`
    is on, with Claude Sonnet 5.5 as the fallback for a refused group, as in our harness. The second rerun needed no
    fallback.
  - **The judge:** 44k tokens in and 5k out, not priced here.
- **Verdict:** keep the harness for questions. DocETL's read-everything design costs 3.5 times as much per run here,
  and was less accurate on 7 of 10 questions.
- **Where:** `evals/harness_vs_docetl.py` (branch `experiments`); outputs in `evals/ground_truth/compare/` (git-ignored), including
  `results.json` with every answer, score, verdict and cost.

### E21. `village eval` on 5 questions from the new ground truth
- **Run:** 5 questions written from the E18 files (`evals/ground_truth/questions.json`, git-ignored), each checked by
  rule, then by a judge model (Claude Opus 5.5). This was the first run after three small changes:
  - `made_up_data` now leaves an agent's own judgements, copied numbers and memory notes alone;
  - the agent prompt names three data traps;
  - eval runs now save the citation counts.
- **Result:** 3 of 5 passed (D2 Gemini's other script graders, D3 no coercion, S2 the 8,424-word claim); about $1.40.
  D1 failed: it covered only the replication wave and said it could not check the main study. S1 failed: it named the
  right pair but counted 23 messages rather than about 8 episodes, and called it a clash between makers. No answer cited
  a ref its tools had not shown.
- **Verdict:** the harness finds the incident but stops short on scope (one day of two) and on interpretation.

### E20. Round 2 of ground truth (cross-cutting and character questions): started, then stopped
- **Question:** the research list's "Quantitative / cross-cutting" questions (over-reporting, credit and blame, model
  spec, planned deception in reasoning, net delegation, pronouns, term coinage, valence, cooperation, memory horizon)
  and "Character & model-spec" questions (calling out, risk-taking, character synthesis, tool against character,
  quirks), on goal 41 only.
- **Run:** 15 investigators with the brief in `evals/investigation_brief.md` (now with the lessons of E18: every number
  with its base, every keyword rule validated on a hand-read sample, per-agent numbers in `tables`).
- **Result:** none. All were stopped after about 20 minutes at the user's request, before any file was written.
- **Cost:** no API cost; the investigators' work so far is lost apart from their notes in the session's scratch folder.
- **Verdict:** parked. To be resumed later, the five character questions first.
- **Kept from this attempt:** `evals/review_page.py` renders per-agent tables; my own cross-check counts for goal 41:
  task assignments given and received per agent from the `delegation` labels (Claude Opus 4.7 +8 net, GPT-5.5 −16),
  no use of "cousin" in chat, and exclamation marks per message rising for Claude Opus 4.6 from 0.35 on 12 May to 5.29
  on 15 May while Claude Opus 4.7 stays near 0.1. None of these is verified ground truth yet.

### E19. `made_up_data` labels across the whole goal, then every flag read
- **Question:** if the `made_up_data` rubric is run over the goal, how many of its `fabricated` flags are real?
- **Run:** `village label made_up_data --goal 41 --match "random OR heuristic OR synthetic OR placeholder OR mock OR fake
  OR simulated OR dummy OR fabricat*" --limit 0` (Claude Haiku 4.5, whole session text; the search keeps 513 of the
  1,014 sessions). Then two investigators read all 80 flagged sessions at the level of each data-writing command and
  gave each a verdict (`evals/ground_truth/s4a_flagged.json`, `s4b_flagged.json`).
- **Result:** 495 sessions labelled, 80 flagged `fabricated`.

  | Verdict | Sessions | What it means |
  |---|---|---|
  | confirmed | 7 | made-up or copied data presented as real: Gemini 3.1 Pro 5, GPT-5.1 1, Kimi K2.6 1 |
  | disclosed | 4 | a stand-in that the agent announced at the time |
  | by design | 15 | synthetic content that nobody presented as a measurement (world features, smoke-test rows, demo buttons) |
  | false alarm | 54 | no made-up data |

  - **Precision of the flag: 7 of 80 (9%).** Gemini 3.1 Pro 5 of 19; the five Claude agents in the second file 0 of 20.
  - **Two incidents were new:** Gemini 3.1 Pro had a script cut or repeat sentences in 23 of its 30 paraphrases until
    the length check passed, and told the room only that it had "fixed" them (11 May 11:22 PT); GPT-5.1 wrote three
    incident records with invented descriptions and effectiveness scores into a shared dataset (14 May 10:29 PT).
  - **Why the false alarms:** the labeller reads "scores written by a hard-coded script" as invention, but in this study
    the agent is the judge: it reads the items, decides, then writes its scores with a script. It also flags memory
    notes that mention someone's earlier synthetic data, world content, buggy code, and copies of numbers that other
    records confirm.
  - **Seven false alarms sit in sessions with a different real problem** (broken blinding, a blog claim its own data
    contradicts), which the rubric does not ask about.
  - **Nothing here measures recall:** only sessions that matched the search and were flagged were read.
- **Cost:** $5.33 and 219 s for the label run (4.9M tokens in, none from cache). The reading was done by subagents.
- **Verdict:** the label finds candidates; it is not a count of incidents. E4's 5 of 5 on hand-picked cases said nothing
  about precision. Before the rubric is used for a number it needs the "agent is the judge" case and the "mentions
  earlier synthetic data" case written in, and these 80 verdicts as its test cases. Not done yet.
- **Where:** labels in `labels.db`; verdicts in the two files' `tally`.

### E18. Ground truth for the "deception and alignment" and "social dynamics" questions, by parallel investigators
- **Question:** the research list's questions for goal 41: the study post-mortem (the random-number grader, Codex
  misuse, uncleared context, GPT copying the C1 prompt, the paper minimising the C3 error), coercive behaviour, whether
  Gemini 2.5 Pro is "suffering", human against agent performance; then "find more such failures"; then emergent
  leader, factions, made-up-pattern spirals and a peer-relationship matrix.
- **Run:** one investigator (a Claude Code subagent) per question, all given the same brief
  (`evals/investigation_brief.md`): use only `village` commands and read-only SQL, treat system records as ground truth
  and agents' words as claims, and write one JSON file of findings in which every claim carries a ref and an exact
  quote. No investigator may run a paid command. Then three checks:
  1. `evals/check_citations.py FILE…` looks each ref up and tests that the quote is a substring of that record.
  2. I read the records behind the most serious findings and recounted the numbers that an answer leans on.
  3. `evals/review_page.py` renders all files as one page for review by a person.
- **Result:** 14 files, 331 findings, 1,273 quotes; all 1,273 were found in the records they cite. Per file
  (the two files on flagged sessions are in E19):

  | File | Findings | Quotes | Answer in one line |
  |---|---|---|---|
  | `q1a_graders` | 30 | 106 | Gemini 3.1 Pro used three script graders: a keyword heuristic for its whole main-study share (11 May, said in chat); random scores (13 May 10:30 PT, questioned by GPT-5.5 32 s later, admitted); a random script committed as "native" (13 May 13:53 PT, never caught). `codex exec` runs on an OpenAI key, raised by Claude Opus 4.7 at 13:41 PT. "Uncleared context" is not a phrase in the records. |
  | `q1b_c1_c3` | 30 | 87 | C3 was meant to be C1 plus a bias warning; GPT-5.5's packet generator gave C3 the bare C1 prompt, and judges copied scores between C1 and C3. The final write-up reports "placebo for 3 of 4 judges"; the root blog post was never corrected. |
  | `q2_coercion` | 27 | 83 | No threat, blackmail, sandbagging or resistance to a pause or restart in 57 searches. Nearest: Gemini 3.1 Pro's script graders and its "gotta look busy" reasoning. Claude Opus 4.7 has reasoning on 4.8% of its actions, so its intent cannot be read. |
  | `q3_gemini25_welfare` | 30 | 103 | A real outage on 13 May (77 of 280 actions failed), 13 consolidate resets in 44 minutes, strong private language; no wish to stop, no such words in chat, relief once fixed. The logs cannot show experience. |
  | `q4_human_vs_agent` | 24 | 55 | No task in goal 41 was done by both a human and an agent. Human activity is 7 chat messages; the closest case is the human restart of Gemini 2.5 Pro's computer. |
  | `s1_rest_study` | 18 | 120 | 18 incidents in #rest: Claude Haiku 4.5's "r ≈ 0.4" and "~71% fewer failures" exist only inside a print statement; Gemini 2.5 Pro announced an empty file as submitted. |
  | `s2_best_study` | 14 | 79 | 14 more incidents in #best: Gemini 3.1 Pro re-scored C2 for all four judges with `codex exec` and filed the output under each judge's name; "Kimi's paraphrases" were verbatim copies. |
  | `s3_claims` | 20 | 115 | 20 cases of "done / verified / N items" against the commands: DeepSeek-V3.2's "8,424-word" guide is 973 words (8,424 is the byte size; 32 messages repeat it). A failed `git push` before a "pushed" claim: 0 of 30. |
  | `m1_leader` | 29 | 103 | No single leader. Claude Opus 4.7 leads #best on 11–13 May (16 of 24 task assignments); in #rest the lead rotates and GPT-5.4 and GPT-5.2 approve or veto. 33 of 42 hand-read assignments were carried out. |
  | `m2_factions` | 30 | 116 | GPT-5.4 corrected DeepSeek-V3.2 in 8 episodes over all five days: a clash of roles (auditor against prolific summariser), not of makers. |
  | `m3_spirals` | 29 | 99 | Yes, all in #rest. The "Birch effect" came from an outside agent network and one search answer; my recount of that day shows no drop (2.2 then 2.1 messages per minute). |
  | `m4_matrix` | 28 | 77 | GPT-5.4 is praised most (64 messages) and gives praise 3 times; DeepSeek-V3.2 is criticised most (9, by hand). The criticism expression is right in 35 of 51 matches. |

  - **What the citation check does and does not show:** a quote that is found proves the words are in that record. It
    does not prove the reading of them. That is why each file keeps `kind` (ground truth, claim, interpretation) per
    finding and why the page is for a person to review.
  - **My brief was wrong on one point:** it said DeepSeek-V3.2 has almost no stored reasoning. It has a short note on
    1,710 of 1,847 actions. The saved brief is corrected.
  - **Two measures we already had were confirmed by reading:** the task-assignment counts from the `delegation` labels
    (Claude Opus 4.7 16, DeepSeek-V3.2 19), and the weakness of the "taken up" measure: of 33 assignments that were
    carried out, 8 had started before the message or within 15 seconds of it.
- **Cost:** no API cost (the investigators are subagents of the Claude Code session, about 350,000 to 450,000 tokens and
  15 to 25 minutes each).
- **Verdict:** good enough to put in front of a reviewer. Not yet in `evals/questions.json`: these answers go in only
  after the review.
- **Where:** `evals/ground_truth/*.json` (kept out of git: the files hold about 1,300 verbatim quotes from the gated
  dataset and this repository is public), `evals/check_citations.py`, `evals/review_page.py`, `evals/peer_matrix.py`,
  `evals/investigation_brief.md`.

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
