"""Asynchronous OpenAgent client."""

from __future__ import annotations

from typing import Optional

import httpx

from ._http import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, AsyncTransport
from .resources import (
    AsyncAgents,
    AsyncAgentRuns,
    AsyncApprovals,
    AsyncBilling,
    AsyncConnectors,
    AsyncDeployments,
    AsyncEvaluations,
    AsyncEvents,
    AsyncExecutions,
    AsyncExtensions,
    AsyncMarketplace,
    AsyncMCP,
    AsyncMemory,
    AsyncModels,
    AsyncProjects,
    AsyncRegistries,
    AsyncSandboxes,
    AsyncTools,
    AsyncWebhooks,
    AsyncWorkflows,
)

__all__ = ["AsyncOpenAgent"]


class AsyncOpenAgent:
    """Asynchronous client for the OpenAgent API (``httpx.AsyncClient``).

    Example:
        async with AsyncOpenAgent(api_key="...", organization_id="org_123") as client:
            agent = await client.agents.create(name="support-bot")
    """

    def __init__(
        self,
        api_key: str = "",
        *,
        base_url: str = "http://localhost:8000",
        organization_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if not api_key:
            import os

            api_key = os.environ.get("OPENAGENT_API_KEY", "")
        if not api_key:
            raise ValueError(
                "api_key is required (pass api_key= or set OPENAGENT_API_KEY)"
            )
        self._transport = AsyncTransport(
            api_key=api_key,
            base_url=base_url,
            organization_id=organization_id,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )
        t = self._transport
        self.agents = AsyncAgents(t)
        self.agent_runs = AsyncAgentRuns(t)
        self.workflows = AsyncWorkflows(t)
        self.executions = AsyncExecutions(t)
        self.tools = AsyncTools(t)
        self.connectors = AsyncConnectors(t)
        self.mcp = AsyncMCP(t)
        self.memory = AsyncMemory(t)
        self.models = AsyncModels(t)
        self.evaluations = AsyncEvaluations(t)
        self.sandboxes = AsyncSandboxes(t)
        self.approvals = AsyncApprovals(t)
        self.marketplace = AsyncMarketplace(t)
        self.registries = AsyncRegistries(t)
        self.billing = AsyncBilling(t)
        self.projects = AsyncProjects(t)
        self.extensions = AsyncExtensions(t)
        self.deployments = AsyncDeployments(t)
        self.events = AsyncEvents(t)
        self.webhooks = AsyncWebhooks(t)

    @property
    def organization_id(self) -> Optional[str]:
        return self._transport.organization_id

    @property
    def base_url(self) -> str:
        return self._transport.base_url

    async def aclose(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> "AsyncOpenAgent":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
