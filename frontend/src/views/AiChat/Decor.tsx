import type { FC, SVGProps } from "react";
import styles from "./index.module.less";

/** Crisp geometric deck motif — not illustration costume. */
export const EmptyDeckArt: FC<SVGProps<SVGSVGElement>> = (props) => (
  <svg
    viewBox="0 0 160 96"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden
    className={styles.emptyArt}
    {...props}
  >
    <rect
      x="28"
      y="18"
      width="92"
      height="58"
      rx="6"
      fill="currentColor"
      opacity="0.06"
      transform="rotate(-6 74 47)"
    />
    <rect
      x="34"
      y="14"
      width="92"
      height="58"
      rx="6"
      stroke="currentColor"
      strokeWidth="1.25"
      opacity="0.18"
      transform="rotate(-3 80 43)"
    />
    <rect
      x="40"
      y="12"
      width="92"
      height="58"
      rx="6"
      fill="var(--panel-bg-solid, #fff)"
      fillOpacity="0.72"
      stroke="currentColor"
      strokeWidth="1.35"
      opacity="0.9"
    />
    <rect x="50" y="24" width="42" height="4" rx="2" fill="var(--ai-accent)" opacity="0.85" />
    <rect x="50" y="34" width="64" height="3" rx="1.5" fill="currentColor" opacity="0.16" />
    <rect x="50" y="42" width="54" height="3" rx="1.5" fill="currentColor" opacity="0.12" />
    <rect x="50" y="50" width="36" height="3" rx="1.5" fill="currentColor" opacity="0.1" />
    <circle cx="122" cy="58" r="11" fill="var(--ai-accent)" opacity="0.14" />
    <path
      d="M116.5 58.5h5.5v-5.5M122 64.5V58.5H128.5"
      stroke="var(--ai-accent)"
      strokeWidth="1.5"
      strokeLinecap="round"
      opacity="0.9"
    />
  </svg>
);

export const PanelCornerPattern: FC = () => (
  <svg
    className={styles.cornerPattern}
    viewBox="0 0 120 120"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden
  >
    <circle cx="96" cy="24" r="28" stroke="currentColor" strokeWidth="1" opacity="0.12" />
    <circle cx="96" cy="24" r="16" stroke="currentColor" strokeWidth="1" opacity="0.1" />
    <path
      d="M72 8h18M90 8v18"
      stroke="var(--ai-accent)"
      strokeWidth="1.5"
      strokeLinecap="round"
      opacity="0.35"
    />
    <rect
      x="8"
      y="88"
      width="22"
      height="14"
      rx="2"
      stroke="currentColor"
      strokeWidth="1"
      opacity="0.1"
    />
    <rect x="12" y="92" width="10" height="2" rx="1" fill="currentColor" opacity="0.12" />
  </svg>
);

export const TitleMark: FC = () => (
  <svg
    className={styles.titleMark}
    viewBox="0 0 18 18"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden
  >
    <rect
      x="2.5"
      y="3.5"
      width="13"
      height="11"
      rx="2"
      stroke="currentColor"
      strokeWidth="1.25"
      opacity="0.55"
    />
    <path
      d="M5.5 7h7M5.5 10h4.5"
      stroke="var(--ai-accent)"
      strokeWidth="1.35"
      strokeLinecap="round"
    />
  </svg>
);
