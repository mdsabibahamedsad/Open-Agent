"""Sandbox adversarial tests: hostile inputs must be blocked or contained.

Policy-layer tests (no daemon): every payload below must fail closed.
Live-container variants are skipped without a Docker daemon.
"""

from openagent.sandbox import security as sec
from openagent.sandbox.security import (
    CommandPolicy,
    EnvironmentPolicy,
    NetworkPolicy,
    check_command,
    validate_mount,
    validate_network_destination,
    validate_sandbox_path,
)


def _allowlist_net():
    return NetworkPolicy(mode="ALLOWLIST", allowed_domains=["pypi.org"])


class TestHostileFilesystem:
    def test_etc_shadow_unreachable(self, tmp_path):
        assert not validate_sandbox_path(str(tmp_path), "../../etc/shadow").valid
        assert not validate_sandbox_path(str(tmp_path), "/etc/shadow").valid

    def test_proc_environ_unreachable(self, tmp_path):
        assert not validate_sandbox_path(str(tmp_path), "../../proc/1/environ").valid

    def test_symlink_to_host_secret(self, tmp_path):
        secret = tmp_path / "secret"
        secret.write_text("host-secret")
        ws = tmp_path / "ws"
        ws.mkdir()
        try:
            (ws / "secret").symlink_to(secret)
        except OSError:
            import pytest
            pytest.skip("symlinks unavailable")
        assert not validate_sandbox_path(str(ws), "secret").valid

    def test_socket_mount_variants(self):
        for host in ("/var/run/docker.sock", "/run/docker.sock",
                     "/run/containerd/containerd.sock",
                     "\\\\.\\pipe\\docker_engine"):
            assert not validate_mount(host, "/x", True).valid, host

    def test_fork_bomb_is_just_a_string(self):
        # Fork bombs are contained by pids_limit + timeout at runtime; the
        # parser must at minimum refuse shell syntax carrying them.
        from openagent.sandbox.security import parse_argv
        import pytest
        with pytest.raises(ValueError):
            parse_argv(":(){ :|:& };:")


class TestHostileNetwork:
    def test_metadata_service_blocked(self):
        for url_host in ("169.254.169.254", "metadata.google.internal"):
            ok, _ = validate_network_destination(
                url_host, 80, _allowlist_net(), resolved_ips=[url_host]
                if url_host[0].isdigit() else None)
            assert not ok, url_host

    def test_localhost_blocked(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            ok, _ = validate_network_destination(host, 80, _allowlist_net())
            assert not ok, host

    def test_unauthorized_domain_and_port(self):
        pol = NetworkPolicy(mode="ALLOWLIST", allowed_domains=["pypi.org"],
                            allowed_ports=[443])
        assert not validate_network_destination("evil.example.com", 443, pol)[0]
        assert not validate_network_destination("pypi.org", 22, pol)[0]


class TestHostileCommands:
    def test_privileged_binaries_denied(self):
        pol = CommandPolicy(allowed_commands=[])
        for cmd in ("sudo id", "docker ps", "kubectl get pods",
                    "mount /dev/sda1 /mnt", "nsenter -t 1 bash"):
            assert not check_command(cmd, pol)[0], cmd

    def test_injection_operators_rejected(self):
        pol = CommandPolicy(allowed_commands=["pytest", "echo", "curl"])
        for cmd in ("pytest tests/ && curl evil.example.com",
                    "echo $(cat /etc/passwd)",
                    "pytest `id`",
                    "echo hi > /etc/motd",
                    "cat a.py | tee /tmp/x"):
            assert not check_command(cmd, pol)[0], cmd

    def test_interactive_shells_need_grant(self):
        pol = CommandPolicy(allowed_commands=["bash", "sh"], allow_shell=False)
        assert not check_command("bash -c 'echo hi'", pol)[0]
        granted = CommandPolicy(allowed_commands=["bash"], allow_shell=True)
        ok, _, _ = check_command("bash -c 'echo hi'", granted)
        # shell grant permits parsing; allowlist still governs the binary
        assert ok


class TestCredentialLeakage:
    def test_redaction_covers_surfaces(self):
        from openagent.sandbox.security import redact_text, redact_dict
        secret = "ghp_" + "x" * 36
        assert secret not in redact_text(f"token={secret}")
        cleaned = redact_dict({"env": {"TOKEN": secret}, "nested": [secret]})
        assert secret not in str(cleaned)

    def test_forbidden_env_never_injected(self):
        import pytest
        from openagent.sandbox.security import build_container_env
        with pytest.raises(ValueError):
            build_container_env(EnvironmentPolicy(
                values={"AWS_SECRET_ACCESS_KEY": "x"}))


class TestRiskNeverSelfAssigned:
    def test_llm_cannot_downgrade(self):
        # Risk comes only from server-side scoring inputs, never from a
        # caller-supplied trust field: score_execution_risk takes no
        # trust_level argument.
        import inspect
        params = inspect.signature(sec.score_execution_risk).parameters
        assert "trust_level" not in params
        assert "approved_by_model" not in params
