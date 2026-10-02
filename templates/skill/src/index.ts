import { defineSkill } from "@openagent/extension-sdk";

export default defineSkill({
  name: "hello-skill",
  displayName: "Hello skill",
  description: "Hello-world skill pack.",
  playbooks: [{ id: "start", steps: ["Say hello.", "Confirm the result."] }],
  prompts: [{ id: "hello.prompt", template: "Say hello to {{name}}." }],
  tools: [],
});
