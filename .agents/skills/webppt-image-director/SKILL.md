---
name: webppt-image-director
description: Direct and generate coherent Nano Banana imagery for WebPPT template decks. Use this skill whenever a WebPPT/PPT Master task needs AI images, image_hint/image_role/image_aspect planning, a consistent image suite, better Nano Banana quality, slide-safe composition, reference-image locking, candidate selection, or image-generation QA. Also use when generated slide images look generic, inconsistent, boxed, badly cropped, cover text has no safe space, or the user asks to improve WebPPT image quality. Do not use for SVG decorations, editable diagrams, charts, or icons that should remain native slide objects.
compatibility: WebPPT repository; works with the installed nano-banana skill and backend/image/generate.py conventions.
---

# WebPPT Image Director

Create an image suite that behaves like one commissioned art direction system, not a set of unrelated generations. Preserve slide editability by keeping titles, labels, data, logos, and diagrams out of raster images.

## Use the existing WebPPT contract

Read the relevant `plan.json`, `plan_lock.json`, template metadata, visual style card, or slide brief before prompting. Keep these existing fields authoritative:

- `need_image`: whether the page genuinely needs a raster visual.
- `image_role`: `background | hero | panel | illustration`.
- `image_aspect`: the actual slot ratio, not a generic default.
- `image_hint`: the page-specific subject and scene.
- `image_file`: the stable local filename.
- `image_copy_safe`: the low-detail region reserved for editable slide copy.
- `image_focal`: the intended subject region inside the generated canvas.

Do not add images to every page. Data, comparison, agenda, and dense explanatory pages often work better with editable text and native shapes.

When generation is requested, follow the installed `nano-banana` skill for model-specific prompting and reference-image behavior. For WebPPT pipeline runs, preserve the repository's configured `IMAGE_API_*` provider (including its OpenAI-compatible `nano-banana-fast` route); use the standalone Nano Banana CLI only for one-off assets or when the user explicitly requests it. This skill owns art direction, suite consistency, slide fit, selection, and QA.

## Workflow

### 1. Establish one deck-level visual lock

Before writing page prompts, define one compact lock containing:

- medium: photography, editorial illustration, paper collage, ink wash, 3D, or another single family;
- lighting direction and contrast;
- color relationship to the deck palette;
- material and surface character;
- camera/lens or illustration treatment;
- recurring motif;
- human/character identity rules when relevant;
- explicit exclusions.

Use at most two compatible style anchors. Avoid mixtures such as “minimal + ornate + retro + cyberpunk.” Reuse the lock verbatim across sibling prompts so model interpretation does not drift.

### 2. Direct each slot, not just each subject

Derive composition from the slide geometry and `image_role`:

- `background`: full bleed, edge-to-edge, low-detail text-safe zone, no frame or letterbox.
- `hero`: one dominant subject, strong silhouette, deliberate negative space for slide copy.
- `panel`: composition must survive the exact crop; keep the focal subject inside the panel-safe center.
- `illustration`: explain one concept visually without embedding labels or diagram text.

If slide copy sits left, place the focal subject right. If copy sits right, place it left. For centered copy, create a quiet central or upper field and move detail toward the edges. Do not invent side placement when slide geometry does not support it.

Use the actual `image_aspect`. A circular crop starts from `1:1`; a vertical rail uses `3:4`, `2:3`, or `9:16`; a full-bleed slide uses `16:9`.

### 3. Write subject-first Nano Banana prompts

Use this order:

1. subject and action;
2. scene and spatial relationship;
3. exact composition and negative-space instruction;
4. deck-level visual lock;
5. lighting, palette, and material;
6. output constraints and avoid list.

Keep prompts concrete. Replace abstract phrases such as “innovation energy” with visible subjects, materials, environments, and actions.

Always include for slide imagery:

```text
No text, letters, numbers, logo, watermark, UI chrome, border, frame, collage grid, letterbox, or pillarbox. Fill the requested aspect ratio edge-to-edge. Keep the designated copy-safe region visually quiet.
```

Do not ask Nano Banana to draw charts, timelines, process arrows, tables, or slide typography. Those elements must remain editable.

### 4. Generate drafts economically

For each distinct visual family:

1. Generate 2–4 low-cost candidates at 512 or 1K.
2. Compare them against the slide slot and the rubric in [quality-rubric.md](references/quality-rubric.md).
3. Select one anchor image for the deck.
4. Use the anchor as the first reference for sibling pages when subject/style continuity matters.
5. Generate only accepted finals at 2K. Use 4K only for a true full-bleed hero that benefits from it.

Prefer reference locking over repeatedly adding adjectives. For recurring people, products, mascots, or environments, carry the accepted reference into every later generation and explicitly state what must remain unchanged.

### 5. Iterate with one change at a time

When a candidate fails, keep the deck lock and successful properties unchanged. Revise only the failed dimension, for example:

- move subject farther right;
- enlarge negative space;
- reduce background detail;
- preserve identity more closely;
- remove accidental text;
- correct the crop for `3:4`.

Do not rewrite the entire prompt after a local failure; broad rewrites cause suite drift.

### 6. Validate before accepting

Reject any candidate with a hard failure from [quality-rubric.md](references/quality-rubric.md). Inspect the final at actual slide crop, not only as a standalone image.

Verify:

- exact role and aspect;
- subject stays inside crop;
- copy-safe area remains usable;
- no embedded text/logo/watermark;
- no visible rectangular edge against the slide;
- palette and material match sibling assets;
- no repeated image used on unrelated slides;
- file suffix matches real image encoding.

Run the repository's existing image and slide QA after materialization. The image suite is complete only when it integrates into the rendered slide without obscuring editable content.

## Output

When asked to plan images, return or save a manifest matching [image-direction-schema.md](references/image-direction-schema.md). Keep `image_hint`, `image_role`, `image_aspect`, and `image_file` directly transferable into the existing PPT Master plan.

When asked to generate assets, save accepted files under the template/project `images/` directory without overwriting unrelated files. Report:

- accepted image paths;
- final per-page prompts;
- reference images used and their roles;
- draft/final resolution;
- rejected candidates and concise reasons;
- any remaining crop or integration risk.

## Failure patterns

- A different art style on every page: deck lock was not reused verbatim.
- Generic stock imagery: subject and action were abstract or underspecified.
- Title competes with image: no explicit copy-safe region was directed.
- Visible image rectangle: background/color integration was ignored.
- Repeated regenerated characters: no accepted identity reference was carried forward.
- High cost without better output: finals were generated before candidate selection.
- Attractive image but weak slide: standalone aesthetics were judged without the real crop and copy overlay.
