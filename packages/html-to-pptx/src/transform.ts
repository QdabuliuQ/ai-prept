import { collectDom, shouldSkipTextExport } from "./collect";
import { parseImage, parseShapeAndBorders, parseSvg } from "./parse/shape";
import { parseText } from "./parse/text";
import type { DomSnapshot, SlideNode } from "./types";

/** DomSnapshot[] → SlideNode[] */
export function transformSnapshots(
  snaps: DomSnapshot[],
  slideRoot: HTMLElement,
): SlideNode[] {
  const collected = new Set(snaps.map((s) => s.el));
  const out: SlideNode[] = [];

  for (const snap of snaps) {
    if (snap.box.w < 0.5 || snap.box.h < 0.5) continue;

    const svg = parseSvg(snap, slideRoot);
    if (svg) {
      out.push(svg);
      continue;
    }

    const img = parseImage(snap, slideRoot);
    if (img) {
      out.push(img);
      continue;
    }

    out.push(...parseShapeAndBorders(snap, slideRoot));

    const skip = shouldSkipTextExport(snap.el, collected);
    out.push(...parseText(snap, slideRoot, { skip }));
  }

  return out;
}

export function collectAndTransform(slideRoot: HTMLElement): SlideNode[] {
  return transformSnapshots(collectDom(slideRoot), slideRoot);
}
