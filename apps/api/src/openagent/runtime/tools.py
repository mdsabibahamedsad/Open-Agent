"""Tool executor system."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import aiohttp
import structlog

from openagent.runtime.engine import resolve_expressions

logger = structlog.get_logger("runtime.tools")


@dataclass
class ToolDefinition:
    """Tool definition from the registry."""
    id: str
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    capabilities: List[str] = field(default_factory=list)
    risk_level: str = "low"  # low, medium, high, critical
    executor_id: str = "default"
    version: str = "1.0"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    """A tool call request."""
    id: str
    name: str
    arguments: Dict[str, Any]
    tool_call_id: Optional[str] = None


@dataclass
class ToolResult:
    """Tool execution result."""
    tool_call_id: str
    name: str
    status: str  # success, error, timeout
    output: Optional[Any] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """Registry for tool definitions."""
    
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._categories: Dict[str, List[str]] = {}
    
    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        key = f"{tool.name}@{tool.version}"
        self._tools[key] = tool
        
        # Index by category
        for cap in tool.capabilities:
            if cap not in self._categories:
                self._categories[cap] = []
            self._categories[cap].append(key)
    
    def unregister(self, name: str, version: str = "1.0") -> bool:
        key = f"{name}@{version}"
        if key in self._tools:
            del self._tools[key]
            return True
        return False
    
    def get(self, name: str, version: str = "1.0") -> Optional[ToolDefinition]:
        return self._tools.get(f"{name}@{version}")
    
    def get_latest(self, name: str) -> Optional[ToolDefinition]:
        """Get the latest version of a tool."""
        versions = [t for k, t in self._tools.items() if t.name == name]
        if not versions:
            return None
        return max(versions, key=lambda t: t.version)
    
    def list_tools(self, category: Optional[str] = None) -> List[ToolDefinition]:
        if category:
            keys = self._categories.get(category, [])
            return [self._tools[k] for k in keys if k in self._tools]
        return list(self._tools.values())
    
    def get_categories(self) -> List[str]:
        return list(self._categories.keys())
    
    def search(self, query: str) -> List[ToolDefinition]:
        query = query.lower()
        return [
            t for t in self._tools.values()
            if query in t.name.lower() or query in t.description.lower()
        ]


class ToolExecutor(ABC):
    """Abstract tool executor interface."""
    
    @property
    @abstractmethod
    def executor_id(self) -> str:
        pass
    
    @property
    @abstractmethod
    def supported_tools(self) -> List[str]:
        """List of tool names this executor handles."""
        pass
    
    @abstractmethod
    async def execute(self, tool_name: str, arguments: Dict[str, Any], 
                      context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a tool and return the result."""
        pass
    
    @abstractmethod
    async def validate_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Validate tool arguments against schema."""
        pass
    
    @abstractmethod
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def list_tools(self) -> List[Dict[str, Any]]:
        pass


class ToolExecutorRegistry:
    """Registry for tool executors."""
    
    def __init__(self):
        self._executors: Dict[str, ToolExecutor] = {}
        self._tool_to_executor: Dict[str, str] = {}  # tool_name -> executor_id
    
    def register(self, executor: ToolExecutor) -> None:
        """Register a tool executor."""
        self._executors[executor.executor_id] = executor
        for tool_name in executor.supported_tools:
            self._tool_to_executor[tool_name] = executor.executor_id
    
    def unregister(self, executor_id: str) -> bool:
        if executor_id in self._executors:
            executor = self._executors[executor_id]
            for tool_name in executor.supported_tools:
                self._tool_to_executor.pop(tool_name, None)
            del self._executors[executor_id]
            return True
        return False
    
    def get_executor_for_tool(self, tool_name: str) -> Optional[ToolExecutor]:
        executor_id = self._tool_to_executor.get(tool_name)
        if executor_id:
            return self._executors.get(executor_id)
        return None
    
    def get_executor(self, executor_id: str) -> Optional[ToolExecutor]:
        return self._executors.get(executor_id)
    
    def get_all(self) -> Dict[str, ToolExecutor]:
        return dict(self._executors)
    
    def list_all_tools(self) -> List[Dict[str, Any]]:
        """List all tools from all executors."""
        tools = []
        for executor in self._executors.values():
            for tool_name in executor.supported_tools:
                schema = executor.get_tool_schema(tool_name)
                if schema:
                    tools.append({
                        "name": tool_name,
                        "executor": executor.executor_id,
                        "schema": schema,
                    })
        return tools


# Global registries
tool_registry = ToolRegistry()
tool_executor_registry = ToolExecutorRegistry()


class ToolExecutionError(Exception):
    """Error during tool execution."""
    def __init__(self, code: str, message: str, tool_name: str):
        super().__init__(message)
        self.code = code
        self.tool_name = tool_name


class BaseToolExecutor(ToolExecutor):
    """Base class for tool executors with common functionality."""
    
    def __init__(self, executor_id: str, supported_tools: List[str]):
        self._executor_id = executor_id
        self._supported_tools = supported_tools
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}
    
    @property
    def executor_id(self) -> str:
        return self._executor_id
    
    @property
    def supported_tools(self) -> List[str]:
        return self._supported_tools
    
    def register_tool_schema(self, tool_name: str, schema: Dict[str, Any]) -> None:
        self._tool_schemas[tool_name] = schema
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        return self._tool_schemas.get(tool_name)
    
    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": name, "schema": schema}
            for name, schema in self._tool_schemas.items()
        ]
    
    async def validate_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        schema = self.get_tool_schema(tool_name)
        if not schema:
            return True  # No schema = no validation
        
        # Simple validation - in production, use jsonschema
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        
        for req in required:
            if req not in arguments:
                return False
        
        # Type checking (simplified)
        for key, value in arguments.items():
            if key in properties:
                prop_schema = properties[key]
                expected_type = prop_schema.get("type")
                if expected_type == "string" and not isinstance(arguments[key], str):
                    return False
                elif expected_type == "number" and not isinstance(arguments[key], (int, float)):
                    return False
                elif expected_type == "boolean" and not isinstance(arguments[key], bool):
                    return False
                elif expected_type == "array" and not isinstance(arguments[key], list):
                    return False
                elif expected_type == "object" and not isinstance(arguments[key], dict):
                    return False
        
        return True
    
    @abstractmethod
    async def execute(self, tool_name: str, arguments: Dict[str, Any], 
                      context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pass


class ToolExecutionManager:
    """Manages tool execution with retries, timeouts, and logging."""
    
    def __init__(
        self,
        executor_registry: ToolExecutorRegistry,
        tool_registry: ToolRegistry,
        default_timeout: int = 30,
        max_retries: int = 2,
    ):
        self.executor_registry = executor_registry
        self.tool_registry = tool_registry
        self.default_timeout = default_timeout
        self.max_retries = max_retries
    
    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        tool_call_id: Optional[str] = None,
    ) -> ToolResult:
        """Execute a tool with full lifecycle management."""
        tool_call_id = tool_call_id or f"tc_{uuid.uuid4().hex[:12]}"
        started_at = datetime.now(timezone.utc)
        
        # Find executor for tool
        executor = self.executor_registry.get_executor_for_tool(tool_name)
        if not executor:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
                error=f"No executor found for tool: {tool_name}",
                error_code="NO_EXECUTOR",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        
        # Get tool definition
        tool_def = self.tool_registry.get_latest(tool_name)
        
        # Validate arguments
        if not await executor.validate_arguments(tool_name, arguments):
            return ToolResult(
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
                error="Invalid arguments",
                error_code="INVALID_ARGUMENTS",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        
        # Check capabilities/permissions
        if not self._check_permissions(tool_name, context):
            return ToolResult(
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
                error="Insufficient permissions",
                error_code="PERMISSION_DENIED",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        
        # Execute with retries
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                start_time = time.time()
                result = await asyncio.wait_for(
                    executor.execute(tool_name, arguments, context),
                    timeout=self.default_timeout,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                
                return ToolResult(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    status="success",
                    output=result,
                    started_at=datetime.now(timezone.utc) - timedelta(milliseconds=duration_ms),
                    completed_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    metadata={"attempt": attempt + 1},
                )
            except asyncio.TimeoutError:
                last_error = f"Tool execution timeout after {self.default_timeout}s"
            except Exception as e:
                last_error = str(e)
            
            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        return ToolResult(
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
            error=last_error or "Max retries exceeded",
            error_code="MAX_RETRIES_EXCEEDED",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    
    def _check_permissions(self, tool_name: str, context: Optional[Dict[str, Any]]) -> bool:
        """Check if the context has permission to execute this tool."""
        # In a real implementation, this would check:
        # - Organization-level tool permissions
        # - User roles and permissions
        # - Capability requirements
        # For now, allow all
        return True


# Import required modules
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID