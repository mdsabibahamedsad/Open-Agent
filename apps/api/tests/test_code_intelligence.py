"""Code intelligence unit tests: discovery, symbols, chunking, search, context.

Pure unit tests — no database required.
"""

from pathlib import Path

from openagent.code import intelligence as intel


def _tree(root: Path):
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text(
        '"""Auth module."""\nimport os\n\nCONSTANT_X = 1\n\n'
        'class Authenticator:\n    def login(self, user):\n        return True\n\n'
        'async def make_token(user):\n    return "tok"\n',
        encoding="utf-8")
    (root / "src" / "app.ts").write_text(
        'import { x } from "./lib";\n\nexport class App {\n  start(): void {}\n}\n'
        'export function boot(): void {}\n',
        encoding="utf-8")
    (root / "tests" / "test_auth.py").write_text(
        "def test_login():\n    assert True\n", encoding="utf-8")
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / "node_modules" / "dep" / "index.js").write_text("junk", encoding="utf-8")
    (root / "README.md").write_text("# Demo\nRun pytest -q.\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (root / "ignored" / "x.py").mkdir(parents=True)
    (root / "ignored" / "x.py" / "keep.py").write_text("y = 1\n")
    (root / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    return root


class TestDiscovery:
    def test_respects_ignores_and_binaries(self, tmp_path):
        files = intel.discover_files(_tree(tmp_path))
        assert "src/auth.py" in files
        assert "src/app.ts" in files
        assert "tests/test_auth.py" in files
        assert not any(f.startswith("node_modules") for f in files)
        assert not any(f.startswith("ignored/") for f in files)
        assert "pic.png" not in files

    def test_languages(self):
        assert intel.detect_language("a.py") == "python"
        assert intel.detect_language("b.tsx") == "typescript"
        assert intel.detect_language("c.go") == "go"
        assert intel.detect_language("README") is None


class TestSymbols:
    def test_python_ast(self):
        src = ("import os\nCONSTANT_X = 1\nclass A:\n    def m(self):\n        pass\n"
               "def f():\n    pass\n")
        syms, refs = intel.extract_symbols(src, "m.py", "python")
        by_name = {s.name: s.kind for s in syms}
        assert by_name["A"] == "class"
        assert by_name["m"] == "method"
        assert by_name["f"] == "function"
        assert by_name["CONSTANT_X"] == "constant"
        assert any(r.kind == "import" for r in refs)

    def test_python_broken_syntax_degrades(self):
        syms, refs = intel.extract_symbols("def broken(:\n", "m.py", "python")
        assert syms == [] and refs == []

    def test_typescript_regex(self):
        src = ('import { x } from "./lib";\nexport class App {\n  start(): void {}\n}\n'
               "export function boot(): void {}\n")
        syms, refs = intel.extract_symbols(src, "a.ts", "typescript")
        kinds = {(s.name, s.kind) for s in syms}
        assert ("App", "class") in kinds
        assert ("boot", "function") in kinds
        assert any(r.to_name == "./lib" for r in refs)

    def test_unknown_language_empty(self):
        assert intel.extract_symbols("hello", "f.xyz", None) == ([], [])


class TestChunks:
    def test_symbol_chunks(self):
        syms, _ = intel.extract_symbols("def a():\n    pass\ndef b():\n    pass\n",
                                        "m.py", "python")
        chunks = intel.chunk_file("def a():\n    pass\ndef b():\n    pass\n",
                                  "m.py", syms)
        assert {c.symbol for c in chunks} == {"a", "b"}

    def test_fallback_window(self):
        chunks = intel.chunk_file("line\n" * 300, "notes.md", [])
        assert len(chunks) > 1
        assert chunks[0].line_start == 1


class TestSearch:
    def test_text_search(self, tmp_path):
        hits = intel.search_text(_tree(tmp_path), "Authenticator")
        assert any(h.file == "src/auth.py" for h in hits)

    def test_regex_search(self, tmp_path):
        hits = intel.search_regex(_tree(tmp_path), r"def test_\w+")
        assert any(h.file == "tests/test_auth.py" for h in hits)

    def test_bad_regex(self, tmp_path):
        import pytest
        with pytest.raises(ValueError):
            intel.search_regex(_tree(tmp_path), r"(unclosed")

    def test_usages(self, tmp_path):
        hits = intel.find_usages(_tree(tmp_path), "make_token")
        assert any(h.file == "src/auth.py" for h in hits)

    def test_is_test_file(self):
        assert intel.is_test_file("tests/test_auth.py")
        assert intel.is_test_file("src/app.test.ts")
        assert not intel.is_test_file("src/app.ts")


class TestContext:
    def test_bounded_package(self, tmp_path):
        root = _tree(tmp_path)
        pkg = intel.build_context_package(
            "fix login", ["src/auth.py", "tests/test_auth.py", "README.md"],
            lambda rel: (root / rel).read_text(encoding="utf-8"))
        assert pkg["files"]
        assert pkg["total_chars"] <= 60_000

    def test_instructions_loading(self, tmp_path):
        root = _tree(tmp_path)
        (root / "AGENTS.md").write_text("test_command: pytest -q\n", encoding="utf-8")
        dirs = intel.load_repo_instructions(root)
        assert dirs.get("test_command") == "pytest -q"


class TestDependencies:
    def test_npm(self, tmp_path):
        from openagent.code.service import parse_dependencies
        deps = parse_dependencies(
            tmp_path, "package.json",
            '{"dependencies": {"react": "^18.0.0"}, "devDependencies": {"vitest": "^1.0.0"}}')
        assert {(d["name"], d["scope"]) for d in deps} == {
            ("react", "runtime"), ("vitest", "dev")}

    def test_requirements(self, tmp_path):
        from openagent.code.service import parse_dependencies
        deps = parse_dependencies(tmp_path, "requirements.txt", "fastapi==0.104\n# c\n")
        assert deps[0]["manager"] == "pip" and deps[0]["name"] == "fastapi"

    def test_go_mod(self, tmp_path):
        from openagent.code.service import parse_dependencies
        deps = parse_dependencies(tmp_path, "go.mod",
                                  "module x\nrequire (\n\tgithub.com/a/b v1.2.3\n)\n")
        assert deps and deps[0]["manager"] == "go"

    def test_discovery(self, tmp_path):
        from openagent.code.service import discover_test_commands
        root = _tree(tmp_path)
        (root / "pyproject.toml").write_text("[tool.pytest]\n", encoding="utf-8")
        cmds = discover_test_commands(root)
        assert any(c["command"] == "pytest -q" for c in cmds)
