"""Hello-world tool (Python runtime)."""
from openagent_extension import define_tool

tool = define_tool(
    name="hello.run",
    description="Hello-world tool.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)


@tool.handler
def greet(ctx, args: dict) -> dict:
    return {"greeting": f"Hello, {args['name']}!"}
