/**
 * Resolve picture placeholder custom geometry from PPTX → CSS clip-path.
 * pptx-renderer often emits rectangular <img> even when the layout ph uses custGeom.
 */

import fs from "node:fs";
import path from "node:path";
import JSZip from "jszip";

function stripNs(xml) {
  return xml.replace(/xmlns(:\w+)?="[^"]*"/g, "");
}

function firstTag(block, tag) {
  const re = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`, "i");
  const m = block.match(re);
  return m ? m[1] : "";
}

function selfClosingBlock(block, tag) {
  const re = new RegExp(`<${tag}\\b[^>]*/>`, "i");
  const m = block.match(re);
  return m ? m[0] : "";
}

function attr(block, name) {
  const re = new RegExp(`\\b${name}="([^"]*)"`, "i");
  return block.match(re)?.[1] ?? null;
}

function parsePathPolygon(custGeomBlock) {
  const pathBlock = custGeomBlock.match(/<a:path\b[^>]*>([\s\S]*?)<\/a:path>/i)?.[0];
  if (!pathBlock) return null;
  const w = Number(attr(pathBlock, "w"));
  const h = Number(attr(pathBlock, "h"));
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return null;

  const pts = [];
  const re = /<a:pt x="(-?\d+)" y="(-?\d+)"/gi;
  let m;
  while ((m = re.exec(pathBlock))) {
    pts.push({ x: Number(m[1]), y: Number(m[2]) });
  }
  if (pts.length < 3) return null;

  const uniq = [];
  for (const p of pts) {
    const last = uniq[uniq.length - 1];
    if (last && last.x === p.x && last.y === p.y) continue;
    uniq.push(p);
  }
  if (uniq.length < 3) return null;

  const poly = uniq
    .map((p) => {
      const px = ((p.x / w) * 100).toFixed(4).replace(/\.?0+$/, "");
      const py = ((p.y / h) * 100).toFixed(4).replace(/\.?0+$/, "");
      return `${px}% ${py}%`;
    })
    .join(", ");

  const isRect =
    uniq.length === 4 &&
    uniq.some((p) => p.x === 0 && p.y === 0) &&
    uniq.some((p) => p.x === w && p.y === 0) &&
    uniq.some((p) => p.x === w && p.y === h) &&
    uniq.some((p) => p.x === 0 && p.y === h);

  if (isRect) return null;
  return `polygon(${poly})`;
}

function spPrBlock(parentBlock) {
  if (!parentBlock) return "";
  const closed = parentBlock.match(/<p:spPr\b[\s\S]*?<\/p:spPr>/i)?.[0];
  if (closed) return closed;
  return parentBlock.match(/<p:spPr\b[^>]*\/>/i)?.[0] || "";
}

function geometryFromSpPr(spPr) {
  if (!spPr) return null;
  const cust = spPr.match(/<a:custGeom>[\s\S]*?<\/a:custGeom>/i)?.[0];
  if (cust) return parsePathPolygon(cust);
  return null;
}

function slugSlot(raw) {
  const s = String(raw)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff_-]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return s || "slot";
}

function placeholderGeometry(layoutXml, phType, phIdx) {
  const blocks = layoutXml.match(/<p:sp\b[\s\S]*?<\/p:sp>/gi) || [];
  for (const block of blocks) {
    const ph = block.match(/<p:ph\b[^>]*\/?>/i)?.[0];
    if (!ph) continue;
    const type = attr(ph, "type") || "body";
    const idx = attr(ph, "idx");
    if (type !== phType) continue;
    if (idx != null && phIdx != null && idx !== String(phIdx)) continue;
    const spPr = spPrBlock(block);
    const clip = geometryFromSpPr(spPr);
    if (clip) return clip;
  }
  return null;
}

function pictureClipsFromSlideXml(slideXml, layoutXml) {
  const clips = [];
  const pics = slideXml.match(/<p:pic\b[\s\S]*?<\/p:pic>/gi) || [];
  for (const pic of pics) {
    const name = attr(pic, "name");
    if (!name) continue;
    const spPr = spPrBlock(pic);
    let clip = geometryFromSpPr(spPr);
    if (!clip) {
      const ph = pic.match(/<p:ph\b[^>]*\/?>/i)?.[0];
      const phType = ph ? attr(ph, "type") || "pic" : "pic";
      const phIdx = ph ? attr(ph, "idx") : null;
      if (layoutXml) clip = placeholderGeometry(layoutXml, phType, phIdx);
    }
    if (!clip) continue;
    clips.push({ slot: slugSlot(name), clipPath: clip, name });
  }
  return clips;
}

async function readZipText(zip, entryPath) {
  const file = zip.file(entryPath.replace(/^\//, ""));
  if (!file) return null;
  return file.async("string");
}

/**
 * @param {string} pptxPath absolute path to .pptx
 * @returns {Promise<string[][]>} clips per slide index — array of { slot, clipPath, name }
 */
export async function loadPictureClipsBySlide(pptxPath) {
  const buf = fs.readFileSync(pptxPath);
  const zip = await JSZip.loadAsync(buf);

  const presXml = await readZipText(zip, "ppt/presentation.xml");
  const presRels = await readZipText(zip, "ppt/_rels/presentation.xml.rels");
  if (!presXml || !presRels) return [];

  const ridToTarget = {};
  for (const m of presRels.matchAll(/Id="(rId\d+)"[^>]*Target="([^"]+)"/g)) {
    let target = m[2];
    if (target.startsWith("../")) target = `ppt/${target.slice(3)}`;
    else if (!target.startsWith("ppt/")) target = `ppt/${target}`;
    ridToTarget[m[1]] = target;
  }
  const slideRids = [...presXml.matchAll(/<p:sldId[^>]*r:id="(rId\d+)"/g)].map(
    (m) => m[1],
  );
  const slidePaths = slideRids
    .map((rid) => ridToTarget[rid])
    .filter((p) => p && /slides\/slide\d+\.xml$/i.test(p));

  const layoutCache = new Map();
  const out = [];

  for (const slidePath of slidePaths) {
    const slideXml = await readZipText(zip, slidePath);
    if (!slideXml) {
      out.push([]);
      continue;
    }
    const relPath = slidePath.replace("slides/", "slides/_rels/") + ".rels";
    const slideRels = await readZipText(zip, relPath);
    let layoutXml = null;
    if (slideRels) {
      const layoutTarget = slideRels.match(
        /Type="[^"]*\/slideLayout"[^>]*Target="([^"]+)"/i,
      )?.[1];
      if (layoutTarget) {
        let layoutPath = layoutTarget.replace(/^\.\.\//, "");
        if (!layoutPath.startsWith("ppt/")) layoutPath = `ppt/${layoutPath}`;
        if (!layoutCache.has(layoutPath)) {
          layoutCache.set(layoutPath, await readZipText(zip, layoutPath));
        }
        layoutXml = layoutCache.get(layoutPath);
      }
    }
    out.push(pictureClipsFromSlideXml(stripNs(slideXml), stripNs(layoutXml || "")));
  }

  return out;
}

/**
 * Apply clip-path to image slot wrappers in converted HTML.
 * @param {string} html
 * @param {{ slot: string, clipPath: string }[]} clips
 */
export function applyPictureClips(html, clips) {
  if (!clips?.length) return { html, applied: 0 };
  let applied = 0;
  let out = html;
  for (const { slot, clipPath } of clips) {
    if (!slot || !clipPath) continue;
    const slotRe = slot.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(
      `(<(?:div|img)[^>]*\\bdata-slot="${slotRe}"[^>]*)(style=")([^"]*)(")`,
      "i",
    );
    const next = out.replace(re, (full, open, q1, style, q2) => {
      if (/clip-path\s*:/i.test(style)) return full;
      applied += 1;
      const merged = `${style.replace(/;\s*$/, "")}; clip-path: ${clipPath}; -webkit-clip-path: ${clipPath}`;
      return `${open}${q1}${merged}${q2}`;
    });
    if (next !== out) {
      out = next;
      continue;
    }
    // Wrapper may carry slot on parent while img is nested
    const wrapRe = new RegExp(
      `(<div[^>]*\\bdata-slot="${slotRe}"[^>]*)(style=")([^"]*)(")`,
      "i",
    );
    out = out.replace(wrapRe, (full, open, q1, style, q2) => {
      if (/clip-path\s*:/i.test(style)) return full;
      applied += 1;
      const merged = `${style.replace(/;\s*$/, "")}; clip-path: ${clipPath}; -webkit-clip-path: ${clipPath}`;
      return `${open}${q1}${merged}${q2}`;
    });
  }
  return { html: out, applied };
}
