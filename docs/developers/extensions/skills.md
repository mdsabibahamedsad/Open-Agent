# Building Skills (`type: skill`)

Skill packs bundle prompts, playbooks, and tool wiring that agents can
discover and install (Template Center `/skills`, catalog-backed). Packs are
content + config — behavior stays in versioned tools.

## 1. Define

```typescript
// src/index.ts
import { defineSkill } from "@openagent/extension-sdk";

export default defineSkill({
  name: "incident-triage",
  displayName: "Incident Triage",
  description: "Playbook for triaging production incidents.",
  playbooks: [
    {
      id: "triage",
      steps: [
        "Collect symptoms, scope, and recent deploys.",
        "Classify severity (SEV1-4) with blast radius.",
        "Propose mitigations; escalate SEV1/2 for approval.",
      ],
    },
  ],
  prompts: [
    { id: "triage.prompt", template: "Triage this incident:\n\n{{symptoms}}\n\nSeverity?" },
  ],
  tools: ["calculator.evaluate"],
  evaluators: ["triage-quality@1"],
});
```

Skill content can also ship as Markdown + front-matter under `skills/`:

```markdown
---
id: triage
severity-guide: SEV1 = full outage, SEV2 = degraded, SEV3 = minor, SEV4 = cosmetic
---

# Triage playbook
1. Collect symptoms…
```

## 2. Manifest

```yaml
manifest_version: "1"
name: my-org/incident-triage
version: 1.0.0
display_name: Incident Triage
description: Production incident triage playbook + prompts.
author: {name: Your Name, email: you@example.com}
license: MIT
type: skill
runtime: {language: typescript, entrypoint: src/index.ts}
permissions: [tool:execute]
capabilities: [incident.triage]
compatibility: {openagent: ">=1.0.0 <2.0.0", sdk: ">=1.0.0 <2.0.0",
  extension_api: "1.x", api_version: v1}
security: {trust_level: COMMUNITY, network_policy: none}
```

## 3. Test

```bash
openagent test   # contract: playbooks parse, prompt templates render, tool refs resolve
```

```typescript
import { describe, expect, it } from "vitest";
import skill from "../src/index.js";

describe("incident-triage", () => {
  it("renders the triage prompt", () => {
    const out = (skill as any).renderPrompt("triage.prompt", { symptoms: "500s on /api" });
    expect(out).toContain("500s on /api");
  });
});
```

## 4. Publish

```bash
openagent validate && openagent package && openagent publish
```

Example: `examples/custom-skill`. Marketplace policy (license compat,
content sanitization) applies before catalog listing.
