import { useMenuActiveStore } from "@/store";
import { useChartInspectorStore } from "@/store/zustand/chartInspectorStore";
import { Close } from "@icon-park/react";
import { useEffect, type FC } from "react";
import styles from "./panel.module.less";

const THEME_SECTION = "ppt-theme";

/** 右侧属性面板宿主（主题色等）；原 ChartInspector，已与 JSON 元素解耦。 */
export const SideInspector: FC = () => {
  const sectionKey = useChartInspectorStore((state) => state.sectionKey);
  const title = useChartInspectorStore((state) => state.title);
  const close = useChartInspectorStore((state) => state.close);
  const setContentEl = useChartInspectorStore((state) => state.setContentEl);
  const menuActive = useMenuActiveStore((state) => state.menuActive);

  useEffect(() => {
    if (sectionKey === THEME_SECTION && menuActive !== "start") {
      close();
    }
  }, [menuActive, sectionKey, close]);

  if (!sectionKey) return null;

  return (
    <aside className={styles.inspector} aria-label={title || "属性面板"}>
      <header className={styles.inspectorHeader}>
        <span className={styles.inspectorTitle}>{title}</span>
        <button
          type="button"
          className={styles.inspectorClose}
          onClick={close}
          aria-label="关闭"
        >
          <Close theme="outline" size="14" fill="currentColor" />
        </button>
      </header>
      <div ref={setContentEl} className={styles.inspectorBody} />
    </aside>
  );
};

export default SideInspector;
