import { useMemo, type ReactNode } from "react";
import {
  Item,
  Menu,
  Separator,
  Submenu,
  useContextMenu as useContextMenuReact,
} from "react-contexify";
import "react-contexify/dist/ReactContexify.css";
import { createPortal } from "react-dom";

export type MenuItem = {
  type: "separator" | "item" | "submenu";
  onClick?: (payload?: unknown) => void;
  label?: string;
  icon?: React.ReactNode;
  disabled?: boolean;
  tip?: ReactNode; // 右侧提示信息（支持 React 节点）
  children?: Menu;
};
export type Menu = Array<MenuItem>;

export const useContextMenu = (
  menu: Menu,
  menuId: string,
  parentSelector?: string
) => {
  const { show, hideAll } = useContextMenuReact({ id: menuId });

  const contextMenu = useMemo(() => {
    // 递归渲染菜单项
    const renderMenuItems = (items: Menu): React.ReactNode[] => {
      return items.map((item, index) => {
        const key = `menu-item-${index}`;

        switch (item.type) {
          case "separator":
            return <Separator key={key} />;

          case "item":
            return (
              <Item
                key={key}
                onClick={(args) => {
                  if (item.onClick) {
                    try {
                      item.onClick(args);
                    } catch (error) {
                      console.error("Menu item onClick error:", error);
                    }
                  }
                  // 延迟关闭菜单，确保 onClick 回调能够完整执行
                  setTimeout(() => {
                    hideAll();
                  }, 0);
                }}
                disabled={item.disabled}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    width: "100%",
                  }}
                >
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    {item.icon && <span>{item.icon}</span>}
                    {item.label}
                  </span>
                  {item.tip}
                </div>
              </Item>
            );

          case "submenu":
            return (
              <Submenu
                key={key}
                label={
                  <>
                    {item.icon && (
                      <span style={{ marginRight: 8 }}>{item.icon}</span>
                    )}
                    {item.label}
                  </>
                }
                disabled={item.disabled}
              >
                {item.children ? renderMenuItems(item.children) : null}
              </Submenu>
            );

          default:
            return null;
        }
      });
    };

    return renderMenuItems(menu);
  }, [menu, hideAll]);

  const ContextMenu = useMemo(() => {
    return () =>
      createPortal(
        <Menu animation="none" id={menuId} style={{ zIndex: 10000 }}>
          {contextMenu}
        </Menu>,
        parentSelector && document.querySelector(parentSelector)
          ? (document.querySelector(parentSelector) as Element)
          : document.body
      );
  }, [contextMenu, menuId, parentSelector]);

  return {
    ContextMenu,
    show,
  };
};
