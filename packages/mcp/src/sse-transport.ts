import { AbstractTransport } from "./transport";
import { MCPTransportType, MCPRequest, MCPResponse } from "./types";

export class SSETransport extends AbstractTransport {
  readonly transportType: MCPTransportType = "sse";
  private baseUrl!: string;
  private sessionId?: string;
  private eventSource?: EventSource;
  private abortController?: AbortController;

  protected async doConnect(): Promise<void> {
    if (!this.config.endpoint) {
      throw new Error("SSE transport requires an endpoint");
    }

    this.validateEndpoint(this.config.endpoint);
    this.baseUrl = this.config.endpoint.replace(/\/$/, "");

    this.abortController = new AbortController();

    await this.establishConnection();
  }

  private async establishConnection(): Promise<void> {
    const initResponse = await this.sendRequest("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {
        sampling: {},
        roots: { listChanged: true },
        elicitation: {},
      },
      clientInfo: {
        name: "openagent",
        version: "0.1.0",
      },
    });

    const initResult = initResponse.result as
      { sessionId?: string } | undefined;
    if (initResult?.sessionId) {
      this.sessionId = initResult.sessionId;
    }

    await this.connectSSE();
  }

  private async connectSSE(): Promise<void> {
    const url = new URL(`${this.baseUrl}/sse`);
    if (this.sessionId) {
      url.searchParams.set("session_id", this.sessionId);
    }

    // NOTE: EventSource (browser and Node) does not support custom request
    // headers — the session travels via the `session_id` URL parameter set
    // above, and protocol versioning is negotiated in the initialize payload.
    this.eventSource = new EventSource(url.toString());

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.eventSource?.close();
        reject(new Error("SSE connection timeout"));
      }, 10000);

      this.eventSource!.onopen = () => {
        clearTimeout(timeout);
        this.setState("CONNECTED");
        resolve();
      };

      this.eventSource!.onerror = () => {
        clearTimeout(timeout);
        if (this.getState() === "CONNECTING") {
          this.eventSource?.close();
          reject(new Error("SSE connection failed"));
        } else {
          this.setState("DEGRADED");
          this.scheduleReconnect();
        }
      };

      this.eventSource!.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.id !== undefined) {
            this.handleResponse(data);
          } else if (data.method) {
            this.handleNotification(data);
          }
        } catch {
          // Ignore parse errors
        }
      };
    });
  }

  private scheduleReconnect(): void {
    setTimeout(() => {
      if (this.getState() !== "DISCONNECTED") {
        this.connectSSE().catch(() => {
          this.scheduleReconnect();
        });
      }
    }, 5000);
  }

  protected async doDisconnect(): Promise<void> {
    this.eventSource?.close();
    this.eventSource = undefined;
    this.abortController?.abort();
    this.sessionId = undefined;
  }

  protected async doSend(request: MCPRequest): Promise<void> {
    if (!this.sessionId) {
      throw new Error("No active session");
    }

    const url = `${this.baseUrl}/mcp`;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
      "MCP-Protocol-Version": "2024-11-05",
      "MCP-Session-Id": this.sessionId,
    };

    await this.sendHTTPRequest(url, headers, request);
  }

  private async sendHTTPRequest(
    url: string,
    headers: Record<string, string>,
    request: MCPRequest,
  ): Promise<void> {
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(request),
      signal: this.abortController?.signal,
      redirect: "manual",
    });

    if (!response.ok) {
      if (response.status === 401) {
        this.sessionId = undefined;
        await this.establishConnection();
        return this.sendHTTPRequest(url, headers, request);
      }
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = (await response.json()) as MCPResponse;
    this.handleResponse(data);
  }

  private async sendRequest(
    method: string,
    params?: unknown,
  ): Promise<MCPResponse> {
    const request: MCPRequest = {
      jsonrpc: "2.0",
      id: this.generateRequestId(),
      method,
      params,
    };

    return new Promise((resolve, reject) => {
      this.pendingRequests.set(request.id, { resolve, reject });
      this.doSend(request).catch(reject);
    });
  }

  private validateEndpoint(endpoint: string): void {
    const url = new URL(endpoint);

    if (url.protocol !== "https:" && url.protocol !== "http:") {
      throw new Error("Endpoint must use HTTP or HTTPS");
    }

    if (url.protocol === "http:" && process.env.NODE_ENV === "production") {
      const allowedHttpHosts =
        (this.config.configuration?.allowed_http_hosts as string[]) || [];
      if (!allowedHttpHosts.includes(url.hostname)) {
        throw new Error("HTTP endpoints not allowed in production");
      }
    }

    const blockedHosts = ["localhost", "127.0.0.1", "0.0.0.0", "::1"];

    const blockedPatterns = [
      /^10\./,
      /^172\.(1[6-9]|2[0-9]|3[0-1])\./,
      /^192\.168\./,
      /^169\.254\./,
      /^127\./,
    ];

    if (blockedHosts.includes(url.hostname)) {
      throw new Error(`Host ${url.hostname} is blocked`);
    }

    for (const pattern of blockedPatterns) {
      if (pattern.test(url.hostname)) {
        throw new Error(`Host ${url.hostname} matches blocked pattern`);
      }
    }
  }
}
