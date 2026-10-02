"""Patch-first editing engine: unified-diff generation, validation, application.

Every modification produces a structured change record. Patches are verified
(file exists, base content matches, path stays in workspace) before anything
is written. Multi-file patches apply atomically per task change-set: any
hunk failure aborts the whole patch (no partial writes).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from openagent.code.security import (
    is_sensitive_filename,
    scan_text_for_secrets,
    validate_workspace_path,
)

MAX_PATCH_BYTES = 500_000
MAX_FILES_PER_PATCH = 50


class PatchError(Exception):
    pass


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)  # raw body lines w/ prefix


@dataclass
class FilePatch:
    old_path: str
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)
    is_new: bool = False
    is_delete: bool = False


@dataclass
class ChangeRecord:
    file: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    summary: str


@dataclass
class PatchResult:
    files_changed: list[str]
    changes: list[ChangeRecord]
    insertions: int
    deletions: int


def generate_diff(original: str, modified: str, filename: str) -> str:
    """Unified diff between two texts (single file)."""
    return "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f"a/{filename}", tofile=f"b/{filename}"))


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FILE_OLD_RE = re.compile(r"^--- ([^\t\n]+)")
_FILE_NEW_RE = re.compile(r"^\+\+\+ ([^\t\n]+)")


def parse_unified_diff(diff_text: str) -> list[FilePatch]:
    """Parse (possibly multi-file) unified diff. Raises PatchError if malformed."""
    if not diff_text or not diff_text.strip():
        raise PatchError("Empty patch")
    if len(diff_text.encode("utf-8")) > MAX_PATCH_BYTES:
        raise PatchError("Patch exceeds size limit")
    files: list[FilePatch] = []
    current: Optional[FilePatch] = None
    current_hunk: Optional[Hunk] = None

    def flush_hunk() -> None:
        nonlocal current_hunk
        if current is not None and current_hunk is not None:
            current.hunks.append(current_hunk)
            current_hunk = None

    for raw in diff_text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("--- "):
            flush_hunk()
            m = _FILE_OLD_RE.match(line)
            if not m:
                raise PatchError(f"Malformed --- header: {line[:80]}")
            old = m.group(1).strip()
            if current is not None and current.old_path == "__pending__":
                current.old_path = _strip_prefix(old)
            else:
                current = FilePatch(old_path=_strip_prefix(old), new_path="__pending__")
                files.append(current)
        elif line.startswith("+++ "):
            m = _FILE_NEW_RE.match(line)
            if not m:
                raise PatchError(f"Malformed +++ header: {line[:80]}")
            if current is None:
                raise PatchError("+++ header without --- header")
            current.new_path = _strip_prefix(m.group(1).strip())
        elif line.startswith("@@"):
            m = _HUNK_RE.match(line)
            if not m:
                raise PatchError(f"Malformed hunk header: {line[:80]}")
            if current is None:
                raise PatchError("Hunk without file header")
            flush_hunk()
            current_hunk = Hunk(
                old_start=int(m.group(1)), old_count=int(m.group(2) or "1"),
                new_start=int(m.group(3)), new_count=int(m.group(4) or "1"))
        elif line.startswith(("diff --git", "index ", "new file", "deleted",
                              "similarity", "rename", "old mode", "new mode")):
            continue
        elif current_hunk is not None and line[:1] in (" ", "-", "+", "\\"):
            if line.startswith("\\"):
                continue  # "\ No newline at end of file"
            current_hunk.lines.append(line)
        elif line.strip() == "":
            continue
        else:
            raise PatchError(f"Malformed patch line: {line[:80]}")

    flush_hunk()
    if not files:
        raise PatchError("No file patches found")
    if len(files) > MAX_FILES_PER_PATCH:
        raise PatchError("Patch touches too many files")
    out: list[FilePatch] = []
    for f in files:
        if f.new_path == "__pending__":
            raise PatchError("Missing +++ header")
        old, new = f.old_path, f.new_path
        f.is_new = old in ("/dev/null", "dev/null")
        f.is_delete = new in ("/dev/null", "dev/null")
        if not f.hunks and not (f.is_new or f.is_delete):
            raise PatchError(f"No hunks for file {new}")
        out.append(f)
    return out


def _strip_prefix(p: str) -> str:
    if p in ("/dev/null", "dev/null"):
        return p
    for prefix in ("a/", "b/"):
        if p.startswith(prefix):
            return p[len(prefix):]
    return p


def _target_path(fp: FilePatch) -> str:
    if fp.is_delete:
        return fp.old_path
    return fp.new_path


def validate_patch(root: str, file_patches: list[FilePatch]) -> tuple[bool, list[str], bool]:
    """Pre-apply checks. Returns (ok, errors, needs_approval).

    needs_approval is True when sensitive filenames are touched or secrets
    appear in added lines.
    """
    errors: list[str] = []
    needs_approval = False
    seen: set[str] = set()
    for fp in file_patches:
        target = _target_path(fp)
        if target in seen:
            errors.append(f"Duplicate file entry: {target}")
        seen.add(target)
        v = validate_workspace_path(root, target)
        if not v.valid:
            errors.append(f"{target}: {v.reason}")
            continue
        if is_sensitive_filename(target):
            needs_approval = True
        for hunk in fp.hunks:
            for line in hunk.lines:
                if line.startswith("+") and not line.startswith("+++"):
                    for finding in scan_text_for_secrets(line[1:], target):
                        errors.append(
                            f"{target}: likely secret ({finding.kind}) in added line — "
                            f"remove it or request approval")
                        needs_approval = True
                        break
    return (len(errors) == 0, errors, needs_approval)


def _apply_hunks(original_lines: list[str], hunks: list[Hunk], filename: str) -> list[str]:
    """Apply hunks with strict context verification (1-indexed old offsets)."""
    result: list[str] = []
    cursor = 0  # 0-indexed position in original_lines consumed so far
    for hunk in hunks:
        start = hunk.old_start - 1 if hunk.old_start > 0 else 0
        if start < cursor:
            raise PatchError(f"{filename}: overlapping hunks (stale context?)")
        if start > len(original_lines):
            raise PatchError(
                f"{filename}: hunk starts at line {hunk.old_start} "
                f"but file has {len(original_lines)} lines (wrong line?)")
        result.extend(original_lines[cursor:start])
        idx = start
        for line in hunk.lines:
            prefix, text = line[0], line[1:]
            if prefix == " ":
                if idx >= len(original_lines) or original_lines[idx] != text:
                    raise PatchError(
                        f"{filename}: context mismatch near line {idx + 1} (stale file?)")
                result.append(original_lines[idx])
                idx += 1
            elif prefix == "-":
                if idx >= len(original_lines) or original_lines[idx] != text:
                    raise PatchError(
                        f"{filename}: removal mismatch near line {idx + 1} "
                        f"(file changed since patch?)")
                idx += 1
            elif prefix == "+":
                result.append(text)
            else:
                raise PatchError(f"{filename}: bad hunk prefix {prefix!r}")
        cursor = idx
    result.extend(original_lines[cursor:])
    # Verify hunk counts loosely (tolerate zero-count edge hunks).
    return result


def apply_file_patch(root: str, fp: FilePatch, dry_run: bool = False) -> ChangeRecord:
    target = _target_path(fp)
    v = validate_workspace_path(root, target)
    if not v.valid:
        raise PatchError(f"{target}: {v.reason}")
    resolved = Path(v.resolved or "")
    if fp.is_delete:
        if not resolved.is_file():
            raise PatchError(f"{target}: file does not exist")
        original: list[str] = []
        if not dry_run:
            resolved.unlink()
        return ChangeRecord(file=target, old_start=1, old_lines=0,
                            new_start=0, new_lines=0, summary="deleted file")
    original_lines: list[str] = []
    if fp.is_new:
        if resolved.exists():
            raise PatchError(f"{target}: file already exists (wrong file?)")
    else:
        if not resolved.is_file():
            raise PatchError(f"{target}: file does not exist (wrong file?)")
        original_lines = resolved.read_text(
            encoding="utf-8", errors="replace").splitlines()
    new_lines = _apply_hunks(original_lines, fp.hunks, target)
    if not dry_run:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text("\n".join(new_lines) + ("\n" if new_lines else ""),
                            encoding="utf-8")
    ins = sum(1 for h in fp.hunks for ln in h.lines if ln.startswith("+"))
    dels = sum(1 for h in fp.hunks for ln in h.lines if ln.startswith("-"))
    first = fp.hunks[0] if fp.hunks else Hunk(1, 0, 1, 0)
    return ChangeRecord(file=target, old_start=first.old_start,
                        old_lines=sum(h.old_count for h in fp.hunks),
                        new_start=first.new_start,
                        new_lines=sum(h.new_count for h in fp.hunks),
                        summary=f"+{ins}/-{dels}")


def apply_patch(root: str, diff_text: str,
                dry_run: bool = False) -> PatchResult:
    """Validate then apply a (multi-file) patch atomically.

    Dry-run first, then write: any hunk failure aborts before any write.
    """
    file_patches = parse_unified_diff(diff_text)
    ok, errors, _ = validate_patch(root, file_patches)
    if not ok:
        raise PatchError("Patch validation failed: " + "; ".join(errors[:5]))
    if dry_run:
        for fp in file_patches:
            apply_file_patch(root, fp, dry_run=True)
        return PatchResult(files_changed=[], changes=[], insertions=0, deletions=0)
    # Two-phase: verify all hunks against current content, then write.
    planned: list[tuple[FilePatch, list[str] | None]] = []
    for fp in file_patches:
        target = _target_path(fp)
        v = validate_workspace_path(root, target)
        resolved = Path(v.resolved or "")
        if fp.is_delete:
            if not resolved.is_file():
                raise PatchError(f"{target}: file does not exist")
            planned.append((fp, None))
            continue
        if fp.is_new:
            if resolved.exists():
                raise PatchError(f"{target}: file already exists")
            planned.append((fp, []))
            continue
        if not resolved.is_file():
            raise PatchError(f"{target}: file does not exist")
        original = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        _apply_hunks(original, fp.hunks, target)  # raises on mismatch
        planned.append((fp, original))
    changes: list[ChangeRecord] = []
    ins = dels = 0
    for fp, _original in planned:
        rec = apply_file_patch(root, fp, dry_run=False)
        changes.append(rec)
        m = re.match(r"\+(\d+)/-(\d+)", rec.summary)
        if m:
            ins += int(m.group(1))
            dels += int(m.group(2))
    return PatchResult(files_changed=[c.file for c in changes], changes=changes,
                       insertions=ins, deletions=dels)
