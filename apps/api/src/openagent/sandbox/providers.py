"""Sandbox isolation providers (provider-neutral interface).

Providers: ``docker`` (initial production transport), ``local`` (explicit
dev-only fallback — NOT a security boundary), ``kubernetes`` (future stub).

The Docker provider shells out to the ``docker`` CLI with fixed argv (no
shell, no string concatenation). That subprocess usage is container-runtime
management — not arbitrary code execution — and is allow-listed in the CI
static gate with this justification.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

import structlog

from openagent.sandbox import security as sec

logger = structlog.get_logger("sandbox.providers")

__all__ = [
    "SandboxStatus", "ExecutionStatus",
    "ContainerSpec", "ExecutionSpec", "ExecutionOutcome",
    "SandboxProvider", "DockerSandboxProvider",
    "LocalSandboxProvider", "KubernetesSandboxProvider",
    "create_provider", "docker_available",
]


class SandboxStatus(str):
    CREATING = "CREATING"
    CREATED = "CREATED"
    STARTING = "STARTING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    DESTROYING = "DESTROYING"
    DESTROYED = "DESTROYED"


class ExecutionStatus(str):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    KILLED = "KILLED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    POLICY_DENIED = "POLICY_DENIED"
    SANDBOX_ERROR = "SANDBOX_ERROR"


@dataclass
class ContainerSpec:
    image: str
    image_digest: str = ""
    command: list[str] = field(default_factory=lambda: ["sleep", "infinity"])
    user: str = "65532:65532"  # non-root by default (nobody-compatible)
    cpu: float = 1.0
    memory_mb: int = 1024
    disk_mb: int = 2048
    pids_limit: int = 128
    readonly_rootfs: bool = True
    tmp_size_mb: int = 256
    network_mode: str = "NO_NETWORK"  # NO_NETWORK | BRIDGED
    mounts: list[dict[str, Any]] = field(default_factory=list)  # {host, container, read_only}
    env: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    stop_timeout_seconds: int = 10


@dataclass
class ExecutionSpec:
    argv: list[str]
    workdir: str = "/workspace"
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 300
    max_output_bytes: int = 1_000_000


@dataclass
class ExecutionOutcome:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    oom_killed: bool = False
    peak_memory_mb: Optional[int] = None
    truncated: bool = False


class SandboxError(Exception):
    pass


class SandboxProvider(Protocol):
    """Provider-neutral isolation interface (§4)."""

    provider_name: str

    async def create(self, spec: ContainerSpec) -> str:
        """Create the sandbox; returns the provider-side handle (container id)."""
        raise NotImplementedError

    async def start(self, handle: str) -> None:
        raise NotImplementedError

    async def execute(self, handle: str, spec: ExecutionSpec) -> ExecutionOutcome:
        raise NotImplementedError

    async def stop(self, handle: str, timeout_seconds: int = 10) -> None:
        raise NotImplementedError

    async def destroy(self, handle: str) -> None:
        raise NotImplementedError

    async def inspect(self, handle: str) -> dict[str, Any]:
        """Provider-side status + resource snapshot (best effort)."""
        raise NotImplementedError


async def docker_available(timeout: float = 5.0) -> tuple[bool, str]:
    """Check the docker CLI + daemon without executing untrusted content."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info", "--format", "{{.ServerVersion}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            return True, out.decode().strip()
        return False, err.decode().strip()[:300]
    except (FileNotFoundError, asyncio.TimeoutError, OSError) as e:
        return False, str(e)[:300]


async def _run_docker(args: list[str], timeout: float = 60.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        out, err = await proc.communicate()
        return 124, out.decode("utf-8", "replace"), "docker CLI timed out"
    return (proc.returncode or 0, out.decode("utf-8", "replace"),
            err.decode("utf-8", "replace"))


def docker_create_argv(spec: ContainerSpec, name: str) -> list[str]:
    """Build the hardened `docker create` argv (§11-§12). Never privileged."""
    args = ["create", "--name", name, "--init",
            "--user", spec.user,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--pids-limit", str(spec.pids_limit),
            "--cpus", str(spec.cpu),
            "--memory", f"{spec.memory_mb}m",
            "--memory-swap", f"{spec.memory_mb}m",
            "--stop-timeout", str(spec.stop_timeout_seconds)]
    if spec.readonly_rootfs:
        args += ["--read-only",
                 "--tmpfs", f"/tmp:rw,noexec,nosuid,size={spec.tmp_size_mb}m",
                 "--tmpfs", "/home/sandbox:rw,nosuid,size=64m"]
    if spec.network_mode == "NO_NETWORK":
        args += ["--network", "none"]
    else:
        # Bridged only when the deployment provides egress filtering
        # (SANDBOX_EGRESS_PROXY); otherwise the manager refuses earlier.
        args += ["--network", "sandbox-egress"]
    for m in spec.mounts:
        check = sec.validate_mount(str(m.get("host", "")), str(m.get("container", "")),
                                   bool(m.get("read_only", True)))
        if not check.valid:
            raise SandboxError(f"Refusing mount: {check.reason}")
        mode = "ro" if m.get("read_only", True) else "rw"
        args += ["--volume", f"{m['host']}:{m['container']}:{mode}"]
    for k, v in spec.labels.items():
        args += ["--label", f"{k}={v}"]
    for k, v in spec.env.items():
        args += ["--env", f"{k}={v}"]
    image = spec.image + (f"@{spec.image_digest}" if spec.image_digest else "")
    args += [image] + list(spec.command)
    return args


class DockerSandboxProvider:
    """Docker container transport. Hardened flags; no privileged, no socket."""

    provider_name = "docker"

    def __init__(self, container_prefix: str = "openagent-sbx-"):
        self.prefix = container_prefix

    async def create(self, spec: ContainerSpec) -> str:
        name = f"{self.prefix}{int(time.time() * 1000)}"
        argv = docker_create_argv(spec, name)
        logger.info("sandbox.docker.create", image=spec.image,
                    cpu=spec.cpu, memory_mb=spec.memory_mb)
        rc, out, err = await _run_docker(argv, timeout=120.0)
        if rc != 0:
            raise SandboxError(f"docker create failed: {err.strip()[:500]}")
        handle = out.strip()
        if not handle:
            raise SandboxError("docker create returned no container id")
        return handle

    async def start(self, handle: str) -> None:
        rc, _, err = await _run_docker(["start", handle], timeout=60.0)
        if rc != 0:
            raise SandboxError(f"docker start failed: {err.strip()[:300]}")

    async def execute(self, handle: str, spec: ExecutionSpec) -> ExecutionOutcome:
        if not spec.argv:
            raise SandboxError("Empty argv")
        started = time.monotonic()
        argv = ["exec", "--user", "65532:65532", "--workdir", spec.workdir]
        for k, v in spec.env.items():
            argv += ["--env", f"{k}={v}"]
        argv += [handle] + list(spec.argv)
        proc = await asyncio.create_subprocess_exec(
            "docker", *argv,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(),
                                              timeout=spec.timeout_seconds)
            timed_out = False
        except asyncio.TimeoutError:
            await self._kill(handle)
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                out, err = b"", b"exec kill timed out"
            timed_out = True
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        truncated = False
        if len(stdout) > spec.max_output_bytes:
            stdout = stdout[:spec.max_output_bytes] + "\n... [truncated]"
            truncated = True
        if len(stderr) > spec.max_output_bytes:
            stderr = stderr[:spec.max_output_bytes] + "\n... [truncated]"
            truncated = True
        oom = await self._oom_flag(handle)
        peak = await self._peak_memory_mb(handle)
        return ExecutionOutcome(
            exit_code=-1 if timed_out else (proc.returncode or 0),
            stdout=stdout, stderr=stderr, duration_ms=duration_ms,
            timed_out=timed_out, oom_killed=oom, peak_memory_mb=peak,
            truncated=truncated)

    async def _kill(self, handle: str) -> None:
        await _run_docker(["kill", handle], timeout=15.0)

    async def _oom_flag(self, handle: str) -> bool:
        rc, out, _ = await _run_docker(
            ["inspect", "--format", "{{.State.OOMKilled}}", handle], timeout=15.0)
        return rc == 0 and out.strip().lower() == "true"

    async def _peak_memory_mb(self, handle: str) -> Optional[int]:
        rc, out, _ = await _run_docker(
            ["stats", "--no-stream", "--format", "{{.MemUsage}}", handle],
            timeout=15.0)
        if rc != 0 or not out.strip():
            return None
        try:
            used = out.strip().split("/")[0].strip().lower()
            if used.endswith("gib"):
                return int(float(used[:-3]) * 1024)
            if used.endswith("mib"):
                return int(float(used[:-3]))
            if used.endswith("kib"):
                return int(float(used[:-3]) / 1024)
        except (ValueError, IndexError):
            return None
        return None

    async def stop(self, handle: str, timeout_seconds: int = 10) -> None:
        await _run_docker(["stop", "--time", str(timeout_seconds), handle],
                          timeout=timeout_seconds + 30.0)

    async def destroy(self, handle: str) -> None:
        await _run_docker(["rm", "--force", handle], timeout=60.0)

    async def inspect(self, handle: str) -> dict[str, Any]:
        rc, out, _ = await _run_docker(["inspect", handle], timeout=15.0)
        if rc != 0:
            return {"handle": handle, "available": False}
        try:
            data = json.loads(out)[0]
            state = data.get("State", {})
            return {"handle": handle, "available": True,
                    "running": state.get("Running"), "status": state.get("Status"),
                    "oom_killed": state.get("OOMKilled"),
                    "privileged": data.get("HostConfig", {}).get("Privileged"),
                    "mounts": [m.get("Destination")
                               for m in data.get("Mounts", [])]}
        except (ValueError, IndexError, KeyError):
            return {"handle": handle, "available": False}


class LocalSandboxProvider:
    """Explicit dev-only fallback. Executes with argv confinement on the host.

    WARNING: this is NOT a security boundary (no container isolation). It
    exists for development/CI without Docker and refuses production use.
    """

    provider_name = "local"

    def __init__(self, root: str, max_output_bytes: int = 1_000_000):
        from pathlib import Path as _P
        self.root = _P(root).resolve()
        self.max_output = max_output_bytes
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    async def create(self, spec: ContainerSpec) -> str:
        import uuid as _u
        return f"local-{_u.uuid4().hex[:16]}"

    async def start(self, handle: str) -> None:
        return None

    async def execute(self, handle: str, spec: ExecutionSpec) -> ExecutionOutcome:
        from pathlib import Path as _P
        target = _P(spec.workdir).resolve() if _P(spec.workdir).is_absolute() \
            else (self.root / spec.workdir).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            raise SandboxError("Execution workdir escapes the sandbox root")
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *spec.argv, cwd=str(target), env={k: str(v) for k, v in spec.env.items()},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self._procs[handle] = proc
        try:
            out, err = await asyncio.wait_for(proc.communicate(),
                                              timeout=spec.timeout_seconds)
            timed_out = False
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            out, err = await proc.communicate()
            timed_out = True
        finally:
            self._procs.pop(handle, None)
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = out.decode("utf-8", "replace")[:self.max_output]
        stderr = err.decode("utf-8", "replace")[:self.max_output]
        return ExecutionOutcome(exit_code=-1 if timed_out else (proc.returncode or 0),
                                stdout=stdout, stderr=stderr,
                                duration_ms=duration_ms, timed_out=timed_out)

    async def stop(self, handle: str, timeout_seconds: int = 10) -> None:
        proc = self._procs.pop(handle, None)
        if proc is None:
            return None
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def destroy(self, handle: str) -> None:
        await self.stop(handle)

    async def inspect(self, handle: str) -> dict[str, Any]:
        return {"handle": handle, "available": True, "provider": "local",
                "security_boundary": False}


class KubernetesSandboxProvider:
    """Future-compatible Kubernetes transport (§53). Not implemented in MP18."""

    provider_name = "kubernetes"

    def __init__(self, *_: Any, **__: Any):
        raise SandboxError(
            "Kubernetes provider is a future extension (MP18 non-goal): "
            "use SANDBOX_PROVIDER=docker or an explicit dev-only local fallback.")


def create_provider(name: str, **kwargs: Any) -> SandboxProvider:
    n = (name or "docker").lower()
    if n == "docker":
        return DockerSandboxProvider(**kwargs)
    if n == "local":
        return LocalSandboxProvider(**kwargs)
    if n in ("kubernetes", "k8s"):
        return KubernetesSandboxProvider(**kwargs)
    raise SandboxError(f"Unknown sandbox provider '{name}'")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _shlex_quote(argv: list[str]) -> str:  # audit-safe logging helper
    return " ".join(shlex.quote(a) for a in argv)
