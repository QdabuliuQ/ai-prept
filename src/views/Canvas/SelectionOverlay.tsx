import type {
  CSSProperties,
  FC,
  PointerEvent as ReactPointerEvent,
} from "react";
import { useEffect, useRef, useState } from "react";
import type {
  ElementTransformBox,
  SelectedElementInfo,
  SlideRect,
} from "@/slide-editor/parent/SlideEditorParentBridge";

type HandleKind =
  | "move"
  | "n"
  | "s"
  | "e"
  | "w"
  | "ne"
  | "nw"
  | "se"
  | "sw"
  | "rotate";

export type SelectionOverlayProps = {
  /** Fallback scale if measuring fails */
  scale: number;
  hoverRect: SlideRect | null;
  selected: SelectedElementInfo | null;
  multiSelected?: SelectedElementInfo[];
  onTransform?: (
    selector: string,
    box: ElementTransformBox,
    editorId?: string,
  ) => void;
  onTransformEnd?: (
    selector: string,
    box: ElementTransformBox,
    editorId?: string,
  ) => void;
  onTransformStart?: () => void;
};

type DragState = {
  kind: HandleKind;
  selector: string;
  editorId?: string;
  startClientX: number;
  startClientY: number;
  startBox: ElementTransformBox;
  /** screen px per slide px */
  screenPerSlide: number;
  pointerId: number;
  captureEl: HTMLElement;
  moved: boolean;
  /** Pointer angle (deg) from box center at rotate start */
  startPointerAngleDeg?: number;
};

const MIN_SIZE = 8;
/** All resize handles (corners + edges) — circular */
const HANDLE_SIZE = 10;
const ROTATE_HANDLE = 14;
/** Gap between rotate knob and selection box edge */
const ROTATE_STEM = 16;
/** Top-left move grip — only way to drag-move */
const MOVE_HANDLE = 16;
/** Horizontal offset from left edge, as % of selection width */
const MOVE_HANDLE_NUDGE_X_PCT = 5;

function clampBox(box: ElementTransformBox): ElementTransformBox {
  return {
    ...box,
    width: Math.max(MIN_SIZE, box.width),
    height: Math.max(MIN_SIZE, box.height),
  };
}

function resizeFromHandle(
  kind: HandleKind,
  start: ElementTransformBox,
  dx: number,
  dy: number,
): ElementTransformBox {
  let { left, top, width, height } = start;
  const { rotation } = start;

  switch (kind) {
    case "e":
      width = start.width + dx;
      break;
    case "w":
      left = start.left + dx;
      width = start.width - dx;
      break;
    case "s":
      height = start.height + dy;
      break;
    case "n":
      top = start.top + dy;
      height = start.height - dy;
      break;
    case "se":
      width = start.width + dx;
      height = start.height + dy;
      break;
    case "sw":
      left = start.left + dx;
      width = start.width - dx;
      height = start.height + dy;
      break;
    case "ne":
      width = start.width + dx;
      top = start.top + dy;
      height = start.height - dy;
      break;
    case "nw":
      left = start.left + dx;
      top = start.top + dy;
      width = start.width - dx;
      height = start.height - dy;
      break;
    default:
      break;
  }

  if (width < MIN_SIZE) {
    if (kind.includes("w")) left = start.left + start.width - MIN_SIZE;
    width = MIN_SIZE;
  }
  if (height < MIN_SIZE) {
    if (kind.includes("n")) top = start.top + start.height - MIN_SIZE;
    height = MIN_SIZE;
  }

  return clampBox({ left, top, width, height, rotation });
}

function rotateFromPointer(
  start: ElementTransformBox,
  clientX: number,
  clientY: number,
  overlayRect: DOMRect,
  screenPerSlide: number,
  startPointerAngleDeg: number,
): ElementTransformBox {
  const cx =
    overlayRect.left + (start.left + start.width / 2) * screenPerSlide;
  const cy =
    overlayRect.top + (start.top + start.height / 2) * screenPerSlide;
  const pointerAngle =
    (Math.atan2(clientY - cy, clientX - cx) * 180) / Math.PI;
  const delta = pointerAngle - startPointerAngleDeg;
  return { ...start, rotation: (start.rotation ?? 0) + delta };
}

/**
 * Parent-side selection overlay: move / resize / rotate with local preview.
 * Uses pointer capture so mouseup always ends the gesture.
 */
export const SelectionOverlay: FC<SelectionOverlayProps> = ({
  scale,
  hoverRect,
  selected,
  multiSelected = [],
  onTransform,
  onTransformEnd,
  onTransformStart,
}: SelectionOverlayProps) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const liveBoxRef = useRef<ElementTransformBox | null>(null);
  const [liveBox, setLiveBox] = useState<ElementTransformBox | null>(null);
  const [liveSelector, setLiveSelector] = useState<string | null>(null);
  const rafRef = useRef(0);
  const pendingBoxRef = useRef<{
    selector: string;
    editorId?: string;
    box: ElementTransformBox;
  } | null>(null);

  useEffect(() => {
    if (dragRef.current) return;
    if (!selected) {
      setLiveBox(null);
      setLiveSelector(null);
      liveBoxRef.current = null;
      return;
    }
    const box = {
      left: selected.rect.left,
      top: selected.rect.top,
      width: selected.rect.width,
      height: selected.rect.height,
      rotation: selected.rotation ?? 0,
    };
    setLiveSelector(selected.selector);
    setLiveBox(box);
    liveBoxRef.current = box;
  }, [selected]);

  const measureScreenPerSlide = () => {
    const el = rootRef.current;
    if (!el) return scale;
    const w = el.getBoundingClientRect().width;
    return w > 0 ? w / 1920 : scale;
  };

  const flushTransform = () => {
    rafRef.current = 0;
    const pending = pendingBoxRef.current;
    if (!pending) return;
    onTransform?.(pending.selector, pending.box, pending.editorId);
  };

  const scheduleTransform = (
    selector: string,
    box: ElementTransformBox,
    editorId?: string,
  ) => {
    pendingBoxRef.current = { selector, editorId, box };
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(flushTransform);
  };

  const onPointerMove = (ev: PointerEvent) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();

    const dxScreen = ev.clientX - drag.startClientX;
    const dyScreen = ev.clientY - drag.startClientY;
    if (!drag.moved && (Math.abs(dxScreen) > 3 || Math.abs(dyScreen) > 3)) {
      drag.moved = true;
    }

    const dx = dxScreen / drag.screenPerSlide;
    const dy = dyScreen / drag.screenPerSlide;

    let next: ElementTransformBox;
    if (drag.kind === "move") {
      if (!drag.moved) return;
      next = {
        ...drag.startBox,
        left: drag.startBox.left + dx,
        top: drag.startBox.top + dy,
        resize: false,
      };
    } else if (drag.kind === "rotate") {
      const overlayRect = rootRef.current?.getBoundingClientRect();
      if (!overlayRect || drag.startPointerAngleDeg == null) return;
      drag.moved = true;
      next = {
        ...rotateFromPointer(
          drag.startBox,
          ev.clientX,
          ev.clientY,
          overlayRect,
          drag.screenPerSlide,
          drag.startPointerAngleDeg,
        ),
        resize: false,
      };
    } else {
      drag.moved = true;
      next = {
        ...resizeFromHandle(drag.kind, drag.startBox, dx, dy),
        resize: true,
      };
    }

    liveBoxRef.current = next;
    setLiveBox(next);
    scheduleTransform(drag.selector, next, drag.editorId);
  };

  const endDrag = (ev: PointerEvent) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== ev.pointerId) return;

    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", endDrag);
    window.removeEventListener("pointercancel", endDrag);

    try {
      drag.captureEl.releasePointerCapture(ev.pointerId);
    } catch {
      /* ignore */
    }

    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }

    // Move grip click-without-drag: do not enter text edit (text uses iframe clicks).
    const wasClick = !drag.moved;
    dragRef.current = null;
    pendingBoxRef.current = null;

    if (wasClick) {
      onTransformEnd?.(drag.selector, drag.startBox, drag.editorId);
      return;
    }

    const finalBox = liveBoxRef.current ?? drag.startBox;
    onTransform?.(drag.selector, finalBox, drag.editorId);
    onTransformEnd?.(drag.selector, finalBox, drag.editorId);
  };

  const beginDrag = (
    e: ReactPointerEvent,
    kind: HandleKind,
    info: SelectedElementInfo,
    box: ElementTransformBox,
  ) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();

    const captureEl = e.currentTarget as HTMLElement;
    const screenPerSlide = measureScreenPerSlide();
    let startPointerAngleDeg: number | undefined;
    if (kind === "rotate") {
      const overlayRect = rootRef.current?.getBoundingClientRect();
      if (overlayRect) {
        const cx =
          overlayRect.left + (box.left + box.width / 2) * screenPerSlide;
        const cy =
          overlayRect.top + (box.top + box.height / 2) * screenPerSlide;
        startPointerAngleDeg =
          (Math.atan2(e.clientY - cy, e.clientX - cx) * 180) / Math.PI;
      }
    }

    dragRef.current = {
      kind,
      selector: info.selector,
      editorId: info.editorId,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startBox: { ...box },
      screenPerSlide,
      pointerId: e.pointerId,
      captureEl,
      moved: false,
      startPointerAngleDeg,
    };
    setLiveSelector(info.selector);
    setLiveBox(box);
    liveBoxRef.current = box;
    onTransformStart?.();

    try {
      captureEl.setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    window.addEventListener("pointermove", onPointerMove, { passive: false });
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
  };

  useEffect(() => {
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      dragRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const displayBox =
    liveSelector && liveBox
      ? liveBox
      : selected
        ? {
            left: selected.rect.left,
            top: selected.rect.top,
            width: selected.rect.width,
            height: selected.rect.height,
            rotation: selected.rotation ?? 0,
          }
        : null;

  const toOverlay = (rect: {
    left: number;
    top: number;
    width: number;
    height: number;
  }) => ({
    top: rect.top * scale,
    left: rect.left * scale,
    width: rect.width * scale,
    height: rect.height * scale,
  });

  const showHover =
    hoverRect &&
    !(
      displayBox &&
      Math.abs(displayBox.left - hoverRect.left) < 0.5 &&
      Math.abs(displayBox.top - hoverRect.top) < 0.5 &&
      Math.abs(displayBox.width - hoverRect.width) < 0.5 &&
      Math.abs(displayBox.height - hoverRect.height) < 0.5
    );

  const cornerHandles: Array<{
    kind: HandleKind;
    cursor: string;
    style: CSSProperties;
  }> = [
    {
      kind: "nw",
      cursor: "nwse-resize",
      style: { left: -HANDLE_SIZE / 2, top: -HANDLE_SIZE / 2 },
    },
    {
      kind: "ne",
      cursor: "nesw-resize",
      style: { right: -HANDLE_SIZE / 2, top: -HANDLE_SIZE / 2 },
    },
    {
      kind: "se",
      cursor: "nwse-resize",
      style: { right: -HANDLE_SIZE / 2, bottom: -HANDLE_SIZE / 2 },
    },
    {
      kind: "sw",
      cursor: "nesw-resize",
      style: { left: -HANDLE_SIZE / 2, bottom: -HANDLE_SIZE / 2 },
    },
  ];

  const edgeHandles: Array<{
    kind: HandleKind;
    cursor: string;
    style: CSSProperties;
  }> = [
    {
      kind: "n",
      cursor: "ns-resize",
      style: {
        left: "50%",
        top: -HANDLE_SIZE / 2,
        marginLeft: -HANDLE_SIZE / 2,
      },
    },
    {
      kind: "e",
      cursor: "ew-resize",
      style: {
        right: -HANDLE_SIZE / 2,
        top: "50%",
        marginTop: -HANDLE_SIZE / 2,
      },
    },
    {
      kind: "s",
      cursor: "ns-resize",
      style: {
        left: "50%",
        bottom: -HANDLE_SIZE / 2,
        marginLeft: -HANDLE_SIZE / 2,
      },
    },
    {
      kind: "w",
      cursor: "ew-resize",
      style: {
        left: -HANDLE_SIZE / 2,
        top: "50%",
        marginTop: -HANDLE_SIZE / 2,
      },
    },
  ];

  const selectedInfo =
    selected && (!liveSelector || liveSelector === selected.selector)
      ? selected
      : (multiSelected.find((m) => m.selector === liveSelector) ?? selected);

  const overlayBox = displayBox ? toOverlay(displayBox) : null;

  return (
    <div ref={rootRef} className="absolute inset-0 z-[5] pointer-events-none">
      {showHover && hoverRect && (
        <div
          className="absolute box-border"
          style={{
            ...toOverlay(hoverRect),
            border: "1px dashed rgba(242, 95, 0, 0.65)",
          }}
        />
      )}

      {displayBox && selectedInfo && overlayBox && (
        <div
          className="absolute box-border pointer-events-none"
          style={{
            ...overlayBox,
            border: "2px solid var(--primary-color, #f25f00)",
            background: "transparent",
            transform:
              displayBox.rotation && Math.abs(displayBox.rotation) > 0.01
                ? `rotate(${displayBox.rotation}deg)`
                : undefined,
            transformOrigin: "center center",
          }}
        >
          {/* Move — top-left corner, nudged right; body/border no longer drag */}
          <button
            type="button"
            title="按住拖动"
            aria-label="按住拖动"
            className="absolute pointer-events-auto z-[4] flex items-center justify-center rounded-full border-0 bg-[var(--primary-color,#f25f00)] shadow-sm cursor-grab active:cursor-grabbing box-border p-0"
            style={{
              left: `calc(${MOVE_HANDLE_NUDGE_X_PCT}% - ${MOVE_HANDLE / 2}px)`,
              top: -MOVE_HANDLE / 2,
              width: MOVE_HANDLE,
              height: MOVE_HANDLE,
            }}
            onPointerDown={(e) => {
              e.stopPropagation();
              beginDrag(e, "move", selectedInfo, {
                ...displayBox,
                resize: false,
              });
            }}
          >
            <svg
              width="9"
              height="9"
              viewBox="0 0 16 16"
              aria-hidden
              fill="white"
            >
              <path d="M8 1.2 10.2 4H5.8L8 1.2Z" />
              <path d="M8 14.8 5.8 12h4.4L8 14.8Z" />
              <path d="M1.2 8 4 5.8v4.4L1.2 8Z" />
              <path d="M14.8 8 12 10.2V5.8L14.8 8Z" />
              <rect x="7.15" y="4" width="1.7" height="8" rx="0.4" />
              <rect x="4" y="7.15" width="8" height="1.7" rx="0.4" />
            </svg>
          </button>

          {/* Rotate — offset above box, connected by a stem */}
          <div
            className="absolute left-1/2 -translate-x-1/2 pointer-events-auto z-[3]"
            style={{
              top: -(ROTATE_HANDLE + ROTATE_STEM),
              width: ROTATE_HANDLE,
              height: ROTATE_HANDLE + ROTATE_STEM,
            }}
            onPointerDown={(e) => {
              e.stopPropagation();
              beginDrag(e, "rotate", selectedInfo, {
                ...displayBox,
                resize: false,
              });
            }}
          >
            <div
              className="absolute left-1/2 -translate-x-1/2 w-px bg-[var(--primary-color,#f25f00)]"
              style={{ top: ROTATE_HANDLE, height: ROTATE_STEM }}
            />
            <div
              className="rounded-full border-2 border-[var(--primary-color,#f25f00)] bg-white cursor-grab box-border"
              title="旋转"
              style={{ width: ROTATE_HANDLE, height: ROTATE_HANDLE }}
            />
          </div>

          {edgeHandles.map((h) => (
            <div
              key={h.kind}
              title="调整宽高"
              className="absolute pointer-events-auto z-[2] rounded-full bg-white border-2 border-[var(--primary-color,#f25f00)] box-border"
              style={{
                width: HANDLE_SIZE,
                height: HANDLE_SIZE,
                cursor: h.cursor,
                ...h.style,
              }}
              onPointerDown={(e) => {
                e.stopPropagation();
                beginDrag(e, h.kind, selectedInfo, {
                  ...displayBox,
                  resize: true,
                });
              }}
            />
          ))}

          {cornerHandles.map((h) => (
            <div
              key={h.kind}
              title="缩放"
              className="absolute pointer-events-auto z-[2] rounded-full bg-white border-2 border-[var(--primary-color,#f25f00)] box-border"
              style={{
                width: HANDLE_SIZE,
                height: HANDLE_SIZE,
                cursor: h.cursor,
                ...h.style,
              }}
              onPointerDown={(e) => {
                e.stopPropagation();
                beginDrag(e, h.kind, selectedInfo, {
                  ...displayBox,
                  resize: true,
                });
              }}
            />
          ))}
        </div>
      )}

      {multiSelected.map((el) => {
        if (displayBox && el.selector === liveSelector) return null;
        if (selected && el.selector === selected.selector) return null;
        return (
          <div
            key={el.selector}
            className="absolute box-border pointer-events-none"
            style={{
              ...toOverlay(el.rect),
              border: "2px solid var(--primary-color, #f25f00)",
              opacity: 0.7,
            }}
          />
        );
      })}
    </div>
  );
};
