# Examples distilled from the live catalog

## Good: concrete composition geometry (`swiss-minimal`)

```markdown
- Composition geometry: one oversized geometric plane — a full-height color
  column, a giant disc, a heavy bar — zoning the page; an asymmetric split
  with content flush to one axis; a hero numeral at architectural scale;
  a single diagonal rule or type line as the deliberate grid break.
```

Why it works: each clause is a buildable page skeleton, not “clean and modern”.

## Good: color discipline without HEX (`zine`)

```markdown
- A tightly limited spot palette (riso logic) sits on a warm paper field;
  a dominant ink pairing does most of the work…
- Color is laid as flat spot fills, not gradients; overlap and offset…

> HEX values come from confirmation `e`; this style governs the flat-spot,
> misregistered-overlay discipline — it names no colors.
```

## Good: hard bans against collapse (`nordic-calm`)

```markdown
Hard bans: dark-tech neon, dense dashboards, memphis clash, heavy shadows,
cramped icon grids.
```

## Good: illus propensity line (`pixel-art`)

```markdown
**core** — when illustration is selected, pixel sprites and blocky forms may
lead the style. … An explicit user request wins either way, and
`image_usage: none` writes no illustration rows.
```

## Bad: vague style stub

```markdown
# Visual style: modern-pro
Clean modern professional look. Use blue and gray.
## Colors
Primary #2563EB, Secondary #64748B
```

Fails: HEX recipe, missing §1–§6, no composition geometry, unusable id taste.

## Bad: rename-only variant

```markdown
# Visual style: zine-cool
Same as zine but cooler.
## 1. Shape & decoration
(copy-paste of zine.md)
```

Fails: <3 axis deltas; composition cloned.

## Variant pattern (acceptable)

```markdown
# Visual style: zine-neon-riso

Base: zine — hotter fluorescent spot inks, heavier misregistration, denser
halftone on covers; still print-flat, never digital glow.

Hard bans: dark-tech HUD grids, soft-rounded SaaS cards, photographic realism.
…
```

Must still rewrite §1 composition list with neon-riso-specific skeletons.
