# Tracewise: End-to-End Pipeline & UI/Backend Demo Video Script

> **Target Duration:** 4:30 – 4:50 minutes  
> **Submission Target:** TigerGraph × Hacker House Goa *Agentic Fraud Investigation*  
> **Format:** Dual-Track Production Script (Audio Voiceover + Visual / Terminal / UI Cues)  
> **Key Narrative:** An agentic fraud investigator on TigerGraph that gathers graph evidence, admits uncertainty, asks for more, and lands on a defensible next-best action.

---

## 1. Production Setup & Recording Layout

### Screen Layout Recommendation: Dual-Pane / Split-Screen
* **Left Window (40% width):** Terminal / VS Code
  * Dark theme (GitHub Dark or One Half Dark), font size 15–16pt for crisp 1080p legibility.
  * Tab 1: Terminal running live backend agent commands (`uv run python -m src.agent.run --evidence-mode agentic`).
  * Tab 2: Terminal running the answer validator (`uv run python -m src.answer.validator cases/`).
  * Tab 3: VS Code showing live case trace (`cases/traces/HHG-014.trace.md`).
* **Right Window (60% width):** Browser at `http://localhost:3000`
  * Tab 1: Home / Landing Page (`/`) with interactive `RingExplorer`, `CaseReplay`, and `PolicySandbox`.
  * Tab 2: Legitimate Case (`/cases/HHG-001`).
  * Tab 3: Fraud Ring & SAR Case (`/cases/HHG-014`).
  * Tab 4: Undocumented Structuring Case (`/cases/HHG-006`).
* **Cutaways / Overlays:**
  * Full-screen graphics from `docs/images/` (`architecture.png`, `data-pipeline.png`, `agent-flow.png`, `approval-routing.png`, `hhg014-device-ring.png`).

---

## 2. Pre-Recording Checklist (10 Minutes Prior)

1. **Wake Savanna:** Check TigerGraph Savanna 4.2.5 instance status (resume if idle).  
   *(No `--offline` fallback for this recording: `--offline` runs against local fixture JSON, not the live graph, and produces zero agentic evidence -- it would silently contradict the entire "agentic" narrative on screen. If Savanna is slow, cut and resume the take rather than switch to `--offline`.)*
2. **Every backend command below MUST include `--evidence-mode agentic`.** The CLI defaults to
   `--evidence-mode deterministic`, which never calls the LLM at all -- no MCP tool selection,
   no confidence-gate entries, nothing tagged `[AGENTIC]` in the trace file. Every command in
   this script already has the flag; if you type a new one live, don't drop it.
3. **Use `uv run python`, not bare `python`.** On a machine with multiple Python installs, bare
   `python` can resolve to an unrelated environment that doesn't even have this project's
   dependencies installed, and every command fails immediately.
4. **Start UI:**
   ```bash
   cd ui && npm run dev
   # Verify http://localhost:3000 shows banner "reading cases/*.json"
   ```
3. **Verify Answers:**
   ```bash
   uv run python -m src.answer.validator cases/
   # Must return: 20 files, 0 violations
   ```
4. **Queue Target Case IDs:** `HHG-001` (legitimate), `HHG-014` (device ring & SAR), `HHG-006` (structuring).
5. **Close Notifications:** Silence Slack, email, Discord, and system popups.

---

## 3. End-to-End Dual-Track Storyboard

### ACT 1: The Hook, Pipeline Architecture & Restraint (0:00 – 0:40)
*Scoring Alignment: Case Summary & Explainability (10%), Investigation Accuracy (25%)*

| Timecode | Video / Screen Actions (Visual) | Audio / Spoken Narration | Backend & Pipeline Context |
| :--- | :--- | :--- | :--- |
| **0:00 - 0:12** | **Full-Screen Graphic Cutaway:**<br/>Display `docs/images/architecture.png` transitioning smoothly into `docs/images/data-pipeline.png`.<br/>Highlight the stats: *590,742 transactions, 14,780 cards, 5,565 closed cases with HNSW vector embeddings*. | "Most fraud demos open with a card block. We’re opening with the exact opposite, because in real financial crime, restraint is the harder problem.<br/><br/>This is **Tracewise**, an agentic fraud investigation system built on TigerGraph Savanna." | **Data Pipeline Layer:**<br/>GSQL bulk-loading job over IEEE-CIS dataset with 0 rejected rows.<br/>Reconstructed card vertices anchored on bank IDs. |
| **0:12 - 0:25** | **Split Screen:**<br/>- **Left (Terminal):** Run:<br/>`uv run python -m src.agent.run --case HHG-001 --evidence-mode agentic --out cases/`<br/>Show execution completing in seconds, stopping at `CLOSE_NO_FRAUD`.<br/>- **Right (Browser):** Switch to `/cases/HHG-001`. | "The benchmark dataset gives us 20 alerts, and half of them are completely legitimate customers. An agent that blindly blocks transactions destroys user trust and scores terribly." | **LangGraph Agent Loop:**<br/>`src/agent/investigator.py`<br/>Assess $\rightarrow$ Plan $\rightarrow$ Execute $\rightarrow$ Integrate. Early conclusion when evidence ledger shows no anomalous signals. |
| **0:25 - 0:40** | **Right (Browser):**<br/>Hover over the **Probability Meter** (`0.08`) and the top badge: `CLOSE_NO_FRAUD` (auto-approved).<br/>Scroll briefly to show 0 SAR filed and clean transaction history. | "Here is case HHG-001. A risk-score model flagged this account. Our agent queried the card history, checked device continuity, and found zero anomalies. Fraud probability: 8%. Verdict: legitimate. Action: `CLOSE_NO_FRAUD`, auto-approved. The agent knows when to stop looking." | **Policy Engine R0/R10:**<br/>`src/policy/engine.py`<br/>Fixed thresholds: $\le 0.15$ legitimate, $\ge 0.85$ fraud. LLM tokens never set probability. |

---

### ACT 2: The Agentic Loop & Uncertainty Flip (HHG-014) (0:40 – 2:00)
*Scoring Alignment: Next Best Action & Uncertainty (25%), Agentic Design (15%)*

| Timecode | Video / Screen Actions (Visual) | Audio / Spoken Narration | Backend & Pipeline Context |
| :--- | :--- | :--- | :--- |
| **0:40 - 0:55** | **Full-Screen Graphic Cutaway:**<br/>Display `docs/images/agent-flow.png`.<br/>Point out the two critical phases: `snapshot_initial` $\rightarrow$ `request_evidence` $\rightarrow$ `reassess` $\rightarrow$ `snapshot_final`. | "Now look at how the agent reasons under real uncertainty. The hackathon rubric dedicates 25% of the score to the Next Best Action, requiring the agent to record its recommendation *before* requesting evidence and *after* it returns." | **State Machine Design:**<br/>12-node LangGraph workflow in `src/agent/graph.py`.<br/>Explicit state transitions enforcing evidence requests before final commitment. |
| **0:55 - 1:25** | **Split Screen:**<br/>- **Left (Terminal):** Run:<br/>`uv run python -m src.agent.run --case HHG-014 --evidence-mode agentic --out cases/`<br/>Highlight logs outputting:<br/>`initial snapshot: CREATE_CASE, FILE_REPORT`<br/>`evidence_request: customer_validation (simulated timeout)`<br/>`reassessing ledger... final snapshot locked`.<br/>- **Right (Browser):** Navigate to `/cases/HHG-014`. | "Case HHG-014 begins with an analyst note: a customer transaction on an unrecognised device.<br/><br/>The agent starts investigating through TigerGraph MCP tools. It freezes an *initial* recommendation: open a case and file a report. But because the fraud probability is in the uncertain band, policy forbids immediate irreversible action without verification." | **Evidence Request Simulation:**<br/>`src/agent/nodes.py`<br/>Logged explicitly in `evidence_requests` array per organizer specification. |
| **1:25 - 2:00** | **Right (Browser):**<br/>Scroll down to the **`RecommendationDelta`** component.<br/>Point to the vertical causal spine: Initial actions on top $\rightarrow$ Customer Validation request $\rightarrow$ 24hr expiration $\rightarrow$ Final revised actions.<br/>*(Optional: switch to Landing Page `/` and scrub the **`CaseReplay`** scrubber to show the moment the state updates).* | "The agent issues a customer validation request. As specified by the rules, we simulate the 24-hour window, which expires with no reply.<br/><br/>Notice that this non-response doesn't wipe the slate clean—it's folded into the evidence ledger. The final recommendation keeps the prior actions and escalates with `MONITOR_CARD` and `DECLINE_TRANSACTION`. Initial and final are preserved side-by-side with full causal reasoning." | **Recommendation Delta:**<br/>`ui/src/components/RecommendationDelta.tsx`<br/>Causal diff highlighting added/removed actions with policy rule citations (R4, R6). |

---

### ACT 3: Graph Traversal, Community Detection & Provenance (2:00 – 3:00)
*Scoring Alignment: Innovation & Graph-Native Capabilities (15%)*

| Timecode | Video / Screen Actions (Visual) | Audio / Spoken Narration | Backend & Pipeline Context |
| :--- | :--- | :--- | :--- |
| **2:00 - 2:30** | **Right (Browser):**<br/>On the Home Page (`/`), scroll to the **`RingExplorer`**.<br/>Click and drag the central device node and watch the spring physics pull the 17 connected card nodes.<br/>Hover over the badge: *1 handset, 17 cards, 18 customers*. | "Why build this on a graph instead of a relational table? Because of this screen.<br/><br/>A tabular classifier scoring one transaction at a time cannot see that the exact same browser fingerprint—same OS, browser build, and screen resolution—was used across 18 distinct customers' cards in seven days. This is a 2-hop traversal: `Transaction -> FROM_DEVICE -> DeviceProfile`, then back out to all transactions." | **Interactive Force Graph:**<br/>`ui/src/components/RingExplorer.tsx`<br/>Built with deterministic Mulberry32 seed and Verlet/rAF physics.<br/>Direct visual representation of `cases/HHG-014.json`. |
| **2:30 - 2:45** | **Left (Terminal / VS Code):**<br/>Open `cases/traces/HHG-014.trace.md`.<br/>Highlight lines showing:<br/>`[GRAPH ALGORITHM] algorithm:tg_wcc(v_type=Card\|DeviceProfile)`<br/>Confirming the community detection cluster. | "We didn't just run an ad-hoc query. We executed TigerGraph’s native `tg_wcc` Weakly Connected Components algorithm directly over the card-and-device graph. TigerGraph mathematically identified this 17-card cluster as a single isolated fraud ring." | **Graph Algorithms:**<br/>`src/graph/algorithms.py`<br/>Native TigerGraph GSQL graph algorithm library execution. |
| **2:45 - 3:00** | **Left (VS Code Trace File):**<br/>Scroll through `HHG-014.trace.md` showing the strict tag taxonomy:<br/>- `[AGENTIC]` (LLM tool selection)<br/>- `[GRAPH]` (Deterministic GSQL)<br/>- `[GRAPHRAG]` (Vector search over closed cases)<br/>- `[DOCUMENT]` (Policy chunks) | "Every case emits a trace file like this. Every single finding is explicitly tagged with its provenance: `AGENTIC` for LLM decisions, `GRAPH` for deterministic query results, `GRAPHRAG` for vector search, and `GRAPH ALGORITHM` for community detection. There is zero guessing about where facts came from." | **Auditable Provenance:**<br/>`src/agent/run.py` (`_write_trace_md`)<br/>Strict separation between LLM exploration and deterministic graph truth. |

---

### ACT 4: The Undocumented Pattern ($500 Structuring) & GraphRAG (3:00 – 3:45)
*Scoring Alignment: Innovation (15%), Investigation Accuracy (25%)*

| Timecode | Video / Screen Actions (Visual) | Audio / Spoken Narration | Backend & Pipeline Context |
| :--- | :--- | :--- | :--- |
| **3:00 - 3:15** | **Full-Screen Graphic Cutaway:**<br/>Show `docs/images/hhg006-structuring.png`.<br/>Highlight the velocity chart: 4 online transactions, each between $450 and $499 within 30 minutes. | "Here is an innovation the organizers' label set missed. In the 5,565 closed training cases, nine were labeled 'undocumented'. We read those analyst notes manually and found five described the exact same behavior: multiple online purchases within an hour, each priced just under $500 to dodge authorization thresholds." | **Pattern Discovery:**<br/>`src/detectors/patterns.py` (`detect_threshold_structuring`)<br/>Detector for online velocity structuring under authorization ceilings. |
| **3:15 - 3:45** | **Right (Browser):**<br/>Navigate to `/cases/HHG-006`.<br/>Point to the **`PrecedentPanel`** showing cited cases: `CC-3748`, `CC-3841`, `CC-3907`, `CC-4086`, `CC-4124`.<br/>Point to **`RuleTrace`** showing Rule R8 firing: `ESCALATE_TO_ANALYST`. | "We built a dedicated detector for this structuring pattern, and it fired on case HHG-006: four transactions totaling $1,906.07.<br/><br/>Our two-pool GraphRAG retrieved all five historical precedents from TigerGraph's HNSW vector index, cross-referenced FinCEN guidance, and routed the case to a human analyst under Rule R8." | **Two-Pool GraphRAG:**<br/>`src/rag/retrieve.py`<br/>Separate retrieval pools for confirmed fraud vs cleared cases to prevent base-rate skew. |

---

### ACT 5: Permission Gates & FinCEN SAR Narrative (3:45 – 4:20)
*Scoring Alignment: Enterprise Governance & Agentic Design (15%)*

| Timecode | Video / Screen Actions (Visual) | Audio / Spoken Narration | Backend & Pipeline Context |
| :--- | :--- | :--- | :--- |
| **3:45 - 4:00** | **Full-Screen Graphic Cutaway:**<br/>Display `docs/images/approval-routing.png`.<br/>**Right (Browser):** On `/cases/HHG-014`, highlight `FILE_REPORT` marked with the amber badge **`L2 approval`** and the `Approve` / `Reject` toggle. | "In enterprise banking, an AI agent cannot be allowed to file regulatory reports or shut down merchant accounts autonomously.<br/><br/>We enforce strict 3-tier routing: `auto`, `L1`, and `L2`. High-impact actions trigger a LangGraph `interrupt()`, holding the action pending team lead review." | **Approval Routing:**<br/>`src/policy/engine.py` (`resolve_route`, `finalize_action`)<br/>Auto actions executed immediately; L1/L2 actions require human analyst / lead authorization. |
| **4:00 - 4:20** | **Right (Browser):**<br/>Scroll down to the **`SarPanel`** on `/cases/HHG-014`.<br/>Show the FinCEN-structured narrative: *Who, What, When, Where, Why Suspicious*, and the verified subjects list. | "When policy does require a regulatory filing, Tracewise generates this FinCEN-compliant Suspicious Activity Report.<br/><br/>Crucially, our SAR engine enforces strict ID guarding: every single transaction, card, and device ID in this narrative is verified against the input facts. If an LLM invents a non-existent ID, the output is rejected and replaced by a deterministic template." | **ID Guardrail:**<br/>`src/sar/narrative.py`<br/>Regex validation verifying every subject ID against known input facts. |

---

### ACT 6: Validation, Benchmark Results & Conclusion (4:20 – 4:45)
*Scoring Alignment: Final Delivery & Polish (10%)*

| Timecode | Video / Screen Actions (Visual) | Audio / Spoken Narration | Backend & Pipeline Context |
| :--- | :--- | :--- | :--- |
| **4:20 - 4:35** | **Split Screen:**<br/>- **Left (Terminal):** Execute live:<br/>`uv run python -m src.answer.validator cases/`<br/>Show the output: **`20 files checked, 0 violations`**.<br/>- **Right (Browser):** Return to `/` and show the benchmark tally: **`9 Legitimate, 10 Uncertain, 1 Fraud`**. | "To ensure absolute compliance, we run our automated validator across all 20 answer files. 20 files, 0 schema violations, 0 policy violations.<br/><br/>The agent accurately categorizes the dataset: 9 legitimate, 10 uncertain, and 1 coordinated fraud ring." | **Answer Validation:**<br/>`src/answer/validator.py`<br/>Validates schema, action names, enum types, probability calibration, and SAR narrative completeness. |
| **4:35 - 4:45** | **Right (Browser):** Smooth scroll past the hero masthead showing *Tracewise: An agentic fraud investigator on TigerGraph*.<br/>Display GitHub repo URL and team credits. | "TigerGraph provides the connected data and graph algorithms; LangGraph directs where to look; and deterministic policy engines keep the agent honest. That is Tracewise. Thank you." | **Project Completion:**<br/>Team Karan, Vaibhav, Bhavya.<br/>Repo: `VaibHUB17/HHgoa4`. |

---

## 4. Commands Cheat Sheet for Recording

Keep these exact commands pasted in a notepad ready for execution during recording:

```bash
# Terminal 1: Run legitimate case (Act 1)
uv run python -m src.agent.run --case HHG-001 --evidence-mode agentic --out cases/

# Terminal 2: Run fraud ring case (Act 2)
uv run python -m src.agent.run --case HHG-014 --evidence-mode agentic --out cases/

# Terminal 3: View trace file (Act 3)
code cases/traces/HHG-014.trace.md

# Terminal 4: Validate all 20 benchmark files (Act 6)
uv run python -m src.answer.validator cases/

# Terminal 5: Verify entire test suite (Optional live flex)
uv run python -m pytest tests/ -q
```

---

## 5. Voiceover Delivery Tips for the Speaker

1. **Pacing:** Speak at a steady, deliberate pace (~135–145 words per minute). Do not rush through the numbers or case IDs.
2. **Key Word Emphasis:**
   - Emphasize *"restraint"*, *"where to look and when to stop"*, *"deterministic policy"*, and *"two-hop traversal"*.
3. **Pronunciation Guide:**
   - `tg_wcc` $\rightarrow$ *"T-G-W-C-C"* (or *"TigerGraph Weakly Connected Components"*).
   - `GSQL` $\rightarrow$ *"G-S-Q-L"*.
   - `HNSW` $\rightarrow$ *"H-N-S-W"*.
   - `SAR` $\rightarrow$ *"S-A-R"* (or *"Suspicious Activity Report"*).
   - `HHG-014` $\rightarrow$ *"H-H-G zero fourteen"*.
4. **Mouse Discipline:** Move the cursor smoothly to buttons/badges, pause for a full second, and click. Avoid jittery cursor movements while speaking.
