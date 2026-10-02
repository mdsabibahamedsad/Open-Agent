import { describe, expect, it } from "vitest";
import { URLSecurityValidator, DomainPolicyEngine } from "./url-validator";

describe("URLSecurityValidator", () => {
  const validator = new URLSecurityValidator();

  it("allows public https URLs", () => {
    const r = validator.validateUrl("https://example.com/path");
    expect(r.valid).toBe(true);
  });

  it("blocks dangerous schemes", () => {
    for (const url of [
      "file:///etc/passwd",
      "javascript:alert(1)",
      "data:text/html,x",
      "ftp://example.com/f",
    ]) {
      expect(validator.validateUrl(url).valid).toBe(false);
    }
  });

  it("blocks localhost, private IPs and metadata endpoints", () => {
    expect(validator.validateUrl("http://localhost:3000").valid).toBe(false);
    expect(validator.validateUrl("http://127.0.0.1/").valid).toBe(false);
    expect(validator.validateUrl("http://10.1.2.3/internal").valid).toBe(false);
    expect(validator.validateUrl("http://192.168.0.1/").valid).toBe(false);
    expect(
      validator.validateUrl("http://169.254.169.254/latest/meta-data").valid,
    ).toBe(false);
  });

  it("enforces DENY domain policy", () => {
    validator.setDomainPolicies([
      {
        id: "1",
        domain: "evil.example",
        action: "DENY",
        priority: 10,
        createdAt: new Date(),
        updatedAt: new Date(),
      },
    ]);
    const r = validator.validateUrl("https://evil.example/phish");
    expect(r.valid).toBe(false);
    validator.setDomainPolicies([]);
  });

  it("flags CONFIRM domains without blocking", () => {
    validator.setDomainPolicies([
      {
        id: "2",
        domain: "review.example",
        action: "CONFIRM",
        priority: 5,
        createdAt: new Date(),
        updatedAt: new Date(),
      },
    ]);
    const r = validator.validateUrl("https://review.example/");
    expect(r.valid).toBe(true);
    expect(r.policyAction).toBe("CONFIRM");
    validator.setDomainPolicies([]);
  });

  it("revalidates redirects", () => {
    const r = validator.validateRedirect(
      "https://example.com",
      "http://127.0.0.1/x",
    );
    expect(r.valid).toBe(false);
  });

  it("sanitizes sensitive query params", () => {
    const out = validator.sanitizeUrl(
      "https://example.com/?token=abc&name=bob",
    );
    expect(out).not.toContain("abc");
    expect(out).toContain("name=bob");
  });
});

describe("DomainPolicyEngine", () => {
  it("most-specific scope wins by priority ordering", () => {
    const engine = new DomainPolicyEngine();
    engine.addPolicy({
      id: "a",
      organizationId: "org1",
      domain: "example.com",
      action: "ALLOW",
      priority: 0,
      createdAt: new Date(),
      updatedAt: new Date(),
    });
    engine.addPolicy({
      id: "b",
      organizationId: "org1",
      domain: "sub.example.com",
      action: "DENY",
      priority: 10,
      createdAt: new Date(),
      updatedAt: new Date(),
    });
    // Policies are priority-sorted; first match in scope order wins.
    expect(engine.evaluate("sub.example.com", { organizationId: "org1" })).toBe(
      "DENY",
    );
    expect(
      engine.evaluate("other.example.com", { organizationId: "org1" }),
    ).toBe("ALLOW");
  });
});
