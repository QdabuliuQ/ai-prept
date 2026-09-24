# Current visual-styles catalog (snapshot)

Source of truth live files:
`ppt-master/skills/ppt-master/references/visual-styles/`

Machine index: `_catalog.json` (rebuild with `webppt-backend styles-catalog`).

**New styles:** always `visual-styles/<id>.md` (root), with `Label-zh` / `Group-zh` / `Family`.
Do **not** add new files under `variants/` unless the user explicitly asks for a variant.
Legacy variants may still exist in `variants/` — leave them unless asked to migrate.

Always re-check the directory before minting a new id — this snapshot can drift.

## Families

| Family | Ids |
|---|---|
| Corporate / product | `swiss-minimal`, `soft-rounded`, `glassmorphism`, `dark-tech`, `blueprint` |
| Editorial / publication | `editorial`, `photo-editorial`, `data-journalism`, `brutalist` |
| Expressive / print | `memphis`, `zine`, `vintage-poster`, `paper-cut` |
| Hand-drawn / brush | `sketch-notes`, `ink-notes`, `chalkboard`, `ink-wash` |
| Specialty | `pixel-art` |
| WebPPT extensions | `gallery-white`, `midnight-luxe`, `nordic-calm`, `kinetic-poster`, `dossier-archive` |

## Card index

| id | one-line | rendering | illus |
|---|---|---|---|
| `blueprint` | Engineering schematic — thin line work, isometric, annotated | `blueprint` | supportive |
| `brutalist` | Newsprint density, ruled boxes, raw structure | `screen-print` | supportive |
| `chalkboard` | Dark slate, chalk strokes, powdery pastels | `chalkboard` | core |
| `dark-tech` | Dark canvas, luminous accents, geometric precision | `digital-dashboard` | sparse |
| `data-journalism` | Dense multi-column charts, sidebars, sources | `editorial` | sparse |
| `dossier-archive` | Indexed brief, tabs/rules, document gravity | `editorial` | sparse |
| `editorial` | Magazine hierarchy, rules & columns, serif/sans | `editorial` | supportive |
| `gallery-white` | Museum quiet, one exhibit plane, sparse captions | `minimalist-swiss` | sparse |
| `glassmorphism` | Translucent panels, gradient light, floating depth | `glassmorphism` | sparse |
| `ink-notes` | Pale field, black hand-ink, sparse accent | `ink-notes` | supportive |
| `ink-wash` | Rice-paper whitespace, brush marks, seal accent | `ink-notes` | supportive |
| `kinetic-poster` | Billboard hierarchy, diagonal cut, poster energy | `screen-print` | supportive |
| `memphis` | Clashing blocks, geometric confetti, bold outlines | `flat` | core |
| `midnight-luxe` | Nocturnal luxury, thin accents (not HUD) | `flat` | sparse |
| `nordic-calm` | Pale airy field, soft large geometry | `flat` | supportive |
| `paper-cut` | Layered cut-paper, soft inter-layer shadow | `paper-cut` | core |
| `photo-editorial` | Full-bleed photo leads; captions point | `corporate-photo` | sparse |
| `pixel-art` | Strict pixel grid, blocky forms, limited palette | `pixel-art` | core |
| `sketch-notes` | Warm paper, doodle lines, soft pastels | `sketch-notes` | core |
| `soft-rounded` | Rounded cards, gentle elevation, approachable | `flat` | supportive |
| `swiss-minimal` | Grid-locked, sharp, aggressive whitespace | `minimalist-swiss` | sparse |
| `vintage-poster` | Mid-century flat blocks, halftone warmth | `vintage-poster` | core |
| `zine` | Riso misregistration, halftone, print grit | `screen-print` | core |

**Count: 23**

## Good parents for *inspiration* (not for Base:/variants/)

When inventing a **standalone** neighbor look, skim these — then write a new root id.
Do not fork them into `variants/` unless the user asks for a variant.

| Want more like… | Read first |
|---|---|
| Quiet luxury / empty | `gallery-white`, `swiss-minimal`, `nordic-calm` |
| Print grit / indie | `zine`, `brutalist`, `vintage-poster` |
| Dark but not HUD | `midnight-luxe` (not `dark-tech`) |
| Hand / teaching | `sketch-notes`, `ink-notes`, `chalkboard` |
| Data-heavy | `data-journalism`, `editorial` |
| Playful loud | `memphis`, `pixel-art` |

## Doctrine quotes (from `_index.md`)

- Styles carry **NO fixed HEX** and define no palette.
- Visual style = how it looks; mode = how you argue — resolve independently.
- `Illus.` tunes centrality after illustration is selected: core / supportive / sparse.
- Composition geometry lists are generative vocabulary, not a finite layout menu.
