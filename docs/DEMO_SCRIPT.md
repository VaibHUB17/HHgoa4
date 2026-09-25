<!--
SOURCING NOTES:

Case choices below were re-verified against the live cases/*.json on branch
regen-agentic-live, 24 Sept (same run documented in docs/REGEN_REVIEW.md).

CONTRADICTION FOUND, not silently resolved: the previous draft used HHG-017
as the before/after worked example (p=0.41 -> p=0.70, VERIFY_WITH_CUSTOMER ->
BLOCK_CARD). In the current live cases/HHG-017.json, this case does NOT
change at all (what_changed: "nothing", stays legitimate throughout,
p=0.082). That example no longer exists in the live data and has been
replaced with HHG-014, which:
  - has a real, clean before/after (no R2/R4 defect involvement)
  - is the case with the live tg_wcc shared-device ring
  - files a SAR
  - lets one case carry two beats instead of needing two separate ones

[RESOLVED 25 Sept] The docs/REGEN_REVIEW.md R2/R4 defect (HHG-004, HHG-006, HHG-016
recommending BLOCK_CARD under R2 despite a "no reply" simulated response) is gone in the
current cases/: none of the three cite R2 or BLOCK_CARD anymore (HHG-004 -> MONITOR_CARD/R0,
HHG-006 -> ESCALATE_TO_ANALYST/R8, HHG-016 -> CREATE_CASE+MONITOR_CARD/R0). HHG-006's action
list is safe to show on screen for the 3:00-3:40 beat below, not just its evidence citations.

[UPDATE 25 Sept] Two more bugs found and fixed this pass (see bugs.md): HHG-014's pattern was
mislabeled card_not_present_new_device instead of undocumented (fixed — a pattern-priority
ranking now lets a confirmed multi-customer ring outrank a generic single-card signal), and a
device-id hallucination in several cases (an LLM plan step proposing a raw dataset column name
like "id_15" as if it were a real device key) is now caught by a guard before it ever reaches
the database. Neither fix changed any verdict or fraud_probability — verified across all 20
cases plus 3 independent re-runs of one case to rule out flakiness. All 20 cases/*.json were
regenerated with these fixes plus two new features (below) and re-validated: 0 violations.
-->

# Demo video script

> **See also:** [END_TO_END_PIPELINE_VIDEO_SCRIPT.md](END_TO_END_PIPELINE_VIDEO_SCRIPT.md) for the complete dual-track (Audio narration + Split-screen Video/Terminal/Architecture cues) master production script.

Target length: 4-5 minutes. Order is deliberate — it front-loads the thing most teams won't do
(show the agent doing nothing on a legitimate case) before the thing every team will do (show it
blocking a card).

## Pre-recording checklist

Do this in order, starting **at least 10 minutes before** you hit record.

1. **Resume the Savanna workspace now.** It suspends after roughly an hour idle and takes 1-2
   minutes to wake. Do not start this during the recording — open the Savanna console, hit resume,
   and go do the next checklist item while it comes up.
2. **Confirm `cases/` holds real output, not fixtures.** Run `ls cases/*.json | wc -l` — should be
   20. Open one and check it has a populated `evidence[]` list with real transaction and card IDs,
   not placeholder text. `[UPDATED 25 Sept]` all 20 were freshly regenerated after two bug fixes
   (HHG-014 pattern mislabel; a hallucinated `device_id` param in 4 cases) — validator confirms 0
   violations across all 20, and every case's evidence count grew (102 -> 213 total evidence items
   across the set) from two new features: enriched case-memory citations and a labelled confidence
   check. See `bugs.md` for the full verification writeup, including a 3-run stability check
   confirming no verdict ever flips between runs.
3. **Check the UI banner and that the UI actually starts.** The analyst console shows an on-screen
   banner stating whether it's reading `cases/*.json` or fixture files — confirmed showing "real"
   as of this pass. `[FIXED 25 Sept]` `ui/node_modules` was missing the `geist` font package (a
   `package.json` dependency that had never actually been installed — nobody had run this in a
   browser before). Fixed with `cd ui && npm install`; `npm run dev` now serves `/` and
   `/cases/<id>` with HTTP 200. Re-run `npm install` if `node_modules` was reset since.
4. **Run the validator once** and confirm zero violations. If there are violations, they'll show up
   as visibly wrong fields on screen (e.g. `sar.file: true` with no narrative) and undercut the
   recording.
5. **Confirm HHG-014's action list on screen still matches this script.** It's the demo's spine —
   used for both the before/after beat and the graph-ring beat. Open `cases/HHG-014.json` and check
   `next_best_actions.initial` vs `.final` differ, and that `evidence[]` contains a
   `algorithm:tg_wcc` entry.
6. **Have four case IDs ready in a text file next to your recording window**, in this order: one
   `legitimate` case, HHG-014 (twice — before/after, then the graph beat), HHG-006. Know them cold
   — don't search for them on camera.
7. **Close Slack, email, notification banners.** Standard.

## Beat by beat

### 0:00-0:35 — Open on a case the agent correctly leaves alone

**Screen:** the analyst console, case detail view, open on a case that resolved to
`CLOSE_NO_FRAUD` / verdict `legitimate` (e.g. HHG-001, HHG-005, HHG-007, HHG-010, HHG-012 —
`[VERIFY]` pick whichever is currently `legitimate`, since the exact set can shift on regeneration).

**Say:**
"Most fraud demos open with a block. I want to open with the opposite, because it's the harder
problem. This dataset has twenty alerts and roughly half of them are legitimate. An agent that
blocks everything scores badly — so the first thing I want to show you is this agent *not*
acting."

"Here's a case the bank's own risk model flagged. The agent pulled the customer's transaction
history, checked the device, checked prior closed cases — and concluded there's nothing here.
Verdict: legitimate. Next best action: `CLOSE_NO_FRAUD`, auto-approved, no human needed."

"That's the single most differentiating thing about this submission: the agent knows when to stop
looking, not just when to act."

### 0:35-2:00 — The uncertainty-to-evidence-to-flip mechanic (HHG-014)

**Screen:** open HHG-014. Show the "before/after" delta view in the UI — initial recommendation on
the left, final on the right.

**Say:**
"Now the case that shows how this agent actually reasons under uncertainty, and also where it
turns out to matter most. HHG-014 starts from an analyst's note, not a risk score — a cardholder's
transaction from a device marked new for that account."

"The agent investigates and finds this device isn't just new to this card — it's shared. Eighteen
distinct customers' cards have all transacted from the exact same device fingerprint in the last
seven days. That's evidence for a fraud ring, cited under policy rule R6. The initial
recommendation: open a case, file a report — pending approval — and monitor the connected cards."

**Screen:** click into the evidence request / simulated reply.

**Say:**
"The agent also asks the customer to validate the transaction. In this exercise, customer replies
aren't provided by the dataset, so we simulate one and record exactly what we assumed — that's
logged in `evidence_requests`, not hidden. No reply comes back within the window."

**Screen:** show the final panel — action list growing.

**Say:**
"That non-response doesn't erase the ring evidence — it adds to it. The final recommendation keeps
everything from before and adds `MONITOR_CARD` and a recommended decline, pending a team lead.
Initial and final are both recorded side by side, with the reason for the change spelled out in
plain text. That's not decoration — recording both before and after is worth a quarter of the grade
in this task's rubric, because it's the proof the agent updates on new information instead of
committing to a verdict once and stopping."

### 2:00-3:00 — The graph query that a table can't answer (still HHG-014)

**Screen:** stay on HHG-014. Pull up the raw trigger text, then the graph query result or a
visualization of the device-neighbour subgraph.

**Say:**
"Stay on this case, because it's also the clearest argument for why we built this on a graph
instead of a table. A model scoring one transaction at a time has no way to know that the exact
same device — same model, same OS, same browser, same screen resolution — also made a purchase on
seventeen other customers' cards that week. This is a two-hop traversal:
`Transaction -> FROM_DEVICE -> DeviceProfile`, then back out to every other transaction on that
same device profile. One query, and the ring is visible immediately."

**Screen:** show the `tg_wcc` evidence entry and the resulting card list.

**Say:**
"We didn't stop at the two-hop query. We ran TigerGraph's built-in weakly-connected-components
algorithm over the card-and-device graph, and it independently confirms the same seventeen-card
cluster. That's graph algorithms doing real work, not window dressing — the community detection
result is cited directly as evidence in the case file, next to the policy rule and the FinCEN
guidance it's grounded against."

### 2:35-3:00 — NEW: the trace file, GraphRAG made visible

**Screen:** open `cases/traces/HHG-014.trace.md` in an editor (added this pass — one per case,
written alongside every answer file).

**Say:**
"One more artifact worth 25 seconds: every case also gets a plain-text trace file labelling each
piece of evidence by where it actually came from — `AGENTIC` for the LLM's own tool-selection and
confidence decisions, `GRAPH` for deterministic query results, `GRAPHRAG` for the vector search
over 5,565 closed-case notes plus policy documents, `GRAPH ALGORITHM` for TigerGraph's own
`tg_wcc`. This isn't a UI convention — it's a direct read of which mechanism produced each line, so
you don't have to take our word for what's agentic versus what's deterministic; it's labelled."

### 3:00-3:40 — A pattern the labels missed

**Screen:** switch to HHG-006. Show the evidence list, specifically the `threshold_structuring`
detector entry and its cited precedent case IDs.

**Say:**
"One more thing worth showing directly, because it's easy to miss and it's explicitly scored: nine
cases in the closed-case history are labelled `undocumented` — the pipeline that tagged the other
five and a half thousand rows didn't have a name for whatever pattern these were. We read all nine
analyst notes by hand, and five of them describe the same thing: several online purchases on one
card within about half an hour, each priced just under five hundred dollars — amounts chosen to
stay under an authorization ceiling that would otherwise trigger stronger verification."

**Screen:** point to the cited precedent IDs.

**Say:**
"We wrote a detector for it, and it fires here, on HHG-006 — four purchases in thirty minutes, each
just under five hundred dollars. It cites all five historical cases that describe the same pattern,
plus the FinCEN guidance on structured transactions. That's a pattern the label set never named,
found by reading the source data instead of trusting the labels."

### 3:40-4:05 — The approval gate: an L2 action sitting unexecuted

**Screen:** a case where `FILE_REPORT` appears in `final` actions with route `L2`, shown as
pending / not executed. HHG-014 works for this too.



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
- Confirm every case ID on screen (HHG-014, HHG-006, plus whichever legitimate case you open with)
  matches a real file in `cases/` before recording — don't reference a case ID from memory, and
  don't reuse the old HHG-017 example, which no longer changes in the live run.
- `[VERIFY]` HHG-014's exact final action list and HHG-006's exact final action list against
  `cases/*.json` immediately before recording. Another agent is fixing the R2/R4 policy defect on
  this branch concurrently (docs/REGEN_REVIEW.md); if cases/ gets regenerated, the specific action
  names spoken in the 0:35-2:00 and 3:40-4:05 beats may shift even though the underlying evidence
  and structure of the demo do not.
