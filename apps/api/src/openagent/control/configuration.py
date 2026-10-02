"""MP26: centralized configuration management (§8) + versioning (§97).

Precedence: Platform -> Organization -> Project -> Environment ->
Execution. Security-restrictive values ALWAYS win over permissive ones
at narrower scopes (a project cannot relax a platform security policy).
Important configuration is versioned (version, actor, timestamp,
changes, rollback reference); critical config is never silently
overwritten.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from openagent.control.types import ConfigScope

SCOPE_RANK = {ConfigScope.PLATFORM: 0, ConfigScope.ORGANIZATION: 1,
              ConfigScope.PROJECT: 2, ConfigScope.ENVIRONMENT: 3,
              ConfigScope.USER: 4}

CONFIG_CATEGORIES = ("platform", "organization", "project", "environment",
                     "runtime", "worker", "region", "security",
                     "observability", "billing")

# Security-sensitive keys: narrower scopes may only make these MORE
# restrictive, never relax them. Values compare by rank where known.
RESTRICTIVE_KEYS: dict[str, dict[str, int]] = {
    "network_policy": {"NO_NETWORK": 0, "INTERNAL_ONLY": 1, "ALLOWLIST": 2,
                       "RESTRICTED": 3, "FULL_OUTBOUND": 4},
    "data_residency": {"PRIVATE_REGION": 0, "ORG_SELECTED": 1, "EU_ONLY": 2,
                       "US_ONLY": 2, "APAC_ONLY": 2, "ANY_REGION": 3},
}


def _more_restrictive(key: str, current: Any, proposed: Any) -> Any:
    ranks = RESTRICTIVE_KEYS.get(key)
    if ranks is None:
        return proposed
    cur_rank = ranks.get(str(current), 99)
    pro_rank = ranks.get(str(proposed), 99)
    # Lower rank = more restrictive. Keep the most restrictive.
    return proposed if pro_rank <= cur_rank else current


@dataclass
class ConfigEntry:
    scope: str
    scope_id: str
    category: str
    key: str
    value: Any
    version: int = 1
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    changes: str = ""


def resolve_config(entries: list[ConfigEntry], *, category: str,
                   key: str) -> tuple[Any, Optional[ConfigEntry]]:
    """Resolve one key across scopes. Returns (value, winning entry)."""
    candidates = [e for e in entries if e.category == category and e.key == key]
    if not candidates:
        return None, None
    candidates.sort(key=lambda e: SCOPE_RANK.get(e.scope, 99))
    value: Any = candidates[0].value
    winner = candidates[0]
    for entry in candidates[1:]:
        if entry.key in RESTRICTIVE_KEYS or entry.category == "security":
            value = _more_restrictive(entry.key, value, entry.value)
        else:
            value = entry.value
        winner = entry
    return value, winner


def resolve_all(entries: list[ConfigEntry]) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    keys = {(e.category, e.key) for e in entries}
    for category, key in sorted(keys):
        value, _ = resolve_config(entries, category=category, key=key)
        resolved.setdefault(category, {})[key] = value
    return resolved


@dataclass
class ConfigVersion:
    version_id: str = field(default_factory=lambda: f"cfgv_{uuid.uuid4().hex[:12]}")
    scope: str = ""
    scope_id: str = ""
    category: str = ""
    key: str = ""
    before: Any = None
    after: Any = None
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    changes: str = ""
    rollback_reference: str = ""

    def sanitized(self) -> dict[str, Any]:
        from openagent.control.observability import redact
        return {"version_id": self.version_id, "scope": self.scope,
                "scope_id": self.scope_id, "category": self.category,
                "key": self.key, "before": redact(copy.deepcopy(self.before)),
                "after": redact(copy.deepcopy(self.after)),
                "created_by": self.created_by,
                "created_at": self.created_at.isoformat(),
                "changes": self.changes,
                "rollback_reference": self.rollback_reference}


def preview_change(current: Any, proposed: Any, *, key: str = "",
                   category: str = "") -> dict[str, Any]:
    """Change preview: current -> proposed + impact summary, no execution."""
    restricted = bool(category == "security" or key in RESTRICTIVE_KEYS)
    relaxing = False
    if restricted and key in RESTRICTIVE_KEYS:
        ranks = RESTRICTIVE_KEYS[key]
        relaxing = ranks.get(str(proposed), 99) > ranks.get(str(current), 99)
    return {"current": current, "proposed": proposed,
            "restricted": restricted,
            "relaxes_security": relaxing,
            "blocked": relaxing,
            "impact": ("relaxes a security restriction and is blocked"
                       if relaxing else
                       "applies on confirmation; versioned for rollback")}
