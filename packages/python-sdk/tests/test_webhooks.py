import time

import pytest

from openagent.errors import ValidationError
from openagent.webhooks import parse_webhook, sign_webhook, verify_webhook

SECRET = "whsec_test_secret"
BODY = b'{"event": "extension.published", "id": "evt_1"}'


def test_sign_verify_roundtrip():
    header = sign_webhook(SECRET, BODY, delivery_id="dlv_1")
    assert header.startswith("v1,t=")
    result = verify_webhook(SECRET, BODY, header)
    assert result == {"ok": True, "reason": "", "delivery_id": "dlv_1"}


def test_sign_verify_positional_timestamp():
    ts = int(time.time())
    header = sign_webhook(SECRET, BODY, "dlv_2", ts)
    result = verify_webhook(SECRET, BODY, header, int(time.time()), 300)
    assert result["ok"] is True
    assert result["delivery_id"] == "dlv_2"


def test_tampered_body_fails():
    header = sign_webhook(SECRET, BODY, delivery_id="dlv_1")
    result = verify_webhook(SECRET, b'{"event": "tampered"}', header)
    assert result["ok"] is False
    assert result["reason"] == "signature mismatch"


def test_wrong_secret_fails():
    header = sign_webhook(SECRET, BODY, delivery_id="dlv_1")
    result = verify_webhook("other", BODY, header)
    assert result["ok"] is False


def test_replay_outside_tolerance_fails():
    old_ts = int(time.time()) - 3600
    header = sign_webhook(SECRET, BODY, delivery_id="dlv_1", timestamp=old_ts)
    result = verify_webhook(SECRET, BODY, header)
    assert result["ok"] is False
    assert result["reason"] == "timestamp outside tolerance"


def test_malformed_header_fails():
    for bad in ["", "v2,t=1,id=x,sig=y", "v1,t=abc", "not-a-header"]:
        result = verify_webhook(SECRET, BODY, bad)
        assert result["ok"] is False


def test_parse_webhook_requires_event():
    assert parse_webhook(BODY)["event"] == "extension.published"
    with pytest.raises(ValidationError):
        parse_webhook(b'{"nope": true}')
    with pytest.raises(ValidationError):
        parse_webhook(b"not json")
