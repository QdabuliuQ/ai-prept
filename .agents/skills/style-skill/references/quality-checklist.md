# Visual-style card QA checklist

Mark each item. Any fail → revise before shipping.

## Identity

- [ ] Filename `{{id}}.md` matches `# Visual style: {{id}}`
- [ ] Id is kebab-case `[a-z0-9-]+`, not an image-rendering name
- [ ] Id does not collide with existing catalog (see catalog.md)
- [ ] Pitch states character + use cases in ≤4 sentences

## Structure

- [ ] Sections §1–§6 present with exact headings from the template
- [ ] §1 has Shape language + Composition geometry + Decoration + Whitespace
- [ ] §1 Composition geometry lists **≥4** concrete skeletons (semicolons or bullets)
- [ ] §2 ends with confirmation-`g` note (character, not font files)
- [ ] §3 ends with confirmation-`e` note and **names no HEX**
- [ ] §5 names one primary paired rendering in backticks
- [ ] §6 starts with **core** / **supportive** / **sparse**

## Differentiation

- [ ] Vs nearest neighbor: ≥3 axes differ (density / corners / whitespace / type / deco / texture / illus / rendering)
- [ ] Composition list is not a copy of the parent or sibling
- [ ] Optional Hard bans prevent collapse into dark-tech HUD / 三栏白卡 when relevant

## WebPPT / SVG fitness

- [ ] Guidance is SVG-native (shapes, rules, opacity, patterns) — no CSS frameworks
- [ ] Does not forbid carriers wholesale; only treats their look
- [ ] Length roughly 35–60 lines (not a novel, not a stub)

## Index / product hooks

- [ ] `_index.md` row added/updated (family table + Character + Paired rendering + Illus.)
- [ ] Ran `python scripts/build-visual-style-catalog.py` so `_catalog.json` includes the id
- [ ] **New styles** live at root `visual-styles/<id>.md` with `Label-zh` / `Group-zh` / `Family` — **not** under `variants/`, and **no** `Base:` line (unless user explicitly requested a variant)
- [ ] Note whether Admin offline fallback `pptMasterStyles.ts` needs a curated entry
