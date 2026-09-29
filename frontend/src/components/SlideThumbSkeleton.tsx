import type { FC } from "react";
import styles from "./SlideThumbSkeleton.module.less";

/** 侧栏 / 网格缩略图加载态：幻灯片比例骨架屏（非 Spin） */
export const SlideThumbSkeleton: FC = () => (
  <div className={styles.root} aria-hidden="true">
    <div className={styles.shimmer} />
    <div className={styles.content}>
      <div className={styles.kicker} />
      <div className={styles.title} />
      <div className={styles.sub} />
      <div className={styles.grid}>
        <div className={styles.col}>
          <div className={styles.line} />
          <div className={`${styles.line} ${styles.lineShort}`} />
          <div className={styles.card} />
          <div className={styles.card} />
        </div>
        <div className={styles.media} />
      </div>
    </div>
  </div>
);
