"""Repository providers: provider-neutral git access.

Protocol + adapters for local git, generic remotes, GitHub, GitLab,
Bitbucket, and self-hosted git. Authentication arrives as an opaque
``GitAuth`` built server-side by the credential system — raw tokens/keys
never appear in tool input, prompts, logs, or errors.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol
from urllib.parse import urlparse

import httpx
import structlog

from openagent.code.git import GitRunner, GitSecurityError
from openagent.code.security import redact_text

logger = structlog.get_logger("code.providers")


@dataclass
class GitAuth:
    """Resolved authentication. Internal only — never serialized to logs/tools."""

    kind: str = "none"  # none | https_token | ssh_key | basic
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    ssh_key_path: Optional[str] = None

    def git_config(self) -> dict[str, str]:
        if self.kind == "https_token" and self.token:
            return {"http.extraHeader": f"AUTHORIZATION: Bearer {self.token}"}
        if self.kind == "basic" and self.username and self.password:
            import base64
            raw = f"{self.username}:{self.password}".encode()
            return {"http.extraHeader":
                    f"AUTHORIZATION: Basic {base64.b64encode(raw).decode()}"}
        return {}

    def ssh_command(self) -> Optional[str]:
        if self.kind == "ssh_key" and self.ssh_key_path:
            return (f"ssh -i {self.ssh_key_path} -o BatchMode=yes "
                    f"-o StrictHostKeyChecking=accept-new")
        return None


CredentialResolver = Callable[[str], Awaitable[GitAuth]]


@dataclass
class RepositoryInfo:
    external_id: str
    name: str
    full_name: str
    clone_url: str
    default_branch: str = "main"
    visibility: str = "private"
    provider: str = "generic"
    web_url: Optional[str] = None


@dataclass
class CloneResult:
    path: str
    head_sha: str
    branch: str


class RepositoryProvider(Protocol):
    provider_id: str

    async def connect(self, info: RepositoryInfo, auth: GitAuth) -> dict[str, Any]:
        """Validate reachability/credentials without cloning. ..."""

    async def list_repositories(self, auth: GitAuth, **filters: Any) -> list[RepositoryInfo]:
        ...

    async def get_repository(self, auth: GitAuth, external_id: str) -> RepositoryInfo:
        ...

    async def clone(self, info: RepositoryInfo, auth: GitAuth, dest: str,
                    ref: Optional[str] = None) -> CloneResult:
        ...

    async def fetch(self, repo_path: str, auth: GitAuth,
                    remote: str = "origin") -> None:
        ...

    async def push(self, repo_path: str, auth: GitAuth, refspec: str,
                   force: bool = False) -> None:
        ...


def _is_https_url(url: str) -> bool:
    return urlparse(url).scheme in ("http", "https")


class LocalGitProvider:
    """Clones/links local git repositories (file paths or file:// URLs)."""

    provider_id = "local"

    def __init__(self, runner: GitRunner):
        self.runner = runner

    async def connect(self, info: RepositoryInfo, auth: GitAuth) -> dict[str, Any]:
        path = info.clone_url.replace("file://", "")
        gitdir = Path(path) / ".git"
        if not (Path(path).is_dir() and (gitdir.is_dir() or (Path(path) / "HEAD").exists())):
            raise GitSecurityError(f"Not a git repository: {info.name}")
        return {"ok": True, "provider": self.provider_id}

    async def list_repositories(self, auth: GitAuth, **filters: Any) -> list[RepositoryInfo]:
        raise GitSecurityError("Local provider cannot enumerate repositories")

    async def get_repository(self, auth: GitAuth, external_id: str) -> RepositoryInfo:
        raise GitSecurityError("Local provider has no registry; connect with explicit path")

    async def clone(self, info: RepositoryInfo, auth: GitAuth, dest: str,
                    ref: Optional[str] = None) -> CloneResult:
        await self.connect(info, auth)
        args = ["clone", "--quiet", info.clone_url, dest]
        if ref:
            args = ["clone", "--quiet", "--branch", ref, info.clone_url, dest]
        await self.runner.check(args)
        sha = (await self.runner.check(["rev-parse", "HEAD"], cwd=dest)).strip()
        branch = (await self.runner.check(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest)).strip()
        return CloneResult(path=dest, head_sha=sha, branch=branch)

    async def fetch(self, repo_path: str, auth: GitAuth, remote: str = "origin") -> None:
        await self.runner.check(["fetch", "--prune", remote], cwd=repo_path)

    async def push(self, repo_path: str, auth: GitAuth, refspec: str,
                   force: bool = False) -> None:
        args = ["push", "origin", refspec]
        if force:
            args = ["push", "--force-with-lease", "origin", refspec]
        await self.runner.check(args, cwd=repo_path)


class GenericGitProvider:
    """Any HTTPS/SSH git remote. No provider-specific logic lives here."""

    provider_id = "generic"

    def __init__(self, runner: GitRunner):
        self.runner = runner

    async def connect(self, info: RepositoryInfo, auth: GitAuth) -> dict[str, Any]:
        out = await self.runner.check(
            ["ls-remote", "--heads", info.clone_url],
            git_config=auth.git_config(), ssh_command=auth.ssh_command())
        return {"ok": True, "provider": self.provider_id,
                "refs": len(out.strip().splitlines())}

    async def list_repositories(self, auth: GitAuth, **filters: Any) -> list[RepositoryInfo]:
        raise GitSecurityError("Generic git remote cannot enumerate repositories")

    async def get_repository(self, auth: GitAuth, external_id: str) -> RepositoryInfo:
        raise GitSecurityError("Generic git remote has no registry; connect with explicit URL")

    async def clone(self, info: RepositoryInfo, auth: GitAuth, dest: str,
                    ref: Optional[str] = None) -> CloneResult:
        args = ["clone", "--quiet", info.clone_url, dest]
        if ref:
            args = ["clone", "--quiet", "--branch", ref, info.clone_url, dest]
        await self.runner.check(args, git_config=auth.git_config(),
                                ssh_command=auth.ssh_command())
        # Scrub any token-bearing remote URL back to the clean URL.
        try:
            await self.runner.check(["remote", "set-url", "origin", info.clone_url],
                                    cwd=dest)
        except GitSecurityError:
            pass
        sha = (await self.runner.check(["rev-parse", "HEAD"], cwd=dest)).strip()
        branch = (await self.runner.check(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest)).strip()
        return CloneResult(path=dest, head_sha=sha, branch=branch)

    async def fetch(self, repo_path: str, auth: GitAuth, remote: str = "origin") -> None:
        await self.runner.check(["fetch", "--prune", remote], cwd=repo_path,
                                git_config=auth.git_config(),
                                ssh_command=auth.ssh_command())

    async def push(self, repo_path: str, auth: GitAuth, refspec: str,
                   force: bool = False) -> None:
        args = ["push", "origin", refspec]
        if force:
            args = ["push", "--force-with-lease", "origin", refspec]
        await self.runner.check(args, cwd=repo_path, git_config=auth.git_config(),
                                ssh_command=auth.ssh_command())


class _HostedGitProvider(GenericGitProvider):
    """Base for hosted forges: URL building + REST listing (server-side token)."""

    api_base: str = ""
    web_base: str = ""

    def _headers(self, auth: GitAuth) -> dict[str, str]:
        if auth.kind == "https_token" and auth.token:
            return {"Authorization": f"Bearer {auth.token}"}
        return {}

    def build_clone_url(self, full_name: str, prefer_ssh: bool = False) -> str:
        raise NotImplementedError


class GitHubProvider(_HostedGitProvider):
    provider_id = "github"
    api_base = "https://api.github.com"
    web_base = "https://github.com"

    def __init__(self, runner: GitRunner, api_base: str = "https://api.github.com",
                 web_base: str = "https://github.com"):
        super().__init__(runner)
        self.api_base = api_base.rstrip("/")
        self.web_base = web_base.rstrip("/")

    def build_clone_url(self, full_name: str, prefer_ssh: bool = False) -> str:
        if prefer_ssh:
            host = urlparse(self.web_base).hostname or "github.com"
            return f"git@{host}:{full_name}.git"
        return f"{self.web_base}/{full_name}.git"

    async def list_repositories(self, auth: GitAuth, **filters: Any) -> list[RepositoryInfo]:
        if not auth.token:
            raise GitSecurityError("GitHub listing requires a token")
        url = f"{self.api_base}/user/repos?per_page=100"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self._headers(auth))
            resp.raise_for_status()
            items = resp.json()
        repos = []
        for r in items:
            repos.append(RepositoryInfo(
                external_id=str(r["id"]), name=r["name"],
                full_name=r["full_name"], clone_url=r["clone_url"],
                default_branch=r.get("default_branch", "main"),
                visibility="private" if r.get("private") else "public",
                provider=self.provider_id, web_url=r.get("html_url")))
        return repos

    async def get_repository(self, auth: GitAuth, external_id: str) -> RepositoryInfo:
        for r in await self.list_repositories(auth):
            if r.external_id == external_id or r.full_name == external_id:
                return r
        raise GitSecurityError(f"GitHub repository not found: {external_id}")


class GitLabProvider(_HostedGitProvider):
    provider_id = "gitlab"
    api_base = "https://gitlab.com/api/v4"
    web_base = "https://gitlab.com"

    def __init__(self, runner: GitRunner, api_base: str = "https://gitlab.com/api/v4",
                 web_base: str = "https://gitlab.com"):
        super().__init__(runner)
        self.api_base = api_base.rstrip("/")
        self.web_base = web_base.rstrip("/")

    def build_clone_url(self, full_name: str, prefer_ssh: bool = False) -> str:
        if prefer_ssh:
            host = urlparse(self.web_base).hostname or "gitlab.com"
            return f"git@{host}:{full_name}.git"
        return f"{self.web_base}/{full_name}.git"

    async def list_repositories(self, auth: GitAuth, **filters: Any) -> list[RepositoryInfo]:
        if not auth.token:
            raise GitSecurityError("GitLab listing requires a token")
        url = f"{self.api_base}/projects?membership=true&per_page=100"
        headers = {"PRIVATE-TOKEN": auth.token}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            items = resp.json()
        repos = []
        for r in items:
            repos.append(RepositoryInfo(
                external_id=str(r["id"]), name=r["path"],
                full_name=r["path_with_namespace"],
                clone_url=r["http_url_to_repo"],
                default_branch=r.get("default_branch", "main"),
                visibility=r.get("visibility", "private"),
                provider=self.provider_id, web_url=r.get("web_url")))
        return repos

    async def get_repository(self, auth: GitAuth, external_id: str) -> RepositoryInfo:
        for r in await self.list_repositories(auth):
            if r.external_id == external_id or r.full_name == external_id:
                return r
        raise GitSecurityError(f"GitLab project not found: {external_id}")


class BitbucketProvider(_HostedGitProvider):
    provider_id = "bitbucket"
    api_base = "https://api.bitbucket.org/2.0"
    web_base = "https://bitbucket.org"

    def build_clone_url(self, full_name: str, prefer_ssh: bool = False) -> str:
        if prefer_ssh:
            return f"git@bitbucket.org:{full_name}.git"
        return f"https://bitbucket.org/{full_name}.git"

    async def list_repositories(self, auth: GitAuth, **filters: Any) -> list[RepositoryInfo]:
        if not auth.token:
            raise GitSecurityError("Bitbucket listing requires a token")
        url = f"{self.api_base}/repositories?role=member&pagelen=100"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self._headers(auth))
            resp.raise_for_status()
            items = resp.json().get("values", [])
        repos = []
        for r in items:
            clone = next((c["href"] for c in r.get("links", {}).get("clone", [])
                          if c.get("name") == "https"), "")
            repos.append(RepositoryInfo(
                external_id=r["uuid"], name=r["name"], full_name=r["full_name"],
                clone_url=clone, default_branch=r.get("mainbranch", {}).get("name", "main"),
                visibility="private" if r.get("is_private") else "public",
                provider=self.provider_id,
                web_url=r.get("links", {}).get("html", {}).get("href")))
        return repos

    async def get_repository(self, auth: GitAuth, external_id: str) -> RepositoryInfo:
        for r in await self.list_repositories(auth):
            if r.external_id == external_id or r.full_name == external_id:
                return r
        raise GitSecurityError(f"Bitbucket repository not found: {external_id}")


PROVIDER_CLASSES: dict[str, type] = {
    "local": LocalGitProvider,
    "generic": GenericGitProvider,
    "github": GitHubProvider,
    "gitlab": GitLabProvider,
    "bitbucket": BitbucketProvider,
}


def create_provider(provider_id: str, runner: GitRunner, **kwargs: Any) -> RepositoryProvider:
    cls = PROVIDER_CLASSES.get(provider_id)
    if cls is None:
        raise GitSecurityError(f"Unknown repository provider: {provider_id}")
    if provider_id in ("github", "gitlab") and kwargs:
        return cls(runner, **kwargs)  # type: ignore[call-arg]
    return cls(runner)
