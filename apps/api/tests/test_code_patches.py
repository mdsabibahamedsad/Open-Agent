"""Patch engine unit tests: parse/validate/apply, atomicity, traversal guards.

Pure filesystem tests (tmp dirs) — no database, no git required except where
noted.
"""

import pytest

from openagent.code.patches import (
    PatchError,
    apply_patch,
    generate_diff,
    parse_unified_diff,
    validate_patch,
)

HELLO = "def hello():\n    return 'hi'\n"


def _write(root, rel, content):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestParse:
    def test_single_file(self):
        diff = generate_diff(HELLO, "def hello():\n    return 'yo'\n", "a.py")
        fps = parse_unified_diff(diff)
        assert len(fps) == 1
        assert fps[0].new_path == "a.py"
        assert len(fps[0].hunks) == 1

    def test_empty_rejected(self):
        with pytest.raises(PatchError):
            parse_unified_diff("")

    def test_malformed_hunk_rejected(self):
        with pytest.raises(PatchError):
            parse_unified_diff("--- a/x.py\n+++ b/x.py\n@@ nonsense @@\n+hi\n")

    def test_missing_headers_rejected(self):
        with pytest.raises(PatchError):
            parse_unified_diff("+just a line\n")


class TestApply:
    def test_replace_line(self, tmp_path):
        _write(tmp_path, "a.py", HELLO)
        diff = generate_diff(HELLO, "def hello():\n    return 'yo'\n", "a.py")
        res = apply_patch(str(tmp_path), diff)
        assert res.files_changed == ["a.py"]
        assert (tmp_path / "a.py").read_text() == "def hello():\n    return 'yo'\n"
        assert res.insertions == 1 and res.deletions == 1

    def test_stale_context_rejected(self, tmp_path):
        _write(tmp_path, "a.py", "def hello():\n    return 'changed!'\n")
        diff = generate_diff(HELLO, "def hello():\n    return 'yo'\n", "a.py")
        with pytest.raises(PatchError):
            apply_patch(str(tmp_path), diff)
        # File untouched.
        assert (tmp_path / "a.py").read_text().startswith("def hello():\n    return 'changed!'")

    def test_wrong_file_rejected(self, tmp_path):
        diff = generate_diff(HELLO, "x", "missing.py")
        with pytest.raises(PatchError):
            apply_patch(str(tmp_path), diff)

    def test_traversal_rejected(self, tmp_path):
        evil = ("--- a/ok.py\n+++ b/../../evil.py\n@@ -1 +1 @@\n-a\n+b\n")
        with pytest.raises(PatchError):
            apply_patch(str(tmp_path), evil)

    def test_secret_in_added_lines_flagged(self, tmp_path):
        _write(tmp_path, "c.py", "x = 1\n")
        diff = generate_diff("x = 1\n", 'x = 1\npassword = "hunter2-hunter"\n', "c.py")
        fps = parse_unified_diff(diff)
        ok, errors, needs_approval = validate_patch(str(tmp_path), fps)
        assert not ok
        assert needs_approval
        assert any("secret" in e.lower() for e in errors)

    def test_sensitive_filename_needs_approval(self, tmp_path):
        _write(tmp_path, ".env", "A=1\n")
        diff = generate_diff("A=1\n", "A=2\n", ".env")
        fps = parse_unified_diff(diff)
        ok, errors, needs_approval = validate_patch(str(tmp_path), fps)
        assert ok and needs_approval

    def test_atomic_multi_file(self, tmp_path):
        _write(tmp_path, "good.py", "a = 1\n")
        _write(tmp_path, "stale.py", "b = 999\n")  # patch expects b = 1
        d1 = generate_diff("a = 1\n", "a = 2\n", "good.py")
        d2 = generate_diff("b = 1\n", "b = 2\n", "stale.py")
        with pytest.raises(PatchError):
            apply_patch(str(tmp_path), d1 + d2)
        # Atomic: good.py must NOT have been modified either.
        assert (tmp_path / "good.py").read_text() == "a = 1\n"

    def test_dry_run_writes_nothing(self, tmp_path):
        _write(tmp_path, "a.py", HELLO)
        diff = generate_diff(HELLO, "zzz", "a.py")
        apply_patch(str(tmp_path), diff, dry_run=True)
        assert (tmp_path / "a.py").read_text() == HELLO

    def test_new_file_and_delete(self, tmp_path):
        diff_new = ("--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+print('new')\n")
        res = apply_patch(str(tmp_path), diff_new)
        assert (tmp_path / "new.py").read_text() == "print('new')\n"
        assert res.files_changed == ["new.py"]
        _write(tmp_path, "gone.py", "x\n")
        diff_del = ("--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n")
        res = apply_patch(str(tmp_path), diff_del)
        assert not (tmp_path / "gone.py").exists()
