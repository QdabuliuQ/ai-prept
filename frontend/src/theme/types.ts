/** 文档主题 token（编辑器 / document.json 共用） */
export type ThemeToken = {
  templateName: string;
  category: string;
  tags: string[];
  primary: string;
  secondary: string;
  background: string;
  textOnLight: string;
  textOnDark: string;
  fontTitle: string;
  fontBody: string;
  /** KPI / 大数字 */
  fontNumeric?: string;
  globalBgPrompt?: string;
  globalDecorPrompt?: string;
};
