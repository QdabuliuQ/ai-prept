declare module "@scena/react-guides" {
  import * as React from "react";

  export interface GuidesProps {
    type?: "horizontal" | "vertical";
    className?: string;
    style?: React.CSSProperties;
    width?: number;
    height?: number;
    unit?: number;
    zoom?: number;
    displayDragPos?: boolean;
    direction?: "start" | "end" | "center";
    backgroundColor?: string;
    lineColor?: string;
    textOffset?: [number, number] | number;
    textColor?: string;
    font?: string;
    rulerStyle?: React.CSSProperties;
    guides?: number[];
    snaps?: number[];
    snapThreshold?: number;
    useResizeObserver?: boolean;
    showGuides?: boolean;
    defaultGuidesPos?: number;
    scrollPos?: number;
    onChangeGuides?: ({ guides }: { guides: number[] }) => void;
  }

  export interface GuidesInterface {
    scrollGuides(pos: number, zoom?: number): void;
    getGuideScrollPos(): number;
    loadGuides?(guides: number[]): void;
    setState?(state: { guides?: number[] }): void;
  }

  class Guides extends React.Component<GuidesProps> implements GuidesInterface {
    scrollGuides(pos: number, zoom?: number): void;
    getGuideScrollPos(): number;
  }

  export default Guides;
}
