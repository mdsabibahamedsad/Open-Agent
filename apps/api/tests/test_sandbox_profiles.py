"""Sandbox profile unit tests: builtins, level gates, custom overlays.

Pure unit tests — no database required.
"""

import pytest

from openagent.sandbox.profiles import (
    get_profile,
    list_profiles,
    profile_from_dict,
    profile_to_dict,
    validate_profile_dict,
)


class TestBuiltinProfiles:
    def test_all_nine_present_and_valid(self):
        assert {p.name for p in list_profiles()} == {
            "READ_ONLY", "TEST", "LINT", "TYPECHECK", "BUILD", "PACKAGE",
            "DEVELOPMENT", "DATA_PROCESSING", "CUSTOM"}
        for p in list_profiles():
            assert p.validate() == [], (p.name, p.validate())

    def test_conservative_defaults(self):
        assert get_profile("TEST").network.mode == "NO_NETWORK"
        assert get_profile("TEST").readonly_rootfs is True
        assert get_profile("READ_ONLY").security_level == 0
        assert get_profile("PACKAGE").network.mode == "ALLOWLIST"
        assert "pypi.org" in get_profile("PACKAGE").network.allowed_domains
        assert get_profile("DEVELOPMENT").commands.allow_shell is True

    def test_unknown_profile(self):
        with pytest.raises(ValueError):
            get_profile("YOLO")


class TestLevelGates:
    def test_network_needs_level_2(self):
        p = profile_from_dict({**profile_to_dict(get_profile("TEST")),
                               "network": {"mode": "ALLOWLIST",
                                           "allowed_domains": ["x.com"],
                                           "allowed_ports": [], "denied_domains": []}})
        assert any("LEVEL_2" in v for v in p.validate())

    def test_full_outbound_needs_level_4(self):
        base = profile_to_dict(get_profile("DEVELOPMENT"))
        base.update({"security_level": 3,
                     "network": {"mode": "FULL_OUTBOUND", "allowed_domains": [],
                                 "allowed_ports": [], "denied_domains": []}})
        assert any("LEVEL_4" in v for v in profile_from_dict(base).validate())

    def test_untrusted_image_needs_level_4(self):
        base = profile_to_dict(get_profile("TEST"))
        base.update({"security_level": 1, "image_trust": "UNTRUSTED"})
        assert any("LEVEL_4" in v for v in profile_from_dict(base).validate())

    def test_shell_needs_level_3(self):
        base = profile_to_dict(get_profile("TEST"))
        base["commands"] = {"allowed_commands": [], "denied_commands": [],
                            "denied_categories": [], "allow_shell": True}
        assert any("LEVEL_3" in v for v in profile_from_dict(base).validate())

    def test_resource_bounds(self):
        base = profile_to_dict(get_profile("TEST"))
        base.update({"cpu": 999.0, "memory_mb": 8, "timeout_seconds": 99999})
        problems = profile_from_dict(base).validate()
        assert len(problems) >= 3


class TestCustomOverlays:
    def test_round_trip(self):
        d = profile_to_dict(get_profile("LINT"))
        p = profile_from_dict(d)
        assert p.validate() == []
        assert p.name == "LINT"

    def test_invalid_dict_fails_closed(self):
        assert validate_profile_dict({}) == []  # pure defaults are valid
        bad = profile_to_dict(get_profile("TEST"))
        bad["network"] = {"mode": "WIDE_OPEN"}
        assert validate_profile_dict(bad) != []
        assert validate_profile_dict({"name": "TEST", "cpu": "lots"}) != []
