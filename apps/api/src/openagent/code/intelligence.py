"""Code intelligence: indexing pipeline, layered search, context builder.

Pure logic lives here (testable without a DB); persistence is handled by
``CodeService``. Semantic search is a provider hook — memory/embedding
infrastructure can be plugged in; without it the engine degrades to
exact + symbol search (never a fake result).
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol


# --------------------------------------------------------------------------
# Ignore rules / language detection
# --------------------------------------------------------------------------

DEFAULT_EXCLUDES = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    "out", "target", ".next", ".nuxt", "coverage", ".coverage",
    ".idea", ".vscode", ".DS_Store", "vendor", "third_party",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svgz", ".pdf",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib",
    ".o", ".a", ".class", ".jar", ".war", ".pyc", ".pyo", ".wasm",
    ".mp3", ".mp4", ".mov", ".avi", ".woff", ".woff2", ".ttf", ".eot",
    ".sqlite", ".db", ".lockb", ".node",
}

EXTENSION_LANGUAGE = {
    ".py": "python", ".pyi": "python",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".java": "java", ".go": "go", ".rs": "rust", ".cs": "csharp",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".sql": "sql", ".html": "html", ".htm": "html", ".css": "css", ".scss": "css",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".md": "markdown", ".mdx": "markdown", ".xml": "xml", ".sh": "shell",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin",
}


def load_gitignore(root: Path) -> list[str]:
    patterns: list[str] = []
    for name in (".gitignore", ".git/info/exclude"):
        p = root / name
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
            except OSError:
                continue
    return patterns


def is_excluded(rel_posix: str, extra_patterns: list[str]) -> bool:
    parts = rel_posix.split("/")
    if any(p in DEFAULT_EXCLUDES for p in parts):
        return True
    for pat in extra_patterns:
        p = pat.strip().lstrip("/")
        if not p:
            continue
        target = rel_posix if "/" in p.rstrip("/") else parts[-1]
        if fnmatch.fnmatch(target, p) or fnmatch.fnmatch(rel_posix, p):
            return True
        if p.endswith("/") and rel_posix.startswith(p):
            return True
    return False


def detect_language(path: str) -> Optional[str]:
    return EXTENSION_LANGUAGE.get(Path(path).suffix.lower())


def is_binary_path(path: str) -> bool:
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


# --------------------------------------------------------------------------
# Data records (mirror DB rows; service persists them)
# --------------------------------------------------------------------------

@dataclass
class IndexedFile:
    path: str
    language: Optional[str]
    size: int
    sha256: str
    mtime_ns: int


@dataclass
class CodeSymbol:
    name: str
    kind: str  # class|function|method|interface|type|constant|variable|module
    file: str
    line_start: int
    line_end: int
    signature: str = ""
    parent: str = ""


@dataclass
class CodeReference:
    from_file: str
    from_symbol: str
    to_name: str
    kind: str  # import|call|usage
    line: int


@dataclass
class CodeChunk:
    file: str
    symbol: str
    content: str
    line_start: int
    line_end: int


# --------------------------------------------------------------------------
# Discovery + fingerprinting
# --------------------------------------------------------------------------

MAX_FILE_BYTES = 1_000_000
MAX_INDEXED_FILES = 50_000


def discover_files(root: Path, extra_patterns: Optional[list[str]] = None,
                   max_files: int = MAX_INDEXED_FILES) -> list[str]:
    """List indexable repo-relative paths, honoring ignore rules."""
    extra = list(extra_patterns or [])
    try:
        extra.extend(load_gitignore(root))
    except OSError:
        pass
    out: list[str] = []
    for p in sorted(root.rglob("*")):
        if len(out) >= max_files:
            break
        if not p.is_file() or p.is_symlink():
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if is_excluded(rel, extra):
            continue
        if is_binary_path(rel):
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        out.append(rel)
    return out


def fingerprint_file(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_size, st.st_mtime_ns


def sha256_file(path: Path, limit_bytes: int = 5_000_000) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        remaining = limit_bytes
        while remaining > 0:
            chunk = f.read(min(65536, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Symbol extraction (AST for Python, grammar-light regex elsewhere)
# --------------------------------------------------------------------------

def extract_python_symbols(source: str, filename: str) -> tuple[list[CodeSymbol], list[CodeReference]]:
    symbols: list[CodeSymbol] = []
    refs: list[CodeReference] = []
    try:
        tree = ast.parse(source, filename=filename)
    except (SyntaxError, ValueError):
        return symbols, refs

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            symbols.append(CodeSymbol(
                name=node.name, kind="class", file=filename,
                line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
                signature=f"class {node.name}",
                parent=".".join(self.stack)))
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._func(node, "method" if self.stack else "function")

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._func(node, "method" if self.stack else "function")

        def _func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str) -> None:
            args = [a.arg for a in node.args.args]
            symbols.append(CodeSymbol(
                name=node.name, kind=kind, file=filename,
                line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
                signature=f"def {node.name}({', '.join(args)})",
                parent=".".join(self.stack)))
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Import(self, node: ast.Import) -> None:
            for a in node.names:
                refs.append(CodeReference(
                    from_file=filename, from_symbol=".".join(self.stack),
                    to_name=a.asname or a.name.split(".")[0], kind="import",
                    line=node.lineno))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            mod = ("." * (node.level or 0)) + (node.module or "")
            for a in node.names:
                refs.append(CodeReference(
                    from_file=filename, from_symbol=".".join(self.stack),
                    to_name=f"{mod}.{a.name}" if mod else a.name, kind="import",
                    line=node.lineno))

    Visitor().visit(tree)
    # Module-level constants / variables.
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    symbols.append(CodeSymbol(
                        name=t.id, kind="constant", file=filename,
                        line_start=node.lineno,
                        line_end=getattr(node, "end_lineno", node.lineno) or node.lineno))
    return symbols, refs


_TS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("class", re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", re.M)),
    ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)", re.M)),
    ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)", re.M)),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M)),
    ("function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", re.M)),
    ("method", re.compile(r"^\s*(?:public|private|protected|static|async|\s)*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[^{]+)?\{", re.M)),
    ("constant", re.compile(r"^\s*(?:export\s+)?const\s+([A-Z][A-Z0-9_]*)\s*=", re.M)),
]

_IMPORT_RE = re.compile(r"^\s*import\s+(?:[^'\"]*from\s+)?['\"]([^'\"]+)['\"]", re.M)
_REQUIRE_RE = re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)", re.M)


def extract_regex_symbols(source: str, filename: str, language: str) -> tuple[list[CodeSymbol], list[CodeReference]]:
    symbols: list[CodeSymbol] = []
    refs: list[CodeReference] = []
    lines = source.splitlines()
    seen: set[tuple[str, str, int]] = set()

    generic = [
        ("class", re.compile(r"^\s*(?:export\s+|public\s+|abstract\s+)*(?:class|struct|interface|trait)\s+([A-Za-z_][\w]*)")),
        ("function", re.compile(r"^\s*(?:export\s+|public\s+|private\s+|protected\s+|static\s+|async\s+|func\s+|fn\s+|def\s+)(?:[\w<>\[\],\s\*&]+\s+)?([A-Za-z_][\w]*)\s*\(")),
        ("constant", re.compile(r"^\s*(?:export\s+|public\s+)?const\s+([A-Z][A-Z0-9_]*)\s*=")),
    ]
    patterns = _TS_PATTERNS if language in ("typescript", "javascript") else generic
    for kind, rx in patterns:
        for m in rx.finditer(source):
            lineno = source.count("\n", 0, m.start()) + 1
            key = (kind, m.group(1), lineno)
            if key in seen:
                continue
            seen.add(key)
            end = min(len(lines), lineno + 40)
            symbols.append(CodeSymbol(name=m.group(1), kind=kind, file=filename,
                                      line_start=lineno, line_end=end,
                                      signature=lines[lineno - 1].strip()[:200]))
    for m in _IMPORT_RE.finditer(source):
        refs.append(CodeReference(from_file=filename, from_symbol="",
                                  to_name=m.group(1), kind="import",
                                  line=source.count("\n", 0, m.start()) + 1))
    for m in _REQUIRE_RE.finditer(source):
        refs.append(CodeReference(from_file=filename, from_symbol="",
                                  to_name=m.group(1), kind="import",
                                  line=source.count("\n", 0, m.start()) + 1))
    return symbols, refs


def extract_symbols(source: str, filename: str, language: Optional[str]) -> tuple[list[CodeSymbol], list[CodeReference]]:
    if language == "python":
        return extract_python_symbols(source, filename)
    if language in ("typescript", "javascript", "java", "go", "rust",
                    "csharp", "c", "cpp", "ruby", "php", "swift", "kotlin"):
        return extract_regex_symbols(source, filename, language)
    return [], []


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------

MAX_CHUNK_CHARS = 4000
CHUNK_OVERLAP_LINES = 20


def chunk_file(source: str, filename: str, symbols: list[CodeSymbol]) -> list[CodeChunk]:
    lines = source.splitlines()
    chunks: list[CodeChunk] = []
    if symbols:
        for sym in sorted(symbols, key=lambda s: s.line_start):
            start = max(1, sym.line_start)
            end = min(len(lines), max(sym.line_end, start))
            content = "\n".join(lines[start - 1:end])
            if len(content) > MAX_CHUNK_CHARS:
                content = content[:MAX_CHUNK_CHARS] + "\n... [truncated]"
            chunks.append(CodeChunk(file=filename, symbol=sym.name,
                                    content=content, line_start=start, line_end=end))
        return chunks
    # Sliding window fallback for symbol-less files (docs, config).
    window = 120
    i = 0
    while i < len(lines):
        end = min(len(lines), i + window)
        chunks.append(CodeChunk(file=filename, symbol="", content="\n".join(lines[i:end]),
                                line_start=i + 1, line_end=end))
        if end >= len(lines):
            break
        i = end - CHUNK_OVERLAP_LINES
    return chunks


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

@dataclass
class SearchHit:
    file: str
    line: int
    excerpt: str
    kind: str = "text"  # text|regex|symbol|reference|semantic


def search_text(root: Path, query: str, files: Optional[list[str]] = None,
                max_hits: int = 100, context_lines: int = 2) -> list[SearchHit]:
    hits: list[SearchHit] = []
    q = query.lower()
    targets = files or discover_files(root)
    for rel in targets:
        if len(hits) >= max_hits:
            break
        p = root / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if q in line.lower():
                hits.append(SearchHit(file=rel, line=i,
                                      excerpt=line.strip()[:300], kind="text"))
                if len(hits) >= max_hits:
                    break
    return hits


def search_regex(root: Path, pattern: str, files: Optional[list[str]] = None,
                 max_hits: int = 100) -> list[SearchHit]:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}")
    hits: list[SearchHit] = []
    targets = files or discover_files(root)
    for rel in targets:
        if len(hits) >= max_hits:
            break
        p = root / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > 2_000_000:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                hits.append(SearchHit(file=rel, line=i,
                                      excerpt=line.strip()[:300], kind="regex"))
                if len(hits) >= max_hits:
                    break
    return hits


def find_usages(root: Path, symbol: str, files: Optional[list[str]] = None,
                max_hits: int = 100) -> list[SearchHit]:
    """Word-boundary usage search (lightweight reference finding)."""
    rx = re.compile(r"\b" + re.escape(symbol) + r"\b")
    hits: list[SearchHit] = []
    targets = files or discover_files(root)
    for rel in targets:
        if len(hits) >= max_hits:
            break
        p = root / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                hits.append(SearchHit(file=rel, line=i,
                                      excerpt=line.strip()[:300], kind="reference"))
                if len(hits) >= max_hits:
                    break
    return hits


class SemanticSearchProvider(Protocol):
    async def search(self, query: str, top_k: int = 20) -> list[dict[str, Any]]:
        """Return [{file, symbol, score, excerpt}]. ..."""


class NoopSemanticProvider:
    async def search(self, query: str, top_k: int = 20) -> list[dict[str, Any]]:
        return []


# --------------------------------------------------------------------------
# Context builder
# --------------------------------------------------------------------------

TEST_FILE_RES = [
    re.compile(r"(?:^|/)(?:test_|_test|tests?/)", re.IGNORECASE),
    re.compile(r"\.(?:test|spec)\.[a-z]+$", re.IGNORECASE),
]

MAX_CONTEXT_FILES = 25
MAX_FILE_CHARS = 12_000
MAX_TOTAL_CHARS = 60_000


def is_test_file(path: str) -> bool:
    return any(rx.search(path) for rx in TEST_FILE_RES)


def build_context_package(objective: str, candidate_files: list[str],
                           read_file: Any, symbols: Optional[list[CodeSymbol]] = None,
                           max_files: int = MAX_CONTEXT_FILES,
                           max_total_chars: int = MAX_TOTAL_CHARS) -> dict[str, Any]:
    """Assemble a bounded context package: rank test-adjacent + symbol-rich files.

    ``read_file(path) -> str`` injects file access (workspace-jailed by caller).
    """
    ranked = sorted(candidate_files,
                    key=lambda f: (not is_test_file(f),
                                   -(sum(1 for s in (symbols or []) if s.file == f))))
    package_files: list[dict[str, Any]] = []
    total = 0
    for rel in ranked[:max_files]:
        try:
            content = read_file(rel)
        except (OSError, ValueError):
            continue
        if len(content) > MAX_FILE_CHARS:
            content = content[:MAX_FILE_CHARS] + "\n... [truncated]"
        if total + len(content) > max_total_chars:
            break
        total += len(content)
        package_files.append({"path": rel, "chars": len(content), "content": content})
    return {"objective": objective[:500], "files": package_files,
            "total_chars": total, "truncated": len(ranked) > len(package_files)}


def load_repo_instructions(root: Path) -> dict[str, Any]:
    """Read advisory instruction files (AGENTS.md etc.) as UNTRUSTED data."""
    directives: dict[str, Any] = {}
    for name in ("AGENTS.md", "CONTRIBUTING.md", "DEVELOPMENT.md"):
        p = root / name
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            directives[name] = text[:4000]
            for line in text.splitlines()[:50]:
                m = re.match(r"^\s*(?:test|build|lint|typecheck)[_-]?command\s*:\s*(.+)$",
                             line, re.IGNORECASE)
                if m:
                    directives[line.split(":")[0].strip().lower()] = m.group(1).strip()[:300]
    return directives
