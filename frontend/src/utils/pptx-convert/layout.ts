/**
 * Rough layout classification from serialized slide nodes.
 * Ported from backend/scripts/lib/pptx-convert/layout.mjs
 */

const TITLE_HINT =
  /^(title|标题|封面|cover|subtitle|副标题|centering title)/i;

export type LayoutStats = {
  pictures: number;
  charts: number;
  tables: number;
  texts: number;
  picRatio: number;
};

export type ClassifiedLayout = {
  base: string;
  stats: LayoutStats;
};

type NodeLike = {
  nodeType?: string;
  children?: NodeLike[];
  size?: { w?: number; h?: number };
  position?: { x?: number; y?: number };
  textBody?: { totalText?: string };
  name?: string;
};

export function flattenNodes(nodes: NodeLike[] | undefined | null): NodeLike[] {
  const out: NodeLike[] = [];
  const walk = (list: NodeLike[] | undefined | null) => {
    for (const n of list || []) {
      out.push(n);
      if (Array.isArray(n.children) && n.children.length) walk(n.children);
    }
  };
  walk(nodes);
  return out;
}

export function classifyLayout({
  nodes,
  index,
  slideCount,
  slideW,
  slideH,
}: {
  nodes: NodeLike[];
  index: number;
  slideCount: number;
  slideW: number;
  slideH: number;
}): ClassifiedLayout {
  const flat = flattenNodes(nodes || []);
  const pics = flat.filter((n) => n.nodeType === "picture");
  const charts = flat.filter((n) => n.nodeType === "chart");
  const tables = flat.filter((n) => n.nodeType === "table");
  const textNodes = flat.filter(
    (n) =>
      n.nodeType === "shape" &&
      String(n.textBody?.totalText || "").trim().length > 0,
  );

  const area = Math.max(1, slideW * slideH);
  const picArea = pics.reduce(
    (s, n) => s + Math.max(0, n.size?.w || 0) * Math.max(0, n.size?.h || 0),
    0,
  );
  const picRatio = picArea / area;

  let base = "content";
  if (index === 0) {
    base = "cover";
  } else if (index === slideCount - 1 && slideCount > 2) {
    base = "closing";
  } else if (charts.length >= 1) {
    base = "chart";
  } else if (tables.length >= 1 && charts.length === 0) {
    base = "table";
  } else if (pics.length >= 3 || (pics.length >= 2 && picRatio >= 0.35)) {
    base = "gallery";
  } else if (picRatio >= 0.45 && textNodes.length <= 3) {
    base = "media";
  } else if (
    textNodes.length <= 2 &&
    textNodes.some(
      (n) =>
        TITLE_HINT.test(n.name || "") ||
        (n.textBody?.totalText || "").length < 40,
    )
  ) {
    base = "section";
  } else {
    base = "content";
  }

  return {
    base,
    stats: {
      pictures: pics.length,
      charts: charts.length,
      tables: tables.length,
      texts: textNodes.length,
      picRatio: Number(picRatio.toFixed(3)),
    },
  };
}

export function uniquifyLayouts(bases: string[]): string[] {
  const counts = new Map<string, number>();
  return bases.map((base) => {
    const n = (counts.get(base) || 0) + 1;
    counts.set(base, n);
    return n === 1 ? base : `${base}-${n}`;
  });
}

export function describeLayout(
  layout: string,
  stats: LayoutStats,
  title: string,
): string {
  const bits = [
    `粗分 layout=${layout}`,
    `图 ${stats.pictures}`,
    `图占比 ${Math.round((stats.picRatio || 0) * 100)}%`,
    `图文槽 text=${stats.texts} chart=${stats.charts} table=${stats.tables}`,
  ];
  if (title) bits.unshift(`页题「${title}」`);
  return bits.join("；");
}
