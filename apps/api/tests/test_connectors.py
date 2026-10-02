"""Unit tests for the universal connector framework (MP21).

Pure-domain coverage: manifests, registry, crypto, SSRF guard, retry,
rate limits, pagination, mapping, resources, errors, SQL guard, polling,
webhooks, OAuth helpers, provider client logic (mocked), gates, config.
"""

import time

import pytest

from openagent.connectors import mapping as mapping_mod
from openagent.connectors import pagination as pagination_mod
from openagent.connectors import polling as polling_mod
from openagent.connectors import ratelimit as ratelimits
from openagent.connectors import resources as resources_mod
from openagent.connectors import retry as retry_mod
from openagent.connectors.crypto import (
    decrypt_secret,
    encrypt_secret,
    generate_webhook_secret,
    mask_credential_payload,
    mask_secret,
)
from openagent.connectors.db_connector import (
    DatabaseError,
    validate_query,
)
from openagent.connectors.errors import (
    ProviderError,
    ProviderErrorKind,
    normalize_http_error,
)
from openagent.connectors.manifest import ManifestError, validate_manifest
from openagent.connectors.netsec import SSRFError, assert_host_safe, assert_url_safe
from openagent.connectors.oauth import (
    OAuthConfig,
    TokenSet,
    build_authorize_url,
    pkce_pair,
    sign_state,
    validate_callback_url,
    verify_state,
)
from openagent.connectors.registry import ConnectorRegistry
from openagent.connectors.types import (
    ConnectorStatus,
    InstanceStatus,
    can_transition_connector,
    can_transition_instance,
)


def _manifest(**overrides):
    base = {
        "id": "acme",
        "name": "Acme",
        "version": "1.2.3",
        "category": "automation",
        "type": "CUSTOM",
        "trust": "CUSTOM",
        "auth": {"type": "api_key"},
        "capabilities": [{"id": "acme.items.read"}],
        "actions": [{
            "id": "acme.list_items",
            "name": "List",
            "input_schema": {"type": "object"},
            "required_capabilities": ["acme.items.read"],
            "mutation": False,
        }],
    }
    base.update(overrides)
    return base


class TestManifest:
    def test_valid(self):
        manifest = validate_manifest(_manifest())
        assert manifest.id == "acme"
        assert manifest.content_hash
        assert manifest.actions[0].risk_level.value == "MEDIUM"

    def test_rejects_bad_id_version(self):
        with pytest.raises(ManifestError):
            validate_manifest(_manifest(id="Bad ID!"))
        with pytest.raises(ManifestError):
            validate_manifest(_manifest(version="banana"))

    def test_rejects_unknown_auth_and_category(self):
        with pytest.raises(ManifestError):
            validate_manifest(_manifest(auth={"type": "telepathy"}))
        with pytest.raises(ManifestError):
            validate_manifest(_manifest(category="alchemy"))

    def test_rejects_unnamespaced_capability(self):
        with pytest.raises(ManifestError):
            validate_manifest(_manifest(
                capabilities=[{"id": "other.items.read"}]))

    def test_rejects_action_without_capability(self):
        with pytest.raises(ManifestError):
            validate_manifest(_manifest(actions=[{
                "id": "acme.do", "name": "Do",
                "input_schema": {"type": "object"},
                "required_capabilities": ["acme.missing"]}]))


class TestLifecycle:
    def test_connector_transitions(self):
        assert can_transition_connector(ConnectorStatus.DRAFT,
                                        ConnectorStatus.ACTIVE)
        assert not can_transition_connector(ConnectorStatus.DEPRECATED,
                                            ConnectorStatus.ACTIVE)
        assert not can_transition_connector(ConnectorStatus.ACTIVE,
                                            ConnectorStatus.DRAFT)

    def test_instance_transitions(self):
        assert can_transition_instance(InstanceStatus.UNCONNECTED,
                                       InstanceStatus.CONNECTING)
        assert can_transition_instance(InstanceStatus.CONNECTED,
                                       InstanceStatus.AUTH_EXPIRED)
        assert not can_transition_instance(InstanceStatus.CONNECTED,
                                           InstanceStatus.UNCONNECTED)


class TestRegistry:
    def test_register_search_actions(self):
        registry = ConnectorRegistry()
        registry.register_manifest(_manifest())
        assert registry.get("acme") is not None
        assert registry.get("missing") is None
        assert registry.search("acme")
        hits = registry.search_actions("list items")
        assert hits and hits[0]["action"] == "acme.list_items"
        # Compact descriptors only.
        assert set(hits[0]) <= {"action", "description", "risk_level",
                                "connector", "trust"}
        assert registry.action_owner("acme.list_items") == ("acme", "1.2.3")
        assert registry.capability_owner("acme.items.read") == "acme"

    def test_status_transitions(self):
        from openagent.connectors.types import ConnectorStatus
        registry = ConnectorRegistry()
        registry.register_manifest(_manifest())
        registry.set_status("acme", ConnectorStatus.DISABLED)
        assert registry.search("acme") == []
        with pytest.raises(Exception):
            registry.set_status("acme", ConnectorStatus.DRAFT)


class TestCrypto:
    KEY = "k" * 40

    def test_roundtrip_with_binding(self):
        token = encrypt_secret(self.KEY, "s3cr3t", associated="org:1")
        assert decrypt_secret(self.KEY, token, associated="org:1") == "s3cr3t"
        with pytest.raises(Exception):
            decrypt_secret(self.KEY, token, associated="org:2")
        with pytest.raises(Exception):
            decrypt_secret("y" * 40, token, associated="org:1")

    def test_rejects_short_key(self):
        with pytest.raises(Exception):
            encrypt_secret("short", "x")

    def test_masking(self):
        assert mask_secret("abcdef123456") == "••••••••"
        assert mask_secret("") == ""
        # Explicit keep= is opt-in only (non-secret prefixes), never default.
        assert mask_secret("abcdef123456", keep=4) == "********…3456"
        masked = mask_credential_payload({"api_key": "abcdef123456",
                                          "name": "x"})
        assert masked["name"] == "x"
        assert masked["api_key"] != "abcdef123456"

    def test_webhook_secret_pair(self):
        raw, digest = generate_webhook_secret()
        assert raw and digest
        import hashlib
        assert hashlib.sha256(raw.encode()).hexdigest() == digest


class TestNetsec:
    def test_blocks_private_and_metadata(self):
        for host in ("127.0.0.1", "10.0.0.5", "169.254.169.254",
                     "metadata.google.internal", "localhost",
                     "host.docker.internal"):
            with pytest.raises(SSRFError):
                assert_host_safe(host, resolved_ips=[host])

    def test_blocks_private_resolution(self):
        with pytest.raises(SSRFError):
            assert_host_safe("example.com", resolved_ips=["192.168.1.1"])
        assert assert_host_safe("example.com",
                                resolved_ips=["93.184.216.34"]) == "example.com"

    def test_url_gate(self):
        with pytest.raises(SSRFError):
            assert_url_safe("ftp://example.com/x", resolve_dns=False)
        with pytest.raises(SSRFError):
            assert_url_safe("http://169.254.169.254/", resolve_dns=False)


class TestRetry:
    def _err(self, kind):
        return ProviderError(kind, "boom")

    def test_retryable(self):
        decision = retry_mod.decide_retry(
            self._err(ProviderErrorKind.RATE_LIMITED), attempt=0,
            idempotent=True, retry_after=5)
        assert decision.retry and decision.delay_seconds == 5

    def test_non_retryable_validation(self):
        decision = retry_mod.decide_retry(
            self._err(ProviderErrorKind.VALIDATION_ERROR), attempt=0,
            idempotent=True)
        assert not decision.retry

    def test_401_refresh_once(self):
        first = retry_mod.decide_retry(
            self._err(ProviderErrorKind.AUTHENTICATION_ERROR), attempt=0,
            idempotent=True)
        assert first.refresh_credential and not first.retry
        second = retry_mod.decide_retry(
            self._err(ProviderErrorKind.AUTHENTICATION_ERROR), attempt=1,
            idempotent=True)
        assert not second.retry and not second.refresh_credential

    def test_non_idempotent_no_resend(self):
        decision = retry_mod.decide_retry(
            self._err(ProviderErrorKind.TIMEOUT), attempt=0, idempotent=False)
        assert not decision.retry


class TestRateLimit:
    def test_header_parsing(self):
        state = ratelimits.parse_headers({"X-RateLimit-Remaining": "0",
                                          "X-RateLimit-Reset": "2000000000"})
        assert state.remaining == 0
        decision = ratelimits.check(state, strategy="fail")
        assert not decision.allowed and decision.strategy == "fail"

    def test_configured_quota(self):
        state = ratelimits.RateLimitState(configured_per_minute=1)
        assert ratelimits.check(state).allowed
        ratelimits.record_call(state)
        decision = ratelimits.check(state, strategy="wait")
        assert not decision.allowed and decision.strategy == "wait"


class TestPagination:
    async def test_cursor_with_caps(self):
        from openagent.connectors.testing import paged
        paginator = pagination_mod.Paginator(pagination_mod.PageSpec(
            strategy="cursor", cursor_param="cursor", cursor_path="next_cursor",
            items_path="items", max_items=3, per_page=2))
        result = await paginator.collect(paged([{"id": i} for i in range(5)]))
        assert len(result.items) == 3
        assert result.truncated is True

    def test_unknown_strategy(self):
        with pytest.raises(ValueError):
            pagination_mod.Paginator(pagination_mod.PageSpec(strategy="teleport"))


class TestMapping:
    def test_paths_and_transforms(self):
        source = {"a": {"b": [{"c": 1}]}, "x": "1"}
        assert mapping_mod.resolve_path(source, "a.b.0.c") == 1
        assert mapping_mod.resolve_path(source, "missing", "dflt") == "dflt"
        out = mapping_mod.apply_mapping(source, {
            "fields": {
                "num": {"from": "x", "transform": {"op": "map", "table": {"1": "one"}}},
                "flat": {"from": "a.b", "transform": {"op": "flatten"}},
                "label": {"from": "x", "transform": {"op": "template",
                                                    "template": "n-{{x}}"}},
            }})
        assert out == {"num": "one", "flat": [{"c": 1}], "label": "n-1"}
        with pytest.raises(ValueError):
            mapping_mod.apply_transform(1, {"op": "rm -rf"}, {})

    def test_resources_keep_provider_ref(self):
        record = resources_mod.normalize(
            "message", "slack", {"id": "1", "text": "hi", "channel": "C1"})
        assert record["provider"] == "slack"
        assert record["provider_id"] == "1"
        assert record["raw_reference"]["provider"] == "slack"


class TestErrors:
    def test_normalize_http(self):
        assert normalize_http_error(401, {}).kind == \
            ProviderErrorKind.AUTHENTICATION_ERROR
        assert normalize_http_error(429, {}).kind == ProviderErrorKind.RATE_LIMITED
        assert normalize_http_error(404, {}).kind == ProviderErrorKind.NOT_FOUND
        assert normalize_http_error(400, {}).kind == ProviderErrorKind.VALIDATION_ERROR
        assert normalize_http_error(503, {}).kind == \
            ProviderErrorKind.PROVIDER_UNAVAILABLE


class TestDatabaseGuard:
    def test_classify(self):
        from openagent.connectors.db_connector import classify_statement
        assert classify_statement("SELECT 1") == "read"
        assert classify_statement("WITH x AS (SELECT 1) SELECT * FROM x") == "read"
        assert classify_statement("DELETE FROM users") == "write"
        assert classify_statement("SELECT 1; DROP TABLE users") == "deny"
        assert classify_statement("SELECT pg_sleep(5)") == "deny"

    def test_read_mode_blocks_writes(self):
        with pytest.raises(DatabaseError):
            validate_query("DELETE FROM users WHERE id = $1", mode="read")

    def test_table_allowlist(self):
        validate_query("SELECT * FROM orders", mode="read",
                       allowed_tables=["orders"])
        with pytest.raises(DatabaseError):
            validate_query("SELECT * FROM users", mode="read",
                           allowed_tables=["orders"])

    def test_params_accepted(self):
        assert validate_query("SELECT * FROM t WHERE id = $1",
                              mode="read")["numbered_params"] == [1]


class TestPolling:
    async def test_dedupe_and_backoff(self):
        cursor = polling_mod.PollCursor(last_seen_id="2")

        async def _fetch(_params):
            return [{"id": "3"}, {"id": "2"}, {"id": "3"}]

        result = await polling_mod.run_poll_cycle(cursor=cursor, fetch=_fetch)
        assert [i["id"] for i in result.new_items] == ["3"]
        assert result.cursor.last_seen_id == "3"
        assert not result.skipped_backoff

    async def test_backoff_skip(self):
        cursor = polling_mod.PollCursor(backoff_until_epoch=time.time() + 600)
        result = await polling_mod.run_poll_cycle(
            cursor=cursor, fetch=lambda _p: (_ for _ in ()).throw(
                AssertionError("must not fetch")))
        assert result.skipped_backoff


class TestWebhooks:
    def test_hmac_roundtrip(self):
        from openagent.connectors.webhooks import verify_hmac
        assert verify_hmac("s3cr3t", b"{}", "sha256=" + __import__(
            "hmac").new(b"s3cr3t", b"{}", __import__("hashlib").sha256
        ).hexdigest())
        assert not verify_hmac("s3cr3t", b"{}", "sha256=dead")
        assert not verify_hmac("", b"{}", "sha256=dead")

    def test_github_slack_stripe(self):
        import hashlib
        import hmac as _hmac

        from openagent.connectors.webhooks import (
            verify_github,
            verify_slack,
            verify_stripe,
        )
        body = b'{"ok": true}'
        secret = "s"
        gh = "sha256=" + _hmac.new(b"s", body, hashlib.sha256).hexdigest()
        assert verify_github(secret, body, {"X-Hub-Signature-256": gh})
        ts = str(int(time.time()))
        base = f"v0:{ts}:".encode() + body
        sig = "v0=" + _hmac.new(b"s", base, hashlib.sha256).hexdigest()
        assert verify_slack(secret, body, {"X-Slack-Request-Timestamp": ts,
                                           "X-Slack-Signature": sig})
        assert not verify_slack(secret, body,
                                {"X-Slack-Request-Timestamp": "1",
                                 "X-Slack-Signature": sig})
        stripe_sig = f"t={ts},v1=" + _hmac.new(
            b"s", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        assert verify_stripe(secret, body, {"Stripe-Signature": stripe_sig})

    def test_replay_guard(self):
        from openagent.connectors.webhooks import ReplayGuard, WebhookError
        guard = ReplayGuard(capacity=2)
        guard.check_and_mark("a")
        with pytest.raises(WebhookError):
            guard.check_and_mark("a")
        guard.check_and_mark("b")
        guard.check_and_mark("c")  # evicts oldest
        guard.check_and_mark("a")  # allowed again after eviction

    def test_timestamp_tolerance(self):
        from openagent.connectors.webhooks import WebhookError, check_timestamp
        check_timestamp(time.time())
        with pytest.raises(WebhookError):
            check_timestamp(time.time() - 3600)


class TestOAuth:
    def test_pkce_state_roundtrip(self):
        verifier, challenge = pkce_pair()
        assert verifier and challenge and verifier != challenge
        token = sign_state({"connection_id": "c1", "iat": time.time()},
                           "sekret")
        payload = verify_state(token, "sekret")
        assert payload["connection_id"] == "c1"
        with pytest.raises(Exception):
            verify_state(token + "x", "sekret")
        with pytest.raises(Exception):
            verify_state(sign_state({"iat": time.time() - 3600}, "sekret"),
                         "sekret")

    def test_authorize_url_https_and_scopes(self):
        config = OAuthConfig(
            authorize_url="https://provider.example/authorize",
            token_url="https://provider.example/token",
            client_id="cid", redirect_uri="https://app.example/cb",
            scopes=["read"])
        url, state, verifier = build_authorize_url(
            config, state_secret="s" * 32, connection_id="c1",
            extra_scopes=["write"])
        assert "scope=read+write" in url or "scope=read%20write" in url
        assert "code_challenge_method=S256" in url
        assert state and verifier

    def test_callback_host_allowlist(self):
        validate_callback_url("https://app.example/cb",
                              allowed_hosts=["app.example"])
        with pytest.raises(Exception):
            validate_callback_url("https://evil.example/cb",
                                  allowed_hosts=["app.example"])

    def test_token_expiry(self):
        tokens = TokenSet(access_token="a", expires_in=100,
                          obtained_at_epoch=time.time() - 200)
        assert tokens.expired()
        assert not TokenSet(access_token="a").expired()

    async def test_exchange_and_refresh(self):
        from openagent.connectors.oauth import OAuthManager
        config = OAuthConfig(
            authorize_url="https://p.example/a", token_url="https://p.example/t",
            client_id="cid", redirect_uri="https://app.example/cb")

        async def _post(url, fields, secrets):
            assert url == "https://p.example/t"
            if fields["grant_type"] == "authorization_code":
                assert fields["code_verifier"] == "v"
                return 200, {"access_token": "a1", "refresh_token": "r1",
                             "expires_in": 3600}
            return 200, {"access_token": "a2", "expires_in": 60}

        manager = OAuthManager(config)
        tokens = await manager.exchange_code(
            code="c", verifier="v", client_secret="s", post_form=_post)
        assert tokens.access_token == "a1"
        refreshed = await manager.refresh(
            refresh_token=tokens.refresh_token, client_secret="s",
            post_form=_post)
        assert refreshed.refresh_token == "r1"  # rotation preserved
        assert refreshed.access_token == "a2"


class TestOfficialManifests:
    def test_all_official_validate(self):
        from openagent.connectors.providers import provider_ids, register_official
        from openagent.connectors.registry import registry
        assert set(register_official()) >= {
            "github", "gitlab", "gmail", "slack", "google_calendar",
            "google_drive", "notion", "hubspot", "postgres", "discord",
            "telegram"}
        for connector_id in provider_ids():
            manifest = registry.get(connector_id)
            assert manifest is not None
            assert manifest.actions
            assert manifest.capabilities
