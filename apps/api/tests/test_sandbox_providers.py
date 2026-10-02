"""Sandbox provider tests: hardened Docker argv, factory gates, local guards.

No Docker daemon required except the explicitly marked live test (skipped
when the daemon is unavailable).
"""

import pytest

from openagent.sandbox.profiles import get_profile
from openagent.sandbox.providers import (
    ContainerSpec,
    SandboxError,
    create_provider,
    docker_create_argv,
)


def _spec(**kw):
    prof = get_profile("TEST")
    return ContainerSpec(image="openagent-sandbox-base", cpu=prof.cpu,
                         memory_mb=prof.memory_mb, pids_limit=prof.pids_limit,
                         readonly_rootfs=True, network_mode="NO_NETWORK",
                         mounts=[{"host": "/srv/ws", "container": "/workspace",
                                  "read_only": False}],
                         env={"CI": "true"},
                         labels={"openagent.sandbox": "sbx_x"}, **kw)


class TestDockerArgv:
    def test_hardened_flags_present(self):
        argv = docker_create_argv(_spec(), "sbx-test")
        joined = " ".join(argv)
        assert "--user 65532:65532" in joined
        assert "--cap-drop ALL" in joined
        assert "no-new-privileges:true" in joined
        assert "--read-only" in joined
        assert "--network none" in joined
        assert "--pids-limit 128" in joined
        assert "--memory 1024m" in joined
        assert "--init" in joined

    def test_never_privileged_or_socket(self):
        argv = docker_create_argv(_spec(), "sbx-test")
        assert "--privileged" not in argv
        assert not any("docker.sock" in a for a in argv)
        assert not any(a in ("--cap-add", "SYS_ADMIN", "NET_ADMIN", "SYS_PTRACE")
                       for a in argv)

    def test_socket_mount_refused(self):
        with pytest.raises(SandboxError):
            docker_create_argv(_spec(mounts=[{"host": "/var/run/docker.sock",
                                             "container": "/sock",
                                             "read_only": True}]), "sbx-test")

    def test_broad_host_mount_refused(self):
        with pytest.raises(SandboxError):
            docker_create_argv(_spec(mounts=[{"host": "/", "container": "/host",
                                             "read_only": True}]), "sbx-test")

    def test_no_argv_string_concatenation(self):
        # argv is a list throughout; nothing is joined into a shell string.
        argv = docker_create_argv(_spec(), "sbx-test")
        assert all(isinstance(a, str) for a in argv)
        assert argv[0] == "create"


class TestFactory:
    def test_unknown_provider(self):
        with pytest.raises(SandboxError):
            create_provider("hypervisor-9000")

    def test_kubernetes_is_fail_closed_stub(self):
        with pytest.raises(SandboxError) as e:
            create_provider("kubernetes")
        assert "future" in str(e.value).lower()

    def test_local_provider_marks_no_boundary(self):
        import asyncio
        prov = create_provider("local", root="/tmp/sbx-test-root")
        loop = asyncio.get_event_loop_policy().new_event_loop()
        try:
            info = loop.run_until_complete(prov.inspect("x"))
        finally:
            loop.close()
        assert info["security_boundary"] is False

    async def test_local_execute_confined(self, tmp_path):
        prov = create_provider("local", root=str(tmp_path))
        from openagent.sandbox.providers import ExecutionSpec
        with pytest.raises(SandboxError):
            await prov.execute("h", ExecutionSpec(argv=["echo", "hi"],
                                                 workdir="/etc"))

    async def test_docker_live_lifecycle(self):
        """Requires a Docker daemon; skipped otherwise (CI runs it)."""
        from openagent.sandbox.providers import docker_available
        ok, _ = await docker_available()
        if not ok:
            pytest.skip("no Docker daemon")
        prov = create_provider("docker")
        handle = await prov.create(_spec(command=["sleep", "30"]))
        try:
            await prov.start(handle)
            from openagent.sandbox.providers import ExecutionSpec
            out = await prov.execute(handle, ExecutionSpec(argv=["echo", "hi"]))
            assert out.exit_code == 0 and "hi" in out.stdout
            info = await prov.inspect(handle)
            assert info["privileged"] is False
        finally:
            await prov.destroy(handle)
