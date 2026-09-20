/**
 * HTML post-process for converted slides:
 * - path rewrite (styles.css → theme.css, assets → images/)
 * - strip renderer misc data-* (keep data-slot*)
 * - externalize long inline SVGs → images/vectors/
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { uniquifySlotIdsInHtml } from "./slots.mjs";

const KEEP_DATA_ATTRS = new Set([
  "data-slot",
  "data-slot-type",
  "data-slot-role",
  "data-element",
  "data-rotate",
]);

/**
 * @param {object} opts
 * @param {string} opts.html
 * @param {string} opts.imagesDir absolute path to package images/
 * @param {string} opts.slideStem e.g. cover / content-2
 * @param {boolean} [opts.preserveSourceDataAttrs=false]
 * @param {number} [opts.svgInlineMaxChars=2500]
 * @returns {{ html: string, warnings: string[], vectorCount: number }}
 */
export function postprocessSlideHtml({
  html,
  imagesDir,
  slideStem,
  preserveSourceDataAttrs = false,
  svgInlineMaxChars = 2500,
}) {
  const warnings = [];
  let out = html;

  out = rewritePaths(out);
  const vectored = externalizeInlineSvgs(out, {
    imagesDir,
    slideStem,
    maxChars: svgInlineMaxChars,
  });
  out = vectored.html;
  if (vectored.count) {
    warnings.push(
      `${slideStem}: 外置 inline SVG ×${vectored.count} → images/vectors/`,
    );
  }

  if (!preserveSourceDataAttrs) {
    const stripped = stripMiscDataAttrs(out);
    out = stripped.html;
    if (stripped.removed) {
      warnings.push(
        `${slideStem}: 移除渲染器杂 data-* ×${stripped.removed}`,
      );
    }
  }

  out = uniquifySlotIdsInHtml(out);
  out = ensureSlideShell(out, slideStem);
  return { html: out, warnings, vectorCount: vectored.count };
}

export function rewritePaths(html) {
  return html
    .replace(/href=(["'])([^"']*?)styles\.css\1/gi, `href=$1../theme.css$1`)
    .replace(/(src|href)=(["'])([^"']*?)\/assets\//gi, `$1=$2$3/images/`)
    .replace(/(src|href)=(["'])\.?\/?assets\//gi, `$1=$2../images/`)
    .replace(/(src|href)=(["'])\.\.\/assets\//gi, `$1=$2../images/`);
}

/**
 * Remove data-* except slot / element / rotate (and optionally svg xmlns leftovers stay).
 */
export function stripMiscDataAttrs(html) {
  let removed = 0;
  const next = html.replace(
    /\sdata-([a-zA-Z0-9:_-]+)(=(["']).*?\3|)/g,
    (full, name) => {
      const key = `data-${name}`.toLowerCase();
      if (KEEP_DATA_ATTRS.has(key)) return full;
      // keep data-slot* prefix variants + data-rotate (WebPPT preview/export)
      if (key.startsWith("data-slot") || key === "data-rotate") return full;
      removed += 1;
      return "";
    },
  );
  return { html: next, removed };
}

/**
 * Replace large inline <svg>...</svg> with <img src="../images/vectors/...">
 */
export function externalizeInlineSvgs(html, { imagesDir, slideStem, maxChars }) {
  const vectorsDir = path.join(imagesDir, "vectors");
  let count = 0;
  let idx = 0;

  const next = html.replace(
    /<svg\b[^>]*>[\s\S]*?<\/svg>/gi,
    (block) => {
      if (block.length < maxChars) return block;
      if (!fs.existsSync(vectorsDir)) {
        fs.mkdirSync(vectorsDir, { recursive: true });
      }
      idx += 1;
      count += 1;
      const hash = crypto
        .createHash("sha1")
        .update(block)
        .digest("hex")
        .slice(0, 10);
      const file = `${slideStem}-${idx}-${hash}.svg`;
      const abs = path.join(vectorsDir, file);
      // ensure xmlns for standalone file
      let svg = block;
      if (!/\sxmlns=/.test(svg)) {
        svg = svg.replace(
          /^<svg\b/i,
          '<svg xmlns="http://www.w3.org/2000/svg"',
        );
      }
      fs.writeFileSync(abs, svg, "utf8");

      // Preserve SVG layout/transform styles on the replacement <img>
      const styleMatch = block.match(/\sstyle=(["'])([\s\S]*?)\1/i);
      const style = styleMatch ? styleMatch[2].trim() : "";
      const rotateMatch = style.match(/rotate\(\s*(-?[\d.]+)\s*deg\s*\)/i);
      const rotateAttr =
        rotateMatch && Math.abs(Number(rotateMatch[1])) >= 0.5
          ? ` data-rotate="${Number(Number(rotateMatch[1]).toFixed(4))}"`
          : "";
      const styleAttr = style ? ` style="${style.replace(/"/g, "&quot;")}"` : "";
      return `<img src="../images/vectors/${file}" alt="" data-slot="vector-${idx}" data-slot-type="image" data-slot-role="vector"${rotateAttr}${styleAttr} />`;
    },
  );

  return { html: next, count };
}

/**
 * Ensure document has theme link + slide/slide-container/layout-* classes.
 */
export function ensureSlideShell(html, layout) {
  let body = html.trim();
  const hasDoc = /<html[\s>]/i.test(body);

  // Promote renderer root into slide-container
  if (!/slide-container/.test(body)) {
    // If we already wrapped with class="slide …", skip
    if (/class=["'][^"']*\bslide\b/.test(body)) {
      body = body.replace(
        /class=(["'])([^"']*)\1/,
        (_m, q, cls) => {
          const parts = new Set(cls.split(/\s+/).filter(Boolean));
          parts.add("slide");
          parts.add("slide-container");
          parts.add(`layout-${layout}`);
          return `class=${q}${[...parts].join(" ")}${q}`;
        },
      );
    }
  } else if (!new RegExp(`layout-${escapeReg(layout)}`).test(body)) {
    body = body.replace(
      /class=(["'])([^"']*\bslide-container\b[^"']*)\1/,
      (_m, q, cls) => {
        const cleaned = cls
          .split(/\s+/)
          .filter((c) => c && !/^layout-/.test(c));
        cleaned.push(`layout-${layout}`);
        return `class=${q}${cleaned.join(" ")}${q}`;
      },
    );
  }

  if (hasDoc) {
    if (!/href=["']\.\.\/theme\.css["']/.test(body)) {
      body = body.replace(
        /<\/head>/i,
        `  <link rel="stylesheet" href="../theme.css" />\n</head>`,
      );
      if (!/<\/head>/i.test(body)) {
        body = body.replace(
          /<head([^>]*)>/i,
          `<head$1>\n  <link rel="stylesheet" href="../theme.css" />`,
        );
      }
    }
    return body;
  }

  return `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(layout)}</title>
  <link rel="stylesheet" href="../theme.css" />
</head>
<body>
${body}
</body>
</html>
`;
}

function escapeReg(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Minimal theme for converted packages */
export function buildThemeCss({ bg = "#ffffff", text = "#111111", accent = "#2563eb" } = {}) {
  return `/* Converted from PPTX — tokens only; page geometry stays in slides/*.html */
:root {
  --color-bg: ${bg};
  --color-surface: ${bg};
  --color-text: ${text};
  --color-muted: #5c5c5c;
  --color-accent: ${accent};
  --color-border: #e5e5e5;
  --color-primary: ${accent};
  --font-sans: "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  --chart-1: ${accent};
  --chart-2: #0d9488;
  --chart-3: #d97706;
  --chart-4: #dc2626;
  --chart-5: #7c3aed;
}

html, body, .slide, .slide-container {
  width: 1920px;
  height: 1080px;
  margin: 0;
  padding: 0;
  box-sizing: border-box;
  overflow: hidden;
}

body {
  background: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-sans);
}

.slide-container img {
  max-width: none;
}

.slide-container svg {
  overflow: visible;
}

/*
 * Renderer often appends decorative SVG frames after text in DOM order, so they
 * paint on top and steal hit-testing. Keep decorations interactive (draggable),
 * but raise text frames above pure SVG-only siblings.
 */
.slide-container > div:has(> svg:only-child),
.pptx-slide-root > div:has(> svg:only-child) {
  z-index: 0;
}
.slide-container > div:has(span),
.slide-container > [data-slot-type="text"],
.pptx-slide-root > div:has(span),
.pptx-slide-root > [data-slot-type="text"] {
  z-index: 2;
}
`;
}
