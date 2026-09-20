import {
  SLIDE_HTML_HEIGHT,
  SLIDE_HTML_WIDTH,
} from "@/utils/slideHtml";
import type { Page } from "@/store/ppt";
import { HtmlSlideFrame } from "@/views/Canvas/HtmlSlideFrame";
import { type FC } from "react";

export interface PreviewCanvasProps {
  page: Page;
  previewZoom?: number;
  /**
   * design：1920×1080 原尺寸（缩略图/导出截图，默认）
   * canvas：缩放到编辑器画布尺寸（少用）
   */
  fit?: "canvas" | "design";
}

/**
 * 轻量预览画布：/embed/slide iframe 渲染 page.html（无标尺/选中/备注）。
 * 供侧栏缩略图、Grid、exportPageAsImage 等使用。
 */
export const PreviewCanvas: FC<PreviewCanvasProps> = ({
  page,
  previewZoom,
  fit = "design",
}) => {
  const w = fit === "design" ? SLIDE_HTML_WIDTH : undefined;
  const h = fit === "design" ? SLIDE_HTML_HEIGHT : undefined;

  return (
    <div
      className="w-full h-full relative pointer-events-none"
      style={previewZoom !== undefined ? { zoom: previewZoom } : undefined}
    >
      <div
        id={`preview-canvas-container-${page.id}`}
        className="absolute overflow-hidden"
        style={{
          width: w ?? "100%",
          height: h ?? "100%",
          left: fit === "design" ? 0 : "50%",
          top: fit === "design" ? 0 : "50%",
          marginLeft: fit === "design" ? 0 : undefined,
          marginTop: fit === "design" ? 0 : undefined,
          transform: fit === "design" ? undefined : "translate(-50%, -50%)",
          backgroundColor: "#111",
        }}
      >
        <HtmlSlideFrame
          page={page}
          fit={fit}
          pointerEventsNone
          title={`preview-${page.id}`}
        />
      </div>
    </div>
  );
};
