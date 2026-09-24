/**
 * Slot tagging helpers — map renderer node metadata → data-slot*.
 * Ported from backend/scripts/lib/pptx-convert/slots.mjs
 */

import { flattenNodes } from "./layout";

type NodeLike = {
  nodeType?: string;
  children?: NodeLike[];
  name?: string;
  textBody?: { totalText?: string };
  size?: { w?: number; h?: number };
  position?: { x?: number; y?: number };
};

export function slotAttrsForNode(
  nodeType: string,
  ctx: {
    name?: string;
    text?: string;
    index?: number;
    fontSizeHint?: number;
  } = {},
): Record<string, string> | null {
  const name = String(ctx.name || "").trim();
  const text = String(ctx.text || "").trim();
  const idx = ctx.index ?? 0;

  if (nodeType === "picture") {
    const slug = slugSlot(name || `image-${idx + 1}`);
    const role =
      /cover|hero|背景|主视觉/i.test(name) ||
      slug === "hero-image" ||
      idx === 0
        ? "hero-image"
        : /logo|图标|icon/i.test(name) || slug === "logo"
          ? "logo"
          : "image";
    return {
      "data-slot":
        slug === "hero-image" || slug === "logo" || /^image-\d+$/.test(slug)
          ? slug
          : slugSlot(name || `image-${idx + 1}`),
      "data-slot-type": "image",
      "data-slot-role": role,
    };
  }

  if (nodeType === "chart") {
    return {
      "data-slot": slugSlot(name || `chart-${idx + 1}`),
      "data-slot-type": "chart",
      "data-slot-role": "chart",
    };
  }

  if (nodeType === "table") {
    return {
      "data-slot": slugSlot(name || `table-${idx + 1}`),
      "data-slot-type": "list",
      "data-slot-role": "table",
    };
  }

  if (nodeType === "shape" && text) {
    const role = inferTextRole(name, text, ctx.fontSizeHint);
    const slug = slugSlot(name || "");
    const known = ["title", "subtitle", "eyebrow", "body", "footer"].includes(
      slug,
    );
    const slot = known
      ? slug
      : role === "heading" || role === "page-title"
        ? "title"
        : role === "lede" || role === "subtitle"
          ? "subtitle"
          : role === "eyebrow" || role === "meta"
            ? "eyebrow"
            : slugSlot(name || `body-${idx + 1}`);
    return {
      "data-slot": slot,
      "data-slot-type": "text",
      "data-slot-role": role,
    };
  }

  return null;
}

function inferTextRole(
  name: string,
  text: string,
  fontSizeHint?: number,
): string {
  const n = String(name || "");
  if (/subtitle|副标题|lede/i.test(n)) return "lede";
  if (/(^|[_\s-])title([_\s-]|$)|标题|heading/i.test(n)) {
    return text.length <= 48 ? "page-title" : "heading";
  }
  if (/eyebrow|标签|caption|页脚|footer|date|作者/i.test(n)) return "meta";
  if (typeof fontSizeHint === "number") {
    if (fontSizeHint >= 40 && text.length <= 60) return "heading";
    if (fontSizeHint >= 28 && text.length <= 100) return "lede";
  }
  if (text.length <= 24) return "meta";
  if (text.length <= 80) return "heading";
  return "body";
}

function slugSlot(raw: string): string {
  const s = String(raw)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff_-]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return s || "slot";
}

/** Deduplicate data-slot ids within one slide HTML string by suffixing -2, -3… */
export function uniquifySlotIdsInHtml(html: string): string {
  const seen = new Map<string, number>();
  return html.replace(/\bdata-slot="([^"]+)"/g, (full, id: string) => {
    const n = (seen.get(id) || 0) + 1;
    seen.set(id, n);
    if (n === 1) return full;
    return `data-slot="${id}-${n}"`;
  });
}

export function guessSlideTitle(nodes: NodeLike[] | undefined | null): string {
  const flat = flattenNodes(nodes || []);
  const texts = flat
    .filter((n) => n.nodeType === "shape" && n.textBody?.totalText)
    .map((n) => ({
      name: n.name || "",
      text: String(n.textBody!.totalText)
        .replace(/\s+/g, " ")
        .trim(),
      area: (n.size?.w || 0) * (n.size?.h || 0),
      y: n.position?.y || 0,
    }))
    .filter((t) => t.text.length > 0);

  const titled = texts.find((t) => /title|标题/i.test(t.name));
  if (titled) return titled.text.slice(0, 80);

  texts.sort((a, b) => a.y - b.y || b.area - a.area);
  return (texts[0]?.text || "未命名页").slice(0, 80);
}
