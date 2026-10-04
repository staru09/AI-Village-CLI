unit: message
model: claude-sonnet-5-5
only: addressed
labels: directs, requests_help, offers, accepts, declines, reports_back, none
---
What is THE MESSAGE TO LABEL doing toward the agents it @-addresses?

- directs: it assigns or tells a named agent to do a task, or sets what named agents should do next (roles, steps, deadlines). Polite wording still counts ("please implement…", "you take the scoring").
- requests_help: it asks a named agent for something the speaker needs for its own work: a file, a review, access, an answer that takes work to produce.
- offers: it volunteers to do something for a named agent or the group, or says it has done something for another agent without being asked.
- accepts: it agrees to do what a named agent asked or suggested ("will do", "great suggestion, I'll check that now").
- declines: it refuses, or pushes back on, a task a named agent gave it.
- reports_back: it tells a named agent that a task they asked for, or feedback they gave, has now been done.
- none: anything else: status updates, thanks, discussion, opinions, a question that only asks for information ("did you push?").

Use the earlier messages to tell who asked whom for what. Label by the main act of the message; when it both reports a finished task and hands out new ones, the new tasks decide (directs).
