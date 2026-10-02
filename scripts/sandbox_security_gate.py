#!/usr/bin/env python3
"""Static security gate for sandbox/execution safety (MP18 §104).

Fails closed on known-prohibited patterns:
  - privileged containers / added capabilities
  - container-runtime socket mounts (docker.sock, containerd, CRI-O, named pipe)
  - broad host mounts in deployment manifests
  - unsafe subprocess usage (shell=True, os.system) in shipped code
  - production local-execution fallback defaults
  - hard-coded high-confidence secrets in shipped code

Security policy code, tests, docs, and examples are scoped out of content
rules where they must (by necessity) name these patterns; what matters is
that *deployment manifests* and *shipped runtime code* stay clean.

Exit 0 = pass, 1 = violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VIOLATIONS: list[str] = []


def _files(*suffixes: str, exclude: tuple[str, ...] = ()) -> list[Path]:
    out: list[Path] = []
    for suffix in suffixes:
        out.extend(ROOT.rglob(f"*{suffix}"))
    skip = (".git", "node_modules", ".next", "dist", ".turbo", ".venv",
            "__pycache__", ".pytest_cache", ".ruff_cache", ".pnpm-store")
    return [p for p in out
            if not any(part in skip for part in p.parts)
            and not any(str(p).endswith(e) or e in str(p) for e in exclude)]


def _check(pattern: str, paths: list[Path], what: str,
           allow_in: tuple[str, ...] = ()) -> None:
    rx = re.compile(pattern)
    for path in paths:
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if any(a in rel for a in allow_in):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                VIOLATIONS.append(f"{what}: {rel}:{i}: {line.strip()[:160]}")


def main() -> int:
    manifests = [p for p in _files("Dockerfile", ".yml", ".yaml")
                 if "infrastructure" in str(p) or "docker-compose" in str(p)
                 or str(p).endswith("Dockerfile")]
    py_src = [p for p in _files(".py")
              if "/apps/api/src/" in str(p).replace("\\", "/")
              or "/apps/worker/src/" in str(p).replace("\\", "/")]
    ts_src = [p for p in _files(".ts", ".tsx")
              if "/apps/web/src/" in str(p).replace("\\", "/")
              or "/packages/" in str(p).replace("\\", "/")]

    # 1. Privileged containers / dangerous capabilities in manifests + images.
    _check(r"--privileged\b", manifests, "privileged-flag")
    _check(r"privileged\s*:\s*true", manifests, "privileged-compose")
    _check(r"--cap-add\s+(SYS_ADMIN|NET_ADMIN|SYS_PTRACE|DAC_OVERRIDE|ALL)\b",
           manifests, "dangerous-capability")

    # 2. Runtime socket mounts in manifests (names, not policy discussions).
    _check(r"docker\.sock|containerd\.sock|crio\.sock|docker_engine",
           manifests, "runtime-socket-mount")
    _check(r"/var/run/docker\.sock\s*:", manifests, "runtime-socket-volume")

    # 3. Broad host mounts in deployment manifests.
    for path in manifests:
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if re.match(r"-\s+/(etc|var|home|root|proc|sys|dev)\b", s):
                VIOLATIONS.append(f"broad-host-mount: {rel}:{i}: {s[:160]}")
            if re.match(r"-\s+[A-Z]:\\", s):
                VIOLATIONS.append(f"broad-host-mount: {rel}:{i}: {s[:160]}")

    # 4. Unsafe subprocess usage in shipped runtime code (tests excluded).
    # NOTE: packages/mcp stdio transport spawns *configured* MCP server
    # binaries (the MCP protocol itself, argv-only). Arbitrary code execution
    # through MCP tools must still route via Tool Runtime -> Sandbox (§96).
    # NOTE: openagent/code/review.py *names* these patterns inside its
    # detection rules (that is the scanner, not usage); allow_shell=True is
    # a profile dataclass field, not subprocess shell.
    _check(r"(?<!allow_)shell\s*=\s*True", py_src, "shell-true",
           allow_in=("tests/", "openagent/code/review.py"))
    _check(r"os\.system\s*\(", py_src, "os-system",
           allow_in=("tests/", "openagent/code/review.py"))
    _check(r"child_process|execSync\s*\(", ts_src, "node-exec",
           allow_in=(".test.", "packages/mcp/src/stdio-transport.ts"))

    # 5. Local-execution fallback must never default on in shipped config.
    _check(r"SANDBOX_ALLOW_LOCAL_FALLBACK\s*=\s*true",
           manifests + [ROOT / ".env.example"], "local-fallback-default-on")

    # 6. Hard-coded high-confidence secrets in shipped code (not tests/docs).
    _check(r"ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}",
           py_src + ts_src, "hardcoded-secret", allow_in=("tests/",))

    # 7. Sandbox security tests must exist and cover the escape surface.
    required = ["test_sandbox_security.py", "test_sandbox_adversarial.py",
                "test_sandbox_profiles.py", "test_sandbox_config.py",
                "test_sandbox_providers.py", "test_sandbox_service.py",
                "test_sandbox_api.py"]
    for name in required:
        if not (ROOT / "apps" / "api" / "tests" / name).exists():
            VIOLATIONS.append(f"missing-security-test: apps/api/tests/{name}")

    # 8. Providers must never construct shell strings for `docker`.
    for path in [ROOT / "apps" / "api" / "src" / "openagent" / "sandbox"
                 / "providers.py"]:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if "shell=True" in text or "os.system" in text:
                VIOLATIONS.append(f"shell-in-provider: {path}")

    if VIOLATIONS:
        print("SANDBOX SECURITY GATE: FAIL")
        for v in VIOLATIONS:
            print(f"  - {v}")
        return 1
    print("SANDBOX SECURITY GATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
