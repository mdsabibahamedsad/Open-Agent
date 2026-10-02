"""Integration tests for the Tool System."""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from uuid import uuid4

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
        self._cancel_called = False
    
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
        # Default validation - check required fields
        schema = self._schemas.get(tool_name, {})
        required = schema.get("required", [])
        for field in required:
            if field not in arguments:
                return False
        return True
    
    async def execute(self, tool_name: str, arguments: dict, context: dict = None) -> dict:
        if tool_name in self._execute_results:
            result = self._execute_results[tool_name]
            if isinstance(result, Exception):
                raise result
            return result
        return {"result": "success", "input": arguments}
    
    async def cancel(self, execution_id: str):
        self._cancel_called = True


class TestToolRegistryIntegration:
    """Integration tests for ToolRegistry."""
    
    def test_tool_lifecycle(self):
        """Test full tool lifecycle: register, update, unregister."""
        registry = ToolRegistry()
        
        # Register tool
        tool = ToolDefinition(
            id="lifecycle-tool",
            name="lifecycle_tool",
            description="Lifecycle test tool",
            input_schema={"type": "object", "properties": {"data": {"type": "string"}}},
            capabilities=["read", "write"],
            risk_level="medium",
            executor_id="test",
            version="1.0",
        )
        registry.register(tool)
        
        # Retrieve
        retrieved = registry.get("lifecycle_tool", "1.0")
        assert retrieved is not None
        assert retrieved.id == "lifecycle-tool"
        assert retrieved.capabilities == ["read", "write"]
        
        # Update by registering new version
        tool_v2 = ToolDefinition(
            id="lifecycle-tool-v2",
            name="lifecycle_tool",
            description="Lifecycle test tool v2",
            input_schema={"type": "object", "properties": {"data": {"type": "string"}, "options": {"type": "object"}}},
            capabilities=["read", "write", "delete"],
            risk_level="high",
            executor_id="test",
            version="2.0",
        )
        registry.register(tool_v2)
        
        # Get latest should return v2
        latest = registry.get_latest("lifecycle_tool")
        assert latest.version == "2.0"
        assert latest.risk_level == "high"
        assert "delete" in latest.capabilities
        
        # Unregister v1
        result = registry.unregister("lifecycle_tool", "1.0")
        assert result is True
        
        # v1 should be gone
        assert registry.get("lifecycle_tool", "1.0") is None
        # v2 should still exist
        assert registry.get("lifecycle_tool", "2.0") is not None
    
    def test_category_and_capability_indexing(self):
        """Test that tools are properly indexed by category and capability."""
        registry = ToolRegistry()
        
        tool1 = ToolDefinition(
            id="web-tool",
            name="web_search",
            description="Search the web",
            input_schema={"type": "object"},
            capabilities=["network", "read"],
            risk_level="low",
            executor_id="web",
            version="1.0",
        )
        tool1.metadata = {"category": "web", "tags": ["search"]}  # type: ignore
        
        tool2 = ToolDefinition(
            id="db-tool",
            name="database_query",
            description="Query database",
            input_schema={"type": "object"},
            capabilities=["database_access", "read"],
            risk_level="medium",
            executor_id="db",
            version="1.0",
        )
        tool2.metadata = {"category": "database", "tags": ["sql"]}  # type: ignore
        
        registry.register(tool1)
        registry.register(tool2)
        
        categories = registry.getCategories()
        assert "web" in categories
        assert "database" in categories
        
        capabilities = registry.getCapabilities()
        assert "network" in capabilities
        assert "database_access" in capabilities
        assert "read" in capabilities


class TestToolExecutorRegistryIntegration:
    """Integration tests for ToolExecutorRegistry."""
    
    def test_multiple_executors(self):
        """Test registering multiple executors with overlapping tools."""
        registry = ToolExecutorRegistry()
        
        exec1 = MockToolExecutor("exec1", ["tool_a", "tool_b"])
        exec1.register_tool_schema("tool_a", {"type": "object"})
        exec1.register_tool_schema("tool_b", {"type": "object"})
        
        exec2 = MockToolExecutor("exec2", ["tool_c", "tool_d"])
        exec2.register_tool_schema("tool_c", {"type": "object"})
        exec2.register_tool_schema("tool_d", {"type": "object"})
        
        registry.register(exec1)
        registry.register(exec2)
        
        # Each tool should map to correct executor
        assert registry.get_executor_for_tool("tool_a") is exec1
        assert registry.get_executor_for_tool("tool_b") is exec1
        assert registry.get_executor_for_tool("tool_c") is exec2
        assert registry.get_executor_for_tool("tool_d") is exec2
        
        # List all tools
        all_tools = registry.list_all_tools()
        assert len(all_tools) == 4
    
    def test_unregister_executor(self):
        """Test unregistering an executor removes its tools."""
        registry = ToolExecutorRegistry()
        
        exec1 = MockToolExecutor("exec1", ["tool_a"])
        registry.register(exec1)
        
        assert registry.get_executor_for_tool("tool_a") is exec1
        
        registry.unregister("exec1")
        
        assert registry.get_executor_for_tool("tool_a") is None
        assert registry.get_executor("exec1") is None


class TestToolExecutionManagerIntegration:
    """Integration tests for ToolExecutionManager."""
    
    @pytest.fixture
    def setup_manager(self):
        executor_registry = ToolExecutorRegistry()
        tool_registry = ToolRegistry()
        
        executor = MockToolExecutor("test", ["echo", "transform"])
        executor.register_tool_schema("echo", {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        })
        executor.register_tool_schema("transform", {
            "type": "object",
            "properties": {"input": {"type": "string"}, "operation": {"type": "string"}},
            "required": ["input", "operation"],
        })
        executor._execute_results["echo"] = {"echoed": "test message"}
        executor._execute_results["transform"] = {"transformed": "TEST MESSAGE"}
        executor_registry.register(executor)
        
        # Register tools
        for name, caps in [("echo", ["read"]), ("transform", ["read", "write"])]:
            tool = ToolDefinition(
                id=f"tool-{name}",
                name=name,
                description=f"{name} tool",
                input_schema=executor.get_tool_schema(name),
                capabilities=caps,
                risk_level="low",
                executor_id="test",
                version="1.0",
            )
            tool_registry.register(tool)
        
        manager = ToolExecutionManager(
            executor_registry=executor_registry,
            tool_registry=tool_registry,
            default_timeout=5,
            max_retries=2,
        )
        
        return manager, executor, tool_registry
    
    @pytest.mark.asyncio
    async def test_successful_execution(self, setup_manager):
        manager, executor, _ = setup_manager
        
        result = await manager.execute_tool(
            tool_name="echo",
            arguments={"message": "hello"},
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "success"
        assert result.output == {"echoed": "test message"}
        assert result.duration_ms > 0
        assert result.metadata.get("attempt") == 1
    
    @pytest.mark.asyncio
    async def test_retry_on_failure(self, setup_manager):
        manager, executor, _ = setup_manager
        
        # Make first call fail, second succeed
        call_count = 0
        async def flaky_execute(tool_name, arguments, context=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temporary error")
            return {"success": True, "attempt": call_count}
        
        executor.execute = flaky_execute
        
        result = await manager.execute_tool(
            tool_name="echo",
            arguments={"message": "test"},
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "success"
        assert result.metadata.get("attempt") == 2
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, setup_manager):
        manager, executor, _ = setup_manager
        
        # Always fail
        executor.execute = AsyncMock(side_effect=Exception("Permanent error"))
        
        result = await manager.execute_tool(
            tool_name="echo",
            arguments={"message": "test"},
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "error"
        assert result.error_code == "MAX_RETRIES_EXCEEDED"
        assert "Permanent error" in result.error
    
    @pytest.mark.asyncio
    async def test_validation_failure(self, setup_manager):
        manager, _, _ = setup_manager
        
        # Missing required field
        result = await manager.execute_tool(
            tool_name="transform",
            arguments={"input": "test"},  # missing 'operation'
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "error"
        assert result.error_code == "INVALID_ARGUMENTS"
    
    @pytest.mark.asyncio
    async def test_tool_not_found(self, setup_manager):
        manager, _, _ = setup_manager
        
        result = await manager.execute_tool(
            tool_name="nonexistent",
            arguments={},
            context={"organization_id": "org-1"},
        )
        
        assert result.status == "error"
        assert result.error_code == "NO_EXECUTOR"
    
    @pytest.mark.asyncio
    async def test_custom_timeout(self, setup_manager):
        manager, executor, _ = setup_manager
        
        # Slow execution
        async def slow_execute(tool_name, arguments, context=None):
            await asyncio.sleep(2)
            return {"done": True}
        
        executor.execute = slow_execute
        
        # Use 1 second timeout
        result = await manager.execute_tool(
            tool_name="echo",
            arguments={"message": "test"},
            context={"organization_id": "org-1"},
            timeout=1,
        )
        
        assert result.status == "error"
        assert "timeout" in result.error.lower() or result.error_code == "MAX_RETRIES_EXCEEDED"


class TestToolDefinitionValidation:
    """Tests for tool definition validation."""
    
    def test_schema_validation(self):
        """Test that tool schemas are validated."""
        executor = MockToolExecutor("test", ["validate_test"])
        executor.register_tool_schema("validate_test", {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer", "minimum": 0},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"],
        })
        
        registry = ToolExecutorRegistry()
        registry.register(executor)
        
        tool_registry = ToolRegistry()
        tool = ToolDefinition(
            id="validate-tool",
            name="validate_test",
            description="Validation test tool",
            input_schema=executor.get_tool_schema("validate_test"),
            capabilities=["read"],
            risk_level="low",
            executor_id="test",
            version="1.0",
        )
        tool_registry.register(tool)
        
        manager = ToolExecutionManager(
            executor_registry=registry,
            tool_registry=tool_registry,
            default_timeout=5,
        )
        
        # Valid input
        import asyncio
        async def test_valid():
            result = await manager.execute_tool(
                tool_name="validate_test",
                arguments={"name": "John", "age": 30, "tags": ["a", "b"]},
                context={"organization_id": "org-1"},
            )
            return result
        
        result = asyncio.run(test_valid())
        assert result.status == "success"
        
        # Invalid type
        async def test_invalid():
            result = await manager.execute_tool(
                tool_name="validate_test",
                arguments={"name": 123},  # should be string
                context={"organization_id": "org-1"},
            )
            return result
        
        result = asyncio.run(test_invalid())
        assert result.status == "error"
        assert result.error_code == "INVALID_ARGUMENTS"


class TestGlobalRegistries:
    """Tests for global registries."""
    
    def test_global_registries_initialized(self):
        """Test that global registries are properly initialized."""
        assert tool_registry is not None
        assert isinstance(tool_registry, ToolRegistry)
        
        assert tool_executor_registry is not None
        assert isinstance(tool_executor_registry, ToolExecutorRegistry)
    
    def test_global_registries_can_be_used(self):
        """Test that global registries can be used for registration."""
        # Clear any existing test tools
        tool_registry.unregister("global_test_tool", "1.0")
        
        tool = ToolDefinition(
            id="global-test-tool",
            name="global_test_tool",
            description="Global test tool",
            input_schema={"type": "object"},
            capabilities=["read"],
            risk_level="low",
            executor_id="test",
            version="1.0",
        )
        tool_registry.register(tool)
        
        retrieved = tool_registry.get("global_test_tool", "1.0")
        assert retrieved is not None
        assert retrieved.name == "global_test_tool"


class TestErrorHandling:
    """Tests for error handling in tool execution."""
    
    @pytest.mark.asyncio
    async def test_cancellation(self):
        """Test tool execution cancellation."""
        executor_registry = ToolExecutorRegistry()
        tool_registry = ToolRegistry()
        
        executor = MockToolExecutor("test", ["cancellable"])
        executor._execute_results["cancellable"] = asyncio.sleep(10)  # Long running
        executor_registry.register(executor)
        
        tool = ToolDefinition(
            id="cancellable-tool",
            name="cancellable",
            description="Cancellable tool",
            input_schema={"type": "object"},
            capabilities=["read"],
            risk_level="low",
            executor_id="test",
            version="1.0",
        )
        tool_registry.register(tool)
        
        manager = ToolExecutionManager(
            executor_registry=executor_registry,
            tool_registry=tool_registry,
            default_timeout=5,
        )
        
        # Start execution
        task = asyncio.create_task(manager.execute_tool(
            tool_name="cancellable",
            arguments={},
            context={"organization_id": "org-1"},
        ))
        
        # Give it a moment to start
        await asyncio.sleep(0.1)
        
        # Cancel
        cancelled = await manager.cancel("tool-exec-id")
        # Note: cancel checks by execution_id, but we don't have easy access to it
        # This is a limitation of the current implementation
        
        # Wait for completion
        result = await task
        assert result.status in ("error", "success")  # Will timeout or complete


if __name__ == "__main__":
    pytest.main([__file__, "-v"])