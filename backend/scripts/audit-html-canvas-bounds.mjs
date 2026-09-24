#!/usr/bin/env node
/**
 * Puppeteer: measure real layout boxes vs 1920×1080 canvas,
 * plus card-internal text clipping (scroll overflow / ancestor clip).
 * Catches flex/grid overflow that static [export:bounds] misses.
 *
 * Usage:
 *   node audit-html-canvas-bounds.mjs <packageDir>
 *
 * Stdout: JSON { ok, issues: string[], pages, checked }
 * Exit 0 even when issues found (Python maps them to hard fails).
 * Exit 1 only on infrastructure failure (no chrome / bad args).
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const CANVAS_W = 1920;
const CANVAS_H = 1080;
const EDGE_MARGIN = 2;
const MAX_BOUNDS_ISSUES_PER_PAGE = 8;
const MAX_CLIP_ISSUES_PER_PAGE = 8;
const CLIP_TOL = 2;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

function resolvePuppeteer() {
  const candidates = [
    path.resolve(process.cwd(), "node_modules/puppeteer"),
    path.resolve(__dirname, "../../node_modules/puppeteer"),
    path.resolve(__dirname, "../../../node_modules/puppeteer"),
  ];
  for (const p of candidates) {
    try {
      return require(p);
    } catch {
      /* try next */
    }
  }
  throw new Error(
    "puppeteer not found. Install at project root: npm i -D puppeteer",
  );
}

function collectHtmlFiles(packageDir) {
  const pairs = [];
  for (const sub of ["slides", "pages"]) {
    const dir = path.join(packageDir, sub);
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir).filter((x) => x.endsWith(".html")).sort()) {
      pairs.push({ rel: `${sub}/${f}`, abs: path.join(dir, f) });
    }
  }
  return pairs;
}

async function auditPage(page, fileUrl) {
  await page.setViewport({ width: CANVAS_W, height: CANVAS_H, deviceScaleFactor: 1 });
  await page.goto(fileUrl, { waitUntil: "networkidle0", timeout: 30_000 });
  await page.evaluate(async () => {
    if (document.fonts?.ready) {
      try {
        await document.fonts.ready;
      } catch {
        /* ignore */
      }
    }
  });
  // Images may 404 in audit; still measure boxes.
  await new Promise((r) => setTimeout(r, 80));

  return page.evaluate(
    ({ canvasW, canvasH, edgeMargin, maxBounds, maxClips, clipTol }) => {
      const root =
        document.querySelector(".slide-container, .slide, #slide") ||
        document.body;
      if (!root) return { checked: 0, hits: [], clips: [] };

      const rootRect = root.getBoundingClientRect();
      const canvas = {
        left: rootRect.left,
        top: rootRect.top,
        right: rootRect.left + canvasW,
        bottom: rootRect.top + canvasH,
      };

      const skipTags = new Set([
        "SCRIPT",
        "STYLE",
        "LINK",
        "META",
        "BR",
        "NOSCRIPT",
        "HEAD",
        "HTML",
      ]);

      function overflowSides(r) {
        const sides = [];
        if (r.right > canvas.right + edgeMargin) {
          sides.push(`right+${Math.round(r.right - canvas.right)}`);
        }
        if (r.bottom > canvas.bottom + edgeMargin) {
          sides.push(`bottom+${Math.round(r.bottom - canvas.bottom)}`);
        }
        if (r.left < canvas.left - edgeMargin) {
          sides.push(`left+${Math.round(canvas.left - r.left)}`);
        }
        if (r.top < canvas.top - edgeMargin) {
          sides.push(`top+${Math.round(canvas.top - r.top)}`);
        }
        return sides;
      }

      function hintFor(el) {
        const slot = el.getAttribute("data-slot") || el.getAttribute("data-slot-role");
        if (slot) return `[data-slot=${slot}]`;
        const de = el.getAttribute("data-element");
        if (de) return `[data-element=${de}]`;
        const id = el.id ? `#${el.id}` : "";
        const cls =
          el.className && typeof el.className === "string"
            ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".")
            : "";
        return `${el.tagName.toLowerCase()}${id}${cls}`.slice(0, 64);
      }

      function clipsOverflow(value) {
        return (
          value === "hidden" ||
          value === "clip" ||
          value === "auto" ||
          value === "scroll"
        );
      }

      function textSample(el) {
        const t = (el.innerText || "").replace(/\s+/g, " ").trim();
        return t.slice(0, 24);
      }

      const raw = [];
      for (const el of root.querySelectorAll("*")) {
        if (el === root || skipTags.has(el.tagName)) continue;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        if (parseFloat(cs.opacity || "1") === 0) continue;

        const r = el.getBoundingClientRect();
        if (r.width < 8 || r.height < 8) continue;
        const sides = overflowSides(r);
        if (!sides.length) continue;

        const area = r.width * r.height;
        const bleedX = Math.max(
          Math.max(0, canvas.left - r.left),
          Math.max(0, r.right - canvas.right),
        );
        const bleedY = Math.max(
          Math.max(0, canvas.top - r.top),
          Math.max(0, r.bottom - canvas.bottom),
        );

        // Allow light full-bleed hero / wash (preview also clips a few px).
        const nearFull =
          r.width >= canvasW * 0.92 && r.height >= canvasH * 0.92;
        if (nearFull && bleedX <= 32 && bleedY <= 32) continue;

        const isMarked =
          el.hasAttribute("data-slot") ||
          el.hasAttribute("data-element") ||
          el.hasAttribute("data-slot-role");
        const isAbs =
          cs.position === "absolute" || cs.position === "fixed";
        // Ignore tiny decorations; keep marked / absolute / large modules.
        if (!isMarked && !isAbs && area < 12_000) continue;
        if (area < 600) continue;

        raw.push({
          el,
          left: Math.round(r.left - canvas.left),
          top: Math.round(r.top - canvas.top),
          width: Math.round(r.width),
          height: Math.round(r.height),
          sides,
          area,
          hint: hintFor(el),
        });
      }

      // Outermost only: skip if an ancestor is also overflowing in raw.
      const hits = [];
      for (const item of raw) {
        let ancestorHit = false;
        let p = item.el.parentElement;
        while (p && p !== root) {
          if (raw.some((o) => o.el === p)) {
            ancestorHit = true;
            break;
          }
          p = p.parentElement;
        }
        if (ancestorHit) continue;
        hits.push({
          hint: item.hint,
          left: item.left,
          top: item.top,
          width: item.width,
          height: item.height,
          overflow: item.sides.join(","),
        });
        if (hits.length >= maxBounds) break;
      }

      // Card-internal text clipping (not canvas overflow).
      const clipRaw = [];
      for (const el of root.querySelectorAll("*")) {
        if (el === root || skipTags.has(el.tagName)) continue;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        if (parseFloat(cs.opacity || "1") === 0) continue;

        const sample = textSample(el);
        if (sample.length < 2) continue;

        // Prefer leaf-ish text boxes: skip if a child also has substantial text.
        let childHasText = false;
        for (const child of el.children) {
          if (skipTags.has(child.tagName)) continue;
          if (textSample(child).length >= 2) {
            childHasText = true;
            break;
          }
        }
        if (
          childHasText &&
          !el.hasAttribute("data-slot") &&
          !el.hasAttribute("data-element")
        ) {
          continue;
        }

        const r = el.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) continue;

        const reasons = [];
        const selfY = el.scrollHeight > el.clientHeight + clipTol;
        const selfX = el.scrollWidth > el.clientWidth + clipTol;
        if (
          (selfY && clipsOverflow(cs.overflowY)) ||
          (selfX && clipsOverflow(cs.overflowX))
        ) {
          reasons.push(
            selfY && selfX
              ? "scroll>client"
              : selfY
                ? "scrollHeight>clientHeight"
                : "scrollWidth>clientWidth",
          );
        }

        const lineClamp = cs.webkitLineClamp;
        if (lineClamp && lineClamp !== "none" && selfY) {
          reasons.push(`line-clamp:${lineClamp}`);
        }
        if (
          cs.textOverflow === "ellipsis" &&
          (clipsOverflow(cs.overflowX) || clipsOverflow(cs.overflow)) &&
          selfX
        ) {
          reasons.push("ellipsis");
        }

        // Clipped by an overflow:hidden ancestor (card shell).
        let p = el.parentElement;
        while (p && p !== root) {
          const pcs = getComputedStyle(p);
          if (
            clipsOverflow(pcs.overflow) ||
            clipsOverflow(pcs.overflowX) ||
            clipsOverflow(pcs.overflowY)
          ) {
            const pr = p.getBoundingClientRect();
            const clipBottom = Math.max(0, r.bottom - pr.bottom);
            const clipRight = Math.max(0, r.right - pr.right);
            const clipTop = Math.max(0, pr.top - r.top);
            const clipLeft = Math.max(0, pr.left - r.left);
            if (
              clipBottom > clipTol ||
              clipRight > clipTol ||
              clipTop > clipTol ||
              clipLeft > clipTol
            ) {
              const bits = [];
              if (clipBottom > clipTol) bits.push(`bottom+${Math.round(clipBottom)}`);
              if (clipRight > clipTol) bits.push(`right+${Math.round(clipRight)}`);
              if (clipTop > clipTol) bits.push(`top+${Math.round(clipTop)}`);
              if (clipLeft > clipTol) bits.push(`left+${Math.round(clipLeft)}`);
              reasons.push(`ancestor-clip:${bits.join(",")}`);
              break;
            }
          }
          p = p.parentElement;
        }

        if (!reasons.length) continue;
        clipRaw.push({
          el,
          hint: hintFor(el),
          sample,
          reason: reasons.join(";"),
        });
      }

      const clips = [];
      for (const item of clipRaw) {
        let ancestorHit = false;
        let p = item.el.parentElement;
        while (p && p !== root) {
          if (clipRaw.some((o) => o.el === p)) {
            ancestorHit = true;
            break;
          }
          p = p.parentElement;
        }
        if (ancestorHit) continue;
        clips.push({
          hint: item.hint,
          sample: item.sample,
          reason: item.reason,
        });
        if (clips.length >= maxClips) break;
      }

      return { checked: raw.length + clipRaw.length, hits, clips };
    },
    {
      canvasW: CANVAS_W,
      canvasH: CANVAS_H,
      edgeMargin: EDGE_MARGIN,
      maxBounds: MAX_BOUNDS_ISSUES_PER_PAGE,
      maxClips: MAX_CLIP_ISSUES_PER_PAGE,
      clipTol: CLIP_TOL,
    },
  );
}

async function main() {
  const packageDir = path.resolve(process.argv[2] || "");
  if (!packageDir || !fs.existsSync(packageDir)) {
    console.error("usage: node audit-html-canvas-bounds.mjs <packageDir>");
    process.exit(1);
  }

  const files = collectHtmlFiles(packageDir);
  if (!files.length) {
    console.log(
      JSON.stringify({
        ok: true,
        issues: [],
        pages: 0,
        checked: 0,
        note: "no slides/*.html or pages/*.html",
      }),
    );
    return;
  }

  const puppeteer = resolvePuppeteer();
  const launchOpts = {
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  };
  const exe =
    process.env.PUPPETEER_EXECUTABLE_PATH ||
    process.env.CHROME_PATH ||
    process.env.GOOGLE_CHROME_BIN ||
    "";
  if (exe) launchOpts.executablePath = exe;

  let browser;
  const attempts = exe
    ? [launchOpts]
    : [
        { ...launchOpts, channel: "chrome" },
        { ...launchOpts, channel: "chrome-canary" },
        launchOpts,
      ];
  let lastErr;
  for (const opts of attempts) {
    try {
      browser = await puppeteer.launch(opts);
      break;
    } catch (err) {
      lastErr = err;
    }
  }
  if (!browser) {
    throw new Error(
      `Puppeteer 无法启动 Chrome。可设置 PUPPETEER_EXECUTABLE_PATH。最后错误: ${lastErr}`,
    );
  }

  const issues = [];
  let checked = 0;
  try {
    const page = await browser.newPage();
    page.setDefaultNavigationTimeout(30_000);
    for (const { rel, abs } of files) {
      const fileUrl = pathToFileURL(abs).href;
      try {
        const result = await auditPage(page, fileUrl);
        checked += result.checked || 0;
        for (const hit of result.hits || []) {
          issues.push(
            `[export:bounds-measured] ${rel}: ${hit.hint} ` +
              `box=(${hit.left},${hit.top},${hit.width}×${hit.height}) ` +
              `overflow=${hit.overflow}；请上移/缩小壳或减行，使全部模块落在 1920×1080 内`,
          );
        }
        for (const clip of result.clips || []) {
          issues.push(
            `[export:text-clip] ${rel}: ${clip.hint} 「${clip.sample}」 ` +
              `reason=${clip.reason}；请加高卡壳、减短正文或增大 gap，禁止靠 overflow/ellipsis 藏字`,
          );
        }
      } catch (err) {
        issues.push(
          `[export:bounds-measured] ${rel}: 测量失败 ${err.message || err}`,
        );
      }
    }
  } finally {
    await browser.close();
  }

  console.log(
    JSON.stringify({
      ok: issues.length === 0,
      issues,
      pages: files.length,
      checked,
    }),
  );
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
