# HHGoa Case Console

Analyst UI for the TigerGraph fraud-investigation agent. Shows case progression, evidence,
uncertainty, and the recommendation the agent made before and after it asked for more
evidence — built to the shape defined in the root `README.md`'s "Answer Format" section.

## Run it

```bash
cd ui
npm install
npm run dev
```

Open `http://localhost:3000`. `npm run build && npm run start` for a production build.

## Where the data comes from

The app reads every `*.json` file in `cases/` at the repo root (sibling of `ui/`) — one file
per case, named `<case_id>.json`, exactly as the root README's Answer Format specifies.

**That folder doesn't exist yet** as of this build; the agent that generates it is a separate
workstream. Until it appears, the app falls back to three fixture cases in `ui/fixtures/`:

- `HHG-017.json` — the fraud case, taken verbatim from the root README's own worked example
  (card testing, shared device, customer denial, SAR filed).
- `HHG-003.json` — a legitimate case built from the real HHG-003 case-pack entry (customer
  dispute over a $49 charge that turns out to be a recurring, forgotten subscription — policy
  rule R7).
- `HHG-020.json` — an uncertain case built from the real HHG-020 case-pack entry (mixed
  evidence, exposure crosses the R8 threshold, escalated to a human analyst rather than
  forced to a binary call).

**Whenever fixture data is in use, a banner across the top of every page says so explicitly**
("Fixture data — cases/ not found, showing 3 sample cases from ui/fixtures/"). Drop 20 real
answer files into `cases/` at the repo root and the banner disappears on the next request —
no code change needed.

## Screens

- `/` — case list. All loaded cases as dense rows: case id, pattern, a calibrated probability
  bar (never a bare float), exposure, verdict, status. Filterable by verdict.
- `/cases/[case_id]` — case detail. Header strip (verdict, probability, exposure, status), the
  before/after recommendation delta (the signature view — see below), the evidence list,
  the entity-neighborhood graph, similar prior cases (confirming vs. disconfirming), the SAR
  panel when `sar.file` is true, and an instrumentation strip (`stop_reason`, `tool_calls`,
  `tokens`, `latency_s`).

The graph view is derived from each case's own fields (card ids, transaction ids, connected
cards, connected device profiles) — not a live TigerGraph query — so it renders for any answer
file without extra plumbing. A device profile shared across more than one card gets a dashed
halo and a heavier teal edge; that's the ring-detection signal behind policy rule R6.

## Design

Token system, palette rationale, and the signature-interaction spec are in `DESIGN.md`.
Short version: an operations-console aesthetic (cold slate ground, teal-cyan structural
accent, magenta-red for fraud/blocked vs. cobalt-blue for cleared/legitimate — chosen to stay
distinguishable under red-green color-vision deficiencies), three type roles (Fraunces for the
verdict word and SAR headline, Inter Tight for everything else, IBM Plex Mono for every
measured number), and a connected-diff treatment for the before/after recommendation that
draws the evidence-request node as the causal link between the two states.

## Verification done

- `npx tsc --noEmit` — passes clean.
- `npm run build` — passes; all three fixture case pages statically generate via
  `generateStaticParams`.
- HTTP-level smoke test: ran `next start`, curled `/` and each `/cases/<id>` route, and
  grepped the real rendered HTML (not the RSC stream) for the load-bearing text — the fixture
  banner, verdict/pattern/probability values, the initial/final recommendation columns and
  the "what changed" sentence, the evidence-request causal-link text, approve/reject buttons,
  route badges (`L1 approval` / `L2 approval` / `Executed`), the SAR panel appearing only on
  the fraud case and absent on the legitimate one, and the probability meter's ARIA attributes
  (`role="meter"`, `aria-valuenow`, `aria-label`).
- **No visual/screenshot verification was performed.** Playwright MCP tools
  (`browser_navigate` / `browser_evaluate` / `browser_take_screenshot` / `browser_resize`)
  were not available in this session (`ToolSearch` returned no matches). The responsive
  behavior at 390/768/1440px, the motion/spring interactions on the recommendation delta, and
  the graph view's actual visual layout have not been confirmed by eye — only by DOM/HTML
  inspection. Run the app locally and check those by hand, or re-run this build with
  Playwright MCP tools available, before treating the visual design as confirmed.

## What's not built (out of scope per the brief)

No settings page, no auth. The approve/reject control on `L1`/`L2` actions is a local UI
state toggle for the demo (there's no backend to persist a real approval decision against —
the brief asks for a visible human decision point, not a workflow engine).
