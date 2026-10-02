import { BrowserDomainPolicyAction, BrowserDomainPolicy } from "../core/types";
import { OpenAgentLogger, createChildLogger } from "@openagent/logger";

const logger = createChildLogger({ module: "browser:security" });

export interface URLValidationResult {
  valid: boolean;
  reason?: string;
  sanitizedUrl?: string;
  policyAction?: BrowserDomainPolicyAction;
}

export interface SecurityConfig {
  allowedSchemes: string[];
  blockedSchemes: string[];
  blockedHosts: string[];
  blockedIpRanges: string[];
  allowLocalhost: boolean;
  allowPrivateIps: boolean;
  allowCloudMetadata: boolean;
  maxRedirects: number;
  validateAfterRedirect: boolean;
  strictMode: boolean;
}

export const defaultSecurityConfig: SecurityConfig = {
  allowedSchemes: ["https", "http"],
  blockedSchemes: [
    "file",
    "ftp",
    "javascript",
    "data",
    "blob",
    "chrome",
    "devtools",
    "chrome-extension",
    "moz-extension",
    "ms-browser-extension",
  ],
  blockedHosts: ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"],
  blockedIpRanges: [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "127.0.0.0/8",
    "::1/128",
    "fe80::/10",
    "fc00::/7",
  ],
  allowLocalhost: false,
  allowPrivateIps: false,
  allowCloudMetadata: false,
  maxRedirects: 10,
  validateAfterRedirect: true,
  strictMode: true,
};

const CLOUD_METADATA_HOSTS = [
  "169.254.169.254",
  "metadata.google.internal",
  "metadata.azure.com",
  "169.254.169.254/latest/meta-data",
  "http://169.254.169.254/latest/meta-data",
  "http://metadata.google.internal/computeMetadata/v1",
  "http://metadata.azure.com/metadata/instance",
];

export class URLSecurityValidator {
  private config: SecurityConfig;
  private domainPolicies: BrowserDomainPolicy[] = [];

  constructor(config: Partial<SecurityConfig> = {}) {
    this.config = { ...defaultSecurityConfig, ...config };
  }

  setDomainPolicies(policies: BrowserDomainPolicy[]): void {
    this.domainPolicies = policies;
  }

  validateUrl(url: string, organizationId?: string): URLValidationResult {
    try {
      const parsed = new URL(url);

      // Check scheme
      const scheme = parsed.protocol.replace(":", "");
      if (!this.config.allowedSchemes.includes(scheme)) {
        return { valid: false, reason: `Scheme '${scheme}' is not allowed` };
      }
      if (this.config.blockedSchemes.includes(scheme)) {
        return { valid: false, reason: `Scheme '${scheme}' is blocked` };
      }

      // Check host
      const hostname = parsed.hostname.toLowerCase();

      // Check blocked hosts
      if (this.config.blockedHosts.includes(hostname)) {
        return { valid: false, reason: `Host '${hostname}' is blocked` };
      }

      // Check IP ranges
      if (this.isIpAddress(hostname)) {
        if (!this.isIpAllowed(hostname)) {
          return {
            valid: false,
            reason: `IP address '${hostname}' is in blocked range`,
          };
        }
      }

      // Check cloud metadata endpoints
      if (
        !this.config.allowCloudMetadata &&
        this.isCloudMetadataEndpoint(parsed)
      ) {
        return { valid: false, reason: "Cloud metadata endpoints are blocked" };
      }

      // Check domain policies
      const policyAction = this.evaluateDomainPolicy(hostname, organizationId);
      if (policyAction === "DENY") {
        return {
          valid: false,
          reason: `Domain '${hostname}' is denied by policy`,
          policyAction: "DENY",
        };
      }
      if (policyAction === "CONFIRM") {
        return {
          valid: true,
          reason: `Domain '${hostname}' requires confirmation`,
          policyAction: "CONFIRM",
        };
      }

      return { valid: true, sanitizedUrl: url, policyAction: policyAction };
    } catch (error) {
      return { valid: false, reason: `Invalid URL: ${String(error)}` };
    }
  }

  validateRedirect(
    originalUrl: string,
    redirectUrl: string,
    organizationId?: string,
  ): URLValidationResult {
    if (!this.config.validateAfterRedirect) {
      return { valid: true, sanitizedUrl: redirectUrl };
    }

    const result = this.validateUrl(redirectUrl, organizationId);
    if (!result.valid) {
      logger.warn("Redirect blocked by security policy", {
        originalUrl,
        redirectUrl,
        reason: result.reason,
      });
    }
    return result;
  }

  private evaluateDomainPolicy(
    hostname: string,
    organizationId?: string,
  ): BrowserDomainPolicyAction {
    let bestMatch: BrowserDomainPolicy | null = null;
    let bestMatchLength = -1;

    for (const policy of this.domainPolicies) {
      if (this.matchesDomain(hostname, policy.domain)) {
        // Check organization scope
        if (policy.organizationId && policy.organizationId !== organizationId) {
          continue;
        }

        const domainLength = policy.domain.length;
        if (domainLength > bestMatchLength) {
          bestMatch = policy;
          bestMatchLength = domainLength;
        }
      }
    }

    return bestMatch?.action || "ALLOW";
  }

  private matchesDomain(hostname: string, policyDomain: string): boolean {
    const normalizedHost = hostname.toLowerCase();
    const normalizedPolicy = policyDomain.toLowerCase();

    // Exact match
    if (normalizedHost === normalizedPolicy) return true;

    // Subdomain match (policy is parent domain)
    if (normalizedPolicy.startsWith(".")) {
      return (
        normalizedHost.endsWith(normalizedPolicy.slice(1)) ||
        normalizedHost === normalizedPolicy.slice(1)
      );
    }

    // Wildcard match
    if (normalizedPolicy.startsWith("*.")) {
      const suffix = normalizedPolicy.slice(2);
      return normalizedHost.endsWith("." + suffix) || normalizedHost === suffix;
    }

    return false;
  }

  private isIpAddress(hostname: string): boolean {
    return (
      /^(\d{1,3}\.){3}\d{1,3}$/.test(hostname) ||
      /^\[?([0-9a-fA-F:]+)\]?$/.test(hostname)
    );
  }

  private isIpAllowed(ip: string): boolean {
    // Remove brackets from IPv6
    const cleanIp = ip.replace(/^\[|\]$/g, "");

    // Check if it's a blocked range
    for (const range of this.config.blockedIpRanges) {
      if (this.ipInRange(cleanIp, range)) {
        return false;
      }
    }

    // Check localhost
    if (
      !this.config.allowLocalhost &&
      (cleanIp === "127.0.0.1" || cleanIp === "::1" || cleanIp === "0.0.0.0")
    ) {
      return false;
    }

    // Check private IPs
    if (!this.config.allowPrivateIps) {
      if (this.isPrivateIp(cleanIp)) {
        return false;
      }
    }

    return true;
  }

  private isPrivateIp(ip: string): boolean {
    // IPv4 private ranges
    const ipv4Match = ip.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
    if (ipv4Match) {
      const [, a, b] = ipv4Match.map(Number);
      // 10.0.0.0/8
      if (a === 10) return true;
      // 172.16.0.0/12
      if (a === 172 && b >= 16 && b <= 31) return true;
      // 192.168.0.0/16
      if (a === 192 && b === 168) return true;
      // 169.254.0.0/16 (link-local)
      if (a === 169 && b === 254) return true;
      // 127.0.0.0/8 (loopback)
      if (a === 127) return true;
    }

    // IPv6 private ranges (simplified)
    if (ip.includes(":")) {
      const lower = ip.toLowerCase();
      if (
        lower === "::1" ||
        lower.startsWith("fe80:") ||
        lower.startsWith("fc00:") ||
        lower.startsWith("fd00:")
      ) {
        return true;
      }
    }

    return false;
  }

  private ipInRange(ip: string, range: string): boolean {
    const [rangeIp, bitsStr] = range.split("/");
    const bits = parseInt(bitsStr, 10);

    if (ip.includes(":")) {
      // IPv6 - simplified check
      return ip.startsWith(rangeIp.split("/")[0]);
    }

    // IPv4
    const ipParts = ip.split(".").map(Number);
    const rangeParts = rangeIp.split(".").map(Number);
    const mask = ~((1 << (32 - bits)) - 1);

    const ipNum =
      (ipParts[0] << 24) | (ipParts[1] << 16) | (ipParts[2] << 8) | ipParts[3];
    const rangeNum =
      (rangeParts[0] << 24) |
      (rangeParts[1] << 16) |
      (rangeParts[2] << 8) |
      rangeParts[3];

    return (ipNum & mask) === (rangeNum & mask);
  }

  private isCloudMetadataEndpoint(url: URL): boolean {
    const hostname = url.hostname.toLowerCase();
    const fullUrl = url.toString().toLowerCase();

    for (const metadataHost of CLOUD_METADATA_HOSTS) {
      if (
        hostname === metadataHost.toLowerCase() ||
        fullUrl.includes(metadataHost.toLowerCase())
      ) {
        return true;
      }
    }
    return false;
  }

  sanitizeUrl(url: string): string {
    try {
      const parsed = new URL(url);
      // Remove sensitive query parameters
      const sensitiveParams = [
        "password",
        "token",
        "api_key",
        "apikey",
        "secret",
        "key",
        "auth",
        "authorization",
      ];
      for (const param of sensitiveParams) {
        if (parsed.searchParams.has(param)) {
          parsed.searchParams.set(param, "[REDACTED]");
        }
      }
      return parsed.toString();
    } catch {
      return url;
    }
  }
}

export class DomainPolicyEngine {
  private policies: Map<string, BrowserDomainPolicy[]> = new Map();

  addPolicy(policy: BrowserDomainPolicy): void {
    const key = this.getPolicyKey(policy);
    if (!this.policies.has(key)) {
      this.policies.set(key, []);
    }
    this.policies.get(key)!.push(policy);
    // Sort by priority (higher first)
    this.policies.get(key)!.sort((a, b) => b.priority - a.priority);
  }

  removePolicy(policyId: string): boolean {
    for (const [key, policies] of this.policies.entries()) {
      const index = policies.findIndex((p) => p.id === policyId);
      if (index !== -1) {
        policies.splice(index, 1);
        return true;
      }
    }
    return false;
  }

  getPolicies(scope: {
    organizationId?: string;
    teamId?: string;
    userId?: string;
    agentId?: string;
    workflowId?: string;
    browserProfileId?: string;
    taskId?: string;
  }): BrowserDomainPolicy[] {
    const results: BrowserDomainPolicy[] = [];

    // Check from most specific to least specific
    const keys = [
      scope.taskId ? `task:${scope.taskId}` : null,
      scope.browserProfileId ? `profile:${scope.browserProfileId}` : null,
      scope.workflowId ? `workflow:${scope.workflowId}` : null,
      scope.agentId ? `agent:${scope.agentId}` : null,
      scope.userId ? `user:${scope.userId}` : null,
      scope.teamId ? `team:${scope.teamId}` : null,
      scope.organizationId ? `org:${scope.organizationId}` : null,
      "global",
    ].filter(Boolean) as string[];

    for (const key of keys) {
      const policies = this.policies.get(key);
      if (policies) {
        results.push(...policies);
      }
    }

    return results;
  }

  evaluate(
    hostname: string,
    scope: {
      organizationId?: string;
      teamId?: string;
      userId?: string;
      agentId?: string;
      workflowId?: string;
      browserProfileId?: string;
      taskId?: string;
    },
  ): BrowserDomainPolicyAction {
    const policies = this.getPolicies(scope);

    for (const policy of policies) {
      if (this.matchesDomain(hostname, policy.domain)) {
        return policy.action;
      }
    }

    return "ALLOW";
  }

  private matchesDomain(hostname: string, policyDomain: string): boolean {
    const normalizedHost = hostname.toLowerCase();
    const normalizedPolicy = policyDomain.toLowerCase();

    if (normalizedHost === normalizedPolicy) return true;
    if (normalizedPolicy.startsWith(".")) {
      return (
        normalizedHost.endsWith(normalizedPolicy.slice(1)) ||
        normalizedHost === normalizedPolicy.slice(1)
      );
    }
    if (normalizedPolicy.startsWith("*.")) {
      const suffix = normalizedPolicy.slice(2);
      return normalizedHost.endsWith("." + suffix) || normalizedHost === suffix;
    }
    return false;
  }

  private getPolicyKey(policy: BrowserDomainPolicy): string {
    if (policy.taskId) return `task:${policy.taskId}`;
    if (policy.browserProfileId) return `profile:${policy.browserProfileId}`;
    if (policy.workflowId) return `workflow:${policy.workflowId}`;
    if (policy.agentId) return `agent:${policy.agentId}`;
    if (policy.userId) return `user:${policy.userId}`;
    if (policy.teamId) return `team:${policy.teamId}`;
    if (policy.organizationId) return `org:${policy.organizationId}`;
    return "global";
  }
}

export const urlSecurityValidator = new URLSecurityValidator();
export const domainPolicyEngine = new DomainPolicyEngine();
