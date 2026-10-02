"""Browser observation + tool-catalog unit tests (no database required)."""

from openagent.browser.observations import compress_observation
from openagent.browser.tools import BROWSER_TOOLS, BrowserToolExecutor, ensure_browser_tools_registered


def _elements(n=5):
    return [
        {"role": "button", "name": f"Action {i}", "selector": f"#b{i}", "visible": True}
        for i in range(n)
    ]


class TestCompressObservation:
    def test_standard_includes_elements_and_text(self):
        out = compress_observation("https://example.com", "Example", _elements(),
                                   "Hello world pricing page", "standard")
        assert "Current URL: https://example.com" in out
        assert "Page title: Example" in out
        assert "Action 0" in out
        assert "Hello world" in out

    def test_minimal_omits_text(self):
        out = compress_observation("https://example.com", "Example", _elements(),
                                   "Hello world", "minimal")
        assert "Hello world" not in out

    def test_budget_enforced(self):
        out = compress_observation("https://example.com", "T", _elements(200),
                                   "x" * 50000, "standard", max_chars=1000)
        assert len(out) <= 1100

    def test_hidden_elements_skipped(self):
        els = [{"role": "button", "name": "ghost", "visible": False}]
        out = compress_observation("https://example.com", "T", els, "", "standard")
        assert "ghost" not in out


class TestBrowserToolCatalog:
    EXPECTED = {"browser.open", "browser.navigate", "browser.click", "browser.type",
                "browser.select", "browser.scroll", "browser.press", "browser.wait",
                "browser.screenshot", "browser.extract", "browser.upload",
                "browser.download", "browser.tabs", "browser.back",
                "browser.forward", "browser.reload", "browser.close"}

    def test_all_spec_tools_present(self):
        names = {t["name"] for t in BROWSER_TOOLS}
        assert self.EXPECTED == names

    def test_schemas_require_session(self):
        for t in BROWSER_TOOLS:
            assert "sessionId" in t["input_schema"]["properties"], t["name"]

    def test_risk_levels_assigned(self):
        by_name = {t["name"]: t for t in BROWSER_TOOLS}
        assert by_name["browser.upload"]["risk_level"] == "HIGH"
        assert by_name["browser.screenshot"]["risk_level"] == "LOW"
        assert by_name["browser.click"]["risk_level"] == "MEDIUM"

    def test_executor_lists_all_tools(self):
        ex = BrowserToolExecutor(service_factory=lambda db: None)
        assert set(ex.supported_tools) == self.EXPECTED
        assert ex.get_tool_schema("browser.click") is not None
        assert ex.get_tool_schema("browser.nope") is None

    def test_registration_idempotent(self):
        ensure_browser_tools_registered()
        ensure_browser_tools_registered()
        from openagent.runtime.tools import tool_executor_registry, tool_registry
        assert tool_executor_registry.get_executor("browser") is not None
        for name in self.EXPECTED:
            assert tool_registry.get_latest(name) is not None
