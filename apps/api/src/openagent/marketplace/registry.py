"""MP23: registry model — official/community/private/git/self-hosted/enterprise.

No registry is trusted implicitly (``IMPLICITLY_TRUSTED_REGISTRIES`` is
empty). Fetching from a registry requires: enabled + marketplace opt-in +
signature policy satisfied. Mirroring is configuration (mirror_of +
provider chain), not a sync engine — full CDN sync is MP24.
"""

from __future__ import annotations

from typing import Any


def registry_usable(registry: dict[str, Any]) -> tuple[bool, str]:
    if not registry.get("enabled", True):
        return False, "registry disabled"
    return True, "ok"


def registry_trust_ok(*, registry_trust: str, minimum: str,
                      ranks: dict[str, int] | None = None) -> bool:
    order = ranks or {"UNTRUSTED": 0, "COMMUNITY": 1, "ORGANIZATION": 2,
                      "VERIFIED": 3, "CORE": 4, "OFFICIAL": 4}
    return order.get(str(registry_trust).upper(), 0) >= order.get(
        str(minimum).upper(), 0)


def signature_policy_ok(*, policy: dict[str, Any],
                        signature_status: str) -> tuple[bool, str]:
    """Enforce a registry's signature policy against an artifact status."""
    if policy.get("require_signed"):
        if signature_status != "VALID":
            return False, "registry requires a VALID signature"
    blocked = {str(s).upper() for s in (policy.get("block_statuses") or [])}
    if str(signature_status).upper() in blocked:
        return False, f"signature status {signature_status} blocked by registry"
    return True, "ok"


def mirror_chain(registry: dict[str, Any],
                 by_slug: dict[str, dict[str, Any]]) -> list[str]:
    """Resolve mirror_of chain for display (cycle-safe, no fetching)."""
    chain: list[str] = []
    seen = {str(registry.get("slug", ""))}
    current = registry
    while current.get("mirror_of"):
        parent_slug = str(current["mirror_of"])
        if parent_slug in seen:
            chain.append(f"{parent_slug} (cycle)")
            break
        seen.add(parent_slug)
        chain.append(parent_slug)
        current = by_slug.get(parent_slug, {})
        if not current:
            break
    return chain
