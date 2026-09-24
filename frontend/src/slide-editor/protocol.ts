/**
 * Shared protocol types for parent ↔ iframe slide editor.
 * Runtime and parent both import from here (runtime copies via relative path in bundle).
 */
export {
  MESSAGE_PROTOCOL_VERSION,
  MessageCategory,
  EventType,
  type BaseMessage,
  type RequestMessage,
  type ResponseMessage,
  type EventMessage,
  type CommandMessage,
} from "./runtime/core/types";
