import { defineSkill } from "@openagent/extension-sdk";

export default defineSkill({
  name: "incident-triage",
  displayName: "Incident Triage",
  description: "Triage production incidents.",
  playbooks: [
    {
      id: "triage",
      steps: [
        "Collect symptoms, scope, and recent deploys.",
        "Classify severity SEV1-4 with blast radius.",
        "Propose mitigations; escalate SEV1/2 for human approval.",
      ],
    },
  ],
  prompts: [
    { id: "triage.prompt", template: "Triage this incident:\n\n{{symptoms}}\n\nSeverity?" },
  ],
  tools: ["calculator.evaluate"],
  renderPrompt(id: string, vars: Record<string, string>) {
    const p = (this as any).prompts.find((x: any) => x.id === id);
    if (!p) throw new Error(`unknown prompt '${id}'`);
    return Object.entries(vars).reduce((t, [k, v]) => t.replace(`{{${k}}}`, v), p.template);
  },
});
