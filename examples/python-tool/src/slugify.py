"""Slugify tool (Python runtime)."""
import re

from openagent_extension import define_tool

tool = define_tool(
    name="text.slugify",
    description="Convert a title to a URL slug.",
    input_schema={
        "type": "object",
        "properties": {"title": {"type": "string", "maxLength": 200}},
        "required": ["title"],
    },
)


@tool.handler
def slugify(ctx, args: dict) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", args["title"].lower()).strip("-")
    return {"slug": slug or "untitled"}
