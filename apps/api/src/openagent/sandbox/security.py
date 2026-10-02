"""Sandbox security policy engine (fail-closed, dependency-light).

Covers network policy (SSRF / metadata / DNS-rebinding guards), filesystem
containment (jail + symlink resolution + forbidden mounts incl. the Docker
socket), environment policy (never inherit host secrets), command policy
(categories, allowlists, structured argv, no shell operators), risk scoring,
and secret redaction (reuses :mod:`openagent.code.security` — no second
redaction implementation).

Repository / AI-generated / workflow / MCP / tool code is UNTRUSTED. Policy
can never be overridden by model-generated instructions.
"""

from __future__ import annotations

import ipaddress
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from openagent.code.security import redact_dict, redact_text  # canonical, reused

__all__ = [
    "NetworkMode", "NETWORK_MODES",
    "CLOUD_METADATA_IPS", "CLOUD_METADATA_HOSTS",
    "FORBIDDEN_MOUNTS", "FORBIDDEN_CONTAINER_PATHS",
    "FORBIDDEN_ENV_NAMES", "ENV_POLICY_ACTIONS",
    "COMMAND_CATEGORIES", "SHELL_OPERATORS",
    "NetworkPolicy", "validate_network_destination", "check_url_against_policy",
    "FilesystemPolicy", "validate_sandbox_path", "validate_mount",
    "EnvironmentPolicy", "build_container_env",
    "CommandPolicy", "parse_argv", "categorize_command",
    "RiskDecision", "score_execution_risk",
    "classify_sandbox_tool_risk",
]

# --------------------------------------------------------------------------
# Network policy
# --------------------------------------------------------------------------

NetworkMode = str
NETWORK_MODES = ("NO_NETWORK", "ALLOWLIST", "RESTRICTED", "FULL_OUTBOUND")
DEFAULT_NETWORK_MODE: NetworkMode = "NO_NETWORK"

# Cloud metadata endpoints that must never be reachable from a sandbox,
# enforced independently of model instructions.
CLOUD_METADATA_IPS = (
    "169.254.169.254",  # AWS / GCP / Azure IMDS
    "169.254.169.123",  # alternative link-local metadata
    "fd00:ec2::254",
)
CLOUD_METADATA_HOSTS = (
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "instance-data-compute",
)

_LOCAL_NAMES = {"localhost", "localhost.localdomain", "localdomain", "host.docker.internal",
                "host.containers.internal", "gateway.docker.internal"}


def _is_forbidden_ip(ip: ipaddress._BaseAddress) -> tuple[bool, str]:
    if any(str(ip) == m for m in CLOUD_METADATA_IPS):
        return True, "cloud metadata endpoint"
    if ip.is_loopback:
        return True, "loopback address"
    if ip.is_private:
        return True, "private network address"
    if ip.is_link_local:
        return True, "link-local address"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True, "non-routable address"
    return False, ""


@dataclass
class NetworkPolicy:
    mode: NetworkMode = DEFAULT_NETWORK_MODE
    allowed_domains: list[str] = field(default_factory=list)
    allowed_ports: list[int] = field(default_factory=list)
    denied_domains: list[str] = field(default_factory=list)

    def normalized(self) -> "NetworkPolicy":
        mode = (self.mode or DEFAULT_NETWORK_MODE).upper()
        if mode not in NETWORK_MODES:
            raise ValueError(f"Unknown network mode '{self.mode}'")
        return NetworkPolicy(
            mode=mode,
            allowed_domains=[d.strip().lower().lstrip(".") for d in self.allowed_domains if d.strip()],
            allowed_ports=[int(p) for p in self.allowed_ports],
            denied_domains=[d.strip().lower().lstrip(".") for d in self.denied_domains if d.strip()],
        )


def _domain_matches(host: str, patterns: list[str]) -> bool:
    host = host.lower()
    for pat in patterns:
        if host == pat or host.endswith("." + pat):
            return True
    return False


def validate_network_destination(host: str, port: Optional[int],
                                 policy: NetworkPolicy,
                                 resolved_ips: Optional[list[str]] = None) -> tuple[bool, str]:
    """Fail-closed destination check.

    ``resolved_ips`` are the DNS answers for ``host`` (DNS-rebinding defense:
    callers should resolve first, then validate every answer). When omitted,
    literal IPs embedded in ``host`` are still validated.
    """
    pol = policy.normalized()
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return False, "empty host"
    if h in CLOUD_METADATA_HOSTS:
        return False, "cloud metadata host is blocked"
    if h in _LOCAL_NAMES:
        return False, "local hostname is blocked"
    if pol.mode == "NO_NETWORK":
        return False, f"network disabled by profile (mode={pol.mode})"
    if _domain_matches(h, pol.denied_domains):
        return False, "domain is explicitly denied"
    if pol.mode == "ALLOWLIST" and not _domain_matches(h, pol.allowed_domains):
        return False, "domain is not on the network allowlist"
    if port is not None and pol.allowed_ports and port not in pol.allowed_ports:
        return False, f"port {port} is not on the allowed-ports list"
    candidates: list[str] = list(resolved_ips or [])
    # A literal IP in the host field is itself a candidate.
    try:
        ipaddress.ip_address(h)
        candidates.append(h)
    except ValueError:
        pass
    for cand in candidates:
        try:
            ip = ipaddress.ip_address(cand)
        except ValueError:
            continue
        bad, reason = _is_forbidden_ip(ip)
        if bad:
            return False, f"resolved address {cand} blocked: {reason}"
    return True, "allowed"


def check_url_against_policy(url: str, policy: NetworkPolicy) -> tuple[bool, str]:
    """Validate a full URL (scheme + host + port) against the network policy."""
    try:
        parts = urlparse(url)
    except Exception:
        return False, "unparseable URL"
    if parts.scheme not in ("http", "https"):
        return False, f"URL scheme '{parts.scheme}' is not allowed"
    if not parts.hostname:
        return False, "URL has no host"
    port = parts.port
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return validate_network_destination(parts.hostname, port, policy)


# --------------------------------------------------------------------------
# Filesystem policy
# --------------------------------------------------------------------------

# Host paths that must never be mounted into a sandbox (broad mounts).
FORBIDDEN_MOUNTS = (
    "/", "C:\\", "C:/", "C:\\Users", "C:/Users", "/home", "/etc", "/var",
    "/root", "/proc", "/sys", "/dev",
    "/var/run/docker.sock", "/run/docker.sock",
    "\\\\.\\pipe\\docker_engine",  # Windows named-pipe socket
)
# Container-side paths that must never be mount targets / writable.
FORBIDDEN_CONTAINER_PATHS = (
    "/var/run/docker.sock", "/run/docker.sock",
    "/proc", "/sys", "/dev",
)
DOCKER_SOCKET_NAMES = ("docker.sock", "docker_engine", "containerd.sock", "crio.sock")


@dataclass
class FilesystemPolicy:
    mode: str = "ISOLATED"  # ISOLATED | WORKSPACE_RW | WORKSPACE_RO
    workspace: str = "/workspace"
    allow_tmp_write: bool = True

    def normalized(self) -> "FilesystemPolicy":
        mode = (self.mode or "ISOLATED").upper()
        if mode not in ("ISOLATED", "WORKSPACE_RW", "WORKSPACE_RO"):
            raise ValueError(f"Unknown filesystem mode '{self.mode}'")
        return FilesystemPolicy(mode=mode, workspace=self.workspace or "/workspace",
                                allow_tmp_write=self.allow_tmp_write)


@dataclass
class PathCheck:
    valid: bool
    reason: str = ""
    resolved: Optional[str] = None


def validate_sandbox_path(workspace_root: str, rel_path: str,
                          must_exist: bool = False) -> PathCheck:
    """Jail a workspace-relative path: no absolutes, no ``..`` escapes, and —
    where the path exists — no symlink escapes (realpath containment)."""
    rel = (rel_path or "").replace("\\", "/").strip()
    if not rel:
        return PathCheck(valid=False, reason="empty path")
    if len(rel) > 1024:
        return PathCheck(valid=False, reason="path too long")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return PathCheck(valid=False, reason="absolute paths are not allowed")
    if re.search(r"[\x00-\x1f\x7f]", rel):
        return PathCheck(valid=False, reason="control characters in path")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return PathCheck(valid=False, reason="path traversal ('..') is not allowed")
    root = Path(workspace_root).resolve()
    candidate = (root.joinpath(*parts) if parts else root)
    # String-level containment first (works for not-yet-existing paths).
    s = str(candidate)
    r = str(root)
    if s != r and not s.startswith(r + "/"):
        return PathCheck(valid=False, reason="path escapes workspace")
    # Realpath containment for existing paths (symlink-escape defense).
    try:
        if candidate.exists() or candidate.is_symlink():
            real = candidate.resolve()
            real.relative_to(root)
    except ValueError:
        return PathCheck(valid=False, reason="symlink escapes workspace")
    except OSError as e:
        return PathCheck(valid=False, reason=f"path stat failed: {e}")
    if must_exist and not candidate.exists():
        return PathCheck(valid=False, reason="path does not exist")
    return PathCheck(valid=True, resolved=str(candidate))


def validate_mount(host_path: str, container_path: str, read_only: bool) -> PathCheck:
    """Validate an explicit mount: no broad host mounts, no socket mounts."""
    hp = (host_path or "").replace("\\", "/").rstrip("/")
    cp = (container_path or "").replace("\\", "/").rstrip("/") or "/"
    if not hp:
        return PathCheck(valid=False, reason="empty host mount path")
    for forbidden in FORBIDDEN_MOUNTS:
        fb = forbidden.replace("\\", "/").rstrip("/") or forbidden
        if hp == fb or hp.startswith(fb + "/"):
            return PathCheck(valid=False, reason=f"host mount '{host_path}' is forbidden")
    lowered = hp.lower()
    if any(name in lowered for name in DOCKER_SOCKET_NAMES):
        return PathCheck(valid=False, reason="container runtime socket mounts are forbidden")
    for forbidden in FORBIDDEN_CONTAINER_PATHS:
        if cp == forbidden or cp.startswith(forbidden + "/"):
            return PathCheck(valid=False, reason=f"container target '{container_path}' is forbidden")
    if not read_only and cp in ("/", "/app", "/runtime"):
        return PathCheck(valid=False, reason=f"container target '{container_path}' must be read-only")
    return PathCheck(valid=True, resolved=f"{host_path}:{container_path}")


# --------------------------------------------------------------------------
# Environment policy
# --------------------------------------------------------------------------

ENV_POLICY_ACTIONS = ("ALLOW", "DENY", "INJECT", "TRANSFORM", "REDACT")

# Names that are never inherited from the host and never injected without an
# explicit credential reference + authorization.
FORBIDDEN_ENV_NAMES = {
    "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_ACCESS_KEY_ID",
    "AZURE_CLIENT_SECRET", "GOOGLE_APPLICATION_CREDENTIALS",
    "DATABASE_URL", "DATABASE_PASSWORD", "DB_PASSWORD",
    "REDIS_URL", "REDIS_PASSWORD",
    "SECRET_KEY", "ENCRYPTION_KEY", "JWT_SECRET",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GIT_TOKEN", "GITHUB_TOKEN",
    "GITLAB_TOKEN", "BITBUCKET_TOKEN", "SSH_AUTH_SOCK",
    "OPENAGENT_API_KEY",
}


@dataclass
class EnvironmentPolicy:
    action: str = "DENY"  # default-deny host inheritance
    allowed_names: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)  # explicit safe values
    # credential_ref -> env name; resolved server-side, never logged
    credential_refs: dict[str, str] = field(default_factory=dict)

    def normalized(self) -> "EnvironmentPolicy":
        action = (self.action or "DENY").upper()
        if action not in ENV_POLICY_ACTIONS:
            raise ValueError(f"Unknown environment action '{self.action}'")
        return EnvironmentPolicy(
            action=action,
            allowed_names=[n.strip() for n in self.allowed_names if n.strip()],
            values=dict(self.values),
            credential_refs=dict(self.credential_refs),
        )


def build_container_env(policy: EnvironmentPolicy,
                        host_env: Optional[dict[str, str]] = None,
                        resolved_credentials: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Build the container environment: minimal safe base + explicit values.

    The host environment is NEVER inherited wholesale. ``resolved_credentials``
    maps env-name -> short-lived secret (already authorized); values are kept
    out of logs by the caller via :func:`redact_text`.
    """
    pol = policy.normalized()
    env: dict[str, str] = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/home/sandbox",
        "LC_ALL": "C.UTF-8",
        "CI": "true",
        "TERM": "dumb",
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_NO_INPUT": "1",
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    }
    for name, value in pol.values.items():
        if name.upper() in FORBIDDEN_ENV_NAMES:
            raise ValueError(f"Refusing to set forbidden env '{name}' as plain value")
        env[name] = value
    if pol.action == "ALLOW":
        for name in pol.allowed_names:
            if name.upper() in FORBIDDEN_ENV_NAMES:
                continue
            if host_env and name in host_env:
                env[name] = host_env[name]
    for ref, name in pol.credential_refs.items():
        # credential refs are the sanctioned path for secrets: resolved
        # server-side, injected as short-lived values, redacted everywhere.
        secret = (resolved_credentials or {}).get(ref) or (resolved_credentials or {}).get(name)
        if secret is None:
            raise ValueError(f"Credential '{ref}' could not be resolved for env '{name}'")
        env[name] = secret
    return env


# --------------------------------------------------------------------------
# Command policy
# --------------------------------------------------------------------------

COMMAND_CATEGORIES = (
    "read", "build", "test", "package", "network", "filesystem",
    "process", "system", "privileged",
)
SHELL_OPERATORS = (";", "&&", "||", "`", "$(", "|", ">", "<", "\n", "\r")


@dataclass
class CommandPolicy:
    allowed_commands: list[str] = field(default_factory=list)  # argv[0] basenames
    denied_commands: list[str] = field(default_factory=list)
    denied_categories: list[str] = field(default_factory=list)
    allow_shell: bool = False

    def normalized(self) -> "CommandPolicy":
        return CommandPolicy(
            allowed_commands=[c.strip().lower() for c in self.allowed_commands if c.strip()],
            denied_commands=[c.strip().lower() for c in self.denied_commands if c.strip()],
            denied_categories=[c.strip().lower() for c in self.denied_categories if c.strip()],
            allow_shell=bool(self.allow_shell),
        )


_PRIVILEGED_BINARIES = {
    "sudo", "su", "doas", "runuser", "setpriv", "chroot", "nsenter",
    "unshare", "mount", "umount", "iptables", "insmod", "modprobe",
    "docker", "podman", "kubectl", "crictl", "ctr", "runc",
}
_NETWORK_BINARIES = {"curl", "wget", "aria2c", "nc", "ncat", "netcat", "ssh", "scp", "sftp",
                     "ftp", "telnet", "socat", "nmap", "tcpdump", "ngrok"}
_PROCESS_BINARIES = {"kill", "killall", "pkill", "pgrep", "ps", "top", "htop"}
_SYSTEM_BINARIES = {"reboot", "shutdown", "poweroff", "halt", "systemctl", "service",
                    "init", "dmesg", "sysctl"}


def categorize_command(binary: str) -> str:
    b = binary.strip().lower()
    if b in _PRIVILEGED_BINARIES:
        return "privileged"
    if b in _NETWORK_BINARIES:
        return "network"
    if b in _PROCESS_BINARIES:
        return "process"
    if b in _SYSTEM_BINARIES:
        return "system"
    if b in {"cat", "less", "more", "head", "tail", "grep", "rg", "sed", "awk", "jq", "ls",
             "find", "stat", "file", "diff", "wc", "sort", "uniq", "cut", "tr"}:
        return "read"
    if b in {"python", "python3", "pytest", "node", "npm", "pnpm", "yarn", "tsc", "eslint",
             "ruff", "mypy", "cargo", "rustc", "go", "javac", "java", "mvn", "gradle",
             "dotnet", "make", "cmake", "ninja", "tsc", "vitest", "jest"}:
        return "build" if b in {"make", "cmake", "ninja", "cargo", "mvn", "gradle",
                                "dotnet", "tsc"} else ("test" if b in {
                                    "pytest", "vitest", "jest"} else "build")
    return "filesystem" if b in {"cp", "mv", "rm", "mkdir", "touch", "ln", "chmod", "chown",
                                 "tar", "unzip", "zip", "rsync"} else "process"


def parse_argv(command: str, allow_shell: bool = False) -> list[str]:
    """Parse to structured argv; rejects shell operators unless explicitly allowed."""
    if not command or not command.strip():
        raise ValueError("Empty command")
    if not allow_shell and any(tok in command for tok in SHELL_OPERATORS):
        raise ValueError("Shell operators are not allowed (structured argv commands only)")
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as e:
        raise ValueError(f"Cannot parse command: {e}")
    if not argv:
        raise ValueError("Empty command")
    binary = argv[0].split("/")[-1].lower()
    if binary in ("bash", "sh", "powershell", "pwsh", "cmd", "cmd.exe", "ash", "zsh", "fish"):
        raise ValueError(f"Interactive shell '{binary}' requires an explicit shell grant")
    return argv


def check_command(command: str, policy: CommandPolicy) -> tuple[bool, str, str]:
    """Returns (allowed, reason, category). Fail-closed."""
    pol = policy.normalized()
    try:
        argv = parse_argv(command, allow_shell=pol.allow_shell)
    except ValueError as e:
        return False, str(e), "system"
    binary = argv[0].split("/")[-1].lower()
    category = categorize_command(binary)
    if binary in pol.denied_commands:
        return False, f"command '{binary}' is explicitly denied", category
    if category in pol.denied_categories:
        return False, f"command category '{category}' is denied", category
    if pol.allowed_commands and binary not in pol.allowed_commands:
        return False, f"command '{binary}' is not on the profile allowlist", category
    return True, "allowed", category


# --------------------------------------------------------------------------
# Risk scoring (the LLM never assigns its own trust level)
# --------------------------------------------------------------------------

@dataclass
class RiskDecision:
    risk_level: str  # LOW | MEDIUM | HIGH | CRITICAL
    risk_reasons: list[str] = field(default_factory=list)
    required_approval: bool = False


def score_execution_risk(*, category: str, network_mode: str,
                         filesystem_mode: str, has_credentials: bool,
                         command: str, target_environment: str = "sandbox",
                         agent_kind: str = "agent") -> RiskDecision:
    reasons: list[str] = []
    level = "LOW"
    approval = False

    def escalate(to: str, reason: str) -> None:
        nonlocal level
        order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        if order.index(to) > order.index(level):
            level = to
        reasons.append(reason)

    if category == "privileged":
        escalate("CRITICAL", "privileged command category")
        approval = True
    elif category in ("network", "system"):
        escalate("HIGH", f"{category} command category")
        approval = True
    elif category in ("build", "package", "test"):
        escalate("MEDIUM", f"{category} execution may run package/build scripts")
    if network_mode in ("ALLOWLIST", "RESTRICTED", "FULL_OUTBOUND"):
        escalate("MEDIUM" if network_mode != "FULL_OUTBOUND" else "HIGH",
                 f"network mode {network_mode}")
        if network_mode == "FULL_OUTBOUND":
            approval = True
    if filesystem_mode == "WORKSPACE_RW":
        escalate("MEDIUM", "writable workspace mount")
    if has_credentials:
        escalate("HIGH", "temporary credentials injected")
        approval = True
    if target_environment.lower() in ("production", "prod"):
        escalate("CRITICAL", "production target environment")
        approval = True
    lowered = command.lower()
    if any(t in lowered for t in ("pip install", "npm install", "npm run", "cargo build",
                                  "curl", "wget", "ssh ")):
        if level == "LOW":
            escalate("MEDIUM", "package install / network-capable invocation")
    return RiskDecision(risk_level=level, risk_reasons=reasons, required_approval=approval)


# --------------------------------------------------------------------------
# Tool risk classification for sandbox.* tools
# --------------------------------------------------------------------------

_SANDBOX_TOOL_RISK = {
    "sandbox.create": "MEDIUM",
    "sandbox.execute": "MEDIUM",
    "sandbox.read": "LOW",
    "sandbox.write": "MEDIUM",
    "sandbox.upload": "MEDIUM",
    "sandbox.download": "LOW",
    "sandbox.stop": "LOW",
    "sandbox.destroy": "MEDIUM",
    "sandbox.images": "LOW",
}


def classify_sandbox_tool_risk(tool_name: str) -> str:
    return _SANDBOX_TOOL_RISK.get(tool_name, "HIGH")


__all__ += ["redact_text", "redact_dict"]
