"""Synchronous OpenAgent client."""

from __future__ import annotations

from typing import Optional

import httpx

from ._http import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, SyncTransport
from .resources import (
    Agents,
    AgentRuns,
    Approvals,
    Billing,
    Connectors,
    Deployments,
    Evaluations,
    Events,
    Executions,
    Extensions,
    Marketplace,
    MCP,
    Memory,
    Models,
    Projects,
    Registries,
    Sandboxes,
    Tools,
    Webhooks,
    Workflows,
)

__all__ = ["OpenAgent"]


class OpenAgent:
    """Synchronous client for the OpenAgent API.

    Example:
        client = OpenAgent(api_key="...", organization_id="org_123")
        agent = client.agents.create(name="support-bot")
    """

    def __init__(
        self,
        api_key: str = "",
        *,
        base_url: str = "http://localhost:8000",
        organization_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        if not api_key:
            import os

            api_key = os.environ.get("OPENAGENT_API_KEY", "")
        if not api_key:
            raise ValueError(
                "api_key is required (pass api_key= or set OPENAGENT_API_KEY)"
            )
        self._transport = SyncTransport(
            api_key=api_key,
            base_url=base_url,
            organization_id=organization_id,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )
        t = self._transport
        self.agents = Agents(t)
        self.agent_runs = AgentRuns(t)
        self.workflows = Workflows(t)
        self.executions = Executions(t)
        self.tools = Tools(t)
        self.connectors = Connectors(t)
        self.mcp = MCP(t)
        self.memory = Memory(t)
        self.models = Models(t)
        self.evaluations = Evaluations(t)
        self.sandboxes = Sandboxes(t)
        self.approvals = Approvals(t)
        self.marketplace = Marketplace(t)
        self.registries = Registries(t)
        self.billing = Billing(t)
        self.projects = Projects(t)
        self.extensions = Extensions(t)
        self.deployments = Deployments(t)
        self.events = Events(t)
        self.webhooks = Webhooks(t)

    @property
    def organization_id(self) -> Optional[str]:
        return self._transport.organization_id

    @property
    def base_url(self) -> str:
        return self._transport.base_url

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "OpenAgent":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
