/**
 * Editor Bridge — iframe ↔ parent postMessage
 */

import {
  MESSAGE_PROTOCOL_VERSION,
  MessageCategory,
  type RequestMessage,
  type ResponseMessage,
  type EventMessage,
  type CommandMessage,
} from "./types";
import { getParentOrigin } from "../utils/parentOrigin";

type RequestHandler = (payload: unknown) => unknown | Promise<unknown>;
type CommandHandler = (payload: unknown) => unknown | Promise<unknown>;

export class EditorBridge {
  private isDestroyed = false;
  private commandHandlers = new Map<string, CommandHandler>();
  private requestHandlers = new Map<string, RequestHandler>();
  private messageListener: ((event: MessageEvent) => void) | null = null;

  constructor() {
    this.setupMessageListener();
  }

  private setupMessageListener() {
    this.messageListener = (event: MessageEvent) => {
      if (this.isDestroyed) return;
      if (event.source !== window.parent) return;

      const message = event.data;
      if (!message || message.version !== MESSAGE_PROTOCOL_VERSION) return;

      if (
        message.category === MessageCategory.REQUEST &&
        message.type === "EXECUTE_COMMAND"
      ) {
        const commandMessage = message.payload as CommandMessage;
        if (
          commandMessage &&
          commandMessage.category === MessageCategory.COMMAND
        ) {
          void this.handleCommand(commandMessage, message.requestId);
        }
      } else if (message.category === MessageCategory.REQUEST) {
        void this.handleRequest(message as RequestMessage);
      } else if (message.category === MessageCategory.COMMAND) {
        void this.handleCommand(message as CommandMessage);
      }
    };

    window.addEventListener("message", this.messageListener);
  }

  private async handleRequest(request: RequestMessage) {
    const handler = this.requestHandlers.get(request.type);
    const response: ResponseMessage = {
      version: MESSAGE_PROTOCOL_VERSION,
      category: MessageCategory.RESPONSE,
      type: request.type,
      requestId: request.requestId,
      timestamp: Date.now(),
      source: "iframe",
      success: false,
    };

    try {
      if (!handler) {
        throw new Error(`Unknown request type: ${request.type}`);
      }
      const result = await handler(request.payload);
      response.success = true;
      response.payload = result;
    } catch (error) {
      response.success = false;
      response.error = {
        code: "REQUEST_FAILED",
        message: (error as Error).message || String(error),
      };
    }

    this.sendResponse(response);
  }

  private async handleCommand(
    command: CommandMessage,
    outerRequestId?: string,
  ) {
    const handler = this.commandHandlers.get(command.commandType);
    const response: ResponseMessage = {
      version: MESSAGE_PROTOCOL_VERSION,
      category: MessageCategory.RESPONSE,
      type: "EXECUTE_COMMAND",
      requestId: outerRequestId || command.requestId || "",
      timestamp: Date.now(),
      source: "iframe",
      success: false,
    };

    try {
      if (!handler) {
        throw new Error(`Unknown command type: ${command.commandType}`);
      }
      const result = await handler(command.payload);
      response.success = true;
      response.payload = result;
    } catch (error) {
      response.success = false;
      response.error = {
        code: "COMMAND_FAILED",
        message: (error as Error).message || String(error),
      };
    }

    this.sendResponse(response);
  }

  private sendResponse(response: ResponseMessage) {
    if (this.isDestroyed) return;
    try {
      window.parent.postMessage(response, getParentOrigin());
    } catch (error) {
      console.error("[EditorBridge] Failed to send response:", error);
    }
  }

  sendEvent(type: string, payload?: unknown) {
    if (this.isDestroyed) return;
    try {
      const event: EventMessage = {
        version: MESSAGE_PROTOCOL_VERSION,
        category: MessageCategory.EVENT,
        type,
        payload,
        timestamp: Date.now(),
        source: "iframe",
      };
      window.parent.postMessage(event, getParentOrigin());
    } catch (error) {
      console.error("[EditorBridge] Failed to send event:", error);
    }
  }

  onCommand(commandType: string, handler: CommandHandler) {
    this.commandHandlers.set(commandType, handler);
  }

  onRequest(requestType: string, handler: RequestHandler) {
    this.requestHandlers.set(requestType, handler);
  }

  destroy() {
    this.isDestroyed = true;
    this.commandHandlers.clear();
    this.requestHandlers.clear();
    if (this.messageListener) {
      window.removeEventListener("message", this.messageListener);
      this.messageListener = null;
    }
  }
}
