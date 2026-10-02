"""Code tool catalogue tests (no database required)."""

from openagent.code.tools import CODE_TOOLS, CodeToolExecutor, ensure_code_tools_registered


EXPECTED = {
    "code.repository.list", "code.repository.status", "code.file.list",
    "code.file.read", "code.search", "code.symbol.find", "code.reference.find",
    "code.diff", "code.patch.apply", "code.branch.create", "code.git.fetch",
    "code.git.commit", "code.git.push", "code.test.run", "code.lint.run",
    "code.typecheck.run", "code.build.run", "code.review", "code.pr.prepare",
}


class TestCodeToolCatalog:
    def test_all_spec_tools_present(self):
        assert {t["name"] for t in CODE_TOOLS} == EXPECTED

    def test_risk_levels(self):
        by_name = {t["name"]: t for t in CODE_TOOLS}
        assert by_name["code.file.read"]["risk_level"] == "LOW"
        assert by_name["code.patch.apply"]["risk_level"] == "MEDIUM"
        assert by_name["code.git.push"]["risk_level"] == "HIGH"

    def test_executor_validates(self):
        ex = CodeToolExecutor(service_factory=lambda db: None)
        assert set(ex.supported_tools) == EXPECTED
        assert ex.get_tool_schema("code.search") is not None
        assert ex.get_tool_schema("code.nope") is None

    def test_registration_idempotent(self):
        ensure_code_tools_registered()
        ensure_code_tools_registered()
        from openagent.runtime.tools import tool_executor_registry, tool_registry
        assert tool_executor_registry.get_executor("code") is not None
        for name in EXPECTED:
            assert tool_registry.get_latest(name) is not None

    def test_workflow_executors_registered(self):
        from openagent.runtime.executors import executor_registry
        for node in ("code_agent", "code_search", "code_read", "code_patch",
                     "code_test", "code_lint", "code_review", "git_commit",
                     "create_pr"):
            assert executor_registry.get(node) is not None, node
