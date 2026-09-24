import { useContextMenu } from "@/hooks/useContextMenu";
import { useContextMenuStore } from "@/store";
import { useEffect, useMemo, useRef, type FC } from "react";

export const GlobalContextMenu: FC<{ parentSelector?: string }> = ({
  parentSelector,
}) => {
  // 使用 Zustand hook 订阅状态变化，确保组件能够响应状态更新
  const menuItems = useContextMenuStore((state) => state.menuItems);
  const visible = useContextMenuStore((state) => state.menuVisible);
  const position = useContextMenuStore((state) => state.menuPosition);

  // 使用 useMemo 稳定 position 的引用，避免不必要的重新渲染
  const positionKey = useMemo(
    () => `${position.x}-${position.y}`,
    [position.x, position.y]
  );

  // 使用 ref 保存最新的 menuItems，避免在 useEffect 中使用数组引用
  const menuItemsRef = useRef(menuItems);
  useEffect(() => {
    menuItemsRef.current = menuItems;
  }, [menuItems]);

  // 使用 useContextMenu hook
  const { ContextMenu, show } = useContextMenu(
    menuItems,
    "global-context-menu",
    parentSelector
  );

  // 监听 store 的变化，当需要显示菜单时调用 show
  useEffect(() => {
    if (visible && position && menuItemsRef.current.length > 0) {
      const mockEvent = {
        clientX: position.x,
        clientY: position.y,
        preventDefault: () => {},
        stopPropagation: () => {},
      } as React.MouseEvent;

      // 延迟到下一个事件循环，避免在 React 渲染过程中同步调用 flushSync
      const timer = setTimeout(() => {
        show({ event: mockEvent });
      }, 0);

      return () => {
        clearTimeout(timer);
      };
    }
    // 使用 positionKey 和 visible 作为依赖项，menuItems 通过 ref 访问
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, positionKey, show]);

  return <ContextMenu />;
};
