# Image direction manifest

Use this JSON shape when a persistent plan is useful:

```json
{
  "schema_version": "1.0",
  "template_id": "deck-id",
  "visual_style": "style-card-id",
  "palette": {
    "bg": "#RRGGBB",
    "text": "#RRGGBB",
    "accent": "#RRGGBB"
  },
  "visual_lock": {
    "medium": "editorial photography",
    "lighting": "soft side light from upper left",
    "color": "warm neutral field with sparse accent red",
    "material": "natural paper grain and real surface texture",
    "camera_or_line": "35mm environmental framing, restrained depth of field",
    "motif": "one diagonal beam recurring subtly",
    "identity": "same subject/product proportions across sibling images",
    "avoid": ["embedded text", "logo", "UI chrome", "letterbox"]
  },
  "anchor_reference": {
    "file": "images/01_cover.png",
    "role": "style and identity reference"
  },
  "assets": [
    {
      "page": 1,
      "slide_file": "01_cover.svg",
      "need_image": true,
      "image_file": "01_cover.png",
      "image_role": "hero",
      "image_aspect": "16:9",
      "image_copy_safe": "left 42%, low visual detail",
      "image_focal": "right-center",
      "image_hint": "concrete English subject/scene brief",
      "draft_resolution": "1K",
      "final_resolution": "2K",
      "references": [],
      "prompt": "final subject-first prompt",
      "status": "planned"
    }
  ]
}
```

Allowed `status` values: `planned`, `drafted`, `selected`, `final`, `rejected`.

The following fields map directly into `plan.json` and must not be renamed:

- `need_image`
- `image_file`
- `image_role`
- `image_aspect`
- `image_hint`
- `image_copy_safe`
- `image_focal`

Keep the manifest concise. Do not embed base64 images, full SVG, full slide HTML, or model logs.
