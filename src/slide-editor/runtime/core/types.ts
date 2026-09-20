/**
 * Core type definitions for slide-editor iframe runtime
 */

export const MESSAGE_PROTOCOL_VERSION = "1.0.0";

export enum MessageCategory {
  REQUEST = "request",
  RESPONSE = "response",
  EVENT = "event",
  COMMAND = "command",
}

export interface BaseMessage {
  version: string;
  category: MessageCategory;
  type: string;
  timestamp: number;
  source: string;
}

export interface RequestMessage extends BaseMessage {
  category: MessageCategory.REQUEST;
  requestId: string;
  payload?: unknown;
}

export interface ResponseMessage extends BaseMessage {
  category: MessageCategory.RESPONSE;
  requestId: string;
  success: boolean;
  payload?: unknown;
  error?: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export interface EventMessage extends BaseMessage {
  category: MessageCategory.EVENT;
  payload?: unknown;
}

export interface CommandMessage extends BaseMessage {
  category: MessageCategory.COMMAND;
  commandType: string;
  requestId?: string;
  payload?: unknown;
}

export enum EventType {
  EDITOR_READY = "EDITOR_READY",
  CONTENT_CHANGED = "CONTENT_CHANGED",
}
