/** Template package format helpers (admin / catalog). */

export type TemplateFormat = "html-slide" | "ppt-master";

/** Packages with slides/*.html export via html-to-pptx (includes ppt-master converts). */
export function isHtmlSlideFormat(format?: string | null): boolean {
  const f = (format || "").trim();
  return !f || f === "html-slide" || f === "ppt-master";
}
