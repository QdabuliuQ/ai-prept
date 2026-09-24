import type { ThemeToken } from "./types";

export type ThemePreset = ThemeToken & { id: string };

const FONT = "Noto Serif SC";

function t(
  id: string,
  templateName: string,
  category: string,
  primary: string,
  secondary: string,
  background: string,
  tags: string[] = []
): ThemePreset {
  return {
    id,
    templateName,
    category,
    tags,
    primary,
    secondary,
    background,
    textOnLight: "#1A1A1A",
    textOnDark: "#F5F5F5",
    fontTitle: FONT,
    fontBody: FONT,
  };
}

/** 30 套可商用预设配色 */
export const THEME_PRESETS: ThemePreset[] = [
  t("navy-gold", "深蓝金", "商务", "#1B3A4B", "#C4A574", "#F7F8FA", ["克制", "路演"]),
  t("ink-blue", "墨蓝", "科技", "#0F2C59", "#3B82F6", "#F5F7FB", ["冷静", "专业"]),
  t("forest", "松绿", "自然", "#1F4D3A", "#7C9A82", "#F4F7F4", ["沉稳", "生态"]),
  t("burgundy", "酒红", "品牌", "#6B1E2A", "#B85C6A", "#F8F4F3", ["质感"]),
  t("slate", "岩灰", "商务", "#2F3A45", "#7A8896", "#F6F7F8", ["中性"]),
  t("teal", "青绿", "科技", "#0F4C5C", "#2A9D8F", "#F3F8F7", ["清爽"]),
  t("copper", "铜棕", "人文", "#5C3A21", "#C0894F", "#F8F4EE", ["温暖"]),
  t("midnight", "午夜", "科技", "#111827", "#60A5FA", "#F3F4F6", ["对比"]),
  t("olive", "橄榄", "自然", "#3F4A2E", "#A3A67A", "#F6F6F0", ["柔和"]),
  t("crimson", "朱红", "品牌", "#8B1E1E", "#E07A5F", "#F9F4F2", ["醒目"]),
  t("indigo", "靛蓝", "科技", "#1E1B4B", "#6366F1", "#F5F5FF", ["现代"]),
  t("sea", "海蓝", "商务", "#0B3D5C", "#1D7A9C", "#F2F7FA", ["可靠"]),
  t("charcoal-amber", "炭琥珀", "路演", "#1C1917", "#D97706", "#FAF7F2", ["锋利"]),
  t("sage", "鼠尾草", "生活", "#3E5C4E", "#8FAE96", "#F5F8F5", ["轻盈"]),
  t("plum", "葡紫", "品牌", "#4A1942", "#9B6B9E", "#F8F4F8", ["独特"]),
  t("steel", "钢青", "金融", "#243B4A", "#5C7C8A", "#F4F6F8", ["稳重"]),
  t("emerald", "祖母绿", "科技", "#064E3B", "#10B981", "#F0FDF7", ["活力"]),
  t("brick", "陶土", "人文", "#7C2D12", "#C2410C", "#FFF7ED", ["质朴"]),
  t("arctic", "极地", "科技", "#0C4A6E", "#38BDF8", "#F0F9FF", ["通透"]),
  t("espresso", "浓缩", "商务", "#292524", "#A8A29E", "#FAFAF9", ["极简"]),
  t("royal", "皇家蓝", "路演", "#1E3A8A", "#F59E0B", "#F8FAFC", ["自信"]),
  t("moss", "苔藓", "教育", "#365314", "#84CC16", "#F7FEE7", ["清新"]),
  t("rose-wood", "玫瑰木", "品牌", "#4C1D24", "#BE6B78", "#FDF6F7", ["细腻"]),
  t("graphite", "石墨", "商务", "#18181B", "#71717A", "#FAFAFA", ["黑白"]),
  t("lagoon", "潟湖", "生活", "#155E75", "#22D3EE", "#ECFEFF", ["明亮"]),
  t("wine-gold", "酒红金", "金融", "#4C0519", "#D4A017", "#FFFBEB", ["奢感"]),
  t("denim", "丹宁", "科技", "#1E3A5F", "#6495ED", "#F0F4FA", ["日常"]),
  t("matcha", "抹茶", "生活", "#3F6212", "#65A30D", "#F7FEE7", ["自然"]),
  t("cocoa", "可可", "人文", "#44403C", "#A16207", "#FAF6F1", ["柔暖"]),
  t("violet-ink", "紫墨", "品牌", "#2E1065", "#A78BFA", "#F5F3FF", ["创意"]),
];

export const DEFAULT_PPT_THEME: ThemePreset = THEME_PRESETS[0];

export function getThemePresetById(id: string): ThemePreset | undefined {
  return THEME_PRESETS.find((p) => p.id === id);
}

export function toThemeToken(preset: ThemePreset): ThemeToken {
  const { id: _id, ...token } = preset;
  return token;
}
