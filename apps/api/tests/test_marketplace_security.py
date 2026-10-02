"""MP23 security tests: content injection, URL abuse, artifact attacks,
webhook forgery/replay, entitlement forgery, tenant predicates.

Pure domain + static API-shape checks — no database required.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from openagent.marketplace import billing as billing_module
from openagent.marketplace import distribution as dist_module
from openagent.marketplace import entitlements as ent_module
from openagent.marketplace import sanitize as sanitize_module


class TestContentInjection:
    @pytest.mark.parametrize("payload", [
        "<script>alert(document.cookie)</script>",
        "<img src=x onerror=alert(1)>",
        "<iframe src='https://evil.example'></iframe>",
        "<a href=\"javascript:alert(1)\">click</a>",
        "<form action='https://evil.example'><input></form>",
        "<STYLE>body{display:none}</STYLE>",
    ])
    def test_active_markup_rejected(self, payload):
        with pytest.raises(sanitize_module.ContentError):
            sanitize_module.validate_body(payload, field="description")

    def test_event_handler_attributes_rejected(self):
        assert sanitize_module.contains_active_markup(
            '<div onmouseover="steal()">x</div>')

    def test_plain_markdown_accepted(self):
        body = "# Title\n\nSome **bold** text with a [link](https://example.com)."
        assert sanitize_module.validate_body(body) == body

    def test_title_strips_but_keeps_text(self):
        assert sanitize_module.validate_title("<b>Hi</b>") == "Hi"
        with pytest.raises(sanitize_module.ContentError):
            sanitize_module.validate_title("   <br>  ")


class TestUrlSafety:
    @pytest.mark.parametrize("url", [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "//evil.example/phish",
        "https://",
        "not a url",
        "",
    ])
    def test_unsafe_urls_rejected(self, url):
        assert not sanitize_module.is_safe_url(url), url

    @pytest.mark.parametrize("url", [
        "https://example.com/docs",
        "http://localhost:3000/x",
        "https://example.com/a?b=c&d=e",
    ])
    def test_safe_urls_accepted(self, url):
        assert sanitize_module.is_safe_url(url), url

    def test_open_redirect_shape_rejected(self):
        # Scheme-relative and bare-host URLs never pass as external links.
        assert not sanitize_module.is_safe_url("evil.example/path")

    def test_phishing_lookalike_still_https(self):
        # Homoglyph defense is registrar-level; the gate guarantees the
        # scheme+host parse so renderers can show the real host.
        assert sanitize_module.is_safe_url("https://examp1e.com/")


class TestArtifactAttacks:
    def _zip(self, members: dict[str, bytes],
             compress=zipfile.ZIP_DEFLATED) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compress) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return buffer.getvalue()

    def test_traversal_variants(self):
        for name in ("../x", "..\\x", "/abs/x", "a/../../x"):
            result = dist_module.verify_archive(
                self._zip({name: b"x"}), filename="p.zip")
            assert not result["ok"], name

    def test_too_many_files(self):
        members = {f"f{i}.txt": b"x" for i in range(2100)}
        result = dist_module.verify_archive(
            self._zip(members), filename="p.zip")
        assert not result["ok"]

    def test_compression_bomb(self):
        bomb = b"A" * (3 * 1024 * 1024)
        result = dist_module.verify_archive(
            self._zip({"bomb.txt": bomb}), filename="p.zip")
        assert not result["ok"]
        assert any("bomb" in p for p in result["problems"])

    def test_oversize_archive(self):
        big = b"x" * (dist_module.MAX_ARCHIVE_BYTES + 1)
        result = dist_module.verify_archive(big, filename="p.zip")
        assert not result["ok"]

    def test_executable_assets_blocked(self):
        for name in ("run.exe", "lib.dll", "app.js", "page.html"):
            problems = dist_module.validate_asset_upload(
                filename=name, mime="application/octet-stream",
                size_bytes=100)
            assert problems, name

    def test_storage_key_cannot_escape(self):
        key = dist_module.content_key("a", "b" * 64, "../../../x")
        assert ".." not in key
        assert dist_module.check_safe_member("../../x") is not None


class TestWebhookSecurity:
    def test_unsigned_rejected(self):
        assert not billing_module.verify_webhook_signature(
            secret="s", raw_body=b"{}", signature="")

    def test_tampered_body_rejected(self):
        import hashlib as _hashlib
        import hmac as _hmac

        secret = "whsec-1"
        good = _hmac.new(secret.encode(), b'{"a":1}',
                         _hashlib.sha256).hexdigest()
        assert billing_module.verify_webhook_signature(
            secret=secret, raw_body=b'{"a":1}', signature=good)
        assert not billing_module.verify_webhook_signature(
            secret=secret, raw_body=b'{"a":2}', signature=good)

    def test_stale_timestamp_rejected(self):
        assert not billing_module.verify_webhook_timestamp("1")
        assert not billing_module.verify_webhook_timestamp("tomorrow")

    def test_wrong_secret_rejected(self):
        import hashlib as _hashlib
        import hmac as _hmac

        sig = _hmac.new(b"right", b"{}", _hashlib.sha256).hexdigest()
        assert not billing_module.verify_webhook_signature(
            secret="wrong", raw_body=b"{}", signature=sig)


class TestEntitlementForgery:
    def test_forged_active_without_scope_fails(self):
        # An entitlement for another org must not authorize this org.
        allowed, _, _ = ent_module.can_install_listing(
            pricing_model="ONE_TIME",
            entitlements=[{"organization_id": "org-other", "user_id": "",
                           "status": "ACTIVE", "valid_from": "",
                           "valid_until": ""}],
            organization_id="org-mine", commerce_configured=True)
        assert not allowed

    def test_status_strings_not_trusted(self):
        live, _ = ent_module.entitlement_is_live({"status": "ACTIVE;;"})
        assert not live

    def test_backdated_window_rejected(self):
        live, reason = ent_module.entitlement_is_live(
            {"status": "ACTIVE", "valid_from": "", "valid_until": "2000-01-01"})
        assert not live
        assert "valid_until" in reason


class TestTenantPredicates:
    def test_public_visible_to_all(self):
        from openagent.db.models.marketplace import Marketplace, MarketplaceType

        row = Marketplace(slug="x", name="x", type=MarketplaceType.PUBLIC_MARKETPLACE)
        from openagent.api.v1.marketplace import _marketplace_visible
        import uuid

        assert _marketplace_visible(row, uuid.uuid4())

    def test_private_hidden_from_others(self):
        import uuid

        from openagent.api.v1.marketplace import _marketplace_visible
        from openagent.db.models.marketplace import (
            Marketplace,
            MarketplaceType,
        )

        owner = uuid.uuid4()
        row = Marketplace(slug="x", name="x",
                          type=MarketplaceType.PRIVATE_MARKETPLACE,
                          owner_organization_id=owner)
        assert _marketplace_visible(row, owner)
        assert not _marketplace_visible(row, uuid.uuid4())
