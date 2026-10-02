"""Agent Runtime core: AgentLoop, ContextBuilder, and AgentLoopContext."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, AsyncGenerator, AsyncIterator
from uuid import UUID

import structlog

from openagent.runtime.agent_models import (
    AgentCapabilities,
    AgentConfig,
    AgentLoopContext,
    AgentLoopState,
    AgentRunResult,
    AgentRunStatus,
    AgentStep,
    AgentBudget,
    AgentCapabilities,
    AgentConfig,
)
from openagent.runtime.engine import expression_engine, resolve_expressions, evaluate_condition
from openagent.runtime.engine import ExpressionEngine, ConditionEngine
from openagent.runtime.models import NodeResult, NodeRunStatus
from openagent.runtime.executors.base import NodeExecutionContext, NodeExecutionResult, NodeRunStatus
from openagent.runtime.executors import executor_registry
from openagent.services.workflow_definition import validate_definition

# Import new tool system
from openagent.runtime.tools import ToolExecutionManager, tool_registry, tool_executor_registry
from openagent.runtime.tools import ToolDefinition as RuntimeToolDefinition

from openagent.db.session import get_db
from openagent.db.models import (
    Agent,
    AgentVersion,
    AgentRun,
    AgentRunStatus,
    WorkflowExecution,
    Tool,
    ToolLifecycleStatus,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("runtime.agent")


class AgentLoop:
    """Core agent execution loop."""
    
    def __init__(
        self,
        context: AgentLoopContext,
        model_provider: 'ModelProvider',
        tool_executor: 'ToolExecutor',
        expression_engine: ExpressionEngine,
        condition_engine: ConditionEngine,
    ):
        self.context = context
        self.model_provider = model_provider
        self.tool_executor = tool_executor
        self.expression_engine = expression_engine
        self.condition_engine = condition_engine
        
        self._step_results: List[Dict[str, Any]] = []
        self._cancelled = False
        
    async def run(self) -> AgentRunResult:
        """Run the agent loop to completion."""
        self.context.status = AgentRunStatus.RUNNING
        self.context.started_at = datetime.now(timezone.utc)
        
        try:
            # Build initial context
            await self._build_initial_context()
            
            # Main agent loop
            while self.context.current_step < self.context.max_steps:
                if self.context.cancelled:
                    return self._create_result(AgentRunStatus.CANCELLED, "Execution cancelled")
                
                # Check budget
                budget_check = self._check_budget()
                if budget_check:
                    return budget_check
                
                # Check timeout
                if self._check_timeout():
                    return self._create_result(AgentRunStatus.TIMED_OUT, "Execution timeout")
                
                # Execute one step
                step_result = await self._execute_step()
                
                if step_result.status == AgentRunStatus.FAILED:
                    return self._create_result(AgentRunStatus.FAILED, step_result.error or "Step failed")
                elif step_result.status == AgentRunStatus.COMPLETED:
                    return step_result
                
                # Check if we should continue
                if self.context.current_step >= self.context.max_steps:
                    return self._create_result(AgentRunStatus.BUDGET_EXCEEDED, "Maximum steps exceeded")
                
            return self._create_result(AgentRunStatus.BUDGET_EXCEEDED, "Maximum steps exceeded")
            
        except asyncio.CancelledError:
            return self._create_result(AgentRunStatus.CANCELLED, "Execution cancelled")
        except Exception as e:
            logger.error("Agent loop failed", error=str(e))
            return self._create_result(AgentRunStatus.FAILED, str(e))
        finally:
            self.context.completed_at = datetime.now(timezone.utc)
    
    async def _build_initial_context(self) -> None:
        """Build the initial context for the agent."""
        self.context.system_prompt = self._build_system_prompt()
        self.context.conversation_history = []
        
        # Add workflow input as first message
        if self.context.input:
            self.context.conversation_history.append({
                "role": "user",
                "content": self._format_input(self.context.input),
            })
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt from agent configuration."""
        config = self.context.config
        if not config:
            return "You are a helpful AI assistant."
        
        parts = [config.instructions] if config.instructions else []
        
        # Add capability hints
        if config.capabilities.tool_invoke:
            parts.append("\nYou have access to tools. Use them when appropriate.")
        
        if config.capabilities.browser_control:
            parts.append("\nYou can browse the web.")
        
        if config.capabilities.code_execution:
            parts.append("\nYou can execute code.")
        
        return "\n\n".join(parts)
    
    def _format_input(self, input_data: Dict[str, Any]) -> str:
        """Format workflow input for the model."""
        if len(input_data) == 1:
            # Single value, return directly
            return list(input_data.values())[0]
        return json.dumps(input_data, indent=2)
    
    def _check_budget(self) -> Optional[AgentRunResult]:
        """Check if budget is exceeded."""
        if self.context.budget.steps_used >= self.context.max_steps:
            return AgentRunResult(
                status=AgentRunStatus.BUDGET_EXCEEDED,
                error="Maximum steps exceeded",
                error_code="BUDGET_EXCEEDED",
            )
        
        if self.context.budget.tool_calls_used >= self.context.budget.max_tool_calls:
            return AgentRunResult(
                status=AgentRunStatus.BUDGET_EXCEEDED,
                error="Maximum tool calls exceeded",
                error_code="BUDGET_EXCEEDED",
            )
        
        return None
    
    def _check_timeout(self) -> bool:
        """Check if execution has timed out."""
        if self.context.budget.max_duration_seconds <= 0:
            return False
        
        elapsed = (datetime.now(timezone.utc) - self.context.started_at).total_seconds()
        return elapsed >= self.context.budget.max_duration_seconds
    
    async def _execute_step(self) -> AgentRunResult:
        """Execute a single step of the agent loop."""
        self.context.current_step += 1
        self.context.budget.steps_used += 1
        
        step = AgentStep(
            step_number=self.context.current_step,
            started_at=datetime.now(timezone.utc),
        )
        
        self.context.current_state = AgentLoopState.BUILDING_CONTEXT
        
        # Build context for model
        messages = self._build_messages()
        
        # Get model config
        model_config = self._get_model_config()
        
        self.context.current_state = AgentLoopState.CALLING_MODEL
        self.context.step_started_at = datetime.now(timezone.utc)
        
        # Call model
        try:
            response = await self._call_model(messages)
        except Exception as e:
            return AgentRunResult(
                status=AgentRunStatus.FAILED,
                error=f"Model call failed: {e}",
                error_code="MODEL_ERROR",
            )
        
        self.context.current_state = AgentLoopState.PARSING_RESPONSE
        
        # Parse response
        tool_calls = self._parse_tool_calls(response)
        text_content = self._extract_text_content(response)
        
        step.model_request = {"messages": messages, "model": self.context.config.model}
        step.model_response = {"content": text_content, "tool_calls": tool_calls}
        
        # If no tool calls, we're done
        if not tool_calls:
            self.context.current_state = AgentLoopState.VALIDATING_OUTPUT
            
            # Validate output if configured
            validation_result = await self._validate_output(text_content)
            if not validation_result.valid:
                return AgentRunResult(
                    status=AgentRunStatus.FAILED,
                    error=validation_result.error,
                    error_code=validation_result.error_code,
                )
            
            # Success!
            return AgentRunResult(
                status=AgentRunStatus.SUCCEEDED,
                output={"content": text_content},
                steps=self.context.steps + [step],
                total_steps=self.context.current_step,
            )
        
        # Execute tool calls
        self.context.current_state = AgentLoopState.EXECUTING_TOOL
        
        tool_results = []
        for tool_call in tool_calls:
            tool_result = await self._execute_tool(tool_call)
            tool_results.append(tool_result)
            
            # Add to conversation history
            self.context.conversation_history.append({
                "role": "assistant",
                "content": text_content,
                "tool_calls": [tool_call],
            })
            self.context.conversation_history.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": json.dumps(tool_result.get("output", {})),
            })
            
            # Record step
            step.tool_calls.append(tool_call)
            step.tool_results.append(tool_result)
            
            # Check for errors
            if tool_result.get("status") == "failed":
                step.error = tool_result.get("error")

        # MP19: approval-gated tools pause the run durably instead of
        # continuing as if the action succeeded.
        waiting = [r for r in tool_results if r.get("status") == "WAITING_FOR_APPROVAL"]
        if waiting:
            self.context.current_state = AgentLoopState.WAITING_FOR_APPROVAL
            step.completed_at = datetime.now(timezone.utc)
            step.status = "waiting"
            self.context.steps.append(step)
            return AgentRunResult(
                status=AgentRunStatus.WAITING,
                output={"waiting_for_approval": True,
                        "approvals": [{"tool": r.get("name"),
                                       "risk_level": r.get("risk_level"),
                                       "reasons": r.get("reasons", []),
                                       "message": r.get("message")} for r in waiting]},
                steps=self.context.steps + [step],
                total_steps=self.context.current_step)
        
        step.completed_at = datetime.now(timezone.utc)
        step.status = "succeeded"
        self.context.steps.append(step)
        
        # Continue loop
        return AgentRunResult(status=AgentRunStatus.RUNNING)
    
    def _get_model_config(self) -> Dict[str, Any]:
        """Get model configuration from agent config."""
        config = self.context.config
        if not config:
            return {}
        
        return {
            "model": config.model,
            "temperature": config.model_config.get("temperature", 0.7),
            "max_tokens": config.model_config.get("max_tokens", 4096),
            "response_format": config.output_config.get("format"),
        }
    
    async def _call_model(self, messages: List[Dict[str, Any]]) -> Any:
        """Call the model provider."""
        model_config = self._get_model_config()
        
        request = ModelRequest(
            model=model_config["model"],
            messages=messages,
            temperature=model_config.get("temperature", 0.7),
            max_tokens=model_config.get("max_tokens", 4096),
        )
        
        return await self.model_provider.generate(request)
    
    def _parse_tool_calls(self, response: Any) -> List[Dict[str, Any]]:
        """Parse tool calls from model response."""
        # This would depend on the model provider's response format
        # For now, return empty list
        return []
    
    def _extract_text_content(self, response: Any) -> str:
        """Extract text content from model response."""
        # This would depend on the model provider's response format
        return ""
    
    async def _execute_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call using the new tool runtime.

        MP19: every tool call passes the central guard first. Denied actions
        fail closed; approval-gated actions return a structured
        WAITING_FOR_APPROVAL status so the agent pauses instead of treating
        the action as succeeded.
        """
        tool_name = tool_call.get("name")
        arguments = tool_call.get("arguments", {})
        tool_call_id = tool_call.get("id", str(uuid.uuid4()))

        try:
            from openagent.approvals.integrations import agent_tool_gate
            gate = agent_tool_gate(
                tool_name=str(tool_name), arguments=dict(arguments or {}),
                organization_id=self.context.organization_id,
                environment="development")
            if gate.get("denied"):
                return {"tool_call_id": tool_call_id, "name": tool_name,
                        "status": "error", "error": gate.get("message"),
                        "error_code": "POLICY_DENIED",
                        "risk_level": gate.get("risk_level"),
                        "reasons": gate.get("reasons", [])}
            if gate.get("waiting"):
                return {"tool_call_id": tool_call_id, "name": tool_name,
                        "status": "WAITING_FOR_APPROVAL",
                        "risk_level": gate.get("risk_level"),
                        "risk_score": gate.get("risk_score"),
                        "policy_decision": gate.get("policy_decision"),
                        "reasons": gate.get("reasons", []),
                        "message": gate.get("message"),
                        "approval_id": None,
                        "note": "Create the persisted approval via the approvals API, "
                                "then resume with the approval_id."}
        except Exception as e:
            logger.error("Approval gate failed closed", tool_name=tool_name, error=str(e))
            return {"tool_call_id": tool_call_id, "name": tool_name,
                    "status": "error", "error": "Guard evaluation failed",
                    "error_code": "GUARD_ERROR"}

        
        # Load tool from database
        db = next(get_db())
        try:
            tool = await db.execute(
                select(Tool).where(
                    Tool.slug == tool_name,
                    Tool.status == ToolLifecycleStatus.ACTIVE,
                    Tool.deleted_at.is_(None),
                )
            )
            tool = tool.scalar_one_or_none()
            
            if not tool:
                return {
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "status": "error",
                    "error": f"Tool {tool_name} not found or not active",
                }
            
            # Register tool in runtime registry if not present
            runtime_tool = RuntimeToolDefinition(
                id=str(tool.id),
                name=tool.slug,
                description=tool.description or "",
                input_schema=tool.input_schema,
                output_schema=tool.output_schema,
                capabilities=[c.value for c in tool.capabilities],
                risk_level=tool.risk_level.value.lower(),
                executor_id=tool.provider,
                version=tool.version,
                metadata=tool.metadata,
            )
            tool_registry.register(runtime_tool)
            
            # Create execution context
            context = {
                "organization_id": str(self.context.organization_id),
                "user_id": str(self.context.user_id) if self.context.user_id else None,
                "agent_id": str(self.context.agent_id) if self.context.agent_id else None,
                "workflow_id": str(self.context.workflow_execution_id) if self.context.workflow_execution_id else None,
            }
            
            # Use tool execution manager
            manager = ToolExecutionManager(
                executor_registry=tool_executor_registry,
                tool_registry=tool_registry,
                default_timeout=tool.timeout,
            )
            
            result = await manager.execute_tool(
                tool_name=tool.slug,
                arguments=arguments,
                context=context,
            )
            
            return {
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "status": result.status,
                "output": result.output,
                "error": result.error,
            }
        except Exception as e:
            logger.error("Tool execution failed", tool_name=tool_name, error=str(e))
            return {
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "status": "error",
                "error": str(e),
            }
        finally:
            await db.close()
    
    async def _validate_output(self, output: str) -> ValidationResult:
        """Validate agent output against output config."""
        config = self.context.config
        if not config or not config.output_config:
            return ValidationResult(valid=True)
        
        # Validate against schema if provided
        schema = config.output_config.get("schema")
        if schema:
            try:
                parsed = json.loads(output)
                # Validate against schema (simplified)
                return ValidationResult(valid=True)
            except json.JSONDecodeError:
                return ValidationResult(
                    valid=False,
                    error="Output is not valid JSON",
                    error_code="INVALID_JSON",
                )
        
        return ValidationResult(valid=True)
    
    def _create_result(self, status: AgentRunStatus, error: Optional[str] = None) -> AgentRunResult:
        """Create a run result."""
        duration = (datetime.now(timezone.utc) - self.context.started_at).total_seconds()
        
        return AgentRunResult(
            status=status,
            error=error,
            steps=self.context.steps,
            total_steps=self.context.current_step,
            total_tokens=sum(s.metadata.get("tokens", 0) for s in self.context.steps),
            duration_seconds=(datetime.now(timezone.utc) - self.context.started_at).total_seconds(),
        )


class ContextBuilder:
    """Builds the context for model calls."""
    
    def __init__(self, context: AgentLoopContext):
        self.context = context
    
    def build_messages(self) -> List[Dict[str, Any]]:
        """Build the message list for the model call."""
        messages = []
        
        # System prompt
        if self.context.system_prompt:
            messages.append({"role": "system", "content": self.context.system_prompt})
        
        # Conversation history
        messages.extend(self.context.conversation_history)
        
        # Add current input if this is the first step
        if self.context.current_step == 1 and self.context.input:
            input_text = self._format_input(self.context.input)
            messages.append({"role": "user", "content": input_text})
        
        return messages
    
    def _format_input(self, input_data: Dict[str, Any]) -> str:
        """Format workflow input for the model."""
        if len(input_data) == 1:
            return list(input_data.values())[0]
        return json.dumps(input_data, indent=2)


@dataclass
class ModelRequest:
    """Request to a model provider."""
    model: str
    messages: List[Dict[str, Any]]
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[str] = None
    response_format: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    """Response from a model provider."""
    id: Optional[str] = None
    content: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelStreamEvent:
    """Streaming event from model."""
    type: str  # delta, tool_call, done, error
    content: Optional[str] = None
    tool_call: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


class ModelProvider(ABC):
    """Abstract model provider interface."""
    
    @property
    @abstractmethod
    def provider_id(self) -> str:
        pass
    
    @property
    @abstractmethod
    def supported_models(self) -> List[str]:
        pass
    
    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelResponse:
        pass
    
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        """Stream model response."""
        response = await self.generate(request)
        yield ModelStreamEvent(type="delta", content=response.content)
        yield ModelStreamEvent(type="done", finish_reason=response.finish_reason, usage=response.usage)
    
    async def health_check(self) -> bool:
        """Check if provider is healthy."""
        return True


class ModelProviderRegistry:
    """Registry for model providers."""
    
    def __init__(self):
        self._providers: Dict[str, ModelProvider] = {}
    
    def register(self, provider: ModelProvider) -> None:
        self._providers[provider.provider_id] = provider
    
    def unregister(self, provider_id: str) -> bool:
        if provider_id in self._providers:
            del self._providers[provider_id]
            return True
        return False
    
    def get(self, provider_id: str) -> Optional[ModelProvider]:
        return self._providers.get(provider_id)
    
    def get_for_model(self, model: str) -> Optional[ModelProvider]:
        """Get provider that supports a model."""
        for provider in self._providers.values():
            if model in provider.supported_models:
                return provider
        return None
    
    def list_models(self) -> List[str]:
        models = set()
        for provider in self._providers.values():
            models.update(provider.supported_models)
        return sorted(models)


# Global registry
model_provider_registry = ModelProviderRegistry()


class ToolExecutor(ABC):
    """Abstract tool executor interface."""
    
    @property
    @abstractmethod
    def executor_id(self) -> str:
        pass
    
    @abstractmethod
    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    async def validate_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
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
    
    def register(self, executor: ToolExecutor) -> None:
        self._executors[executor.executor_id] = executor
    
    def unregister(self, executor_id: str) -> bool:
        if executor_id in self._executors:
            del self._executors[executor_id]
            return True
        return False
    
    def get(self, executor_id: str) -> Optional[ToolExecutor]:
        return self._executors.get(executor_id)
    
    def get_all(self) -> Dict[str, ToolExecutor]:
        return dict(self._executors)


# Global tool executor registry
tool_executor_registry = ToolExecutorRegistry()


@dataclass
class ValidationResult:
    valid: bool
    error: Optional[str] = None
    error_code: Optional[str] = None


# Import required modules
import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, AsyncGenerator, AsyncIterator
from uuid import UUID
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, AsyncGenerator, AsyncIterator
from uuid import UUID