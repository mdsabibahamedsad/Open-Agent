"""Sandbox configuration tests: fail-closed validation, prod gates.

Pure unit tests — no database, no daemon. Environment is mutated per-test
and restored afterwards.
"""

import os

import pytest

from openagent.sandbox.config import SandboxSettings, is_production, load_settings


@pytest.fixture
def clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("SANDBOX_") or key == "OPENAGENT_ENV":
            monkeypatch.delenv(key, raising=False)


class TestSettings:
    def test_defaults_valid_in_dev(self, clean_env):
        s = load_settings()
        assert s.provider == "docker"
        assert s.default_profile == "TEST"

    def test_unknown_profile_fails(self, clean_env, monkeypatch):
        monkeypatch.setenv("SANDBOX_DEFAULT_PROFILE", "YOLO")
        with pytest.raises(ValueError):
            load_settings()

    def test_bad_numbers_fail(self, clean_env, monkeypatch):
        monkeypatch.setenv("SANDBOX_MAX_MEMORY", "huge")
        with pytest.raises(ValueError):
            load_settings()

    def test_default_timeout_capped(self, clean_env, monkeypatch):
        monkeypatch.setenv("SANDBOX_DEFAULT_TIMEOUT", "99999")
        with pytest.raises(ValueError):
            load_settings()

    def test_production_requires_pinning(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAGENT_ENV", "production")
        assert is_production()
        with pytest.raises(ValueError):
            load_settings()

    def test_production_forbids_local_fallback(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAGENT_ENV", "production")
        monkeypatch.setenv("SANDBOX_PROVIDER", "local")
        monkeypatch.setenv("SANDBOX_IMAGE_DIGEST", "sha256:abc")
        with pytest.raises(ValueError) as e:
            load_settings()
        assert "local" in str(e.value).lower()

    def test_production_ok_when_pinned(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAGENT_ENV", "production")
        monkeypatch.setenv("SANDBOX_IMAGE_DIGEST", "sha256:abc123")
        s = load_settings()
        assert s.validate() == []

    def test_direct_validation(self):
        s = SandboxSettings(provider="nope")
        assert any("provider" in p.lower() for p in s.validate())
