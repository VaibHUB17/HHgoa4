---
name: build-showcase-app
description: >
  Build a polished, working end-to-end prototype for a hackathon/showcase task from a raw
  task brief — pick the real stack, prove the riskiest unknown first, build a distinctive
  UI (not templated AI-default design), parallelize component work across subagents, write
  animated-diagram architecture docs, and verify everything by actually running it before
  calling it done. Use when the user pastes a hackathon/shortlisting/challenge brief and
  wants a working submission, or says "build a prototype for this", "create a showcase app",
  "make this qualify for the task", or names a specific pipeline shape (X → Y → Z) they want
  demoed end to end.
---

# Build showcase app

A task brief plus this skill should produce: a running app, a proven end-to-end demo, an
honest README, and (if asked) animated architecture docs — in one pass, without the user
having to steer each step.

This is not a template to fill in. It is an order of operations. Skipping steps is how you
end up with a beautiful UI wrapped around a pipeline that has never actually run.

**Read [reference-stack.md](reference-stack.md) before step 2.** It is the concrete
companion to this file: exact npm packages, exact install commands, exact bundler gotchas
already hit and fixed, a worked provider-research table (which face-search / search API /
chain to pick and why), the exact MCP tools used for verification and how, and a worked
palette example. This file (SKILL.md) is the order of operations; reference-stack.md is the
"stop re-Googling this, here's the answer" sheet. Update reference-stack.md's tables at the
end of a build if you found something it doesn't already cover — that's what keeps it useful.

## 0. Read the brief like a judge will

Before anything else, extract three things from the brief, verbatim:

- **The exact deliverable shape.** If it says "pipeline: A → B → C", that phrase is the
  rubric. Every stage needs to be visibly real in the final demo, not implied.
- **The one requirement most likely to be faked.** Briefs that say "genuine", "real",
  "not hardcoded", or "must demonstrate X" are telling you where a lazy submission would
  cut a corner — and where a reviewer will look hardest. Find that stage. It is almost
  always something that needs a live external API, a real search, or a real cryptographic
  operation, not a local computation you can fully control.
- **Constraints that aren't about code**: no-resubmission rules, a required recording,
  a submission form, a required attribution/logo, a specific platform. Write these down
  (see step 8) — they get forgotten under implementation pressure.

Then call `advisor()` once, before writing any code, with your read of the brief and your
proposed stack. Get the architecture right before you get the pixels right.

## 1. Identify and de-risk the one genuinely unknown thing

Every brief has exactly one part that "should work" but hasn't been tried: an API whose
free-tier response shape you're guessing at, a browser capability that behaves differently
across engines, a cryptographic property you're asserting rather than testing. Find it.

- If it needs a credential the user hasn't provided: ask for it now (or use
  `AskUserQuestion` to make the tradeoff explicit — e.g. "provider A is free but does X,
  provider B costs money but does Y") rather than building three more layers on top of an
  unverified foundation.
- If the user gives you a key mid-session, that changes the priority order: **stop and run
  the real thing immediately**, before doing more UI or doc work. An untested integration is
  the single biggest risk to a one-shot submission, and it silently stops being untested the
  moment you have the credential — don't sit on it.
- Build a fallback path for anything that costs money or has a rate limit: a `/selftest`-style
  route that proves the same code path with free, deterministic inputs (public-domain data,
  a local simulated chain, cached fixtures). This becomes your insurance for the recording —
  if the paid path flakes on demo day, the free path still proves the mechanism works.
- When a library's docs are ambiguous about a wire format, don't guess once and move on:
  write the adapter behind an interface so a wrong guess is a one-file fix, and add a
  same-request fallback (try the default shape, retry with an explicit parameter if the
  first attempt returns empty) so a documented-but-wrong assumption degrades instead of
  breaking silently.

## 2. Pick the stack for one-shot delivery, not for résumé value

Default frontend stack, unless the brief names a different one: **Next.js 16 App Router +
Tailwind v4 + `motion` (`import ... from "motion/react"`)** for every component
micro-interaction, **hand-authored SVG + SMIL** (not a diagramming library) for any diagram
that needs to animate, and **`next/font/google`** with three explicit roles (display / body
/ mono). Exact install commands, exact version pins, and exactly why each of these beats the
obvious alternative (GSAP, react-spring, Mermaid, three.js) are in reference-stack.md — use
that table instead of re-deciding from scratch.

Domain-specific row (ML model, external API, chain/backend) still needs real research per
project — reference-stack.md has a worked example (face detection + search API + testnet
selection) to copy the *process* from, not the specific vendor, unless the new task is also
face/chain-shaped.

Rule that generalizes regardless of domain: pick one animation library and make every
interaction speak it — never three animation libraries competing in the same page. Pick a
blockchain/backend choice that has both a zero-setup local mode and a real public mode
behind one config flag — never only the public one, since a flaky public testnet on demo day
is not a risk worth taking. Prefer local-first ML/data (models bundled and served from the
app, not fetched from a CDN) whenever the task cares about privacy or offline-capability.

State the stack choice once, briefly, and move — this is not the place to spend the
user's turns on options they didn't ask to compare.

## 3. Design pass before any component code

Load a design/frontend-aesthetics skill if one is available (search installed skills for
"design" or "frontend"). Before writing a single component:

- Name the actual subject the UI is about (a face-forensics console, a trading blotter, a
  lab notebook) and derive the palette, type pairing, and one signature interaction from
  *that*, not from "dark mode with an accent color." The three defaults to actively avoid
  unless the brief asks for them: cream background + serif + terracotta; near-black +
  single neon accent with nothing else considered; broadsheet hairline-grid newspaper
  layout. All three are fine choices *when derived from the subject* — the failure mode is
  reaching for one by default.
- Write down a compact token system (4-6 named colors, 2-3 type roles, one layout
  concept, one signature element) before coding. Revisit it once and cut anything that
  reads as the generic default for a project like this one.
- Build 1-2 shared interaction primitives first, using `motion`'s `whileHover`/`whileTap`
  variants and `useSpring`/`useMotionValue` for anything that should feel physical rather
  than tweened: a button component with real hover/press physics, a domain-appropriate
  control that replaces a raw `<input type=range>` or `<select>` (e.g. a calibrated-scale
  slider instead of a stock range input, if the domain is measurement/scoring). Every other
  component should consume these, not reinvent buttons. See reference-stack.md's "worked
  palette" section for what a finished token system looks like before you derive your own.
- If a copy/tone skill is installed (e.g. one that strips AI-isms), invoke it explicitly on
  all UI copy, labels, error messages, and documentation. Sycophancy, tricolon padding, and
  stock vocabulary read as "templated" just as loudly as a generic color palette does.

## 4. Parallelize component polish, not architecture

Once the core data flow and shared primitives exist and typecheck, component-level visual
polish is the right unit of work to hand to subagents in parallel — but only after the
architecture is stable, never before.

- Partition by **file**, not by feature — give each subagent an explicit, non-overlapping
  file list ("edit only X.tsx and Y.tsx") so two agents never touch the same file.
- In every subagent prompt: state the design tokens/CSS variables to use (don't let each
  agent invent its own palette), state what must NOT change (business logic, prop
  contracts, copy that's already correct), and require `tsc --noEmit` (or the equivalent
  compile check) before reporting done.
- If the user names a specific model for subagents (e.g. "only use model X"), pass that as
  the `model` parameter on every `Agent` call — don't default to the parent session's model.
- Launch independent subagents in one message with multiple tool calls, not sequentially.
- When agents report back, don't trust the summary — run the typecheck and build yourself
  across the whole tree, since two agents editing adjacent files can pass individually and
  still conflict.

## 5. Verify by running it, not by reading the code

This is the step that most often gets skipped under time pressure, and it's the one a judge
actually checks.

- Typecheck and production-build the whole project after every batch of changes, not just
  at the end.
- Drive the actual UI with the **Playwright MCP tools**
  (`mcp__plugin_playwright_playwright__browser_navigate` /
  `browser_evaluate` / `browser_take_screenshot` / `browser_resize`) if available: fill in
  real inputs (upload a real test file via a constructed `File`/`DataTransfer` and a
  dispatched `change` event, click real buttons), then poll `document.body.innerText` /
  `querySelectorAll` for the specific text a completed state produces — not a fixed sleep —
  and read back the real DOM state, not just "the component renders." If the task has a
  multi-stage pipeline, drive it stage by stage and print the real output of each stage (an
  API response, a computed score, a transaction hash). Screenshot at 3 widths minimum
  (~390 / ~768 / 1440) via `browser_resize` and actually `Read` the PNG back — don't assume
  responsive CSS worked because it typechecked. Concrete evaluate-script pattern is in
  reference-stack.md's MCP tools table.
- For any claim you're about to write in a README ("the encoder tells people apart",
  "the chain detects tampering"), construct the smallest experiment that would falsify it
  and run that experiment. A same-vs-different comparison, an edit-then-reverify check, a
  replay-should-be-rejected check. Put the actual measured numbers in the docs, not a
  description of what should happen.
- If you fix a visual bug that "only reproduces sometimes" or "only on some machines",
  don't just patch the symptom — identify the structural cause (a GPU compositing edge
  case, a race in a load sequence) and remove the mechanism that allows it, so you're not
  hoping the bug doesn't recur during the recording.

## 6. Docs: architecture doc + diagrams, written from the code, not from memory

- Write the architecture doc by reading the actual source files (adapters, contracts, API
  routes) and citing real function/file names — never generic pipeline prose that would be
  true of any project in this category.
- If the diagram should be animated (the user asked for "moving" or "animated" diagrams, or
  the brief rewards visual polish): author hand-written SVG with SMIL (`<animate>`,
  `<animateMotion>`) rather than reaching for a diagramming library — SVG is inspectable
  XML, renders animated inline on GitHub, and needs no runtime dependency. Match the app's
  own palette (hardcode hex values; CSS custom properties don't resolve in a standalone
  SVG file). Validate the SVG parses as well-formed XML before calling it done.
  Embed the diagram directly in the README (`![](docs/name.svg)`) so it's the first thing a
  reviewer sees, not buried in a docs subfolder.
- Write a separate SETUP.md with copy-pasteable, verified-real commands only — cross-check
  every command against the actual `package.json` scripts before writing it down. Include
  where to get every required API key/credential, with the real signup URL.
- Apply the unslop/de-AI-tone pass to every doc file, not just the UI copy.

## 7. Honest limitations section, always

Write down what's actually weak: an API that does something adjacent to what's claimed
(whole-image similarity being sold as face search, for instance), a model that isn't
state-of-the-art, a security shortcut taken for demo convenience (server-side signing
instead of a wallet connection). A judge trusts a submission more, not less, when it names
its own weak points precisely instead of staying silent.

## 8. Close the loop on submission logistics

Re-read the non-code constraints from step 0 and check them off explicitly: is there a
required recording, and does the demo order match what the brief calls the pipeline stages;
is there a submission form link; is resubmission disallowed (if so, say so out loud before
the user submits, as a final gate); does the repo need a specific license or attribution.
Give the user a short, concrete "what's left" list rather than declaring done — done means
the checklist is empty, not that the code compiles.

## Anti-patterns this skill exists to prevent

- Building the whole UI before proving the one risky integration works.
- Treating "search returns something" as equivalent to "search returns a genuine match" —
  when the brief demands a real biometric/semantic/cryptographic decision, that decision
  needs to be re-derived independently, not trusted from an upstream API's ranking.
- Writing architecture docs as generic prose that could describe any project in the genre.
- Letting parallel subagents invent their own design language instead of consuming shared
  tokens/primitives.
- Calling a visual bug fixed because it didn't reproduce once.
- Declaring "done" without a checklist of the brief's actual non-code requirements.
