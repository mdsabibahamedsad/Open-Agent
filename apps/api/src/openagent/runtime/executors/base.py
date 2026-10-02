"""Base executor interface and result types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from openagent.runtime.models import ExecutionContext, NodeResult, NodeRunStatus


@dataclass
class NodeExecutionResult:
    """Result of a node execution."""
    status: NodeRunStatus
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    error_retryable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    # For WAITING status - when execution should resume
    resume_at: Optional[datetime] = None
    resume_token: Optional[str] = None


class NodeExecutor(ABC):
    """Base class for node executors."""
    
    # Node type this executor handles
    node_type: str = ""
    
    # Capabilities required by this executor
    required_capabilities: List[str] = field(default_factory=list)
    
    # Whether this node can run in parallel with others
    supports_parallel: bool = True
    
    # Default timeout in seconds
    default_timeout: int = 300

    @abstractmethod
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        """
        Execute the node.
        
        Args:
            node_config: The node's configuration from the workflow definition
            context: Runtime context with inputs, variables, credentials, etc.
            
        Returns:
            NodeExecutionResult with status, outputs, and any error info
        """
        pass

    def get_timeout(self, node_config: Dict[str, Any]) -> int:
        """Get timeout for this node."""
        timeout = node_config.get("timeout_seconds")
        if isinstance(timeout, (int, float)) and timeout > 0:
            return int(timeout)
        return self.default_timeout

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate node configuration. Return list of error messages."""
        return []

    def get_required_capabilities(self) -> List[str]:
        """Get required capabilities for this executor."""
        return self.required_capabilities


@dataclass
class NodeExecutionContext:
    """Context passed to node executors during execution."""
    execution_id: str
    workflow_id: str
    workflow_version_id: str
    organization_id: str
    node_id: str
    node_type: str
    node_name: str
    node_config: Dict[str, Any]
    
    # Inputs from upstream nodes
    inputs: Dict[str, Any]
    
    # Workflow variables
    variables: Dict[str, Any]

    # Credentials (resolved references)
    credentials: Dict[str, str] = field(default_factory=dict)
    
    # Cancellation support
    cancelled: bool = False
    
    # Timeout
    timeout_at: Optional[datetime] = None
    
    # Logging
    def log(self, level: str, message: str, **kwargs: Any) -> None:
        """Log a message with execution context."""
        pass  # Implemented by runtime
    
    # Cancellation check
    def check_cancelled(self) -> None:
        """Raise if execution was cancelled."""
        if self.cancelled:
            raise ExecutionCancelled("Execution cancelled")


class ExecutionCancelled(Exception):
    """Raised when execution is cancelled."""
    pass


class NodeExecutorRegistry:
    """Registry for node executors."""
    
    def __init__(self):
        self._executors: Dict[str, NodeExecutor] = {}
    
    def register(self, executor: NodeExecutor) -> None:
        """Register an executor for a node type."""
        if not executor.node_type:
            raise ValueError("Executor must have a node_type")
        self._executors[executor.node_type] = executor
    
    def unregister(self, node_type: str) -> bool:
        """Unregister an executor."""
        if node_type in self._executors:
            del self._executors[node_type]
            return True
        return False
    
    def get(self, node_type: str) -> Optional[NodeExecutor]:
        """Get executor for a node type."""
        return self._executors.get(node_type)
    
    def get_all(self) -> Dict[str, NodeExecutor]:
        """Get all registered executors."""
        return dict(self._executors)
    
    def get_supported_types(self) -> List[str]:
        """Get list of supported node types."""
        return list(self._executors.keys())


# Global executor registry
executor_registry = NodeExecutorRegistry()