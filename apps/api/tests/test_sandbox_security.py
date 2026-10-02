"""Sandbox security unit tests: network, filesystem, env, commands, risk.

Pure unit tests — no database, no Docker daemon required.
"""

import pytest

from openagent.sandbox.security import (
    EnvironmentPolicy,
    NetworkPolicy,
    build_container_env,
    categorize_command,
    check_command,
    check_url_against_policy,
    parse_argv,
    score_execution_risk,
    validate_mount,
    validate_network_destination,
    validate_sandbox_path,
)


class TestNetworkPolicy:
    def test_default_denies_everything(self):
        ok, reason = validate_network_destination("pypi.org", 443, NetworkPolicy())
        assert not ok and "disabled" in reason

    def test_blocks_metadata_ip(self):
        pol = NetworkPolicy(mode="ALLOWLIST", allowed_domains=["example.com"])
        ok, _ = validate_network_destination("169.254.169.254", 80, pol,
                                             resolved_ips=["169.254.169.254"])
        assert not ok

    def test_blocks_localhost_and_private(self):
        pol = NetworkPolicy(mode="FULL_OUTBOUND")
        for host in ("localhost", "127.0.0.1", "10.0.0.5", "192.168.1.1",
                     "host.docker.internal", "metadata.google.internal"):
            ok, _ = validate_network_destination(host, 80, pol, resolved_ips=[host]
                                                 if host[0].isdigit() else None)
            assert not ok, host

    def test_dns_rebinding_answer_rejected(self):
        pol = NetworkPolicy(mode="ALLOWLIST", allowed_domains=["example.com"])
        ok, reason = validate_network_destination(
            "example.com", 443, pol, resolved_ips=["93.184.216.34", "127.0.0.1"])
        assert not ok and "127.0.0.1" in reason

    def test_allowlist_subdomain_match_and_deny_override(self):
        pol = NetworkPolicy(mode="ALLOWLIST",
                            allowed_domains=["pypi.org"],
                            denied_domains=["evil.pypi.org"])
        ok, _ = validate_network_destination("files.pythonhosted.org", 443, pol)
        assert not ok
        pol2 = NetworkPolicy(mode="ALLOWLIST", allowed_domains=["pypi.org"])
        ok, _ = validate_network_destination("files.pypi.org", 443, pol2)
        # files.pypi.org is a subdomain of the allowlisted pypi.org
        assert ok
        ok, _ = validate_network_destination("evil.pypi.org", 443, pol)
        assert not ok

    def test_url_scheme_and_port_gates(self):
        pol = NetworkPolicy(mode="ALLOWLIST", allowed_domains=["example.com"],
                            allowed_ports=[443])
        assert not check_url_against_policy("ftp://example.com/x", pol)[0]
        assert not check_url_against_policy("http://example.com:8080/x", pol)[0]
        assert check_url_against_policy("https://example.com/x", pol)[0]

    def test_unknown_mode_fails_closed(self):
        with pytest.raises(ValueError):
            NetworkPolicy(mode="WIDE_OPEN").normalized()


class TestFilesystemPolicy:
    def test_allows_relative_inside(self, tmp_path):
        assert validate_sandbox_path(str(tmp_path), "src/a.py").valid

    def test_rejects_traversal_and_absolute(self, tmp_path):
        assert not validate_sandbox_path(str(tmp_path), "../../etc/passwd").valid
        assert not validate_sandbox_path(str(tmp_path), "/etc/shadow").valid
        assert not validate_sandbox_path(str(tmp_path), "C:/Windows/x").valid

    def test_rejects_symlink_escape(self, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        link = tmp_path / "ws" / "link"
        link.parent.mkdir()
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks unavailable")
        assert not validate_sandbox_path(str(link.parent), "link").valid

    def test_forbids_docker_socket_mount(self):
        assert not validate_mount("/var/run/docker.sock", "/sock", True).valid
        assert not validate_mount("/data", "/var/run/docker.sock", True).valid
        assert not validate_mount("\\\\.\\pipe\\docker_engine", "/pipe", True).valid

    def test_forbids_broad_host_mounts(self):
        for host in ("/", "/home", "/etc", "/var", "C:/Users"):
            assert not validate_mount(host, "/workspace", True).valid, host

    def test_allows_explicit_workspace_mount(self):
        assert validate_mount("/srv/tenants/a/ws1", "/workspace", False).valid
        assert validate_mount("/srv/tenants/a/ws1", "/workspace", True).valid


class TestEnvironmentPolicy:
    def test_minimal_base_without_host_inherit(self):
        env = build_container_env(EnvironmentPolicy())
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "DATABASE_URL" not in env

    def test_forbidden_plain_values_rejected(self):
        with pytest.raises(ValueError):
            build_container_env(EnvironmentPolicy(
                values={"GITHUB_TOKEN": "ghp_live"}))

    def test_credential_refs_resolve_server_side(self):
        env = build_container_env(
            EnvironmentPolicy(credential_refs={"cred_1": "GITHUB_TOKEN"}),
            resolved_credentials={"cred_1": "s3cr3t"})
        assert env["GITHUB_TOKEN"] == "s3cr3t"

    def test_unresolved_credential_fails_closed(self):
        with pytest.raises(ValueError):
            build_container_env(
                EnvironmentPolicy(credential_refs={"cred_1": "GITHUB_TOKEN"}),
                resolved_credentials={})

    def test_allowlist_skips_forbidden_names(self):
        env = build_container_env(
            EnvironmentPolicy(action="ALLOW",
                              allowed_names=["MY_FLAG", "SECRET_KEY"]),
            host_env={"MY_FLAG": "1", "SECRET_KEY": "x"})
        assert env["MY_FLAG"] == "1"
        assert "SECRET_KEY" not in env


class TestCommandPolicy:
    def test_structured_argv_and_shell_rejection(self):
        assert parse_argv("pytest tests/ -q") == ["pytest", "tests/", "-q"]
        with pytest.raises(ValueError):
            parse_argv("pytest tests/; rm -rf /")
        with pytest.raises(ValueError):
            parse_argv("bash -c 'echo hi'")
        with pytest.raises(ValueError):
            parse_argv("")

    def test_categories(self):
        assert categorize_command("sudo") == "privileged"
        assert categorize_command("docker") == "privileged"
        assert categorize_command("curl") == "network"
        assert categorize_command("pytest") == "test"

    def test_allowlist_and_deny(self):
        from openagent.sandbox.security import CommandPolicy
        pol = CommandPolicy(allowed_commands=["pytest", "python"],
                            denied_categories=["network"])
        ok, _, cat = check_command("pytest tests/", pol)
        assert ok and cat == "test"
        assert not check_command("curl http://x", pol)[0]
        assert not check_command("npm install", pol)[0]


class TestRiskScoring:
    def test_low_for_plain_test(self):
        d = score_execution_risk(category="read", network_mode="NO_NETWORK",
                                 filesystem_mode="WORKSPACE_RO",
                                 has_credentials=False, command="pytest -q")
        assert d.risk_level == "LOW" and not d.required_approval

    def test_privileged_is_critical(self):
        d = score_execution_risk(category="privileged", network_mode="NO_NETWORK",
                                 filesystem_mode="ISOLATED",
                                 has_credentials=False, command="sudo id")
        assert d.risk_level == "CRITICAL" and d.required_approval

    def test_production_target_denied(self):
        d = score_execution_risk(category="test", network_mode="NO_NETWORK",
                                 filesystem_mode="WORKSPACE_RW",
                                 has_credentials=False, command="pytest",
                                 target_environment="production")
        assert d.risk_level == "CRITICAL" and d.required_approval

    def test_credentials_and_full_outbound_escalate(self):
        d = score_execution_risk(category="build", network_mode="FULL_OUTBOUND",
                                 filesystem_mode="WORKSPACE_RW",
                                 has_credentials=True, command="make")
        assert d.risk_level in ("HIGH", "CRITICAL") and d.required_approval
