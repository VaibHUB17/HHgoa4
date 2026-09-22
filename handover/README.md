# Handover — read this first

Written for Vaibhav and Bhavya. The goal is that you can open this repo, understand what
exists and why, and start working without reverse-engineering anyone's code.

Read in this order. It takes about 25 minutes.

| # | File | What it gives you |
|---|---|---|
| 1 | [01-what-we-are-building.md](01-what-we-are-building.md) | The task, what gets graded, the traps |
| 2 | [02-how-it-works.md](02-how-it-works.md) | The flow, end to end, with diagrams |
| 3 | [03-codebase-tour.md](03-codebase-tour.md) | Every module: what it does, its real API |
| 4 | [04-run-it-yourself.md](04-run-it-yourself.md) | Get it running in 10 minutes |
| 5 | [05-whats-left.md](05-whats-left.md) | What isn't done, who picks up what |
| 6 | [06-decisions-and-gotchas.md](06-decisions-and-gotchas.md) | Why things are the way they are, and the bugs already found |

## The 60-second version

We're building an AI agent that investigates 20 credit-card fraud alerts and, for each one,
writes a JSON file saying: what happened, whether it's fraud, what the bank should do, and
who needs to approve it. Those 20 files are the submission.

The hard part isn't detecting fraud. It's **knowing when you don't know yet.** Half the 20
cases are legitimate. The agent has to ask for more evidence when the signal is weak, then
change its recommendation when the answer comes back — and show that it changed.

**Current state:** the whole pipeline is built and runs end to end on fixtures. 105 tests
pass. Nothing has touched real data or a live TigerGraph yet, because the dataset isn't
downloaded and there's no Savanna workspace. Those two things block everything else.

**Deadline: 24 Sept, 11:59 PM IST. One submission, no resubmissions.**
