# Design tokens — HHGoa fraud case console

## Subject
Not a forensics lab, not a crypto dashboard. This is an **operations console**: an analyst
triaging 20 live cases against a clock, deciding whether to rubber-stamp an AI agent's
recommendation to block someone's card. The tone is procedural and legible under pressure —
closer to a trading blotter or an NOC dashboard than a noir "hacker" screen. Explicitly not:
cream+serif+terracotta (too editorial), near-black+single-neon (too hacker-movie), broadsheet
hairline-grid (too newspaper).

## Palette

```
--slate       #10151c   ground — cool graphite-blue, not pure black (this runs in daylight, an office tool)
--panel       #171e28   card / panel surface
--panel-hi    #202a37   raised panel, hover state
--line        #2a3341   hairline border
--line-hi     #3a4658   hairline, emphasis / focus ring base
--paper       #e7ebf0   primary text — cool white, not warm bone (matches the slate ground)
--dim         #8d99ab   secondary text
--faint       #5c6a7e   tertiary text / placeholder
--signal      #2dd4bf   accent — structural teal-cyan: links, active tab, primary buttons, graph edges
--fraud       #f2578a   fraud / blocked — magenta-red, NOT pure red
--clear       #4f8ff0   cleared / legitimate — cobalt blue, NOT pure green
--warn        #e8a53d   uncertain / pending-approval — amber
```

`--fraud` (magenta-red, hue ~340) vs `--clear` (cobalt blue, hue ~215) are chosen specifically
to stay distinguishable under deuteranopia and protanopia: both sit outside the red/green
confusion axis that breaks a red/green pair, and they differ in blue channel as well as hue,
so a blue-cone deficiency (tritanopia) still separates them by warmth. `--warn` (amber) is the
third state and never doubles as either verdict color.

## Type roles

- **Display** — `Fraunces` (serif, but used sparingly, only for the verdict word on the case
  header and the SAR headline — the one moment the UI wants to sound like a real filing, not
  a dashboard widget). Not Playfair/Bodoni (the two SKILL.md explicitly flags as generic).
- **Body** — `Inter Tight` — every label, sentence, button, nav item.
- **Mono** — `IBM Plex Mono` — every number: fraud_probability, exposure, amounts, IDs, dates,
  tool_calls/tokens/latency. If it's a measured value, it's mono. This is what makes the
  probability strip and instrumentation read as *instrumented data*, not decoration.

## Layout concept

**Instrument strip + record, not a card grid.** Case list is a dense table-like list (rows,
not cards with padding to spare) — an analyst scanning 20 cases wants density, not marketing
cards. Case detail is a single scrolling record with a fixed-position header strip (verdict,
probability, exposure, status never scroll away) — like a ticket/claim record, not a hero
layout. Graph view is a contained panel within the case record, not a separate full-bleed
canvas, so the analyst never loses the case context while looking at the entity neighborhood.

## Signature interaction

**The before/after recommendation delta as a connected diff, not two side-by-side lists.**
`initial` and `final` render as two columns with a vertical spine between them. Each action
that changed animates a connecting line from its `initial` slot to its `final` slot through
the `evidence_requests` node sitting on the spine — literally drawing the causal link evidence
→ new recommendation. Removed actions fade and strike through in place; added actions slide in
from the spine with a spring (motion `layout` + `AnimatePresence`); unchanged actions stay
static with no motion at all, so the eye is drawn only to what evidence actually changed.
`useReducedMotion()` swaps the spring/slide for an instant opacity crossfade.

## Fraud probability treatment

Never a bare "0.72". A horizontal calibrated bar (0–1 scale, tick marks at .15/.30/.70/.85 —
the policy's own thresholds from RESEARCH.md §7.2) with the value as a mono label capped at
2 decimals, and a text band (`uncertain` / `likely fraud` / `likely legitimate`) so the bar
never implies more precision than a float carries. Same component in the case list (compact)
and case detail (full width with tick labels).
