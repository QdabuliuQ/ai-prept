import PptxGenJS from "pptxgenjs";
import type { SlideConfig } from "./config";
import type { PreparedSlide, ShapeNode, SlideNode } from "./types";

function shapeType(pptx: PptxGenJS, name: ShapeNode["shapeName"]) {
  if (name === "ellipse") return pptx.ShapeType.ellipse;
  if (name === "roundRect") return pptx.ShapeType.roundRect;
  if (name === "triangle") return pptx.ShapeType.triangle;
  if (name === "rtTriangle") return pptx.ShapeType.rtTriangle;
  return pptx.ShapeType.rect;
}

function drawNode(slide: PptxGenJS.Slide, pptx: PptxGenJS, node: SlideNode) {
  if (node.kind === "shape") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const opts: any = {
      x: node.x,
      y: node.y,
      w: node.w,
      h: node.h,
    };
    if (node.rotate != null && Math.abs(node.rotate) >= 0.5) {
      opts.rotate = node.rotate;
    }
    if (node.fill.type === "solid") {
      opts.fill = {
        type: "solid",
        color: node.fill.color,
        transparency: node.fill.transparency,
      };
    } else {
      opts.fill = { type: "none" };
    }
    if (node.rectRadius != null) opts.rectRadius = node.rectRadius;
    if (node.line) {
      opts.line = {
        color: node.line.color,
        width: node.line.widthPt,
        transparency: node.line.transparency,
        dashType:
          node.line.dashType === "solid" ? undefined : node.line.dashType,
      };
    } else {
      opts.line = { color: "FFFFFF", width: 0, transparency: 100 };
    }
    if (node.shadow) {
      opts.shadow = {
        type: "outer",
        color: node.shadow.color,
        blur: node.shadow.blurPt,
        offset: node.shadow.offsetPt,
        angle: node.shadow.angle,
        opacity: node.shadow.opacity ?? 0.35,
      };
    }
    slide.addShape(shapeType(pptx, node.shapeName), opts);
    return;
  }

  if (node.kind === "borderLine") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const opts: any = {
      x: node.x,
      y: node.y,
      w: Math.max(node.w, 0.01),
      h: Math.max(node.h, 0.01),
      fill: { type: "solid", color: node.color },
      line: { color: node.color, width: 0, transparency: 100 },
    };
    slide.addShape(pptx.ShapeType.rect, opts);
    return;
  }

  if (node.kind === "image" && node.dataUrl) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const opts: any = {
      data: node.dataUrl,
      x: node.x,
      y: node.y,
      w: node.w,
      h: node.h,
    };
    if (node.rotate != null && Math.abs(node.rotate) >= 0.5) {
      opts.rotate = node.rotate;
    }
    const sizing = node.sizing || "stretch";
    const intrinsic = node.intrinsicSize;
    if (
      (sizing === "cover" || sizing === "contain") &&
      intrinsic &&
      intrinsic.width > 0 &&
      intrinsic.height > 0
    ) {
      // PptxGenJS takes initial w/h as the *source* aspect ratio, then applies
      // sizing.{w,h} as the target box. Pass normalized intrinsic ratio here
      // or cover/contain silently becomes stretch.
      const maxDim = Math.max(intrinsic.width, intrinsic.height);
      opts.w = intrinsic.width / maxDim;
      opts.h = intrinsic.height / maxDim;
      opts.sizing = { type: sizing, w: node.w, h: node.h };
    }
    slide.addImage(opts);
    return;
  }

  if (node.kind === "text") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const opts: any = {
      x: node.x,
      y: node.y,
      w: node.w,
      h: node.h,
      color: node.color,
      transparency: node.transparency,
      outline: node.outline
        ? {
            size: node.outline.size,
            color: {
              color: node.outline.color,
              transparency: node.outline.transparency,
            },
          }
        : undefined,
      fontSize: node.fontSizePt,
      fontFace: node.fontFace,
      bold: node.bold,
      italic: node.italic,
      align: node.align,
      valign: node.valign,
      wrap: node.wrap === true,
      margin: node.margin ?? 0,
      fit: "none",
    };
    if (node.lineSpacingMultiple != null) {
      opts.lineSpacingMultiple = node.lineSpacingMultiple;
    } else if (node.lineSpacingPt != null) {
      opts.lineSpacing = node.lineSpacingPt;
    }
    if (node.charSpacingPt != null) opts.charSpacing = node.charSpacingPt;
    if (node.vert && node.vert !== "horz") {
      opts.vert = node.vert;
    } else if (node.rotate != null && Math.abs(node.rotate) >= 0.5) {
      opts.rotate = node.rotate;
    }

    if (node.runs?.length) {
      const payload = node.runs.map((run) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const runOpts: any = {};
        if (run.color != null) runOpts.color = run.color;
        if (run.transparency != null) runOpts.transparency = run.transparency;
        if (run.outline != null) {
          runOpts.outline = {
            size: run.outline.size,
            color: {
              color: run.outline.color,
              transparency: run.outline.transparency,
            },
          };
        }
        if (run.fontSizePt != null) runOpts.fontSize = run.fontSizePt;
        if (run.fontFace != null) runOpts.fontFace = run.fontFace;
        if (run.bold != null) runOpts.bold = run.bold;
        if (run.italic != null) runOpts.italic = run.italic;
        if (run.charSpacingPt != null) runOpts.charSpacing = run.charSpacingPt;
        if (run.breakLine) runOpts.breakLine = true;
        return Object.keys(runOpts).length
          ? { text: run.text, options: runOpts }
          : { text: run.text };
      });
      slide.addText(payload, opts);
    } else {
      slide.addText(node.text, opts);
    }
  }
}

export async function packagePresentation(
  slides: PreparedSlide[],
  config: SlideConfig
): Promise<Blob> {
  const pptx = new PptxGenJS();
  pptx.defineLayout({
    name: "HTML_TO_PPTX",
    width: config.slideWidthIn,
    height: config.slideHeightIn,
  });
  pptx.layout = "HTML_TO_PPTX";

  for (const prepared of slides) {
    const slide = pptx.addSlide();
    if (prepared.backgroundColor) {
      slide.background = { color: prepared.backgroundColor };
    }
    const sorted = [...prepared.nodes].sort((a, b) => a.z - b.z);
    for (const node of sorted) drawNode(slide, pptx, node);
  }

  const out = await pptx.write({ outputType: "blob" });
  return out as Blob;
}
