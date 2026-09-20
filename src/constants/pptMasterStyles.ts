/**
 * Fallback PPT Master visual-style options when `_catalog.json` is unavailable.
 * Prefer live catalog via GET /api/admin/styles (built from ppt-master cards).
 *
 * Rebuild catalog:
 *   cd agent && .venv/bin/python scripts/build-visual-style-catalog.py
 */

export type PptMasterVisualStyleOption = {
  value: string;
  label: string;
  group: string;
};

export type PptMasterStyleSelectGroup = {
  label: string;
  options: { value: string; label: string }[];
};

export const PPT_MASTER_VISUAL_STYLES: PptMasterVisualStyleOption[] = [
  { value: "swiss-minimal", label: "swiss-minimal 瑞士极简", group: "企业 / 产品" },
  { value: "soft-rounded", label: "soft-rounded 柔和圆角", group: "企业 / 产品" },
  { value: "glassmorphism", label: "glassmorphism 玻璃拟态", group: "企业 / 产品" },
  { value: "dark-tech", label: "dark-tech 暗色科技", group: "企业 / 产品" },
  { value: "blueprint", label: "blueprint 蓝图线稿", group: "企业 / 产品" },
  { value: "editorial", label: "editorial 编辑杂志", group: "编辑 / 出版" },
  { value: "photo-editorial", label: "photo-editorial 摄影编辑", group: "编辑 / 出版" },
  { value: "data-journalism", label: "data-journalism 数据新闻", group: "编辑 / 出版" },
  { value: "brutalist", label: "brutalist 粗野主义", group: "编辑 / 出版" },
  { value: "memphis", label: "memphis 孟菲斯", group: "表现 / 印刷" },
  { value: "zine", label: "zine 小誌印刷", group: "表现 / 印刷" },
  { value: "vintage-poster", label: "vintage-poster 复古海报", group: "表现 / 印刷" },
  { value: "paper-cut", label: "paper-cut 剪纸层叠", group: "表现 / 印刷" },
  { value: "sketch-notes", label: "sketch-notes 手绘笔记", group: "手绘 / 笔触" },
  { value: "ink-notes", label: "ink-notes 墨线笔记", group: "手绘 / 笔触" },
  { value: "chalkboard", label: "chalkboard 黑板粉笔", group: "手绘 / 笔触" },
  { value: "ink-wash", label: "ink-wash 水墨留白", group: "手绘 / 笔触" },
  { value: "pixel-art", label: "pixel-art 像素风", group: "特殊" },
  { value: "gallery-white", label: "gallery-white 画廊留白", group: "扩展 / 高级" },
  { value: "midnight-luxe", label: "midnight-luxe 午夜奢静", group: "扩展 / 高级" },
  { value: "nordic-calm", label: "nordic-calm 北欧静气", group: "扩展 / 高级" },
  { value: "kinetic-poster", label: "kinetic-poster 动能海报", group: "扩展 / 高级" },
  { value: "dossier-archive", label: "dossier-archive 档案简报", group: "扩展 / 高级" },
];

export const PPT_MASTER_VISUAL_STYLE_IDS = PPT_MASTER_VISUAL_STYLES.map(
  (s) => s.value,
);

/** Ant Design Select options grouped by category (offline fallback). */
export function pptMasterVisualStyleSelectOptions(): PptMasterStyleSelectGroup[] {
  const groups = new Map<string, { value: string; label: string }[]>();
  for (const s of PPT_MASTER_VISUAL_STYLES) {
    const list = groups.get(s.group) || [];
    list.push({ value: s.value, label: s.label });
    groups.set(s.group, list);
  }
  return Array.from(groups.entries()).map(([label, options]) => ({
    label,
    options,
  }));
}
