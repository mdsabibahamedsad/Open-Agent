"""Official connector provider package (MP21).

Each provider module exposes MANIFEST + execute + test + normalize_event.
This index wires them into the global definition registry and resolves
per-action executors for the engine. Third-party connectors plug in via
register_provider without touching core.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

import structlog

from openagent.connectors.registry import registry

logger = structlog.get_logger("openagent.connectors.providers")

Executor = Callable[[str, dict[str, Any], dict[str, Any], dict[str, Any]],
                     Awaitable[dict[str, Any]]]
Tester = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]
Normalizer = Callable[[str, dict[str, Any]], dict[str, Any]]

_PROVIDERS: dict[str, dict[str, Any]] = {}


def register_provider(connector_id: str, *, manifest: dict[str, Any],
                      execute: Executor,
                      test: Optional[Tester] = None,
                      normalize_event: Optional[Normalizer] = None) -> None:
    _PROVIDERS[connector_id] = {"manifest": manifest, "execute": execute,
                                "test": test, "normalize_event": normalize_event}
    registry.register_manifest(manifest)


def get_executor(connector_id: str) -> Optional[Executor]:
    entry = _PROVIDERS.get(connector_id)
    return entry.get("execute") if entry else None


def get_tester(connector_id: str) -> Optional[Tester]:
    entry = _PROVIDERS.get(connector_id)
    return entry.get("test") if entry else None


def get_normalizer(connector_id: str) -> Optional[Normalizer]:
    entry = _PROVIDERS.get(connector_id)
    return entry.get("normalize_event") if entry else None


def provider_ids() -> list[str]:
    return sorted(_PROVIDERS)


def register_official() -> list[str]:
    """Import + register all bundled official connectors. Idempotent."""
    from openagent.connectors.providers import (
        business,
        github,
        gitlab,
        gmail,
        google,
        messaging,
        postgres,
        slack,
    )
    modules = {
        "github": github,
        "gitlab": gitlab,
        "gmail": gmail,
        "slack": slack,
        "google_calendar": google,
        "google_drive": google,
        "notion": business,
        "hubspot": business,
        "postgres": postgres,
        "discord": messaging,
        "telegram": messaging,
    }
    manifests = {
        "github": github.MANIFEST,
        "gitlab": gitlab.MANIFEST,
        "gmail": gmail.MANIFEST,
        "slack": slack.MANIFEST,
        "google_calendar": google.CALENDAR_MANIFEST,
        "google_drive": google.DRIVE_MANIFEST,
        "notion": business.NOTION_MANIFEST,
        "hubspot": business.HUBSPOT_MANIFEST,
        "postgres": postgres.MANIFEST,
        "discord": messaging.DISCORD_MANIFEST,
        "telegram": messaging.TELEGRAM_MANIFEST,
    }

    def _executor_for(connector_id: str, module: Any) -> Executor:
        async def _execute(action_id: str, params: dict[str, Any],
                           auth: dict[str, Any],
                           ctx: dict[str, Any]) -> dict[str, Any]:
            return await module.execute(action_id, params, auth, ctx)
        return _execute

    registered: list[str] = []
    for connector_id, module in modules.items():
        if connector_id in _PROVIDERS:
            registered.append(connector_id)
            continue
        manifest = manifests[connector_id]
        normalizer = getattr(module, "normalize_event", None)
        if connector_id in ("discord", "telegram", "notion", "hubspot",
                            "google_calendar", "google_drive"):
            # Shared modules: keep only matching-manifest actions routable.
            normalizer = getattr(module, "normalize_event", None)
        register_provider(
            connector_id, manifest=manifest,
            execute=_executor_for(connector_id, module),
            test=getattr(module, "test", None),
            normalize_event=normalizer)
        registered.append(connector_id)
    logger.info("official connectors registered", count=len(registered))
    return registered
