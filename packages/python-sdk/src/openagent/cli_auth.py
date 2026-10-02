"""Credential loading shared with the CLI story (env-first)."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

ENV_API_KEY = "OPENAGENT_API_KEY"
ENV_BASE_URL = "OPENAGENT_API_URL"
ENV_ORGANIZATION_ID = "OPENAGENT_ORG"
ENV_ORGANIZATION_ID_ALT = "OPENAGENT_ORGANIZATION_ID"

DEFAULT_BASE_URL = "http://localhost:8000"

__all__ = [
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_ORGANIZATION_ID",
    "DEFAULT_BASE_URL",
    "load_credentials",
    "resolve_config",
]


def load_credentials(env: Optional[Dict[str, str]] = None) -> Dict[str, Optional[str]]:
    """Load credentials from the environment.

    Reads ``OPENAGENT_API_KEY`` / ``OPENAGENT_API_URL`` / ``OPENAGENT_ORG``
    (``OPENAGENT_ORGANIZATION_ID`` is accepted as an alias).
    """
    source = dict(env) if env is not None else dict(os.environ)
    org = source.get(ENV_ORGANIZATION_ID) or source.get(ENV_ORGANIZATION_ID_ALT)
    return {
        "api_key": source.get(ENV_API_KEY),
        "base_url": source.get(ENV_BASE_URL, DEFAULT_BASE_URL),
        "organization_id": org,
    }


def resolve_config(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    organization_id: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Merge explicit arguments over environment credentials."""
    creds = load_credentials(env)
    return {
        "api_key": api_key or creds["api_key"] or "",
        "base_url": base_url or creds["base_url"] or DEFAULT_BASE_URL,
        "organization_id": organization_id or creds["organization_id"],
    }
