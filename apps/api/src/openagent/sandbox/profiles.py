"""Sandbox execution profiles: reusable, validated resource+policy bundles.

Profiles: READ_ONLY, TEST, LINT, TYPECHECK, BUILD, PACKAGE, DEVELOPMENT,
DATA_PROCESSING, CUSTOM. Security levels LEVEL_0..LEVEL_4 gate what a
profile may enable; higher levels require explicit policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from openagent.sandbox.security import (
    CommandPolicy,
    EnvironmentPolicy,
    FilesystemPolicy,
    NetworkPolicy,
)

__all__ = [
    "SecurityLevel", "SECURITY_LEVELS",
    "SandboxProfile", "BUILTIN_PROFILES", "get_profile", "list_profiles",
    "validate_profile_dict", "profile_to_dict", "profile_from_dict",
]

SecurityLevel = int
SECURITY_LEVELS = (0, 1, 2, 3, 4)
SECURITY_LEVEL_NAMES = {
    0: "LEVEL_0 — Read-only",
    1: "LEVEL_1 — Restricted execution",
    2: "LEVEL_2 — Controlled network",
    3: "LEVEL_3 — Developer environment",
    4: "LEVEL_4 — Elevated approved execution",
}

# Image trust tiers (§15). Production should use CORE/VERIFIED/ORGANIZATION.
IMAGE_TRUST_TIERS = ("CORE", "VERIFIED", "ORGANIZATION", "CUSTOM", "UNTRUSTED")


@dataclass
class SandboxProfile:
    name: str
    description: str = ""
    security_level: SecurityLevel = 1
    cpu: float = 1.0
    memory_mb: int = 1024
    disk_mb: int = 2048
    pids_limit: int = 128
    timeout_seconds: int = 300
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    filesystem: FilesystemPolicy = field(default_factory=FilesystemPolicy)
    environment: EnvironmentPolicy = field(default_factory=EnvironmentPolicy)
    commands: CommandPolicy = field(default_factory=CommandPolicy)
    image: str = ""
    image_digest: str = ""
    image_trust: str = "CORE"
    readonly_rootfs: bool = True
    allow_artifact_upload: bool = True
    max_artifacts_mb: int = 256
    max_output_bytes: int = 1_000_000

    def validate(self) -> list[str]:
        """Fail-closed validation; returns a list of violations (empty = ok)."""
        problems: list[str] = []
        if not (0.05 <= self.cpu <= 64):
            problems.append(f"cpu {self.cpu} out of range 0.05..64")
        if not (64 <= self.memory_mb <= 65536):
            problems.append(f"memory_mb {self.memory_mb} out of range 64..65536")
        if not (128 <= self.disk_mb <= 102400):
            problems.append(f"disk_mb {self.disk_mb} out of range 128..102400")
        if not (16 <= self.pids_limit <= 8192):
            problems.append(f"pids_limit {self.pids_limit} out of range 16..8192")
        if not (5 <= self.timeout_seconds <= 8 * 3600):
            problems.append(f"timeout_seconds {self.timeout_seconds} out of range 5..28800")
        if self.security_level not in SECURITY_LEVELS:
            problems.append(f"unknown security_level {self.security_level}")
        try:
            self.network.normalized()
        except ValueError as e:
            problems.append(f"network: {e}")
        try:
            self.filesystem.normalized()
        except ValueError as e:
            problems.append(f"filesystem: {e}")
        try:
            self.environment.normalized()
        except ValueError as e:
            problems.append(f"environment: {e}")
        self.commands.normalized()
        if self.image_trust not in IMAGE_TRUST_TIERS:
            problems.append(f"unknown image_trust '{self.image_trust}'")
        if self.image_trust == "UNTRUSTED" and self.security_level < 4:
            problems.append("UNTRUSTED images require security LEVEL_4")
        # Level gates: higher capability requires higher level.
        if self.network.mode != "NO_NETWORK" and self.security_level < 2:
            problems.append(f"network mode {self.network.mode} requires LEVEL_2+")
        if self.network.mode == "FULL_OUTBOUND" and self.security_level < 4:
            problems.append("FULL_OUTBOUND network requires LEVEL_4")
        if not self.readonly_rootfs and self.security_level < 3:
            problems.append("writable rootfs requires LEVEL_3+")
        if self.filesystem.mode == "WORKSPACE_RW" and self.security_level < 1:
            problems.append("WORKSPACE_RW requires LEVEL_1+")
        if self.commands.allow_shell and self.security_level < 3:
            problems.append("shell execution requires LEVEL_3+")
        return problems

    def assert_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise ValueError("Invalid sandbox profile '" + self.name + "': " + "; ".join(problems))


_TEST_COMMANDS = ["python", "python3", "pytest", "node", "npm", "pnpm", "yarn", "go",
                  "cargo", "git", "cat", "ls", "echo", "env", "pwd", "vitest", "jest"]
_LINT_COMMANDS = ["ruff", "mypy", "eslint", "tsc", "flake8", "black", "prettier",
                  "pylint", "clippy", "gofmt", "go vet", "cat", "ls", "echo", "git"]
_BUILD_COMMANDS = ["python", "python3", "node", "npm", "pnpm", "yarn", "tsc", "make",
                   "cmake", "ninja", "cargo", "rustc", "go", "javac", "java", "mvn",
                   "gradle", "dotnet", "git", "cat", "ls", "echo", "tar"]
_PACKAGE_COMMANDS = ["pip", "python", "python3", "node", "npm", "pnpm", "yarn",
                     "cargo", "go", "git", "cat", "ls", "echo", "tar"]


def _base(name: str, description: str, **kw: Any) -> SandboxProfile:
    return SandboxProfile(name=name, description=description, **kw)


BUILTIN_PROFILES: dict[str, SandboxProfile] = {
    "READ_ONLY": _base(
        "READ_ONLY", "File inspection only; no execution.",
        security_level=0, cpu=0.25, memory_mb=256, disk_mb=512, pids_limit=32,
        timeout_seconds=60, readonly_rootfs=True,
        filesystem=FilesystemPolicy(mode="WORKSPACE_RO"),
        commands=CommandPolicy(allowed_commands=["cat", "ls", "head", "tail", "grep", "find", "stat", "file", "diff", "wc", "jq"]),
    ),
    "TEST": _base(
        "TEST", "Unit/integration tests; no network.",
        security_level=1, cpu=1.0, memory_mb=1024, disk_mb=2048, pids_limit=128,
        timeout_seconds=600,
        filesystem=FilesystemPolicy(mode="WORKSPACE_RW"),
        commands=CommandPolicy(allowed_commands=_TEST_COMMANDS),
    ),
    "LINT": _base(
        "LINT", "Linters and formatters; no network.",
        security_level=1, cpu=0.5, memory_mb=512, disk_mb=1024, pids_limit=64,
        timeout_seconds=300,
        filesystem=FilesystemPolicy(mode="WORKSPACE_RW"),
        commands=CommandPolicy(allowed_commands=_LINT_COMMANDS),
    ),
    "TYPECHECK": _base(
        "TYPECHECK", "Type checkers; no network.",
        security_level=1, cpu=0.5, memory_mb=1024, disk_mb=1024, pids_limit=64,
        timeout_seconds=300,
        filesystem=FilesystemPolicy(mode="WORKSPACE_RW"),
        commands=CommandPolicy(allowed_commands=["mypy", "tsc", "pyright", "pyre",
                                                 "clippy", "go vet", "cat", "ls", "echo", "git"]),
    ),
    "BUILD": _base(
        "BUILD", "Compilers and bundlers; no network.",
        security_level=1, cpu=2.0, memory_mb=2048, disk_mb=4096, pids_limit=256,
        timeout_seconds=1200,
        filesystem=FilesystemPolicy(mode="WORKSPACE_RW"),
        commands=CommandPolicy(allowed_commands=_BUILD_COMMANDS),
    ),
    "PACKAGE": _base(
        "PACKAGE", "Dependency installation; restricted network (registries).",
        security_level=2, cpu=1.0, memory_mb=1024, disk_mb=4096, pids_limit=128,
        timeout_seconds=900,
        network=NetworkPolicy(mode="ALLOWLIST", allowed_domains=[
            "pypi.org", "files.pythonhosted.org",
            "registry.npmjs.org", "registry.yarnpkg.com", "npmjs.com",
            "github.com", "objects.githubusercontent.com",
            "crates.io", "static.crates.io", "proxy.golang.org",
            "repo.maven.apache.org", "repo1.maven.org", "plugins.gradle.org",
            "nuget.org", "api.nuget.org",
        ]),
        filesystem=FilesystemPolicy(mode="WORKSPACE_RW"),
        commands=CommandPolicy(allowed_commands=_PACKAGE_COMMANDS),
    ),
    "DEVELOPMENT": _base(
        "DEVELOPMENT", "Interactive-style dev server; restricted network, shell allowed.",
        security_level=3, cpu=2.0, memory_mb=2048, disk_mb=8192, pids_limit=256,
        timeout_seconds=3600, readonly_rootfs=False,
        network=NetworkPolicy(mode="RESTRICTED"),
        filesystem=FilesystemPolicy(mode="WORKSPACE_RW"),
        commands=CommandPolicy(allowed_commands=[], allow_shell=True),
    ),
    "DATA_PROCESSING": _base(
        "DATA_PROCESSING", "Batch data jobs; no network, larger disk.",
        security_level=1, cpu=2.0, memory_mb=4096, disk_mb=10240, pids_limit=128,
        timeout_seconds=3600,
        filesystem=FilesystemPolicy(mode="WORKSPACE_RW"),
        commands=CommandPolicy(allowed_commands=["python", "python3", "node", "cat", "ls",
                                                 "echo", "jq", "csvkit", "git"]),
        max_output_bytes=5_000_000,
    ),
    "CUSTOM": _base(
        "CUSTOM", "Organization-defined; validated like any profile.",
        security_level=1, cpu=1.0, memory_mb=1024, disk_mb=2048, pids_limit=128,
        timeout_seconds=300,
        filesystem=FilesystemPolicy(mode="WORKSPACE_RW"),
        commands=CommandPolicy(allowed_commands=[]),
    ),
}


def get_profile(name: str) -> SandboxProfile:
    try:
        return BUILTIN_PROFILES[name.upper()]
    except KeyError:
        raise ValueError(f"Unknown sandbox profile '{name}'") from None


def list_profiles() -> list[SandboxProfile]:
    return [BUILTIN_PROFILES[k] for k in sorted(BUILTIN_PROFILES)]


def profile_to_dict(p: SandboxProfile) -> dict[str, Any]:
    return {
        "name": p.name, "description": p.description,
        "security_level": p.security_level,
        "cpu": p.cpu, "memory_mb": p.memory_mb, "disk_mb": p.disk_mb,
        "pids_limit": p.pids_limit, "timeout_seconds": p.timeout_seconds,
        "network": {"mode": p.network.mode, "allowed_domains": p.network.allowed_domains,
                    "allowed_ports": p.network.allowed_ports,
                    "denied_domains": p.network.denied_domains},
        "filesystem": {"mode": p.filesystem.mode, "workspace": p.filesystem.workspace,
                       "allow_tmp_write": p.filesystem.allow_tmp_write},
        "environment": {"action": p.environment.action,
                        "allowed_names": p.environment.allowed_names,
                        "values": p.environment.values,
                        "credential_refs": p.environment.credential_refs},
        "commands": {"allowed_commands": p.commands.allowed_commands,
                     "denied_commands": p.commands.denied_commands,
                     "denied_categories": p.commands.denied_categories,
                     "allow_shell": p.commands.allow_shell},
        "image": p.image, "image_digest": p.image_digest, "image_trust": p.image_trust,
        "readonly_rootfs": p.readonly_rootfs,
        "allow_artifact_upload": p.allow_artifact_upload,
        "max_artifacts_mb": p.max_artifacts_mb,
        "max_output_bytes": p.max_output_bytes,
    }


def profile_from_dict(data: dict[str, Any]) -> SandboxProfile:
    net = data.get("network", {})
    fs = data.get("filesystem", {})
    env = data.get("environment", {})
    cmd = data.get("commands", {})
    return SandboxProfile(
        name=str(data.get("name", "CUSTOM")).upper(),
        description=str(data.get("description", "")),
        security_level=int(data.get("security_level", 1)),
        cpu=float(data.get("cpu", 1.0)),
        memory_mb=int(data.get("memory_mb", 1024)),
        disk_mb=int(data.get("disk_mb", 2048)),
        pids_limit=int(data.get("pids_limit", 128)),
        timeout_seconds=int(data.get("timeout_seconds", 300)),
        network=NetworkPolicy(mode=net.get("mode", "NO_NETWORK"),
                              allowed_domains=list(net.get("allowed_domains", [])),
                              allowed_ports=list(net.get("allowed_ports", [])),
                              denied_domains=list(net.get("denied_domains", []))),
        filesystem=FilesystemPolicy(mode=fs.get("mode", "ISOLATED"),
                                    workspace=fs.get("workspace", "/workspace"),
                                    allow_tmp_write=bool(fs.get("allow_tmp_write", True))),
        environment=EnvironmentPolicy(action=env.get("action", "DENY"),
                                      allowed_names=list(env.get("allowed_names", [])),
                                      values=dict(env.get("values", {})),
                                      credential_refs=dict(env.get("credential_refs", {}))),
        commands=CommandPolicy(allowed_commands=list(cmd.get("allowed_commands", [])),
                               denied_commands=list(cmd.get("denied_commands", [])),
                               denied_categories=list(cmd.get("denied_categories", [])),
                               allow_shell=bool(cmd.get("allow_shell", False))),
        image=str(data.get("image", "")),
        image_digest=str(data.get("image_digest", "")),
        image_trust=str(data.get("image_trust", "CUSTOM")),
        readonly_rootfs=bool(data.get("readonly_rootfs", True)),
        allow_artifact_upload=bool(data.get("allow_artifact_upload", True)),
        max_artifacts_mb=int(data.get("max_artifacts_mb", 256)),
        max_output_bytes=int(data.get("max_output_bytes", 1_000_000)),
    )


def validate_profile_dict(data: dict[str, Any]) -> list[str]:
    try:
        return profile_from_dict(data).validate()
    except (ValueError, TypeError, KeyError) as e:
        return [f"profile decode: {e}"]
