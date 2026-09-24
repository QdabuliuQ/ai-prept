---
name: style-skill
description: >-
  Author and expand PPT Master visual-style cards (visual-styles/*.md) for
  WebPPT / ppt-master. Use whenever the user asks to write a new visual style,
  expand the style catalog, summarize style-card conventions, update
  visual-styles/_index.md, or mentions style-skill / visual-style / 风格卡 /
  视觉风格. Prefer this skill over inventing ad-hoc style formats — cards must
  match the existing catalog contract so load_style_card() and Admin --style
  can consume them. New styles are standalone curated cards — do NOT create
  variants/ unless the user explicitly asks for a variant.
---

# PPT Master Visual Style Author (style-skill)

Write **visual style cards** that teach SVG layout taste for one deck-wide look.
Runtime path: `ppt-master/skills/ppt-master/references/visual-styles/<id>.md`
(loaded by WebPPT Agent via `load_style_card(id)`).

This skill is for **authoring cards in Cursor**. The generate pipeline only
reads the `.md` files — it does not load this skill at runtime.

## Before writing

1. Read [`references/catalog.md`](references/catalog.md) — existing ids / families.
2. Read 1–2 **neighbor** cards in the same family as models (taste reference only).
3. Confirm the new `id` is unused (kebab-case, `[a-z0-9-]+`, matches filename).

## Hard rules (non-negotiable)

Copied from catalog doctrine — violate none:

1. **No fixed HEX / no named palette recipe.** Describe *how* colors behave
   (dark field + luminous accent; flat spot inks; pale field + soft accent).
   Never list `#RRGGBB` swatches. Per-deck palette is invented at plan time.
2. **Style ≠ mode.** Style = how it looks. Do not decide argument structure,
   page count, or which carriers are eligible.
3. **Capability boundary.** Style governs treatment, density, weight, coherence.
   Do not forbid native SVG primitives, charts, tables, or photos as a class —
   describe how they should *feel* when used.
4. **Typography character, not font files.** Ask for grotesque / serif-sans
   pairing / monospace labels etc. Editable native text only; decorative
   lettering eligibility is separate.
5. **One style per deck** when used. Card must be coherent alone.
6. **Composition geometry is generative vocabulary**, not a finite menu —
   give 4–6 concrete page skeletons the author can remix.
7. **Paired image-rendering** is an aesthetic cousin id from
   `image-renderings/` (e.g. `flat`, `screen-print`). Never use a rendering
   name as the `visual_style` id.
8. **Illustration propensity** is exactly one of: `core` | `supportive` | `sparse`.
9. **No variants by default.** New styles are **standalone** root cards:
   `visual-styles/<id>.md` with `Label-zh` / `Group-zh` / `Family`.
   Do **not** write `Base: …`, do **not** use `<parent>-<modifier>` as the id
   pattern, and do **not** place files under `variants/` unless the user
   **explicitly** asks for a variant of an existing style.

## Required file structure

Output **one markdown file** per style. Use this skeleton exactly
(see [`references/card-template.md`](references/card-template.md)):

```markdown
# Visual style: <id>

Label-zh: <中文短名>
Group-zh: <企业 / 产品 | 编辑 / 出版 | 表现 / 印刷 | 手绘 / 笔触 | 特殊 | 扩展 / 高级>
Family: <corporate-product|editorial|expressive-print|hand-drawn|specialty|extension>

<2–4 sentence pitch: character + typical use cases. No Base: line.>

[Optional] Hard bans: <anti-patterns this style must not collapse into.>

---

## 1. Shape & decoration

- Shape language: …
- Composition geometry: … ; … ; … (4–6 concrete skeletons)
- Decoration: …
- Whitespace: …

## 2. Typography character

- …

> Families are chosen at confirmation `g`; this style asks for a <character> …
> Editable native text; decorative-lettering eligibility is separate.

## 3. Using the deck's colors

- …
- …

> HEX values come from confirmation `e`; this style only governs <discipline> —
> it names no colors.

## 4. Texture / elevation

- …

## 5. Paired image-rendering

`<rendering-id>` — <one-line why it matches>.

## 6. Illustration propensity

**<core|supportive|sparse>** — <when illustration is selected, how it participates>.
An explicit user request wins either way, and `image_usage: none` writes no
illustration rows.
```

Keep cards roughly **35–60 lines**. Prefer concrete geometry over abstract adjectives.

## Workflows

### A. New preset (default — always prefer this)

1. Pick a **Family** / **Group-zh** (corporate / editorial / expressive / hand / specialty / extension).
2. Mint a **standalone** kebab id (not `<existing>-something`).
3. Write the full card with distinct **composition geometry** vs nearest neighbors.
4. Place at `visual-styles/<id>.md` (root — **not** `variants/`).
5. Add a row to `_index.md` under the right §1.x table.
6. Rebuild catalog (see After writing).

### B. Variant of an existing style (**only if user explicitly asks**)

1. User must say they want a *variant* / 变体 of a named base.
2. Then: `variants/<id>.md`, optional `Base: <parent>`, ≥3 axes differ from parent.
3. Otherwise refuse and do workflow A instead.

Reject rename-only clones of a parent.

### C. Batch expand

1. Propose a matrix of **standalone** looks (user confirms count/coverage).
2. Write cards in batches of 5–10 into **root** `visual-styles/`; after each batch run the checklist.
3. Update `_index.md` once per batch.
4. Do **not** dump a batch into `variants/`.

### D. Repair / normalize an existing card

Bring missing §1–§6, strip HEX, strengthen composition geometry, align illus line.
If repairing a legacy `variants/` card, keep it there unless the user asks to promote it.

## Quality gate

Before finishing, run [`references/quality-checklist.md`](references/quality-checklist.md).
Fail any item → revise; do not ship.

## Anti-patterns

- Collapsing every dark style into `dark-tech` HUD (neon grids, orbit rings, particles)
  unless the id *is* dark-tech / glassmorphism / blueprint.
- “三栏白卡 / three equal cards” as default geometry for any style.
- Copy-pasting composition lists across siblings.
- Using image-rendering ids as style ids.
- Writing CSS / `@font-face` / Tailwind guidance — these cards feed **SVG** taste.
- Shipping new styles as `variants/*` or with `Base:` / 「变体」 grouping by default.

## After writing

1. Write/update `.md` under
   `ppt-master/skills/ppt-master/references/visual-styles/<id>.md`
   (**root only** for new styles)
2. Update `_index.md` curated table when status=`curated`
3. **Rebuild machine catalog** (required for Admin / CLI):

```bash
cd backend && .venv/bin/python scripts/build-visual-style-catalog.py
# or: webppt-backend styles-catalog --list
```

4. Optionally sync Admin offline fallback `src/constants/pptMasterStyles.ts`
   (live Admin reads `_catalog.json` via `/api/admin/styles`)
5. Smoke: `webppt-backend ppt-master --style <id> --pages 3 --mock -- "冒烟"`

## Progressive disclosure

- Full catalog snapshot → [`references/catalog.md`](references/catalog.md)
- Blank template → [`references/card-template.md`](references/card-template.md)
- QA checklist → [`references/quality-checklist.md`](references/quality-checklist.md)
- Good / bad excerpts → [`references/examples.md`](references/examples.md)
