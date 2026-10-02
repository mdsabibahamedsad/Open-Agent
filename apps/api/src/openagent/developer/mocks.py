"""MP28: deterministic standard mocks (§59) for extension tests.

Every mock is side-effect free, seeded, and safe to run offline:
LLM, Tool, Connector, MCP, Browser, Sandbox, Memory, Workflow, Agent,
Webhook, Storage. Deterministic: same seed -> same outputs.
"""

from __future__ import annotations

import hashlib
from typing import Any


def _pick(seed: str, options: list[Any]) -> Any:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return options[int(digest, 16) % len(options)]


class MockLLM:
    def __init__(self, seed: str = "openagent"):
        self.seed = seed
        self.calls: list[dict] = []

    def complete(self, prompt: str, **kwargs: Any) -> dict:
        self.calls.append({"prompt": prompt, **kwargs})
        return {
            "text": f"[mock completion for: {prompt[:64]}]",
            "model": kwargs.get("model", "mock-smart"),
            "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": 16},
        }


class MockToolRuntime:
    def __init__(self, seed: str = "openagent"):
        self.seed = seed
        self.invocations: list[dict] = []

    def invoke(self, tool: str, args: dict) -> dict:
        self.invocations.append({"tool": tool, "args": args})
        return {"ok": True, "tool": tool, "output": {"echo": args}}


class MockConnector:
    def __init__(self, connector: str = "mock-crm", seed: str = "openagent"):
        self.connector = connector
        self.seed = seed

    def action(self, action: str, payload: dict | None = None) -> dict:
        return {"ok": True, "connector": self.connector, "action": action,
                "result": {"id": f"mock-{abs(hash(action)) % 9999}", "input": payload or {}}}


class MockMCP:
    def __init__(self, server: str = "mock-mcp", seed: str = "openagent"):
        self.server = server
        self.seed = seed
        self.connected = False

    def connect(self) -> dict:
        self.connected = True
        return {"server": self.server, "state": "connected",
                "capabilities": ["tools", "resources", "prompts"]}

    def call_tool(self, tool: str, args: dict) -> dict:
        if not self.connected:
            raise RuntimeError("mock MCP server is not connected")
        return {"tool": tool, "output": {"echo": args}}


class MockBrowser:
    def __init__(self, seed: str = "openagent"):
        self.seed = seed
        self.actions: list[dict] = []

    def goto(self, url: str) -> dict:
        self.actions.append({"type": "goto", "url": url})
        return {"ok": True, "url": url, "title": "Mock Page"}

    def extract(self, selector: str = "body") -> dict:
        return {"selector": selector, "text": "[mock extracted text]"}


class MockSandbox:
    def __init__(self, seed: str = "openagent"):
        self.seed = seed
        self.executions: list[dict] = []

    def execute(self, command: str) -> dict:
        self.executions.append({"command": command})
        if "rm -rf" in command or "mkfs" in command:
            return {"ok": False, "error": "POLICY_DENIED: destructive command refused by mock"}
        return {"ok": True, "stdout": f"[mock output of: {command[:80]}]", "exit_code": 0}


class MockMemory:
    def __init__(self, seed: str = "openagent"):
        self.seed = seed
        self._store: dict[str, str] = {}

    def write(self, key: str, value: str) -> dict:
        self._store[key] = value
        return {"ok": True, "key": key}

    def read(self, key: str) -> dict:
        return {"key": key, "value": self._store.get(key)}


class MockWorkflow:
    def __init__(self, seed: str = "openagent"):
        self.seed = seed

    def run(self, workflow: str, inputs: dict | None = None) -> dict:
        return {"workflow": workflow, "status": "SUCCEEDED", "outputs": dict(inputs or {})}


class MockAgent:
    def __init__(self, name: str = "mock-agent", seed: str = "openagent"):
        self.name = name
        self.seed = seed

    def run(self, task: str) -> dict:
        verdict = _pick(f"{self.seed}:{task}", ["SUCCEEDED", "SUCCEEDED", "NEEDS_REVIEW"])
        return {"agent": self.name, "status": verdict, "result": f"[mock result for: {task[:64]}]"}


class MockWebhook:
    def __init__(self, secret: str = "mock-secret"):
        self.secret = secret
        self.deliveries: list[dict] = []

    def send(self, event: str, payload: dict) -> dict:
        import json

        from openagent.developer.errors import sign_webhook

        body = json.dumps({"event": event, "payload": payload}).encode()
        header = sign_webhook(self.secret, body, delivery_id=f"mock-{len(self.deliveries)}")
        self.deliveries.append({"event": event, "header": header})
        return {"event": event, "signature": header}


class MockStorage:
    def __init__(self):
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> dict:
        self._objects[key] = data
        return {"ok": True, "key": key, "bytes": len(data)}

    def get(self, key: str) -> bytes | None:
        return self._objects.get(key)
