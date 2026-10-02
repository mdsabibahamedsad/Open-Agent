"""MP28 unit tests: manifest, versioning, permissions, packaging, signing,
security scanner, webhook verification, service validation, mocks.

Pure domain — no database required.
"""

from __future__ import annotations

import pytest

from openagent.developer import service as dev_service
from openagent.developer.errors import (
    OpenAgentError,
    ValidationError,
    parse_webhook,
    sign_webhook,
    verify_webhook,
)
from openagent.developer.manifest import ManifestError, load_manifest_dict
from openagent.developer.mocks import (
    MockAgent,
    MockBrowser,
    MockConnector,
    MockLLM,
    MockMCP,
    MockMemory,
    MockSandbox,
    MockStorage,
    MockToolRuntime,
    MockWebhook,
    MockWorkflow,
)
from openagent.developer.packaging import (
    PackageFile,
    build_package,
    inspect_package,
    resolve_dependencies,
    verify_checksums,
)
from openagent.developer.permissions import check_permissions
from openagent.developer.security import install_hooks_safe, scan_files
from openagent.developer.signing import (
    canonical_digest,
    generate_keypair,
    sign_digest,
    verify_digest,
)
from openagent.developer.types import EXTENSION_TYPES, PERMISSION_CATALOG
from openagent.developer.versioning import (
    VersionError,
    bump,
    check_compatibility,
    is_breaking_change,
    satisfies,
    validate_constraint,
    validate_semver,
)


def _manifest(**overrides):
    base = {
        "name": "example-tool",
        "version": "1.0.0",
        "description": "Example tool",
        "author": {"name": "Acme"},
        "license": "MIT",
        "type": "tool",
        "runtime": {"language": "typescript", "entrypoint": "src/index.ts"},
        "permissions": ["tool:execute", "filesystem:workspace"],
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------- manifest ---

def test_manifest_accepts_valid_tool():
    loaded = load_manifest_dict(_manifest())
    assert loaded.name == "example-tool"
    assert loaded.version == "1.0.0"


def test_manifest_rejects_unknown_type():
    with pytest.raises(ManifestError):
        load_manifest_dict(_manifest(type="teleporter"))


def test_manifest_rejects_unknown_permission():
    with pytest.raises(ManifestError):
        load_manifest_dict(_manifest(permissions=["root:everything"]))


def test_manifest_requires_allowlist_for_outbound():
    with pytest.raises(ManifestError):
        load_manifest_dict(_manifest(permissions=["network:outbound"]))
    loaded = load_manifest_dict(_manifest(
        permissions=["network:outbound"],
        network={"allowed_hosts": ["api.example.com"]},
    ))
    assert loaded.permissions == ["network:outbound"]


def test_manifest_rejects_secret_values():
    with pytest.raises(ManifestError):
        load_manifest_dict(_manifest(secrets=["sk-live-1234567890"]))
    loaded = load_manifest_dict(_manifest(secrets=["MY_API_KEY"]))
    assert loaded.secrets == ["MY_API_KEY"]


def test_manifest_rejects_bad_semver():
    with pytest.raises(ManifestError):
        load_manifest_dict(_manifest(version="1.0"))


def test_extension_type_registry_complete():
    for expected in ("agent", "tool", "connector", "mcp-server", "skill",
                     "evaluator", "workflow-node", "model-provider",
                     "memory-provider", "sandbox-profile", "ui-extension"):
        assert expected in EXTENSION_TYPES


# ------------------------------------------------------------ versioning ---

def test_semver_and_constraints():
    assert str(validate_semver("1.2.3")) == "1.2.3"
    with pytest.raises(VersionError):
        validate_semver("1.0")
    assert satisfies("1.2.3", "^1.0.0")
    assert not satisfies("2.0.0", "^1.0.0")
    assert satisfies("1.5.0", ">=1.0.0 <2.0.0")
    assert not satisfies("2.0.0", ">=1.0.0 <2.0.0")
    assert bump("1.2.3", "minor") == "1.3.0"
    assert is_breaking_change("1.0.0", "2.0.0")
    assert not is_breaking_change("1.0.0", "1.1.0")
    validate_constraint("*")


def test_compatibility_matrix():
    assert check_compatibility("1.4.0", ">=1.0.0 <2.0.0") == []
    problems = check_compatibility("1.4.0", ">=1.0.0 <2.0.0", extension_api="9.x")
    assert problems


# ---------------------------------------------------------- permissions ---

def test_permissions_no_self_grant():
    decision = check_permissions(["tool:execute", "browser:use"],
                                 granted=["tool:execute"])
    assert not decision.allowed
    assert "browser:use" in decision.denied


def test_permissions_high_risk_needs_approval_for_untrusted():
    decision = check_permissions(["secret:access"], granted=["secret:access"],
                                 trust="UNTRUSTED")
    assert not decision.allowed
    assert decision.requires_approval == ["secret:access"]


def test_permissions_trusted_with_approval_ok():
    decision = check_permissions(["secret:access"], granted=["secret:access"],
                                 trust="VERIFIED", approvals_present=True)
    assert decision.allowed


def test_permission_catalog_covers_spec():
    for perm in ("network:outbound", "tool:execute", "memory:read",
                 "browser:use", "sandbox:execute", "mcp:connect",
                 "secret:access", "workflow:execute", "agent:invoke"):
        assert perm in PERMISSION_CATALOG


# ------------------------------------------------------------ packaging ---

def test_package_deterministic():
    kwargs = dict(name="example-tool", version="1.0.0",
                  manifest=_manifest(),
                  files=[PackageFile("files/src/index.ts", b"export {}")])
    first = build_package(**kwargs)
    second = build_package(**kwargs)
    assert first.content == second.content
    assert first.filename == "example-tool-1.0.0.oaext"


def test_package_inspect_and_checksums():
    built = build_package(name="example-tool", version="1.0.0",
                          manifest=_manifest(),
                          files=[PackageFile("files/src/index.ts", b"export {}")])
    info = inspect_package(built.content)
    assert info["manifest"]["name"] == "example-tool"
    ok, problems = verify_checksums(built.content)
    assert ok, problems


def test_package_rejects_zip_slip():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("CHECKSUMS.sha256", "")
        zf.writestr("signatures.json", '{"signatures": []}')
        zf.writestr("../evil.sh", b"evil")
    with pytest.raises(ValueError):
        inspect_package(buf.getvalue())


def test_dependency_resolution_and_conflicts():
    resolved = resolve_dependencies(
        [{"name": "@openagent/sdk", "version": "^1.0.0"}],
        {"@openagent/sdk": ["1.0.0", "1.2.0", "2.0.0"]},
    )
    assert resolved == {"@openagent/sdk": "1.2.0"}
    with pytest.raises(ValueError):
        resolve_dependencies(
            [{"name": "@openagent/sdk", "version": "^1.0.0"}],
            {"@openagent/sdk": ["2.0.0"]},
        )


# --------------------------------------------------------------- signing ---

def test_signing_roundtrip_and_revocation():
    keys = generate_keypair("test-key")
    digest = canonical_digest({"hello": "world"})
    sig = sign_digest(digest, keys.private_pem, keys.key_id)
    assert verify_digest(digest, sig["signature_b64"], keys.public_pem,
                         key_id=keys.key_id)
    assert not verify_digest("00" * 32, sig["signature_b64"], keys.public_pem,
                             key_id=keys.key_id)
    assert not verify_digest(digest, sig["signature_b64"], keys.public_pem,
                             revoked_key_ids=frozenset({keys.key_id}),
                             key_id=keys.key_id)


# --------------------------------------------------------------- scanning ---

def test_secret_detection_blocks_publish():
    report = scan_files({"src/index.ts": 'const key = "AKIAIOSFODNN7EXAMPLE";\n'})
    assert report.secret_hits
    assert report.blocks_publish


def test_secret_allowlist_for_examples():
    report = scan_files({"README.md": "example: AKIAIOSFODNN7EXAMPLE is an example\n"})
    assert not report.secret_hits


def test_dangerous_patterns_flagged():
    report = scan_files({"src/i.py": "import os\nos.system('rm -rf /')\n"})
    assert report.findings
    report2 = scan_files({"Dockerfile": "VOLUME /var/run/docker.sock\n"})
    assert report2.blocks_install


def test_install_hooks_detected():
    assert install_hooks_safe({"scripts": {"postinstall": "node evil.js"}}) == ["postinstall"]
    assert install_hooks_safe({"scripts": {"build": "tsc"}}) == []


# ---------------------------------------------------- webhooks + errors ---

def test_webhook_sign_verify_roundtrip():
    body = b'{"event": "tool.completed.v1"}'
    header = sign_webhook("secret", body, delivery_id="d1", timestamp=1_700_000_000)
    result = verify_webhook("secret", body, header, now=1_700_000_100)
    assert result["ok"]
    assert result["delivery_id"] == "d1"


def test_webhook_tamper_and_replay_rejected():
    body = b'{"event": "tool.completed.v1"}'
    header = sign_webhook("secret", body, delivery_id="d1", timestamp=1_700_000_000)
    assert not verify_webhook("secret", b'{"event": "other"}', header,
                              now=1_700_000_100)["ok"]
    assert not verify_webhook("secret", body, header, now=1_700_000_100 + 3600)["ok"]
    assert not verify_webhook("secret", body, "garbage", now=1_700_000_100)["ok"]


def test_parse_webhook_requires_event():
    assert parse_webhook(b'{"event": "x"}') == {"event": "x"}
    with pytest.raises(ValidationError):
        parse_webhook(b'{"nope": 1}')
    with pytest.raises(ValidationError):
        parse_webhook(b"not json")


def test_error_taxonomy_safe_shape():
    err = OpenAgentError("boom")
    public = err.to_public("req_1")
    assert public == {"error": {"code": "OPENAGENT_ERROR", "message": "boom",
                                "request_id": "req_1"}}
    assert "traceback" not in str(public)


# --------------------------------------------------------------- service ---

def test_full_validation_ok_and_secret_blocked():
    ok_result = dev_service.run_full_validation(
        manifest=_manifest(), files={"src/index.ts": "export const x = 1;\n"})
    assert ok_result["ok"], ok_result["errors"]
    bad = dev_service.run_full_validation(
        manifest=_manifest(),
        files={"src/index.ts": 'api_key = "sk-abcdefghij1234567890";\n'})
    assert not bad["ok"]
    assert any("secret" in e.lower() for e in bad["errors"])


def test_package_extension_metadata():
    out = dev_service.package_extension(
        manifest=_manifest(), files={"src/index.ts": "export {}"})
    assert out["filename"] == "example-tool-1.0.0.oaext"
    assert len(out["content_digest"]) == 64


def test_doctor_checks_shape():
    checks = dev_service.doctor_checks()
    assert {c["check"] for c in checks} >= {"python", "fastapi", "cryptography"}


# ----------------------------------------------------------------- mocks ---

def test_mocks_deterministic_and_safe():
    assert MockLLM().complete("hello")["text"].startswith("[mock completion")
    assert MockToolRuntime().invoke("t", {"a": 1})["ok"] is True
    assert MockSandbox().execute("rm -rf /")["ok"] is False
    assert MockSandbox().execute("echo hi")["ok"] is True
    mem = MockMemory()
    mem.write("k", "v")
    assert mem.read("k")["value"] == "v"
    assert MockAgent().run("task")["status"] in ("SUCCEEDED", "NEEDS_REVIEW")
    assert MockConnector().action("list", {})["ok"] is True
    mcp = MockMCP()
    mcp.connect()
    assert mcp.call_tool("ping", {})["tool"] == "ping"
    assert MockBrowser().goto("https://example.com")["ok"] is True
    assert MockWorkflow().run("wf", {"a": 1})["status"] == "SUCCEEDED"
    store = MockStorage()
    store.put("k", b"v")
    assert store.get("k") == b"v"
    hook = MockWebhook()
    delivery = hook.send("tool.completed.v1", {"ok": True})
    assert delivery["signature"].startswith("v1,")
