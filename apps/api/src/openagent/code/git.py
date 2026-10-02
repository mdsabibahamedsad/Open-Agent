"""Confined git CLI runner.

This module is the ONLY place that spawns git. The Code Agent itself never
touches subprocess/shell: it calls tools -> CodeService -> this runner.

Confinement: allowlisted subcommands, no shell, cwd jailed under an approved
root, timeouts, sanitized environment (no interactive credential prompts),
and redacted errors. MP18's sandbox will swap the transport; the interface
stays the same.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from openagent.code.security import redact_text

# Subcommands the agent plane may invoke. Anything else (e.g. `git daemon`,
# `git instaweb`, shell-ish helpers) is rejected.
ALLOWED_GIT_COMMANDS = {
    "clone", "fetch", "checkout", "branch", "status", "diff", "log", "show",
    "add", "commit", "push", "pull", "merge", "rebase", "tag", "rev-parse",
    "ls-files", "ls-remote", "remote", "stash", "clean", "reset", "rm", "mv",
}

# Flags that are never permitted (interactive, unsafe, or escape-y).
FORBIDDEN_FLAGS = {
    "--upload-pack", "--receive-pack", "--exec", "-c", "--config",
}

DEFAULT_TIMEOUT_SECONDS = 120


@dataclass
class GitResult:
    returncode: int
    stdout: str
    stderr_redacted: str


class GitSecurityError(Exception):
    pass


class GitRunner:
    """Jailed git invocation bound to an approved filesystem root."""

    def __init__(self, root: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self.root = Path(root).resolve()
        self.timeout = timeout_seconds

    def _jail(self, cwd: Optional[str]) -> Path:
        target = (self.root / (cwd or ".")).resolve() if cwd else self.root
        try:
            target.relative_to(self.root)
        except ValueError:
            raise GitSecurityError("git cwd escapes the approved root")
        return target

    @staticmethod
    def _check_args(args: list[str]) -> None:
        if not args:
            raise GitSecurityError("empty git command")
        if args[0] not in ALLOWED_GIT_COMMANDS:
            raise GitSecurityError(f"git subcommand '{args[0]}' is not allowed")
        for a in args[1:]:
            if a in FORBIDDEN_FLAGS:
                raise GitSecurityError(f"git flag '{a}' is not allowed")
            if a.startswith("--upload-pack=") or a.startswith("--receive-pack=") \
                    or a.startswith("--exec=") or a.startswith("-c") or a.startswith("--config"):
                raise GitSecurityError(f"git flag '{a}' is not allowed")

    def _env(self, extra: Optional[dict[str, str]] = None,
             git_config: Optional[dict[str, str]] = None,
             ssh_command: Optional[str] = None) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GIT_TERMINAL_PROMPT": "0",  # never block on credential prompts
            "GIT_SSH_COMMAND": ssh_command
            or os.environ.get("GIT_SSH_COMMAND", "ssh -o BatchMode=yes"),
            "LC_ALL": "C",
        }
        if extra:
            # Only safe, non-secret overrides are accepted.
            for k, v in extra.items():
                if k in {"GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                         "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"}:
                    env[k] = v
        if git_config:
            # Inject `git -c key=value` semantics via environment so secrets
            # never appear in argv or repository config (e.g. http.extraHeader
            # carrying an AUTHORIZATION bearer token for HTTPS remotes).
            env["GIT_CONFIG_COUNT"] = str(len(git_config))
            for i, (k, v) in enumerate(git_config.items()):
                env[f"GIT_CONFIG_KEY_{i}"] = k
                env[f"GIT_CONFIG_VALUE_{i}"] = v
        return env

    async def run(self, args: list[str], cwd: Optional[str] = None,
                  timeout: Optional[int] = None,
                  max_output_bytes: int = 2_000_000,
                  git_config: Optional[dict[str, str]] = None,
                  ssh_command: Optional[str] = None) -> GitResult:
        self._check_args(args)
        workdir = self._jail(cwd)
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args,
                cwd=str(workdir),
                env=self._env(git_config=git_config, ssh_command=ssh_command),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout or self.timeout)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                raise GitSecurityError(f"git {' '.join(args[:2])} timed out")
        except FileNotFoundError:
            raise GitSecurityError("git executable not found on this host")
        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        if len(stdout) > max_output_bytes:
            stdout = stdout[:max_output_bytes] + "\n... [truncated]"
        if len(stderr) > max_output_bytes:
            stderr = stderr[:max_output_bytes] + "\n... [truncated]"
        return GitResult(returncode=proc.returncode or 0,
                         stdout=stdout, stderr_redacted=redact_text(stderr))

    async def check(self, args: list[str], cwd: Optional[str] = None,
                    timeout: Optional[int] = None,
                    git_config: Optional[dict[str, str]] = None,
                    ssh_command: Optional[str] = None) -> str:
        """Run and raise on non-zero exit with a redacted message."""
        res = await self.run(args, cwd=cwd, timeout=timeout,
                             git_config=git_config, ssh_command=ssh_command)
        if res.returncode != 0:
            raise GitSecurityError(
                f"git {' '.join(args[:3])} failed (exit {res.returncode}): "
                f"{res.stderr_redacted[:500]}")
        return res.stdout
