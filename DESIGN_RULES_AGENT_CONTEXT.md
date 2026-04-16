# Design Rules Agent Context

Use these rules as shared design guidance when creating style decisions for landing pages.

## 1) App-Specific Before Category-Specific

- Start from app-level signals first (name, short description, screenshot feel, review language).
- Category defaults are fallback, not the first choice.

## 2) Vibe Fingerprint

Derive and encode:
- `brand_tone`
- `content_energy`
- `visual_bias`
- `ui_mood`
- `palette_hint`

Keep it compact and deterministic.

## 3) Palette and Contrast

- Keep text contrast readable on both background and cards.
- Avoid near-identical background and surface values.
- Use one primary, one accent, and one neutral secondary consistently.

## 4) Section Rhythm

- `benefit-first` for utility and clarity-heavy apps.
- `proof-first` for trust-sensitive apps.
- `visual-first` for media-forward apps.

## 5) Visual Polish

- Strong hierarchy: clear hero, clear section heads, clear CTA.
- Clean spacing rhythm and consistent card depth.
- Screenshot framing should look intentional, not cramped.

## 6) Category Heuristics

- Music: expressive, immersive, visual-forward.
- Gaming: high-energy, contrast-rich, urgency-forward.
- Finance: trust-first, calm rhythm, proof-heavy.
- Productivity: concise, practical, low-noise.
- Default: balanced and readable.

## 7) Anti-Patterns

- Do not reuse identical style choices for all apps in a category.
- Do not generate low-contrast palettes.
- Do not use conflicting choices (for example, minimal hero + overloaded visual sections).
