/** 模板 HTML 预览 iframe 地址（无 store 依赖，可供 admin / 公开库使用） */

export function buildTemplateSlideEmbedSrc(
  templateDir: string,
  relFile: string,
): string {
  const path = relFile.replace(/^\/+/, "");
  return `/embed/template/${encodeURIComponent(templateDir)}/${path
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
}
