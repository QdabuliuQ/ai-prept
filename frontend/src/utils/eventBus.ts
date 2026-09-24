import mitt, { type Emitter } from "mitt";

// 导出mitt的类型
export type {
  EventHandlerList,
  EventHandlerMap,
  Handler,
  WildcardHandler,
} from "mitt";

// 全局事件总线实例
export const globalEventBus = mitt();

// 创建命名空间事件总线的工厂函数
export function createEventBus<
  Events extends Record<string, any> = Record<string, any>,
>(): Emitter<Events> {
  return mitt<Events>();
}

// 为特定组件创建独立的事件总线实例
const componentEventBuses = new Map<string, Emitter<any>>();

export function getComponentEventBus<
  Events extends Record<string, any> = Record<string, any>,
>(componentId: string): Emitter<Events> {
  if (!componentEventBuses.has(componentId)) {
    componentEventBuses.set(componentId, mitt<Events>());
  }
  return componentEventBuses.get(componentId)!;
}

// 清理组件事件总线
export function clearComponentEventBus(componentId: string): void {
  const bus = componentEventBuses.get(componentId);
  if (bus) {
    bus.all.clear();
    componentEventBuses.delete(componentId);
  }
}

// 导出默认的全局事件总线
export default globalEventBus;
