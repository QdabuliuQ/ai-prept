# WebPPT image quality rubric

Judge images at their real slide crop with representative editable copy overlaid.

## Hard failures

Reject immediately when any condition is true:

- wrong aspect ratio or visible letterbox/pillarbox;
- accidental text, letters, numbers, logo, signature, or watermark;
- key subject is cropped or occupies the copy-safe region;
- severe anatomy, product, perspective, or identity error;
- visual style clearly conflicts with the deck lock;
- image has a visible boxed edge where it must blend into the slide;
- file is corrupt or its suffix does not match its encoding.

## Score out of 100

### Slide fit — 30

- Correct role and crop: 10
- Copy-safe region works with actual text: 10
- Focal hierarchy supports the slide message: 10

### Subject quality — 25

- Prompt/subject accuracy: 10
- Structural realism or illustration coherence: 10
- Appropriate detail at final size: 5

### Suite consistency — 20

- Medium, material, and lighting match anchor: 10
- Palette and recurring motif feel intentional: 5
- Repeated identity/product remains stable: 5

### Integration — 15

- Edges and background blend with slide: 5
- Image does not imitate editable UI/diagram/text: 5
- Visual density complements neighboring pages: 5

### Technical delivery — 10

- Resolution and format are suitable: 5
- No duplicate/reused unrelated asset: 3
- Stable filename and traceable prompt/reference record: 2

Accept a final at 82 or above with no hard failure. A cover or full-bleed hero should score at least 88.

When rejecting, name the first one or two decisive reasons. Long generic critique makes the next prompt drift.

