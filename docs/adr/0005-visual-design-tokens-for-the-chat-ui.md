# ADR-0005: Visual Design Tokens for the Chat UI (thehub.io-inspired)

* **Status:** Proposed
* **Date:** 2026-07-07
* **Related:** ADR-0004 (frontend architecture), ALE-74 (implementation)

## Context

ALE-74 scopes the React chat UI's data flow and testing but not its visual
language. thehub.io — a sibling consumer site in the same job-market domain
this project's data is sourced from — was reviewed as a style reference via a
direct screenshot (a live browser session for computed-style/devtools
inspection was attempted and unavailable; no scraping of markup or CSS was
performed). This ADR defines an original token set in the same visual mood,
not a reproduction of thehub.io's actual styles or assets, which remain their IP.

Observed pattern (from the screenshot, described at the level of layout/mood,
not literal values): a restrained lowercase wordmark with no icon; a nav that
groups links with a hairline divider rather than heavy separators; one
reserved saturated accent color spent entirely on the primary CTA, with every
other surface neutral (near-black text, grays, white/off-white bands); a
single grotesk sans typeface carrying hierarchy through weight rather than a
second display face; rounded white cards on light-gray section bands instead
of hard borders; exactly one decorative flourish (a small textured graphic),
not several.

## Decision 1: Token system lives in CSS custom properties, not inline/magic values

**Decision:** All colors, spacing, radii, and type sizes are defined once as
CSS custom properties (e.g. `src/styles/tokens.css`: `--color-accent`,
`--space-4`, etc.) and consumed everywhere else by reference — never a
hardcoded hex or px value inside a component.

**Rationale:**
- Mirrors the project's existing "isolate the thing that will change behind
  one seam" pattern (`src/api/client.ts` for the API per ADR-0004 Decision 2,
  `llm_client.base.Generator` for the LLM provider per ADR-0001,
  `HubClientConfig` for Hub client tuning) — applied here to design values
  instead of a service or provider boundary.
- The project is explicitly expected to possibly scale beyond prototype
  (the same framing ADR-0002 Decision 2 and ADR-0003 Decision 4 use to justify
  paying a small cost now). A rebrand or theme change later should be a
  single-file edit, not a repo-wide find/replace across every component.

## Decision 2: Palette — one reserved accent, everything else neutral

**Decision:**

| Token | Value | Use |
|---|---|---|
| `--color-ink` | `#1A2233` | headings, primary text |
| `--color-text-secondary` | `#5B6474` | subheads, muted body |
| `--color-surface` | `#FFFFFF` | cards, input |
| `--color-surface-alt` | `#F5F6F8` | section bands |
| `--color-border` | `#E3E5EA` | hairline dividers only |
| `--color-accent` | `#4338CA` | the single CTA/action color — send button, links, focus ring |
| `--color-accent-hover` | `#372DAE` | hover/active state |

**Rationale:** the reference layout spends its entire color budget on one
saturated accent reserved for the primary action; everything else is
near-black or gray. That discipline maps directly onto a chat UI, where the
"send" action is the one thing that should visually shout — and it keeps the
palette small enough to hold in your head, which matters more for a solo
learning project than for a large team with a design system to enforce it.

## Decision 3: Single grotesk sans, not a display/body pairing

**Decision:** `font-family: Inter, "Helvetica Neue", Arial, sans-serif` for
both headings and body; weight (700 headings / 400–500 body) does the
differentiation work instead of a second typeface.

**Rationale:** general frontend-design guidance favors a deliberate
display/body pairing by default, but where a brief pins down a direction, the
brief wins — and the reference site's own restraint (one family,
weight-driven hierarchy) *is* the pinned-down direction here. Introducing a
second display face would be adding personality the brief didn't ask for.

## Decision 4: Spacing/radius/shadow scale

**Decision:** 4px base spacing scale (`--space-1: 4px` … `--space-8: 64px`);
`--radius-sm: 6px` (inputs/buttons), `--radius-md: 12px` (cards); one soft
shadow token `--shadow-card: 0 1px 3px rgba(16,24,40,0.08)`.

**Rationale:** the reference layout uses whitespace and rounded cards instead
of hard borders as its primary separator. Codifying that as a scale — instead
of ad hoc paddings/radii per component — keeps that discipline consistent as
more views get added later, and is cheap to define once versus expensive to
retrofit across N components after the fact (the same cost asymmetry ADR-0002
Decision 2 uses for payload indexing).

## Decision 5: Application to the chat UI specifically

- Input bar → styled like a split search bar (single pill container, icon +
  placeholder, solid `--color-accent` button) instead of a generic bordered
  `<input>`.
- Message list → sits on `--color-surface-alt`; individual messages are
  `--color-surface` cards with `--shadow-card` — the same visual grammar the
  reference site uses for its category-card grid, reused rather than
  inventing a second card language.
- Sources (`ChatResponse.sources`, per ADR-0004 Decision 4) → rendered as
  small `--shadow-card` chips (title, company, score) rather than a bare
  list, for the same reason.

## Alternatives considered and rejected

- **Sampling exact hex/font values from thehub.io via devtools** — rejected:
  not attempted at all once a live browser session wasn't available, and even
  if it had been, redefining brand-identical values would raise the exact IP
  concern this ADR's Context section explicitly avoids. An original palette
  in the same mood serves the brief without that risk.
- **A display/body font pairing** — rejected per Decision 3: not what the
  reference direction calls for; would add unrequested personality.
- **Adopting a full design-system library (e.g. Tailwind's default theme,
  MUI) now** — rejected: one view, a small fixed token set; a dependency for
  theming machinery the project doesn't yet need. Revisit if a second real
  view or dark-mode requirement appears (see Revisit triggers).

## Consequences

**Positive:** one small, documented seam for all visual values, consistent
with the project's existing isolation pattern for external/volatile
dependencies; no thehub.io assets, CSS, or brand values reproduced; a
recognizable, coherent visual language available to `ALE-74` from day one
instead of default browser styling.

**Negative / accepted risks:** token values were derived from visual
inspection of a single screenshot at one viewport size, not from computed
styles across breakpoints — treat this as a starting palette to refine
in-browser during implementation, not as final, validated values. No
accessibility contrast audit has been run yet against `--color-accent` on
`--color-surface`.

## Revisit triggers

- If the app grows a second real view or a dark-mode requirement, revisit
  whether a design-system library (vs. hand-rolled tokens) is worth the
  dependency (mirrors ADR-0004's own "second real view" revisit trigger for
  Next.js/routing).
- Before shipping beyond a local demo, run a contrast check on
  `--color-accent`/`--color-ink` against WCAG AA and adjust if it fails —
  not yet verified.
- If thehub.io's own visual direction changes materially, or a closer visual
  fidelity pass becomes valuable, redo this ADR's Context section with real
  browser-based inspection (computed styles, not a screenshot) once that
  tooling is available.
