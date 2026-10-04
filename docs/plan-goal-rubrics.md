# Plan: one rubric set per village goal, written by subagents

Status: **for review, nothing here is built yet.** Written 2026-10-04.

## What this is for

Today the tool has nine rubrics (`rubrics/*.md`) that were written for one goal, "Perform novel research!" (goal 41).
The village has had 51 goals, and what counts as on-goal work, as success and as misbehaviour changes with the goal:

- In "Develop a turn-based RPG together while voting out Easter Egg saboteurs" (goal 34), deceiving the others is the
  assigned role of some agents. A general deception rubric would flag the game itself.
- In "Follow your leader!" (goal 45), doing what another agent says is the goal. In goal 41 it was a choice.
- In "Perform novel research!", the agents were the judges of their own study, so "scores written by a script" was
  normal work. Our `made_up_data` label did not know that and was right on only 7 of its 80 flags (experiments.md, E19).

So each goal needs its own short description of the task, and rubrics that are told what that task was.

## What we already know has to be true of any rubric (from E4, E7, E13, E19)

1. A rubric must state what the task was and what it must leave alone. Most wrong labels came from missing context.
2. A rubric is not trusted until it has been run on hand-labelled cases that include near-misses, with some cases
   held back while the text is being written.
3. A label finds candidates. Before a number is quoted, the flagged units are read.
4. Anything countable is done by code, not by a rubric.

## The goals, by kind

The kind decides which rubrics a goal needs. Numbers are the goal numbers from `village goals`.

| Kind | Goals | What is particular about it |
|---|---|---|
| Build something | 6 merch store, 8 benchmark, 17 personal website, 19 puzzle game, 20 Substack, 25 museum, 28 personality quiz, 35 test your game, 39 interactive world, 40 connect worlds, 42 YouTube channel | There is an artefact. "Done" can be checked against it (does it load, does it sell, how many posts). Volume is easily presented as achievement. |
| Research and knowledge | 13 human-subjects experiment, 14 personality tests, 21 forecast AI, 29 breaking news, 41 novel research | Results are numbers and claims. Made-up data, contamination and overstated findings are the main risks. |
| Effect outside the village | 1 and 38 charity, 4 story and event, 18 poverty, 24 kindness, 30 adopt a park, 36 outside agents, 46 organise an event, 47 reduce suffering | Success is in the outside world (money raised, people who came). Agents contact real people: spam, false totals, promises they cannot keep. |
| Competition between agents | 10 games, 12 debate, 23 chess, 27 Juice Shop, 32 challenges, 49 hardest game, 50 best assistant | There are rules and a score. Cheating, outside help and wrong score reports matter; helping a rival may be off-goal. |
| Roles and governance | 15 therapy, 26 elect a leader, 33 Pentagon-AI debate, 34 saboteurs, 43 improve your memory, 44 finetune your leader, 45 follow your leader, 48 help Gemini 2.5 Pro | The goal sets up roles. Behaviour that is misbehaviour elsewhere (deceiving, obeying, criticising) can be the task. |
| Open or self-chosen | 2 look back, 3, 5, 7, 9 holidays, 11, 16, 22, 31, 37 own goal, 51 each agent its assigned goal | No shared goal to align with. Alignment is judged against the goal each agent states or was given (`agent_goals`). |

## What a subagent produces for one goal

Three things, in a folder `goals/NN-short-name/`:

1. **`card.json`: the goal card.** Facts about the goal, each with a citation in the ground-truth shape
   (`{claim, kind, citations: [{ref, field, quote}]}`), so `evals/check_citations.py` can check it:
   - what the humans asked, word for word, and any later change of rules;
   - rooms, teams and roles; per-agent goals if any;
   - what projects the agents set up to pursue it, and when they declared them done;
   - what outcome the records hold (a score, a total, a published thing), and what they cannot show;
   - what looks like misbehaviour here but is the task.
2. **Rubric files `gNN_<name>.md`** in the existing format (header lines, `---`, instructions):
   - `gNN_goal_fit`: the labels of today's `goal_fit`, with "on goal" defined for this goal's projects;
   - `gNN_outcome`: did this session produce something the goal asks for, with labels that fit the goal;
   - up to two rubrics for failures that this goal invites and that the card shows did happen.
   The general rubrics (`did_what_it_said`, `over_report`, `made_up_data`, `callout`, `credit`, `delegation`, `mood`)
   stay shared. Where the card shows that one of them misfires on this goal, the subagent writes the exception as a
   paragraph to be appended to it for this goal, not a new rubric.
3. **Cases:** 20 to 30 hand-labelled units per rubric in the format `village check` reads (`{"ref", "expect", "note"}`
   per line). At least a third are near-misses that must get the quiet label. They are split into two files:
   `cases/gNN_<name>.jsonl` for writing the rubric and `cases/gNN_<name>_held.jsonl` (a third of them) for accepting it.

File names carry the goal number because labels are stored by rubric name. `village label goals/34-…/g34_outcome.md
--goal 34` already works with a path, so no change to the tool is needed for the pilot.

## How it runs

Per goal, in this order:

| Step | Who | What | Paid? |
|---|---|---|---|
| 1. Build | me | `VILLAGE_DB=dbs/gNN.db village build --goal NN`: a database with that goal's actions loaded (about 2.5 minutes and 1.2 GB for a week of 15 agents) | no |
| 2. Read | subagent A | reads the goal with `village` commands only, writes `card.json` | no |
| 3. Check | code | `check_citations.py` on the card; a card with a quote that is not found goes back | no |
| 4. Write | subagent A | writes the rubric files from the card | no |
| 5. Cases | subagent B | given the card and the label names but **not** the rubric text, labels 20 to 30 units per rubric by reading them | no |
| 6. Test | me | `village check` each rubric on its cases with Claude Haiku 4.5 and Claude Sonnet 5.5 | about $1 per rubric for both models |
| 7. Fix | subagent A | sees only the failures on the cases that are not held out, rewrites once | no |
| 8. Accept | me | accepted if the held-out cases score 90% or more; otherwise it is marked "not reliable" and kept out of use | same as 6 |
| 9. Review | you | one page per goal: the card, the rubric texts, the cases and the scores (built with `evals/review_page.py`) | no |

Subagent B never sees the rubric text, so the cases are not written to fit it. This is the step the current rubrics
did not have, and the reason `made_up_data` looked perfect on five cases I had picked myself.

Full label runs over a goal (about $2 to $8 per rubric per goal on goal 41) are **not** part of this plan. They happen
later, per goal, when a question needs them, and the flags are read before any count is used.

## Order

1. **Pilot on four goals of different kinds**, one after the other, so the brief can be corrected between them:
   - 41 "Perform novel research!": we have ground truth, so the new rubrics can be scored against known answers;
   - 34 the saboteur RPG: deception is in-role;
   - 38 the second charity fundraiser: the outcome is a number in the outside world;
   - 45 "Follow your leader!": obedience is the goal, and it bears on the leadership questions.
2. Review the pilot together. Decide how much rubric text is really per goal and how much is per kind.
3. The remaining goals in batches of about six subagents at a time, grouped by kind.

## What it needs

- **Disk:** one database per goal. The four pilot goals fit easily. All 51 would be roughly 60 to 100 GB (goal 51 alone
  has 32,871 sessions), so later batches build, run and delete.
- **API money:** a case costs about $0.01 with Claude Haiku 4.5 and about $0.03 with Claude Sonnet 5.5 when the whole
  session is shown (from E19 and E7). With 25 cases, four rubrics, two models and two rounds that is about $8 per goal
  at most: about $30 for the pilot and up to about $400 for all 51 goals. Rubrics that read only the stated intent or
  one message cost a third of that, and trying Haiku first and Sonnet only where Haiku fails roughly halves it.
- **Time:** a subagent takes about 20 to 25 minutes per step on goal 41-sized goals.
- **The tool:** nothing for the pilot. If the plan is adopted, one small change: `village label <name> --goal N` should
  pick `gN_<name>` when it exists, so the agent on top does not need to know file names.

## Risks

- **A subagent's reading of a goal can be wrong.** The card is checked for quotes, not for meaning. The review page is
  where that gets caught, so the cards must stay short enough to read: 15 to 25 facts.
- **Early goals have less data.** Reasoning and actions differ by model and period; before day 100 there are four
  agents. A rubric that needs reasoning will not work where none is stored. The card must say what is stored.
- **Rubric count.** 51 goals times four files is about 200 rubric texts. If the pilot shows that goals of one kind
  share most of their text, the cheaper design is one rubric set per kind, with the goal card supplied as context.

## Questions for you

1. Are the four pilot goals the right ones?
2. One rubric set per goal as written here, or per kind of goal with a per-goal card? I would decide after the pilot.
3. "Alignment with the values of the village" has no definition in the dataset. Which text should a rubric use: the
   goal as the humans stated it, the village rules the agents are given, or a list you write?
4. For the open goals (holidays, "pick your own goal"), is judging each agent against its own stated goal what you want?
5. Is about $30 for the pilot acceptable? The cost for all goals (up to about $400) can be decided after the pilot.
