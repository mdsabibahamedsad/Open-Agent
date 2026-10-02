"""Agent executor for workflow runtime integration."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from openagent.runtime.agent_core import (
    AgentConfig,
    AgentLoopContext,
    AgentLoop,
    AgentRunResult,
    AgentRunStatus,
    AgentCapabilities,
    AgentBudget,
    AgentRunStatus,
)
from openagent.runtime.agent_core import ContextBuilder
from openagent.runtime.engine import resolve_expressions
from openagent.runtime.executors.base import (
    NodeExecutor,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeRunStatus,
)
from openagent.runtime.models import NodeResult
from openagent.runtime.agent_core import ContextBuilder
from openagent.runtime.engine import resolve_expressions
from openagent.runtime.executors import executor_registry
from openagent.services.workflow_definition import validate_definition

from openagent.db.session import get_db
from openagent.db.models import (
    Agent,
    AgentVersion,
    AgentRun,
    AgentRunStatus,
    WorkflowExecution,
    ExecutionEvent,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("runtime.agent_executor")


class AgentNodeExecutor(NodeExecutor):
    """Executor for AI Agent node in workflows."""
    
    node_type = "agent"
    default_timeout = 3600  # 1 hour
    required_capabilities = ["agent_runtime"]
    
    def __init__(self):
        super().__init__()
        self._agent_runtime = None
    
    @property
    def node_type(self) -> str:
        return "agent"
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        """Execute the agent node."""
        
        # Get agent configuration
        agent_id = node_config.get("agent_id")
        version = node_config.get("version")
        task = node_config.get("task")
        
        if not agent_id:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Agent node requires 'agent_id' in config",
                error_code="INVALID_CONFIG",
            )
        
        # Load agent and version
        db = next(get_db())
        try:
            agent = await self._get_agent(agent_id)
            if not agent:
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error=f"Agent {agent_id} not found",
                    error_code="AGENT_NOT_FOUND",
                )
            
            # Get version
            if version:
                version_obj = await self._get_version(db, agent.id, version)
            else:
                # Get latest published version
                version_obj = await self._get_latest_published_version(db, agent.id)
            
            if not version_obj:
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error="No valid agent version found",
                    error_code="NO_VERSION",
                )
            
            # Build agent config from version
            agent_config = self._build_agent_config(version_obj)
            
            # Create execution context
            context = AgentLoopContext(
                execution_id=context.execution_id,
                agent_id=str(agent.id),
                agent_version_id=str(version_obj.id),
                organization_id=context.organization_id,
                workflow_execution_id=context.execution_id,  # Link to workflow execution
                node_execution_id=context.node_id,
                input=task if task else context.inputs,
                config=agent_config,
            )
            
            # Create and run agent loop
            agent_loop = AgentLoop(
                context=context,
                model_provider=model_provider_registry.get_for_model(agent_config.model),
                tool_executor=tool_executor_registry,
                expression_engine=expression_engine,
                condition_engine=condition_engine,
            )
            
            # Run agent
            result = await agent_loop.run()
            
            # Convert result
            if result.status == AgentRunStatus.SUCCEEDED:
                return NodeExecutionResult(
                    status=NodeRunStatus.SUCCEEDED,
                    outputs=result.output or {},
                    metadata={
                        "agent_id": str(agent.id),
                        "agent_version": version_obj.version,
                        "steps": result.total_steps,
                        "duration_seconds": result.duration_seconds,
                        "tokens": result.total_tokens,
                    }
                )
            else:
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error=result.error,
                    error_code=result.error_code,
                    metadata={
                        "agent_id": str(agent.id),
                        "agent_version": version_obj.version,
                        "steps": result.total_steps,
                    }
                )
                
        except Exception as e:
            logger.error("Agent execution failed", error=str(e))
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error=str(e),
                error_code="AGENT_EXECUTION_ERROR",
            )
        finally:
            await db.close()
    
    async def _get_agent(self, agent_id: str) -> Optional[Agent]:
        db = next(get_db())
        try:
            result = await db.execute(
                select(Agent).where(
                    Agent.id == agent_id,
                    Agent.deleted_at.is_(None),
                )
            )
            return result.scalar_one_or_none()
        finally:
            await db.close()
    
    async def _get_version(self, db: AsyncSession, agent_id: UUID, version: str) -> Optional[AgentVersion]:
        result = await db.execute(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent_id,
                AgentVersion.version == version,
            )
        )
        return result.scalar_one_or_none()
    
    async def _get_latest_published_version(self, db: AsyncSession, agent_id: UUID) -> Optional[AgentVersion]:
        result = await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .where(AgentVersion.status == "published")
            .order_by(AgentVersion.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    def _build_agent_config(self, version: AgentVersion) -> AgentConfig:
        """Build AgentConfig from version definition."""
        config = version.configuration or {}
        
        return AgentConfig(
            name=version.name,
            instructions=version.instructions,
            model=config.get("model", "gpt-4"),
            model_config=config.get("model_config", {}),
            tools=config.get("tools", []),
            output_config=config.get("output_config", {}),
            budget=AgentBudget(
                max_steps=config.get("max_steps", 10),
                max_tool_calls=config.get("max_tool_calls", 20),
                max_duration_seconds=config.get("max_duration_seconds", 300),
            ),
            capabilities=AgentCapabilities(
                model_invoke=True,
                tool_invoke=True,
                network_request=config.get("capabilities", {}).get("network", False),
                browser_control=config.get("capabilities", {}).get("browser", False),
                code_execution=config.get("capabilities", {}).get("code", False),
            ),
        )


# Import required modules
import structlog
from openagent.runtime.agent_core import AgentConfig, AgentLoopContext, AgentLoop, AgentRunResult, AgentRunStatus
from openagent.runtime.engine import expression_engine, resolve_expressions
from openagent.runtime.executors.base import NodeExecutionContext, NodeExecutionResult, NodeRunStatus
from openagent.runtime.models import NodeResult
from openagent.runtime.agent_core import ContextBuilder
from openagent.runtime.engine import resolve_expressions, expression_engine, condition_engine
from openagent.runtime.executors import executor_registry
from openagent.services.workflow_definition import validate_definition
from openagent.db.session import get_db
from openagent.db.models import Agent, AgentVersion, AgentRun, WorkflowExecution

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("runtime.agent_executor")

# Need to import these for the executor
from openagent.runtime.agent_core import AgentLoop, ContextBuilder
from openagent.runtime.engine import expression_engine, condition_engine
from openagent.runtime.model_adapters import model_provider_registry
from openagent.runtime.tools import tool_executor_registry
from openagent.db.session import get_db
from openagent.db.models import WorkflowExecution, WorkflowExecutionStatus
from openagent.runtime.models import NodeRunStatus

# Import workflow execution status
from openagent.db.models.workflow_execution import WorkflowExecutionStatus

logger = structlog.get_logger("runtime.agent_executor")