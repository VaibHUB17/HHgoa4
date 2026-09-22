# Reference stack — exact libraries, exact reasons, exact rejects

This is the concrete "what to actually install" companion to SKILL.md. It's written from
one real build (Facechain: webcam face capture → live web search → biometric re-verify →
blockchain anchor, a Next.js app) so every choice below has a real reason attached, not a
generic "popular choice" justification. Reuse the decisions; don't re-research them.

When a new task needs a different domain (not face/chain), keep the *frontend + animation*
column as your default and re-derive only the domain-specific row (the ML/data/backend one).

## Frontend + animation stack (default for any showcase app)

| Layer | Use | Install | Why this, not the alternative |
|---|---|---|---|
| Framework | Next.js 16, App Router, Turbopack | `npx create-next-app@latest <name> --ts --tailwind --eslint --app --src-dir --use-npm --no-turbopack` (add `--no-turbopack` if the ML lib you bundle has a bad export map — see below) | One-command scaffold, file-system routing, API routes double as your backend with zero extra server. |
| Styling | Tailwind v4 (`@tailwindcss/postcss`) | comes with the scaffold above | `@theme inline { --color-x: var(--x) }` in globals.css maps CSS custom properties straight into Tailwind utility classes — you get `bg-ink`, `text-amber` etc. as first-class utilities while still defining the actual color values in plain CSS variables (needed anyway for dark-mode media queries and for anything that isn't a rendered React tree, like standalone SVG). |
| Component animation | **`motion`** (formerly Framer Motion), imported as `import { motion, AnimatePresence, useReducedMotion, useSpring, useMotionValue } from "motion/react"` | `npm i motion` | Already the ecosystem-standard React animation library; one dependency covers spring physics, exit animations (`AnimatePresence`), gesture variants (`whileHover`/`whileTap`), and `useReducedMotion()` for accessibility — no separate spring library, no separate gesture library. Rejected: **GSAP + SplitText** (SplitText is a paid Business-plan plugin; GSAP's timeline API is stronger for scroll-scrubbed cinematic sequences but this app has none); **react-spring** (lower-level, more boilerplate for the same spring result `motion` gives for free); **CSS-only transitions** (fine for hover states, but can't do physics-based overshoot/settle, which is what makes an accepted-vs-rejected verdict *feel* like a verdict). |
| Diagrams / architecture visuals | **hand-authored inline SVG with SMIL** (`<animate>`, `<animateMotion>`) — no library | nothing to install | GitHub renders SVG inline in READMEs *and executes SMIL animation*, so `![](docs/pipeline.svg)` animates on the repo page with zero JS, zero runtime dependency, and it's inspectable/diffable XML. Rejected: **Mermaid** (renders on GitHub too, but static — no animation, and its layout engine fights you on anything that isn't a strict flowchart/sequence shape); **excalidraw/draw.io exports** (raster or non-animated, and not text-diffable in git); **d3/three.js diagram** (needs a JS runtime to render at all — dead in a README, only works inside the app itself). |
| 3D-looking depth/perspective backgrounds | Flat SVG with **pre-projected geometry** (compute the perspective math into 2D coordinates yourself: `y = horizon + (H-horizon) * t^n` for receding grid lines) — not real 3D transforms | nothing to install | A real `rotateX()` + `preserve-3d` composited layer that extends far past the viewport (e.g. a "ground plane" taller than the screen) can hit a GPU-tiler bug on some Chrome/ANGLE configurations: the compositor mis-judges the projected bounds and blanks everything below the first viewport until a resize forces a repaint. This is real and was hit in production. Pre-projecting the perspective into flat 2D SVG coordinates makes the bug structurally impossible — there is no 3D transform left for a tiler to mis-judge, and it's cheaper to paint. Only use real CSS 3D transforms for something that stays fully inside one viewport and is small (a card flip, not a background). |
| Fonts | `next/font/google` with 3 explicit roles: one **display serif** (character, used large and sparingly — e.g. Bodoni Moda, Playfair Display), one **body sans** (Inter Tight, Geist), one **mono** for data/labels (JetBrains Mono, IBM Plex Mono) | built into `next/font/google`, no separate install | Three roles, not two: the mono face is what makes numeric/technical output (hashes, scores, timestamps) read as *measured data* instead of decorative text — it's doing signal work, not just a stylistic choice. Never ship only a sans-serif "safe" pairing when the brief rewards distinctiveness. |
| Chain client | **viem** (+ `@nomicfoundation/hardhat-toolbox-viem`) | `npm i viem` (root) and inside a `chain/` subproject: `npm i --save-dev hardhat @nomicfoundation/hardhat-toolbox-viem viem dotenv` | TypeScript-first, tree-shakeable, and Hardhat's official viem toolbox generates typed contract bindings automatically post-compile. Rejected: **ethers.js v5/v6** (still fine, but viem is the current default recommendation for new Hardhat projects and has a smaller bundle for the browser-side read calls). |

## Face/vision ML stack (swap this row out for other domains)

| Layer | Use | Install | Why / gotcha |
|---|---|---|---|
| Face detection + embedding | **`@vladmandic/human`** | `npm i @vladmandic/human` | Ships prebuilt TFJS model weights you copy into `public/models/` (blazeface detector, facemesh, iris, `faceres` — a 1024-d embedding model — antispoof, liveness) so the whole face pipeline runs offline in the browser with zero third-party calls until the operator explicitly runs a search. Rejected: **face-api.js** (unmaintained since ~2020); **MediaPipe Face Mesh directly** (gives you landmarks, not a ready descriptor/embedding — you'd have to bolt on your own recognition model). |
| **Known bundler gotcha** | | | `@vladmandic/human`'s `package.json` export map has malformed subpath keys (missing the leading `./`), so `import "@vladmandic/human/dist/human.esm.js"` fails to resolve, and the bare `import "@vladmandic/human"` specifier falls through to the `"node"` condition — the **Node build**, which `require()`s `@tensorflow/tfjs-node` and breaks any browser bundle. Fix: alias the bare specifier straight to the browser ESM file in `next.config.ts`, in both the turbopack and webpack resolver sections: `turbopack: { resolveAlias: { "@vladmandic/human": "./node_modules/@vladmandic/human/dist/human.esm.js" } }` and a matching `config.resolve.alias` entry keyed `"@vladmandic/human$"` in the `webpack()` callback. Then `await import("@vladmandic/human")` in a `"use client"` file works normally. This exact failure will happen again with any TFJS-based package that ships both node and browser builds — check the export map before assuming the bare import "just works." |
| Accuracy technique: flip test-time augmentation | encode the frame **and** its horizontal mirror, average the two descriptors, for the one committed "probe" capture only (not for every candidate — too expensive) | no install, ~15 lines against the same lib | Standard evaluation practice in the face-recognition literature (flip-averaging is used in ArcFace-style evaluation, Deng et al., CVPR 2019); cancels pose asymmetry and measurably stabilizes the descriptor between two captures of the same face. |
| Accuracy technique: quality gate on candidates | refuse to score a detected face below ~48px min side or below ~0.45 detector confidence; show the reason instead of a misleading score | no install | Cosine similarity on face embeddings degrades badly on low-resolution crops (a small/blurry face drifts toward the "mean face" and inflates false-positive similarity) — this is the single easiest place a demo silently lies if you don't gate it. |

## Search/lookup provider research (worked example — redo this table for a new domain)

| Provider considered | Verdict | Why |
|---|---|---|
| SerpApi — Google Lens engine (`engine=google_lens`) | **chosen, default** | Free tier: 250 searches/month, no card, key issued instantly at signup. It is **whole-image visual similarity, not a face search** — say this explicitly in your own docs, because a reviewer who knows the difference will check. Two-step call: `POST https://serpapi.com/image` (multipart, ≤500KB) returns an `image_id`, then `GET https://serpapi.com/search?engine=google_lens&image_id=...` returns `visual_matches`. Undocumented gotcha found by testing: the default call sometimes returns matches without needing `type=visual_matches` at all, and sometimes needs it explicitly — call once without the param, retry once with `type=visual_matches` if the first response is empty, rather than hardcoding one shape. |
| FaceCheck.ID | chosen as **paid fallback / true face search** | Actual face-embedding search over an indexed web crawl, so it finds social-profile hits far more reliably than whole-image similarity — but costs credits (~$0.30/search), paid in crypto only, and its free "demo" mode may return blurred/withheld URLs (verify this with one real demo call before relying on it — don't assume). API: `POST /api/upload_pic` (multipart) → `id_search`, then poll `POST /api/search` with that id until `output.items` appears. |
| Azure Face API / AWS Rekognition | rejected for this build | Real face-search products, but both require account setup with billing attached before the first call, which fails the "free, instant key" requirement of a fast prototype. Worth reconsidering if the brief explicitly rewards enterprise-grade accuracy over speed of setup. |

**Process to redo this table for a new domain:** WebSearch `<capability> API free tier pricing <current year>`, then WebSearch `<capability> API rate limit no credit card`, then actually call the signup/docs endpoint (unauthenticated, to see what error shape comes back — confirms the field names before you write real code against them) rather than trusting docs prose alone.

## Chain research (worked example)

| Chain considered | Verdict | Why |
|---|---|---|
| Local Hardhat node (chain id 31337) | **chosen, default** | Zero external dependency, never flaky during a recording, `npx hardhat node` + a deploy script gets a contract live in seconds. Always ship this as the default even when a public chain is also wired up — never make the public chain the only path. |
| Polygon Amoy (chain id 80002) | **chosen, optional public mode** | Uses Sepolia as its L1 root, EVM-compatible, free faucets exist (`faucet.polygon.technology`, Alchemy's Amoy faucet, QuickNode's Amoy faucet — check current drip amounts, they change). Switch via one `CHAIN_TARGET=amoy` env var; same contract, same deploy script, different `--network` flag. |
| Base Sepolia | considered, not chosen | Equally valid EVM testnet; no specific reason to prefer Amoy except Polygon's faucet ecosystem being slightly more mature at time of research. Swap freely if the brief names a preferred chain family. |

**Canonicalization rule that generalizes beyond chain work:** whenever you hash a JSON-like
structure for later re-verification, sort object keys at every depth and forbid floating-point
fields (quantize to integers — e.g. similarity as basis points, 0-10000) before serializing.
A float that round-trips through JSON on a different runtime/locale can print differently and
silently break a digest comparison. Test this specifically: hash the same logical bundle with
its keys in two different orders and assert the digest is identical.

## MCP tools / verification tooling actually used

| Tool | What it's for here | Concrete pattern that worked |
|---|---|---|
| **Playwright MCP** (`mcp__plugin_playwright_playwright__*` — `browser_navigate`, `browser_evaluate`, `browser_take_screenshot`, `browser_resize`, `browser_console_messages`) | The only reliable way to prove a claim about live, stateful, client-side behavior — not just "the component renders" but "this exact user flow produces this exact DOM state." | `browser_navigate` to the app, then a single `browser_evaluate` whose function body: (1) fetches a real test asset through your own proxy route so you get real bytes, not a placeholder; (2) constructs a `File`/`DataTransfer` and dispatches a real `change` event on the file input, exactly as a user's file picker would; (3) polls `document.body.innerText` / `querySelectorAll` in a `while (Date.now() - t0 < timeout)` loop for the *specific text a completed state produces* (not a fixed sleep — async pipelines vary in latency); (4) returns a compact string summary, since the tool result becomes part of the conversation and a full DOM dump would blow the context budget. Follow with `browser_take_screenshot({ fullPage: true })` and `Read` the PNG to visually confirm, at three widths minimum: 390 (mobile), ~768 (tablet), 1440 (desktop) via `browser_resize`. |
| **WebSearch** | Pricing/free-tier verification for external APIs, faucet URLs, chain IDs, current-year library recommendations — anything where the model's training data could be stale. | Always include the current year in the query explicitly (the model doesn't know "now" by default) and always end with a Sources section per the tool's own output contract. |
| **WebFetch** | Reading a specific GitHub repo/package's actual file tree or README when WebSearch snippets aren't specific enough (e.g. "does this repo have install scripts / telemetry / a malformed export map") | Point it at `https://api.github.com/repos/<owner>/<repo>/git/trees/main?recursive=1` for a file listing before fetching the README, when you need to know exactly what's in a repo rather than what its README claims. |
| **Agent tool with `model: "fable"` (or whatever model the user names)** | Parallel component-level polish once architecture is stable — see SKILL.md step 4 | Always pass the *shared design tokens* (the CSS variable names, not raw hex) into the subagent prompt explicitly, and always end the prompt with "run `npx tsc --noEmit` and report the result" so the agent self-checks before handing back. |
| A `frontend-design`-type skill (built-in aesthetic-direction skill, if the harness has one) | Loaded once, before any component code, with a one-line description of the actual subject ("dark, cinematic biometric-forensics console with a webcam scan, evidence cards, blockchain receipt") | Its output is a compact token system (named hex values, 2-3 font roles, one signature interaction) — treat that output as the spec the rest of the build must match, and revisit it once to strip anything that reads as a generic default before writing code. |

## Concrete worked palette (an example output, not a rule to copy verbatim)

For a "forensic/evidence console" subject, the palette that shipped:

```
--ink        #0b0d10   ground
--bench      #14181d   panel
--bench-hi   #1a1f26   raised panel
--rule       #232a32   hairline
--rule-hi    #333c47   hairline, emphasis
--bone       #e8e4db   primary text (warm, not pure white)
--dim        #7c8791   secondary text
--faint      #4c555e   tertiary text
--amber      #e8a33d   single accent ("safelight")
--verdict    #6fd3b4   accepted / positive state
--reject     #c4574b   rejected / negative state
```

The generalizable rule, not the specific hex values: **one warm neutral for text against one
cool-graphite ground**, **exactly one saturated accent color**, and **two semantic colors**
(a positive/accepted and a negative/rejected) that are visually distinct from the accent and
from each other even for common color-vision deficiencies (avoid pure red/green as the only
distinguishing pair — this shipped brick-red + teal-green specifically to stay distinguishable).
Re-derive the actual hex values from the new subject; don't reuse these verbatim on an
unrelated project or every showcase app you make will look like the same one.

## Research-log habit

Keep a running table like the ones above *during* the build, not reconstructed after —
every time you WebSearch or WebFetch to decide between options, add one row: option,
verdict, one-sentence why. This is what makes the next build faster: you're not
re-Googling "which face API is free" from zero, you're updating a table that already has
the answer and just needs a freshness check (pricing/rate-limits/free-tiers change; recheck
before trusting a table older than a few months).
