"""MP27: network zero-trust (§48-51). Workload -> policy ->
destination -> allow/deny. Domain allowlists, CIDR, ports, protocols,
environment, workload type. Reuses the connector SSRF engine — no
parallel rule set. Trust zones documented in code for the docs page."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Optional

TRUST_ZONES = (
    "A:public-api", "B:control-plane", "C:worker-plane",
    "D:sandbox", "E:storage", "F:external",
)

# East-west defaults: only the listed flows are allowed without an
# explicit policy entry (§50).
DEFAULT_FLOWS = frozenset({
    ("A:public-api", "B:control-plane"),
    ("B:control-plane", "C:worker-plane"),
    ("C:worker-plane", "D:sandbox"),
    ("C:worker-plane", "E:storage"),
    ("B:control-plane", "E:storage"),
    ("D:sandbox", "F:external"),  # filtered egress only
    ("C:worker-plane", "F:external"),  # filtered egress only
})


@dataclass
class NetworkRule:
    workload: str = ""      # workload kind or workload_id; "" = any
    environment: str = ""   # "" = any
    domains: list[str] = field(default_factory=list)
    cidrs: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    protocols: list[str] = field(default_factory=list)  # https|wss|...
    effect: str = "allow"   # allow|deny

    def validate(self) -> tuple[bool, str]:
        if self.effect not in ("allow", "deny"):
            return False, "effect must be allow|deny"
        for cidr in self.cidrs:
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                return False, f"invalid CIDR {cidr}"
        return True, "ok"


def _ssrf_floor(host: str) -> Optional[str]:
    """Local SSRF floor (loopback/private/link-local/multicast/reserved
    + cloud metadata). Mirrors the connector netsec blocklists so the
    identity layer stays dependency-light and self-hostable; full HTTP
    paths (connectors/browser/MCP/tools) enforce the complete netsec
    engine including DNS-rebinding and redirect checks."""
    from urllib.parse import urlparse
    target = host.strip().lower()
    if target in ("localhost", "metadata.google.internal") or \
            target.endswith(".internal"):
        return f"blocked host {host}"
    if target in ("169.254.169.254", "fd00:ec2::254",
                  "100.100.100.200"):
        return "blocked cloud metadata endpoint"
    try:
        addr = ipaddress.ip_address(target)
    except ValueError:
        return None  # hostname: policy + resolving-layer checks apply
    if addr.is_loopback or addr.is_link_local or addr.is_multicast \
            or addr.is_reserved or addr.is_private or \
            addr.is_unspecified:
        return f"blocked IP {host}"
    return None


def _full_ssrf_check(url: str) -> Optional[str]:
    """Use the complete connector netsec engine when importable."""
    try:
        from openagent.connectors.netsec import SSRFError, assert_url_safe
    except Exception:
        return None  # local floor above already applied
    try:
        assert_url_safe(url)
        return None
    except SSRFError as exc:
        return f"SSRF guard: {exc}"
    except Exception:
        return None  # DNS-dependent checks degrade; policy applies


def _domain_allowed(host: str, allowlist: list[str]) -> bool:
    host = host.lower()
    for entry in allowlist:
        entry = entry.lower().lstrip("*.")
        if host == entry or host.endswith("." + entry):
            return True
    return False


@dataclass
class AccessRequest:
    workload: str
    environment: str
    host: str
    port: int = 443
    protocol: str = "https"
    zone_from: str = ""
    zone_to: str = "F:external"


class NetworkPolicyEngine:
    def __init__(self, rules: Optional[list[NetworkRule]] = None) -> None:
        self._rules = list(rules or [])

    def add(self, rule: NetworkRule) -> None:
        ok, reason = rule.validate()
        if not ok:
            raise ValueError(reason)
        self._rules.append(rule)

    def decide(self, request: AccessRequest) -> tuple[bool, str]:
        # 1. SSRF floor: local checks always run; the full shared engine
        #    adds DNS-rebinding/redirect coverage when importable.
        url = f"{request.protocol}://{request.host}:{request.port}/"
        floor = _ssrf_floor(request.host)
        if floor is not None:
            return False, floor
        full = _full_ssrf_check(url)
        if full is not None:
            return False, full
        # 2. Zone flow default.
        if request.zone_from and request.zone_to:
            if (request.zone_from, request.zone_to) not in DEFAULT_FLOWS:
                # Explicit rule may still open it below; otherwise deny.
                pass
        # 3. Explicit rules: denies win, then allows.
        matched_allow = False
        matched_reason = "no rule allows this destination"
        for rule in self._rules:
            if rule.workload and rule.workload != request.workload:
                continue
            if rule.environment and rule.environment != request.environment:
                continue
            if rule.domains and not _domain_allowed(request.host,
                                                    rule.domains):
                continue
            if rule.ports and request.port not in rule.ports:
                continue
            if rule.protocols and request.protocol not in rule.protocols:
                continue
            if rule.cidrs:
                continue  # CIDR rules apply to resolved IPs at enforcement
            if rule.effect == "deny":
                return False, "denied by network policy"
            matched_allow = True
            matched_reason = "allowed by network policy"
        if request.zone_from and request.zone_to and \
                (request.zone_from, request.zone_to) not in DEFAULT_FLOWS \
                and not matched_allow:
            return False, "cross-zone flow not permitted"
        return matched_allow, matched_reason

    def decide_ip(self, request: AccessRequest, ip: str) -> tuple[bool, str]:
        """CIDR-aware decision once the destination IP is resolved."""
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False, "unresolvable destination"
        for rule in self._rules:
            if rule.workload and rule.workload != request.workload:
                continue
            if rule.environment and rule.environment != request.environment:
                continue
            for cidr in rule.cidrs:
                if addr in ipaddress.ip_network(cidr, strict=False):
                    if rule.effect == "deny":
                        return False, f"denied by CIDR {cidr}"
                    return True, f"allowed by CIDR {cidr}"
        return self.decide(request)
