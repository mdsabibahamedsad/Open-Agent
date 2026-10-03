import { AbstractTransport } from "./transport";
import { MCPTransportType, MCPRequest, MCPResponse } from "./types";

export class StreamableHttpTransport extends AbstractTransport {
  readonly transportType: MCPTransportType = "streamable_http";
  private baseUrl!: string;
  private sessionId?: string;
  private abortController?: AbortController;

  protected async doConnect(): Promise<void> {
    if (!this.config.endpoint) {
      throw new Error("Streamable HTTP transport requires an endpoint");
    }

    this.validateEndpoint(this.config.endpoint);
    this.baseUrl = this.config.endpoint.replace(/\/$/, "");

    this.abortController = new AbortController();

    const initResult = await this.initialize();
    if (initResult.sessionId) {
      this.sessionId = initResult.sessionId;
    }

    if (initResult.capabilities) {
      this.emit("capabilities", initResult.capabilities);
    }
  }

  private async initialize(): Promise<{
    sessionId?: string;
    capabilities?: unknown;
  }> {
    const response = await this.sendRequest("initialize", {
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

    const result = response.result as
      { sessionId?: string; capabilities?: unknown } | undefined;
    return {
      sessionId: result?.sessionId,
      capabilities: result?.capabilities,
    };
  }

  protected async doDisconnect(): Promise<void> {
    if (this.sessionId) {
      try {
        await this.sendRequest("shutdown", {});
      } catch {
        // Ignore shutdown errors
      }
    }
    this.abortController?.abort();
    this.sessionId = undefined;
  }

  protected async doSend(request: MCPRequest): Promise<void> {
    const url = `${this.baseUrl}/mcp`;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
      "MCP-Protocol-Version": "2024-11-05",
    };

    if (this.sessionId) {
      headers["MCP-Session-Id"] = this.sessionId;
    }

    await this.sendWithRetry(url, headers, request);
  }

  private async sendWithRetry(
    url: string,
    headers: Record<string, string>,
    request: MCPRequest,
    retryCount = 0,
  ): Promise<void> {
    const maxRetries = 3;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(request),
        signal: this.abortController?.signal,
        redirect: "manual",
      });

      if (response.status === 401 && retryCount < maxRetries) {
        // Session might have expired, try to reinitialize
        this.sessionId = undefined;
        await this.initialize();

        if (this.sessionId) {
          headers["MCP-Session-Id"] = this.sessionId;
        }

        return this.sendWithRetry(url, headers, request, retryCount + 1);
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const sessionId = response.headers.get("mcp-session-id");
      if (sessionId) {
        this.sessionId = sessionId;
      }

      const contentType = response.headers.get("content-type") || "";

      if (contentType.includes("text/event-stream")) {
        await this.handleStreamResponse(response, request.id);
      } else {
        const data = (await response.json()) as MCPResponse;
        this.handleResponse(data);
      }
    } catch (error) {
      if (retryCount < maxRetries && this.isRetryableError(error)) {
        await this.sleep(1000 * Math.pow(2, retryCount));
        return this.sendWithRetry(url, headers, request, retryCount + 1);
      }
      throw error;
    }
  }

  private async handleStreamResponse(
    response: Response,
    requestId: string | number,
  ): Promise<void> {
    const reader = response.body?.getReader();
    if (!reader) return;

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        if (trimmed.startsWith("data: ")) {
          const data = trimmed.slice(6);
          try {
            const parsed = JSON.parse(data);
            if (parsed.id === requestId) {
              this.handleResponse(parsed);
            } else if (!parsed.id && parsed.method) {
              this.handleNotification(parsed);
            }
          } catch {
            // Ignore parse errors for non-JSON data
          }
        }
      }
    }
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

  private isRetryableError(error: unknown): boolean {
    if (error instanceof Error) {
      return (
        error.message.includes("ECONNRESET") ||
        error.message.includes("ETIMEDOUT") ||
        error.message.includes("ENOTFOUND") ||
        error.message.includes("network")
      );
    }
    return false;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
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
