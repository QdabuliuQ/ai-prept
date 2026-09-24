/**
 * HTML post-process for browser-converted slides.
 * Ported from backend/scripts/lib/pptx-convert/postprocess.mjs — no node:fs;
 * large inline SVGs become image payloads returned to the caller.
 */

import { uniquifySlotIdsInHtml } from "./slots";

const KEEP_DATA_ATTRS = new Set([
  "data-slot",
  "data-slot-type",
  "data-slot-role",
  "data-element",
  "data-rotate",
]);

export type ConvertImagePayload = {
  path: string;
  dataBase64: string;
};

export function postprocessSlideHtml({
  html,
  slideStem,
  preserveSourceDataAttrs = false,
  svgInlineMaxChars = 2500,
}: {
  html: string;
  slideStem: string;
  preserveSourceDataAttrs?: boolean;
  svgInlineMaxChars?: number;
}): {
  html: string;
  warnings: string[];
  vectorCount: number;
  images: ConvertImagePayload[];
} {
  const warnings: string[] = [];
  let out = rewritePaths(html);
  const vectored = externalizeInlineSvgs(out, {
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

  if (/\b(?:src|href|xlink:href)=(["'])blob:/i.test(out)) {
    warnings.push(
      `${slideStem}: 仍含 blob: 图片地址（转换未落盘，预览会空图）`,
    );
  }

  return {
    html: out,
    warnings,
    vectorCount: vectored.count,
    images: vectored.images,
  };
}

export function rewritePaths(html: string): string {
  return html
    .replace(/href=(["'])([^"']*?)styles\.css\1/gi, `href=$1../theme.css$1`)
    .replace(/(src|href)=(["'])([^"']*?)\/assets\//gi, `$1=$2$3/images/`)
    .replace(/(src|href)=(["'])\.?\/?assets\//gi, `$1=$2../images/`)
    .replace(/(src|href)=(["'])\.\.\/assets\//gi, `$1=$2../images/`);
}

export function stripMiscDataAttrs(html: string): {
  html: string;
  removed: number;
} {
  let removed = 0;
  const next = html.replace(
    /\sdata-([a-zA-Z0-9:_-]+)(=(["']).*?\3|)/g,
    (full, name: string) => {
      const key = `data-${name}`.toLowerCase();
      if (KEEP_DATA_ATTRS.has(key)) return full;
      if (key.startsWith("data-slot") || key === "data-rotate") return full;
      removed += 1;
      return "";
    },
  );
  return { html: next, removed };
}

function utf8ToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function externalizeInlineSvgs(
  html: string,
  { slideStem, maxChars }: { slideStem: string; maxChars: number },
): { html: string; count: number; images: ConvertImagePayload[] } {
  const images: ConvertImagePayload[] = [];
  let count = 0;
  let idx = 0;

  const next = html.replace(/<svg\b[^>]*>[\s\S]*?<\/svg>/gi, (block) => {
    if (block.length < maxChars) return block;
    idx += 1;
    count += 1;
    const hash = simpleHash(block).slice(0, 10);
    const file = `${slideStem}-${idx}-${hash}.svg`;
    const rel = `images/vectors/${file}`;
    let svg = block;
    if (!/\sxmlns=/.test(svg)) {
      svg = svg.replace(/^<svg\b/i, '<svg xmlns="http://www.w3.org/2000/svg"');
    }
    images.push({ path: rel, dataBase64: utf8ToBase64(svg) });

    const styleMatch = block.match(/\sstyle=(["'])([\s\S]*?)\1/i);
    const style = styleMatch ? styleMatch[2].trim() : "";
    const rotateMatch = style.match(/rotate\(\s*(-?[\d.]+)\s*deg\s*\)/i);
    const rotateAttr =
      rotateMatch && Math.abs(Number(rotateMatch[1])) >= 0.5
        ? ` data-rotate="${Number(Number(rotateMatch[1]).toFixed(4))}"`
        : "";
    const styleAttr = style
      ? ` style="${style.replace(/"/g, "&quot;")}"`
      : "";
    return `<img src="../images/vectors/${file}" alt="" data-slot="vector-${idx}" data-slot-type="image" data-slot-role="vector"${rotateAttr}${styleAttr} />`;
  });

  return { html: next, count, images };
}

function simpleHash(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

export function ensureSlideShell(html: string, layout: string): string {
  let body = html.trim();
  const hasDoc = /<html[\s>]/i.test(body);

  if (!/slide-container/.test(body)) {
    if (/class=["'][^"']*\bslide\b/.test(body)) {
      body = body.replace(/class=(["'])([^"']*)\1/, (_m, q, cls: string) => {
        const parts = new Set(cls.split(/\s+/).filter(Boolean));
        parts.add("slide");
        parts.add("slide-container");
        parts.add(`layout-${layout}`);
        return `class=${q}${[...parts].join(" ")}${q}`;
      });
    }
  } else if (!new RegExp(`layout-${escapeReg(layout)}`).test(body)) {
    body = body.replace(
      /class=(["'])([^"']*\bslide-container\b[^"']*)\1/,
      (_m, q, cls: string) => {
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

function escapeReg(s: string): string {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtml(s: string): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
