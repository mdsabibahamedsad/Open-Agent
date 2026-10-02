// Automation pack: bundle agents + workflows + connectors.
// Declare members in openagent.yaml (capabilities) and keep each member's
// implementation in its own file; this entrypoint wires them together.
export const members = ["hello-agent", "hello-node", "hello-connector"];
export default { members };
