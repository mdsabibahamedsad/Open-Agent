"""Tests for the Tool System."""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

from openagent.runtime.tools import (
    ToolRegistry,
    ToolDefinition,
    ToolExecutor,
    ToolExecutorRegistry,
    ToolExecutionManager,
    ToolExecutionError,
    tool_registry,
    tool_executor_registry,
)


class MockToolExecutor(ToolExecutor):
    """Mock tool executor for testing."""
    
    def __init__(self, executor_id: str, supported_tools: list):
        self._executor_id = executor_id
        self._supported_tools = supported_tools
        self._schemas = {}
        self._execute_results = {}
        self._validate_results = {}
    
    @property
    def executor_id(self) -> str:
        return self._executor_id
    
    @property
    def supported_tools(self) -> list:
        return self._supported_tools
    
    def register_tool_schema(self, tool_name: str, schema: dict):
        self._schemas[tool_name] = schema
    
    def get_tool_schema(self, tool_name: str):
        return self._schemas.get(tool_name)
    
    def list_tools(self) -> list:
        return [{"name": name, "schema": self._schemas.get(name, {})} for name in self._supported_tools]
    
    async def validate_arguments(self, tool_name: str, arguments: dict) -> bool:
        if tool_name in self._validate_results:
            return self._validate_results[tool_name]
        return True
    
    async def execute(self, tool_name: str, arguments: dict, context: dict = None) -> dict:
        if tool_name in self._execute_results:
            return self._execute_results[tool_name]
        return {"result": "success"}


class TestToolRegistry:
    """Tests for ToolRegistry."""
    
    def setup_method(self):
        self.registry = ToolRegistry()
    
    def test_register_tool(self):
        tool = ToolDefinition(
            id="test-tool-1",
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            capabilities=["read"],
            risk_level="low",
            executor_id="test",
            version="1.0",
        )
        self.registry.register(tool)
        
        retrieved = self.registry.get("test_tool", "1.0")
        assert retrieved is not None
        assert retrieved.name == "test_tool"
        assert retrieved.id == "test-tool-1"
    
    def test_get_latest_version(self):
        tool_v1 = ToolDefinition(
            id="test-tool-1",
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object"},
            capabilities=["read"],
            risk_level="low",
            executor_id="test",
            version="1.0",
        )
        tool_v2 = ToolDefinition(
            id="test-tool-2",
            name="test_tool",
            description="A test tool v2",
            input_schema={"type": "object"},
            capabilities=["read", "write"],
            risk_level="medium",
            executor_id="test",
            version="2.0",
        )
        self.registry.register(tool_v1)
        self.registry.register(tool_v2)
        
        latest = self.registry.get_latest("test_tool")
        assert latest is not None
        assert latest.version == "2.0"
    
    def test_list_tools(self):
        tool1 = ToolDefinition(
            id="test-tool-1",
            name="tool1",
            description="Tool 1",
            input_schema={"type": "object"},
            capabilities=["read"],
            risk_level="low",
            executor_id="test",
            version="1.0",
        )
        tool2 = ToolDefinition(
            id="test-tool-2",
            name="tool2",
            description="Tool 2",
            input_schema={"type": "object"},
            capabilities=["write"],
            risk_level="high",
            executor_id="test",
            version="1.0",
        )
        self.registry.register(tool1)
        self.registry.register(tool2)
        
        tools = self.registry.list_tools()
        assert len(tools) == 2
    
    def test_search_tools(self):
        tool = ToolDefinition(
            id="test-tool-1",
            name="web_search",
            description="Search the web for information",
            input_schema={"type": "object"},
            capabilities=["network", "read"],
            risk_level="low",
            executor_id="test",
            version="1.0",
        )
        self.registry.register(tool)
        
        results = self.registry.search("web")
        assert len(results) == 1
        assert results[0].name == "web_search"
        
        results = self.registry.search("search")
        assert len(results) == 1
        
        results = self.registry.search("nonexistent")
        assert len(results) == 0


class TestToolExecutorRegistry:
    """Tests for ToolExecutorRegistry."""
    
    def setup_method(self):
        self.registry = ToolExecutorRegistry()
        self.executor = MockToolExecutor("test-executor", ["tool1", "tool2"])
        self.executor.register_tool_schema("tool1", {"type": "object", "properties": {"input": {"type": "string"}}})
    
    def test_register_executor(self):
        self.registry.register(self.executor)
        
        retrieved = self.registry.get_executor("test-executor")
        assert retrieved is self.executor
        
        # Check tool to executor mapping
        exec_for_tool1 = self.registry.get_executor_for_tool("tool1")
        assert exec_for_tool1 is self.executor
    
    def test_list_all_tools(self):
        self.registry.register(self.executor)
        
        tools = self.registry.list_all_tools()
        assert len(tools) == 2
        assert any(t["name"] == "tool1" for t in tools)


class TestToolExecutionManager:
    """Tests for ToolExecutionManager."""
    
    def setup_method(self):
        self.executor_registry = ToolExecutorRegistry()
        self.tool_registry = ToolRegistry()
        self.manager = ToolExecutionManager(
            executor_registry=self.executor_registry,
            tool_registry=self.tool_registry,
            default_timeout=5,
            max_retries=1,
        )
        
        self.executor = MockToolExecutor("test", ["test_tool"])
        self.executor.register_tool_schema("test_tool", {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        })
        self.executor._execute_results["test_tool"] = {"data": "test result"}
        self.executor_registry.register(self.executor)
        
        self.tool = ToolDefinition(
            id="tool-1",
            name="test_tool",
            description="Test tool",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            capabilities=["read"],
            risk_level="low",
            executor_id="test",
            version="1.0",
        )
        self.tool_registry.register(self.tool)
    
    @pytest.mark.asyncio
    async def test_execute_tool_success(self):
        result = await self.manager.execute_tool(
            tool_name="test_tool",
            arguments={"query": "test"},
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "success"
        assert result.output == {"data": "test result"}
        assert result.duration_ms > 0
    
    @pytest.mark.asyncio
    async def test_execute_tool_invalid_args(self):
        result = await self.manager.execute_tool(
            tool_name="test_tool",
            arguments={},  # Missing required 'query'
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "error"
        assert result.error_code == "INVALID_ARGUMENTS"
    
    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self):
        result = await self.manager.execute_tool(
            tool_name="nonexistent_tool",
            arguments={},
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "error"
        assert result.error_code == "NO_EXECUTOR"
    
    @pytest.mark.asyncio
    async def test_execute_tool_with_retry(self):
        # First call fails, second succeeds
        call_count = 0
        
        async def failing_execute(tool_name, arguments, context=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temporary failure")
            return {"data": "success after retry"}
        
        self.executor.execute = failing_execute
        
        result = await self.manager.execute_tool(
            tool_name="test_tool",
            arguments={"query": "test"},
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "success"
        assert result.metadata.get("attempt") == 2
    
    @pytest.mark.asyncio
    async def test_execute_tool_timeout(self):
        async def slow_execute(tool_name, arguments, context=None):
            await asyncio.sleep(10)
            return {"data": "done"}
        
        self.executor.execute = slow_execute
        
        # Use short timeout
        manager = ToolExecutionManager(
            executor_registry=self.executor_registry,
            tool_registry=self.tool_registry,
            default_timeout=1,  # 1 second timeout
            max_retries=0,
        )
        
        result = await manager.execute_tool(
            tool_name="test_tool",
            arguments={"query": "test"},
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "error"
        assert result.error_code in ("MAX_RETRIES_EXCEEDED", "TOOL_TIMEOUT")


class TestToolExecutionError:
    """Tests for ToolExecutionError."""
    
    def test_error_creation(self):
        error = ToolExecutionError("TEST_ERROR", "Test message", "test_tool")
        
        assert error.code == "TEST_ERROR"
        assert str(error) == "Test message"
        assert error.tool_name == "test_tool"


class TestGlobalRegistries:
    """Tests for global registries."""
    
    def test_global_registries_exist(self):
        assert tool_registry is not None
        assert tool_executor_registry is not None
        assert isinstance(tool_registry, ToolRegistry)
        assert isinstance(tool_executor_registry, ToolExecutorRegistry)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])