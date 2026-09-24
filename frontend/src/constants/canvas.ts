/** 画布实际像素尺寸（编辑 / 预览 / 导出统一），比例 16:9 */
export const CANVAS_WIDTH = 1000;
export const CANVAS_HEIGHT = 562.5;

/** 宽高比：16:9 */
export const CANVAS_ASPECT_RATIO = 16 / 9;
export const CANVAS_ASPECT_RATIO_CSS = "16 / 9";

/** 新建元素默认居中于画布 */
export function getCenteredElementPosition(width: number, height: number) {
  return {
    x: Math.round((CANVAS_WIDTH - width) / 2),
    y: Math.round((CANVAS_HEIGHT - height) / 2),
  };
}
