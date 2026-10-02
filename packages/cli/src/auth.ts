import fs from "node:fs";
import http from "node:http";
import { ApiClient } from "./http.js";
import {
  getProfile,
  maskApiKey,
  removeProfileSecrets,
  saveProfile,
} from "./config.js";

export interface LoginOptions {
  apiKey?: string;
  tokenStdin?: boolean;
  profile?: string;
  org?: string;
  apiUrl?: string;
  port?: number;
  noBrowser?: boolean;
}

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (c) => {
      data += c;
    });
    process.stdin.on("end", () => resolve(data.trim()));
    process.stdin.on("error", reject);
    if (process.stdin.isTTY) resolve("");
  });
}

export async function loginInteractive(
  opts: LoginOptions = {},
): Promise<{ profile: string; apiUrl: string }> {
  const base = getProfile(opts.profile, opts.org);
  const apiUrl = opts.apiUrl ?? base.apiUrl;
  const profileName = opts.profile ?? base.name;

  if (opts.apiKey) {
    saveProfile(profileName, {
      apiUrl,
      apiKey: opts.apiKey.trim(),
      orgId: opts.org ?? base.orgId,
      makeActive: true,
    });
    return { profile: profileName, apiUrl };
  }
  if (opts.tokenStdin) {
    const token = (await readStdin()).trim();
    if (!token)
      throw new Error("No token received on stdin. Pipe a token with --token.");
    saveProfile(profileName, {
      apiUrl,
      apiKey: token,
      orgId: opts.org ?? base.orgId,
      makeActive: true,
    });
    return { profile: profileName, apiUrl };
  }

  // Browser device flow: try server device endpoints, fallback to manual paste.
  const client = new ApiClient({ baseUrl: apiUrl, timeoutMs: 10_000 });
  let device:
    | {
        device_code?: string;
        user_code?: string;
        verification_uri?: string;
        verification_url?: string;
        expires_in?: number;
        interval?: number;
      }
    | undefined;
  try {
    device = await client.post("/api/v1/auth/device/code", {
      scopes: ["developer"],
    });
  } catch {
    device = undefined;
  }
  if (!device || (!device.verification_uri && !device.verification_url)) {
    // Manual fallback: prompt for key.
    process.stdout.write(
      `Open ${apiUrl}/login in your browser, create an API key, then paste it below.\n`,
    );
    process.stdout.write("API key: ");
    const pasted = await readStdinLine();
    if (!pasted) throw new Error("Login cancelled: no API key provided.");
    saveProfile(profileName, {
      apiUrl,
      apiKey: pasted.trim(),
      orgId: opts.org ?? base.orgId,
      makeActive: true,
    });
    return { profile: profileName, apiUrl };
  }

  const verifyUrl =
    device.verification_uri ?? device.verification_url ?? `${apiUrl}/login`;
  process.stdout.write(`\nVisit to authorize:\n  ${verifyUrl}\n`);
  if (device.user_code) process.stdout.write(`Code: ${device.user_code}\n`);
  process.stdout.write("Waiting for authorization… (Ctrl+C to cancel)\n");

  const intervalMs = Math.max(2000, (device.interval ?? 5) * 1000);
  const deadline = Date.now() + (device.expires_in ?? 600) * 1000;
  for (;;) {
    if (Date.now() > deadline)
      throw new Error(
        "Device authorization expired. Run `openagent login` again.",
      );
    await new Promise((r) => setTimeout(r, intervalMs));
    try {
      const tok = await client.post<{
        api_key?: string;
        token?: string;
        access_token?: string;
      }>("/api/v1/auth/device/token", {
        device_code: device.device_code,
      });
      const key = tok.api_key ?? tok.token ?? tok.access_token;
      if (key) {
        saveProfile(profileName, {
          apiUrl,
          apiKey: key,
          orgId: opts.org ?? base.orgId,
          makeActive: true,
        });
        return { profile: profileName, apiUrl };
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (/pending|authorization_pending|slow_down/i.test(msg)) continue;
      // If token endpoint missing, fall back to manual paste.
      if (/404/.test(msg)) {
        process.stdout.write(
          "Server does not support device polling; paste an API key instead.\nAPI key: ",
        );
        const pasted = await readStdinLine();
        if (!pasted) throw new Error("Login cancelled.");
        saveProfile(profileName, {
          apiUrl,
          apiKey: pasted.trim(),
          orgId: opts.org ?? base.orgId,
          makeActive: true,
        });
        return { profile: profileName, apiUrl };
      }
    }
  }
}

function readStdinLine(): Promise<string> {
  return new Promise((resolve) => {
    let data = "";
    const onData = (c: Buffer) => {
      data += c.toString();
      if (data.includes("\n")) {
        cleanup();
        resolve(data.trim());
      }
    };
    const onEnd = () => {
      cleanup();
      resolve(data.trim());
    };
    const cleanup = () => {
      process.stdin.off("data", onData);
      process.stdin.off("end", onEnd);
      process.stdin.pause();
    };
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", onData);
    process.stdin.on("end", onEnd);
    process.stdin.resume();
  });
}

export function logout(profile?: string): boolean {
  const base = getProfile(profile);
  return removeProfileSecrets(base.name);
}

export async function whoami(
  apiUrl: string,
  apiKey: string | undefined,
  orgId: string | undefined,
): Promise<unknown> {
  const client = new ApiClient({ baseUrl: apiUrl, apiKey, orgId });
  // Primary: GET /api/v1/auth/me; fallback: GET /api/v1/developer/sdk for connectivity.
  try {
    return await client.get("/api/v1/auth/me");
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (/404/.test(msg)) {
      const sdk = await client.get("/api/v1/developer/sdk");
      return {
        fallback:
          "auth/me not available; showing developer SDK metadata for connectivity",
        sdk,
        key: maskApiKey(apiKey),
      };
    }
    throw e;
  }
}

export function startLocalCallbackServer(
  port: number,
  onToken: (token: string) => void,
): http.Server {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    const token =
      url.searchParams.get("token") ?? url.searchParams.get("api_key");
    if (token) {
      onToken(token);
      res.writeHead(200, { "Content-Type": "text/plain" });
      res.end("Authorized. You may close this window and return to the CLI.\n");
    } else {
      res.writeHead(400, { "Content-Type": "text/plain" });
      res.end("Missing token parameter.\n");
    }
  });
  server.listen(port);
  void fs;
  return server;
}
