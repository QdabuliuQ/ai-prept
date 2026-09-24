import { getRandomId } from "@/utils";
import { buildBlankSlideHtml } from "@/utils/slideHtml";
import type { Page } from "@/store/zustand/pptStore";

function blankPage(partial?: Partial<Page>): Page {
  const page: Page = {
    id: `page_${getRandomId()}`,
    visible: true,
    toggleInAnimation: "backInLeft",
    toggleInDuration: "default",
    toggleInDelay: "0s",
    autoToggle: false,
    autoToggleTime: 5,
    backgroundType: "solidColor",
    background: "#fff",
    bgColor: "#e4e4e4",
    fgColor: "#9C92AC",
    bgOpacity: 0.4,
    remark: "",
    ...partial,
  };
  page.html = partial?.html ?? buildBlankSlideHtml(page);
  return page;
}

export default {
  name: "",
  gridLine: true,
  gridSize: 20,
  gridType: "grid" as const,
  showLine: true,
  verticalLine: [] as number[],
  horizontalLine: [] as number[],
  rule: true,
  guideLineShow: true,
  keyboardToggle: true,
  pages: [blankPage()],
};
