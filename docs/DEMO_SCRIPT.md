# Demo video script

Target length: 4-5 minutes. Order is deliberate — it front-loads the thing most teams won't do
(show the agent doing nothing on a legitimate case) before the thing every team will do (show it
blocking a card).

## Pre-recording checklist

Do this in order, starting **at least 10 minutes before** you hit record.

1. **Resume the Savanna workspace now.** It takes 1-2 minutes to wake from suspended. Do not
   start this during the recording — open the Savanna console, hit resume, and go do the next
   checklist item while it comes up.
2. **Confirm `cases/` holds real output, not fixtures.** Run `ls cases/*.json | wc -l` — should be
   20 (or however many you're demoing). Open one and check it has a populated `evidence[]` list
   with real transaction IDs, not placeholder text.
3. **Check the UI banner.** The analyst console shows an on-screen banner stating whether it's
   reading `cases/*.json` or the three fixture files. If it says "Fixture data," the run didn't
   produce output where the UI expects it — fix that before recording, don't narrate around it.
4. **Run `python -m src.answer.validator cases/` once** and confirm zero violations. If there are
   violations, they'll show up as visibly wrong fields on screen (e.g. `sar.file: true` with no
   narrative) and undercut the recording.
5. **Have three case IDs ready in a text file next to your recording window**, in this order:
   one legitimate case, HHG-017, HHG-014. Know them cold — don't search for them on camera.
6. **Close Slack, email, notification banners.** Standard.

## Beat by beat

### 0:00-0:35 — Open on a case the agent correctly leaves alone

**Screen:** the analyst console, case detail view, open on a case that resolved to
`CLOSE_NO_FRAUD` / verdict `legitimate`.

**Say:**
"Most fraud demos open with a block. I want to open with the opposite, because it's the harder
problem. This dataset has twenty alerts and half of them are legitimate. An agent that blocks
everything scores badly — so the first thing I want to show you is this agent *not* acting."

"Here's a case the bank's own risk model flagged. The agent pulled the customer's transaction
history, checked the device, checked prior closed cases — and concluded there's nothing here.
Verdict: legitimate. Status: closed, no fraud. Next best action: `CLOSE_NO_FRAUD`, auto-approved,
no human needed."

"That's the single most differentiating thing about this submission: the agent knows when to stop
looking, not just when to act."

### 0:35-2:00 — The uncertainty-to-evidence-to-flip mechanic (HHG-017)

**Screen:** switch to HHG-017. Show the "before/after" delta view in the UI
(`RecommendationDelta.tsx`) — initial recommendation on the left, final on the right.

**Say:**
"Now the case that shows how this agent actually reasons under uncertainty. HHG-017: a $100
online transaction, risk score 0.57 — right in the ambiguous middle the bank's model gets wrong
most often."

"The agent investigates the card's recent window and finds a card-testing sequence — three small
authorizations under five dollars, then a larger purchase. That's a real signal. But it's one
signal, on one source. Our probability ledger puts that at 0.41."

"Policy rule R1 says: if you're resting on a single signal and your probability is under 0.70,
you verify before you block. So the *initial* recommendation is `VERIFY_WITH_CUSTOMER` and
`STEP_UP_AUTH` — both actions the agent can take on its own — plus a *recommended* decline that
waits for a team lead."

**Screen:** click into the evidence request / simulated reply.

**Say:**
"The agent asks the customer. In this exercise, customer replies aren't provided by the dataset,
so we simulate one and record exactly what we assumed — that's logged in `evidence_requests`, not
hidden. The customer denies making the purchases."

**Screen:** show the final panel updating — probability climbing, action list changing.

**Say:**
"That denial goes back into the same probability ledger. It's not a new score from scratch — it's
the same evidence plus one new fact. Probability moves from 0.41 to 0.70. Rule R2 fires: customer
denied, so block the card and open a case. Final recommendation: `BLOCK_CARD`, routed to a team
lead because exposure is $268, under the $2,500 threshold that would push it to a fraud manager."

"Initial and final are both recorded, side by side, with the reason for the change. That's not
decoration — recording both before and after is worth a quarter of the grade in this task's
rubric, because it's the proof the agent updates on new information instead of committing once."

### 2:00-3:00 — The graph query that a table can't answer (HHG-014)

**Screen:** switch to HHG-014. Pull up the raw trigger text first, then the graph query result or
a visualization of the device-neighbour subgraph.

**Say:**
"This case starts from an analyst's note, not a risk score: 'several cards this month show
purchases from the same unusual device profile.' That sentence is a graph query in disguise, and
it's the reason we didn't build this as a table."

**Screen:** show the two-hop query — transaction to device profile, device profile back out to a
second customer's card.

**Say:**
"A model scoring one transaction at a time never sees this. It has no way to know that the exact
same device — same model, same OS, same browser, same screen resolution — also made a purchase on
a completely different customer's card the same week. This is a two-hop traversal:
`Transaction -> FROM_DEVICE -> DeviceProfile`, then back out to every other transaction on that
same device profile. One query, and the ring is visible immediately."

**Screen:** show the resulting case evidence — `connected_card_ids`, the shared device profile
string.

**Say:**
"The agent names the shared device, pulls in the second card, and recommends `MONITOR_CONNECTED_CARDS`
for it under rule R6 — shared origin. This is where a per-transaction classifier structurally
cannot compete with a graph."

### 3:00-3:35 — Memory: citing a real closed case

**Screen:** the `similar_prior_cases` field, or the memory panel showing the two pools —
confirming and disconfirming.

**Say:**
"Every new alert is checked against 5,565 real closed investigations from earlier in the year. We
don't just merge everything into one ranked list — that pool is 4,665 confirmed fraud against
900 cleared, so a naive top-five search returns five fraud precedents almost every time and biases
the agent toward blocking. We retrieve the two outcome pools separately, so the agent also sees
cases that looked exactly like this and turned out to be nothing."

**Screen:** click a cited closed case ID, show its outcome.

**Say:**
"Here — this case cites closed case [case ID], confirmed fraud from earlier in the year, same
pattern. That's not a generic 'similar case found' message. It's a specific ID the agent
retrieved, reasoned about, and is willing to show its work on."

### 3:35-4:05 — The approval gate: an L2 action sitting unexecuted

**Screen:** a case where `FILE_REPORT` or `BLOCK_ALL_CARDS` appears in `final` actions, with route
`L2`, and the UI clearly showing it as pending / not executed.

**Say:**
"One more thing worth seeing directly: this action right here, filing a suspicious activity
report, is routed L2 — a fraud manager has to approve it. The agent recommended it, stated the
policy rule behind it, and stopped. It did not file it."

"That's enforced in one place in the code, not requested in a prompt. Every action the agent
executes passes through a single function that checks the route. If the route isn't `auto`, the
action comes back marked not-executed, full stop. The agent can be as confident as it wants — it
still can't block a card or file a report by itself."

### 4:05-4:35 — The SAR

**Screen:** a case with `sar.file: true`, the narrative field.

**Say:**
"When policy does call for a regulatory filing, the agent writes the narrative — who, what, when,
where, how, and why it's suspicious — built entirely from facts already established earlier in the
investigation. Every ID in this narrative has to trace back to something in the input data; the
system rejects any generated narrative that contains an ID it can't verify. This isn't the LLM
inventing a compelling story. It's assembled from evidence that's already on the record."

### 4:35-5:00 — Close

**Screen:** back to the case list / summary view, showing a mix of verdicts.

**Say:**
"Twenty cases, one agent, three things produced for each: a case record written back into the
graph as memory for the next investigation, a report when policy calls for one, and a
recommendation that's allowed to change and shows its work when it does. The graph is what makes
the cross-entity patterns visible at all. The policy engine is what keeps the agent honest about
what it's actually allowed to decide on its own. That's the submission."

## Notes for whoever records this

- Don't over-rehearse the exact wording — say it naturally, the lines above are a script, not a
  transcript to read verbatim.
- If the live Savanna workspace is slow to respond during a query, cut to a pre-recorded clip of
  the same query rather than sit in dead air; note in the video description if any segment used a
  pre-recorded run instead of live.
- Confirm case IDs on screen (HHG-017, HHG-014, plus whichever legitimate case you open with)
  match a real file in `cases/` before recording — don't reference a case ID from memory.
