"""Official connector tests on the mock harness (MP21).

No real provider credentials: mock HTTP + mock auth + contract validation
for every bundled connector.
"""

import pytest

from openagent.connectors.testing import (
    MockProviderHTTP,
    mock_ctx,
    mock_rate_limited,
    mock_unauthorized,
    validate_manifest_contract,
)


def _auth(**secrets):
    return {"credential_id": "00000000-0000-0000-0000-000000000000",
            "credential_type": "api_key",
            "secrets": {"api_key": "test", **secrets},
            "expires_at": None}


class TestContracts:
    @pytest.mark.parametrize("connector_id", [
        "github", "gitlab", "gmail", "slack", "google_calendar",
        "google_drive", "notion", "hubspot", "postgres", "discord",
        "telegram"])
    def test_contract(self, connector_id):
        from openagent.connectors.providers import register_official
        register_official()
        from openagent.connectors.registry import registry
        manifest = registry.get(connector_id)
        assert manifest is not None
        from openagent.connectors.manifest import manifest_to_dict
        report = validate_manifest_contract(manifest_to_dict(manifest))
        assert report["connector"] == connector_id


class TestGitHub:
    async def test_create_issue(self):
        from openagent.connectors.providers import github
        http = MockProviderHTTP()
        http.add("POST", "/issues",
                 {"id": 1, "number": 7, "html_url": "https://x/7"})
        outcome = await github.execute(
            "github.create_issue",
            {"owner": "acme", "repo": "api", "title": "Bug",
             "body": "x"}, _auth(), mock_ctx(http))
        assert outcome["result"]["number"] == 7
        assert outcome["verified"] is True

    async def test_bad_repo_rejected(self):
        from openagent.connectors.errors import ProviderError
        from openagent.connectors.providers import github
        with pytest.raises(ProviderError):
            await github.execute(
                "github.create_issue",
                {"owner": "../evil", "repo": "api", "title": "x"},
                _auth(), mock_ctx())

    async def test_merge_is_single_shot(self):
        from openagent.connectors.providers import github
        http = MockProviderHTTP()
        http.add("PUT", "/merge",
                 {"merged": True, "sha": "abc"})
        outcome = await github.execute(
            "github.merge_pr",
            {"owner": "acme", "repo": "api", "number": 3,
             "merge_method": "squash"}, _auth(), mock_ctx(http))
        assert outcome["result"]["merged"] is True

    async def test_unauthorized_maps(self):
        from openagent.connectors.errors import ProviderError
        from openagent.connectors.providers import github
        http = MockProviderHTTP()
        http.add("GET", "/repos", mock_unauthorized())
        with pytest.raises(ProviderError):
            await github.execute("github.list_repos", {}, _auth(),
                                 mock_ctx(http))


class TestSlack:
    async def test_send_and_history(self):
        from openagent.connectors.providers import slack
        http = MockProviderHTTP()
        http.add("POST", "/chat.postMessage",
                 {"ok": True, "ts": "1.0", "channel": "C1"})
        http.add("GET", "/conversations.history",
                 {"ok": True, "messages": [{"ts": "1.0", "user": "U1",
                                            "text": "hi"}]})
        sent = await slack.execute(
            "slack.send_message", {"channel": "C1", "text": "hello"},
            _auth(), mock_ctx(http))
        assert sent["result"]["ts"] == "1.0"
        history = await slack.execute(
            "slack.get_history", {"channel": "C1", "limit": 5},
            _auth(), mock_ctx(http))
        assert history["result"]["messages"][0]["user"] == "U1"

    async def test_empty_text_rejected(self):
        from openagent.connectors.errors import ProviderError
        from openagent.connectors.providers import slack
        with pytest.raises(ProviderError):
            await slack.execute("slack.send_message",
                                {"channel": "C1", "text": "  "},
                                _auth(), mock_ctx())


class TestGmail:
    async def test_send_builds_rfc822(self):
        from openagent.connectors.providers import gmail
        http = MockProviderHTTP()
        http.add("POST", "/messages/send", {"id": "m1", "threadId": "t1"})
        outcome = await gmail.execute(
            "gmail.send_message",
            {"to": "user@example.com", "subject": "Hi", "body": "Hello"},
            _auth(access_token="tok"), mock_ctx(http))
        assert outcome["result"]["id"] == "m1"
        sent = http.calls[0]["json"]
        assert sent["raw"]

    async def test_bad_recipient_rejected(self):
        from openagent.connectors.errors import ProviderError
        from openagent.connectors.providers import gmail
        with pytest.raises(ProviderError):
            await gmail.execute(
                "gmail.send_message",
                {"to": "not-an-email", "subject": "x", "body": "y"},
                _auth(access_token="t"), mock_ctx())


class TestGitLab:
    async def test_create_issue(self):
        from openagent.connectors.providers import gitlab
        http = MockProviderHTTP()
        http.add("POST", "/issues", {"id": 9, "iid": 2, "web_url": "u"})
        outcome = await gitlab.execute(
            "gitlab.create_issue",
            {"project_id": "acme/api", "title": "Bug"}, _auth(),
            mock_ctx(http))
        assert outcome["result"]["iid"] == 2


class TestGoogle:
    async def test_create_event(self):
        from openagent.connectors.providers import google
        http = MockProviderHTTP()
        http.add("POST", "/events", {"id": "e1", "htmlLink": "u"})
        outcome = await google.execute(
            "google_calendar.create_event",
            {"summary": "Standup", "start": "2026-10-01T09:00:00Z",
             "end": "2026-10-01T09:15:00Z"}, _auth(access_token="t"),
            mock_ctx(http))
        assert outcome["result"]["id"] == "e1"

    async def test_drive_get_file(self):
        from openagent.connectors.providers import google
        http = MockProviderHTTP()
        http.add("GET", "/files/abc",
                 {"id": "abc", "name": "doc.txt"})
        outcome = await google.execute(
            "google_drive.get_file", {"file_id": "abc"},
            _auth(access_token="t"), mock_ctx(http))
        assert outcome["result"]["name"] == "doc.txt"


class TestBusiness:
    async def test_notion_create_page(self):
        from openagent.connectors.providers import business
        http = MockProviderHTTP()
        http.add("POST", "/pages", {"id": "p1", "url": "u"})
        outcome = await business.execute(
            "notion.create_page",
            {"parent_id": "a" * 32, "title": "Notes", "content": "hi"},
            _auth(access_token="t"), mock_ctx(http))
        assert outcome["result"]["id"] == "p1"

    async def test_hubspot_create_contact(self):
        from openagent.connectors.providers import business
        http = MockProviderHTTP()
        http.add("POST", "/contacts", {"id": "c1"})
        outcome = await business.execute(
            "hubspot.create_contact", {"email": "a@b.co"},
            _auth(access_token="t"), mock_ctx(http))
        assert outcome["result"]["id"] == "c1"


class TestMessaging:
    async def test_discord_send(self):
        from openagent.connectors.providers import messaging
        http = MockProviderHTTP()
        http.add("POST", "/messages", {"id": "m1"})
        outcome = await messaging.execute(
            "discord.send_message",
            {"channel_id": "123", "content": "hi"}, _auth(),
            mock_ctx(http))
        assert outcome["result"]["id"] == "m1"

    async def test_telegram_send(self):
        from openagent.connectors.providers import messaging
        http = MockProviderHTTP()
        http.add("POST", "/sendMessage",
                 {"ok": True, "result": {"message_id": 42}})
        outcome = await messaging.execute(
            "telegram.send_message", {"chat_id": "1", "text": "hi"},
            _auth(bot_token="tok"), mock_ctx(http))
        assert outcome["result"]["message_id"] == 42


class TestPostgresManifest:
    def test_manifest_shape(self):
        from openagent.connectors.providers import postgres
        actions = {a["id"] for a in postgres.MANIFEST["actions"]}
        assert actions == {"postgres.query", "postgres.read",
                           "postgres.inspect"}

    async def test_read_forces_read_mode(self):
        from openagent.connectors import db_connector
        from openagent.connectors.providers import postgres
        calls = {}

        async def _fake_execute_postgres(*, dsn, sql, params=None,
                                         timeout_seconds=15, max_rows=500):
            calls["sql"] = sql
            calls["dsn"] = dsn
            return {"status": "ok", "kind": "read", "rows": [],
                    "row_count": 0, "truncated": False, "latency_ms": 1}

        original = db_connector.execute_postgres
        db_connector.execute_postgres = _fake_execute_postgres
        try:
            outcome = await postgres.execute(
                "postgres.read",
                {"sql": "SELECT 1", "mode": "write"},
                {"secrets": {"dsn": "postgresql://u:p@localhost:5432/db"}},
                {"http": None, "logger": None, "connection": {"config": {}}})
            assert outcome["verified"] is True
            assert calls["dsn"].startswith("postgresql://")
        finally:
            db_connector.execute_postgres = original


class TestHarnessBehaviors:
    async def test_rate_limit_surfaces(self):
        from openagent.connectors.errors import ProviderError
        from openagent.connectors.providers import slack
        http = MockProviderHTTP()
        http.add("GET", "/conversations.list", mock_rate_limited())
        with pytest.raises(ProviderError):
            await slack.execute("slack.list_channels", {}, _auth(),
                                mock_ctx(http))

    async def test_pagination_helper(self):
        from openagent.connectors.pagination import PageSpec, Paginator
        from openagent.connectors.testing import paged
        paginator = Paginator(PageSpec(strategy="cursor",
                                       cursor_param="cursor",
                                       cursor_path="next_cursor",
                                       items_path="items", max_items=10,
                                       per_page=3))
        result = await paginator.collect(paged([{"id": i} for i in range(7)],
                                                 per_page=3))
        assert len(result.items) == 7
        assert result.pages_fetched == 3
        assert result.truncated is False
