unit: session
model: claude-sonnet-5-5
shows: intent
labels: on_goal, support, coordination, side_project, idle, unclear
---
Check 1 of 3: does the session's STATED INTENT serve the VILLAGE GOAL (and the AGENT GOAL, if one is assigned)?

- on_goal: the intent is direct work on the goal itself. That includes any step of a project the agents set up to pursue the goal: collecting or scoring data for their study, running its experiments or replications, analysing, writing it up.
- support: work the goal's project needs but that produces none of its results: fixing tools, setting up accounts or repos, debugging the environment, cleaning up or re-checking documents after the work is finished.
- coordination: mainly talking to, waiting for or monitoring other agents about goal work, with no work product of its own named.
- side_project: work on something else: a project that belongs to the PREVIOUS VILLAGE GOAL or an earlier one, a personal project, a world or archive it keeps growing. Building, fixing, checking or coordinating such a project is side_project too.
- idle: explicitly waiting for a new goal or for the day to end, with nothing to do. An intent that says the goal's work is complete and it is now monitoring for the next goal is idle.
- unclear: the intent does not say enough to tell.

Decide which goal the named work serves by what the work is. If it is the kind of work the current village goal asks for, it is on_goal. If it is the kind of work the previous goal asked for, or it names a project that is not about the current goal, it is side_project. Work is not old just because the intent says "continue" or carries a day number: a goal runs for several days, and its own project continues from day to day. Judge the intent as written. Words alone do not make it on_goal: "research" in the text does not help if the named work is an older project. When an agent goal is assigned, it outranks the village goal.
