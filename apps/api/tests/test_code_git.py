"""Review + git-runner/provider integration tests (real local git, no DB)."""

import asyncio
from pathlib import Path

import pytest

from openagent.code.git import GitRunner, GitSecurityError
from openagent.code.providers import GitAuth, LocalGitProvider, create_provider
from openagent.code.review import gate_summary, review_diff, review_text


def _run(cwd, *args):
    import subprocess
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=60)


@pytest.fixture
def origin_repo(tmp_path):
    remote = tmp_path / "remote"
    remote.mkdir()
    _run(remote, "init", "-b", "main")
    _run(remote, "config", "user.email", "t@example.com")
    _run(remote, "config", "user.name", "t")
    (remote / "app.py").write_text("def add(a, b):\n    return a + b\n")
    _run(remote, "add", "-A")
    _run(remote, "commit", "-m", "init")
    return remote


class TestReview:
    def test_eval_flagged(self):
        res = review_text("x = eval(user_input)\n", "a.py")
        assert not res.passed
        assert any(f.severity == "HIGH" for f in res.findings)

    def test_hardcoded_password_blocked(self):
        res = review_text('password = "supersecret1"\n', "c.py")
        assert not res.passed
        assert any(f.category == "secrets" for f in res.findings)

    def test_clean_code_passes(self):
        res = review_text("def add(a, b):\n    return a + b\n", "a.py")
        assert res.passed

    def test_diff_review_maps_lines(self):
        diff = ("--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n"
                "-    return a + b\n+    return eval(a)\n")
        res = review_diff(diff)
        assert not res.passed
        assert res.findings and res.findings[0].file == "a.py"

    def test_gate_summary(self):
        res = review_text("x = 1\n# TODO later\n", "a.py")
        gate = gate_summary(res)
        assert gate["passed"] is True
        assert gate["by_severity"].get("INFO") == 1


class TestGitRunner:
    def test_allows_safe_commands(self, tmp_path, origin_repo):
        runner = GitRunner(str(tmp_path))
        out = asyncio.run(runner.check(["--version"]))
        assert "git version" in out

    def test_rejects_unknown_subcommand(self, tmp_path):
        runner = GitRunner(str(tmp_path))
        with pytest.raises(GitSecurityError):
            asyncio.run(runner.check(["daemon", "--export-all"]))

    def test_rejects_config_flag(self, tmp_path):
        runner = GitRunner(str(tmp_path))
        with pytest.raises(GitSecurityError):
            asyncio.run(runner.check(["-c", "x=y", "status"], cwd="."))

    def test_rejects_cwd_escape(self, tmp_path):
        runner = GitRunner(str(tmp_path / "jail"))
        with pytest.raises(GitSecurityError):
            asyncio.run(runner.check(["status"], cwd="../../.."))

    def test_clone_local_repo(self, tmp_path, origin_repo):
        runner = GitRunner(str(tmp_path))
        prov = LocalGitProvider(runner)
        info = prov_info(str(origin_repo))
        res = asyncio.run(prov.clone(info, GitAuth(), "ws1"))
        assert Path(res.path, "app.py").is_file()
        assert len(res.head_sha) == 40

    def test_branch_and_status(self, tmp_path, origin_repo):
        runner = GitRunner(str(tmp_path))
        prov = LocalGitProvider(runner)
        asyncio.run(prov.clone(prov_info(str(origin_repo)), GitAuth(), "ws2"))
        asyncio.run(runner.check(["checkout", "-b", "openagent/task/x"], cwd="ws2"))
        branch = asyncio.run(runner.check(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd="ws2")).strip()
        assert branch == "openagent/task/x"
        status = asyncio.run(runner.check(["status", "--porcelain"], cwd="ws2"))
        assert status == ""

    def test_errors_redacted(self, tmp_path):
        runner = GitRunner(str(tmp_path))
        # Unroutable localhost port: fails immediately, no network needed.
        res = asyncio.run(runner.run(["ls-remote", "https://token123@127.0.0.1:9/r.git"],
                                     cwd="."))
        assert res.returncode != 0
        assert "token123" not in res.stderr_redacted

    def test_create_provider_registry(self, tmp_path):
        runner = GitRunner(str(tmp_path))
        assert create_provider("local", runner).provider_id == "local"
        assert create_provider("github", runner).provider_id == "github"
        assert create_provider("gitlab", runner).provider_id == "gitlab"
        assert create_provider("bitbucket", runner).provider_id == "bitbucket"
        with pytest.raises(GitSecurityError):
            create_provider("nope", runner)


def prov_info(path):
    from openagent.code.providers import RepositoryInfo
    return RepositoryInfo(external_id=path, name="demo", full_name="demo",
                          clone_url=path, default_branch="main")
