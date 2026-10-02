"""Hello-world agent (Python runtime)."""
from openagent_extension import define_agent

agent = define_agent(
    name="hello",
    description="Hello-world agent. Replace with your logic.",
    model={"default": "gpt-4o-mini"},
    system_prompt="Be concise.",
)


@agent.on_run
def run(ctx, input: dict) -> dict:
    return {"ok": True, "input": input}
