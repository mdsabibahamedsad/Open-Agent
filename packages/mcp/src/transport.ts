import { EventEmitter } from "events";
import {
  MCPTransportType,
  MCPConnectionState,
  MCPServerConfig,
  MCPRequest,
  MCPResponse,
  MCPNotification,
  MCPError,
} from "./types";

export interface MCPTransport {
  readonly transportType: MCPTransportType;
  connect(config: MCPServerConfig): Promise<void>;
  disconnect(): Promise<void>;
  send(request: MCPRequest): Promise<MCPResponse>;
  on(
    event: "close" | "error" | "notification" | "capabilities",
    listener: (...args: any[]) => void,
  ): this;
  isConnected(): boolean;
  getState(): MCPConnectionState;
}

export abstract class BaseTransport
  extends EventEmitter
  implements MCPTransport
{
  abstract readonly transportType: MCPTransportType;
  protected state: MCPConnectionState = "DISCONNECTED";
  protected requestId = 0;
  // `any` is deliberate: JSON-RPC results are untyped by design, and the
  // stored resolver belongs to a `Promise<MCPResponse>` executor whose
  // callback types are invariant under `strictFunctionTypes`.
  protected pendingRequests = new Map<
    string | number,
    { resolve: (value: any) => void; reject: (error: Error) => void }
  >();

  abstract connect(config: MCPServerConfig): Promise<void>;
  abstract disconnect(): Promise<void>;
  abstract send(request: MCPRequest): Promise<MCPResponse>;

  isConnected(): boolean {
    return this.state === "CONNECTED";
  }

  getState(): MCPConnectionState {
    return this.state;
  }

  protected setState(state: MCPConnectionState): void {
    this.state = state;
  }

  protected generateRequestId(): string | number {
    return ++this.requestId;
  }

  protected createRequest(method: string, params?: unknown): MCPRequest {
    return {
      jsonrpc: "2.0",
      id: this.generateRequestId(),
      method,
      params,
    };
  }

  protected handleResponse(response: MCPResponse): void {
    const pending = this.pendingRequests.get(response.id);
    if (pending) {
      this.pendingRequests.delete(response.id);
      if (response.error) {
        pending.reject(new MCPProtocolError(response.error));
      } else {
        pending.resolve(response.result);
      }
    }
  }

  protected handleNotification(notification: MCPNotification): void {
    this.emit("notification", notification);
  }
}

export class MCPProtocolError extends Error {
  public readonly code: number;
  public readonly data?: unknown;

  constructor(error: MCPError) {
    super(error.message);
    this.name = "MCPProtocolError";
    this.code = error.code;
    this.data = error.data;
  }
}

export interface MCPTransportFactory {
  createTransport(type: MCPTransportType): MCPTransport;
}

export function createTransportFactory(): MCPTransportFactory {
  return {
    createTransport(type: MCPTransportType): MCPTransport {
      switch (type) {
        // Transports take no constructor arguments: configuration arrives
        // later via connect(config), which stores it as `this.config`.
        case "stdio":
          return new StdioTransport();
        case "streamable_http":
          return new StreamableHttpTransport();
        case "sse":
          return new SSETransport();
        default:
          throw new Error(`Unsupported transport type: ${type}`);
      }
    },
  };
}

export abstract class AbstractTransport extends BaseTransport {
  protected config!: MCPServerConfig;
  protected connected = false;

  async connect(config: MCPServerConfig): Promise<void> {
    this.config = config;
    this.setState("CONNECTING");
    try {
      await this.doConnect();
      this.connected = true;
      this.setState("CONNECTED");
    } catch (error) {
      this.setState("FAILED");
      throw error;
    }
  }

  protected abstract doConnect(): Promise<void>;

  async disconnect(): Promise<void> {
    if (!this.connected) return;
    try {
      await this.doDisconnect();
    } finally {
      this.connected = false;
      this.setState("DISCONNECTED");
    }
  }

  protected abstract doDisconnect(): Promise<void>;

  async send(request: MCPRequest): Promise<MCPResponse> {
    if (!this.connected) {
      throw new Error("Transport not connected");
    }

    return new Promise((resolve, reject) => {
      this.pendingRequests.set(request.id, { resolve, reject });
      this.doSend(request).catch(reject);
    });
  }

  protected abstract doSend(request: MCPRequest): Promise<void>;
}

import { StdioTransport } from "./stdio-transport";
import { StreamableHttpTransport } from "./streamable-http-transport";
import { SSETransport } from "./sse-transport";
