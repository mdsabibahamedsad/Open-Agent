"""Runtime core: coordinates workflow execution."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set
from contextlib import asynccontextmanager

import structlog

from openagent.runtime.models import (
    ExecutionContext,
    ExecutionPlan,
    NodeRunStatus,
    NodeResult,
    WorkflowRunStatus,
    WorkflowRunStatus,
)
from openagent.runtime.planner import ExecutionPlan, build_execution_plan
from openagent.runtime.engine import resolve_expressions, evaluate_condition
from openagent.runtime.executors import executor_registry
from openagent.runtime.executors.base import NodeExecutionContext, NodeExecutionResult, NodeRunStatus
from openagent.runtime.executors import register_builtin_executors
from openagent.services.workflow_definition import validate_definition

from openagent.db.session import get_db
from openagent.db.models import (
    Workflow,
    WorkflowExecution,
    WorkflowVersion,
    ExecutionEvent,
    WorkflowExecutionStatus,
    WorkflowExecutionTriggerType,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("runtime.core")


# Ensure built-in executors are registered
register_builtin_executors()

# Register browser tools through Tool Runtime (policy-gated, no second tool system).
try:
    from openagent.browser.tools import ensure_browser_tools_registered
    ensure_browser_tools_registered()
except Exception:  # browser optional at runtime; API layer reports clearly
    logger.warning("browser_tools_registration_skipped")

# Register code tools through Tool Runtime (same single boundary).
try:
    from openagent.code.tools import ensure_code_tools_registered
    ensure_code_tools_registered()
except Exception:  # code engine optional at runtime; API layer reports clearly
    logger.warning("code_tools_registration_skipped")

# Register sandbox tools through Tool Runtime (execution boundary for
# code/workflow/tool/agent execution; never bypassed).
try:
    from openagent.sandbox.tools import ensure_sandbox_tools_registered
    ensure_sandbox_tools_registered()
except Exception:  # sandbox optional at runtime; API layer reports clearly
    logger.warning("sandbox_tools_registration_skipped")


class ExecutionRuntime:
    """Core workflow execution runtime."""
    
    def __init__(
        self,
        db_session: AsyncSession,
        worker_id: str = "runtime",
    ):
        self.db = db_session
        self.worker_id = worker_id
        self._active_executions: Dict[str, ExecutionContext] = {}
        self._execution_plans: Dict[str, ExecutionPlan] = {}
        
    async def create_execution(
        self,
        workflow_id: str,
        organization_id: str,
        triggered_by: Optional[str] = None,
        trigger_input: Optional[Dict[str, Any]] = None,
        version: Optional[str] = None,
    ) -> str:
        """
        Create a new workflow execution.
        
        Returns the execution ID.
        """
        # Load workflow and version
        db = self.db
        workflow = await self._get_workflow(organization_id, workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        # Get version
        if version:
            result = await db.execute(
                select(WorkflowVersion).where(
                    WorkflowVersion.workflow_id == workflow.id,
                    WorkflowVersion.version == version,
                )
            )
            workflow_version = result.scalar_one_or_none()
        else:
            # Get latest version
            result = await db.execute(
                select(WorkflowVersion)
                .where(WorkflowVersion.workflow_id == workflow.id)
                .order_by(WorkflowVersion.created_at.desc())
                .limit(1)
            )
            workflow_version = result.scalar_one_or_none()
        
        if not workflow_version:
            raise ValueError("No workflow version found")
        
        # Create execution record
        execution = WorkflowExecution(
            organization_id=organization_id,
            workflow_id=workflow.id,
            workflow_version_id=workflow_version.id,
            status=WorkflowExecutionStatus.QUEUED,
            trigger_type=TriggerType.MANUAL,  # Default, will be overridden by trigger
        )
        
        db.add(execution)
        await db.flush()
        await db.commit()
        
        return str(execution.id)
    
    async def start_execution(self, execution_id: str) -> None:
        """Start executing a queued workflow."""
        execution = await self._get_execution(execution_id)
        if not execution:
            raise ValueError(f"Execution {execution_id} not found")
        
        if execution.status != WorkflowExecutionStatus.QUEUED:
            raise ValueError(f"Execution {execution_id} is not in QUEUED status")
        
        # Update status to RUNNING
        execution.status = WorkflowExecutionStatus.RUNNING
        execution.started_at = datetime.now(timezone.utc)
        
        # Load workflow version and build execution plan
        workflow_version = await self._get_workflow_version(execution.workflow_version_id)
        plan = build_execution_plan(
            workflow_id=str(execution.workflow_id),
            workflow_version_id=str(execution.workflow_version_id),
            definition=workflow_version.definition or {},
        )
        plan.execution_id = execution_id
        plan.workflow_id = str(execution.workflow_id)
        plan.workflow_version_id = str(execution.workflow_version_id)
        
        self._execution_plans[execution_id] = plan
        
        # Create execution context
        context = ExecutionContext(
            execution_id=str(execution.id),
            workflow_id=str(execution.workflow_id),
            workflow_version_id=str(execution.workflow_version_id),
            organization_id=str(execution.organization_id),
            triggered_by=None,
        )
        
        self._active_executions[execution_id] = context
        
        # Emit execution started event
        await self._emit_event(execution_id, "execution.started", {})
        
        # Start execution (non-blocking)
        asyncio.create_task(self._run_execution(execution_id))
    
    async def _run_execution(self, execution_id: str) -> None:
        """Run the execution to completion."""
        plan = self._execution_plans.get(execution_id)
        if not plan:
            logger.error("Execution plan not found", execution_id=execution_id)
            return
        
        context = self._active_executions.get(execution_id)
        if not context:
            logger.error("Execution context not found", execution_id=execution_id)
            return
        
        try:
            # Execute each level in the execution order
            for level in plan.execution_order:
                # Check if execution was cancelled
                if context.cancelled:
                    await self._fail_execution(execution_id, "Execution cancelled")
                    return
                
                # Check timeout
                if context.timeout_at and datetime.now(timezone.utc) > context.timeout_at:
                    await self._fail_execution(execution_id, "Execution timeout")
                    return
                
                # Execute nodes in this level in parallel
                await self._execute_level(execution_id, plan, level)
            
            # Check if any node failed
            failed_nodes = [
                nid for nid, result in context.node_results.items()
                if result.status == NodeRunStatus.FAILED
            ]
            
            if failed_nodes:
                await self._fail_execution(execution_id, f"Nodes failed: {failed_nodes}")
            else:
                await self._complete_execution(execution_id)
                
        except Exception as e:
            logger.error("Execution failed", execution_id=execution_id, error=str(e))
            await self._fail_execution(execution_id, str(e))
        finally:
            # Cleanup
            self._active_executions.pop(execution_id, None)
            self._execution_plans.pop(execution_id, None)
    
    async def _execute_level(self, execution_id: str, plan: ExecutionPlan, level: List[str]) -> None:
        """Execute all nodes in a level in parallel."""
        tasks = []
        
        for node_id in level:
            node_plan = plan.node_map.get(node_id)
            if not node_plan:
                continue
            
            # Skip disabled nodes
            if node_plan.is_disabled:
                continue
            
            # Check if node is already done
            context = self._active_executions.get(execution_id)
            if context and node_id in context.node_results:
                continue
            
            # Check if dependencies are satisfied
            if not self._dependencies_satisfied(node_plan, execution_id):
                # Skip for now, will be picked up later
                continue
            
            # Check if node is in fan-in set - wait for all inputs
            if node_plan.node_id in plan.fan_in_node_ids:
                if not self._all_inputs_ready(node_plan, execution_id):
                    continue
            
            # Create task
            task = asyncio.create_task(self._execute_node(execution_id, node_plan))
            tasks.append((node_plan.node_id, task))
        
        # Wait for all tasks in this level
        if tasks:
            results = await asyncio.gather(*[t for _, t in tasks], return_exceptions=True)
            
            for (node_id, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    logger.error("Node execution failed", node_id=node_id, error=str(result))
                    # The node executor should handle errors and return failed result
    
    async def _execute_node(self, execution_id: str, node_plan: NodeExecutionPlan) -> NodeResult:
        """Execute a single node."""
        executor = executor_registry.get(node_plan.node_type)
        if not executor:
            return NodeResult(
                node_id=node_plan.node_id,
                status=NodeRunStatus.FAILED,
                error=f"No executor registered for node type: {node_plan.node_type}",
                error_code="NO_EXECUTOR",
            )
        
        # Get execution context
        context = self._active_executions.get(execution_id)
        if not context:
            return NodeResult(
                node_id=node_plan.node_id,
                status=NodeRunStatus.FAILED,
                error="Execution context not found",
                error_code="NO_CONTEXT",
            )
        
        # Build node execution context
        node_context = NodeExecutionContext(
            execution_id=execution_id,
            workflow_id=context.workflow_id,
            workflow_version_id=context.workflow_version_id,
            organization_id=context.organization_id,
            node_id=node_plan.node_id,
            node_type=node_plan.node_type,
            node_name=node_plan.name,
            node_config=node_plan.config,
            inputs=self._get_node_inputs(node_plan, execution_id),
            variables=context.variables,
        )
        
        # Emit node started event
        await self._emit_event(execution_id, "node.started", {
            "node_id": node_plan.node_id,
            "node_type": node_plan.node_type,
        })
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Apply timeout
            timeout = executor.get_timeout(node_plan.config)
            result = await asyncio.wait_for(
                executor.execute(node_plan.config, node_context),
                timeout=timeout,
            )
            
            completed_at = datetime.now(timezone.utc)
            
            node_result = NodeResult(
                node_id=node_plan.node_id,
                status=result.status,
                outputs=result.outputs,
                error=result.error,
                error_code=result.error_code,
                error_retryable=result.error_retryable,
                started_at=start_time,
                completed_at=completed_at,
                metadata=result.metadata,
            )
            
            # Store result
            context = self._active_executions.get(execution_id)
            if context:
                context.node_results[node_plan.node_id] = node_result
            
            # Emit completion event
            await self._emit_event(execution_id, "node.completed", {
                "node_id": node_plan.node_id,
                "status": result.status.value,
            })
            
            return node_result
            
        except asyncio.TimeoutError:
            return NodeResult(
                node_id=node_plan.node_id,
                status=NodeRunStatus.TIMED_OUT,
                error=f"Node timed out after {timeout}s",
                error_code="TIMEOUT",
            )
        except Exception as e:
            logger.error("Node execution failed", node_id=node_plan.node_id, error=str(e))
            return NodeResult(
                node_id=node_plan.node_id,
                status=NodeRunStatus.FAILED,
                error=str(e),
                error_code="EXECUTION_ERROR",
            )
    
    def _get_node_inputs(self, node_plan: NodeExecutionPlan, execution_id: str) -> Dict[str, Any]:
        """Get inputs for a node from upstream node outputs."""
        plan = self._execution_plans.get(execution_id)
        if not plan:
            return {}
        
        # Get inputs from edges
        inputs = {}
        for edge in plan.edges:
            if edge["to"] == node_plan.node_id:
                # This edge targets our node
                source_id = edge["from"]
                context = self._active_executions.get(execution_id)
                if context and source_id in context.node_results:
                    source_result = context.node_results[source_id]
                    if source_result.status == NodeRunStatus.SUCCEEDED:
                        # Use label or default output
                        label = edge.get("label") or "output"
                        inputs[label] = source_result.outputs
        
        return inputs
    
    def _dependencies_satisfied(self, node_plan: NodeExecutionPlan, execution_id: str) -> bool:
        """Check if all dependencies for a node are satisfied."""
        plan = self._execution_plans.get(execution_id)
        if not plan:
            return False
        
        # Check all incoming edges
        for edge in plan.edges:
            if edge["to"] == node_plan.node_id:
                source_id = edge["from"]
                context = self._active_executions.get(execution_id)
                if not context or source_id not in context.node_results:
                    return False
                source_result = context.node_results[source_id]
                if source_result.status != NodeRunStatus.SUCCEEDED:
                    return False
        return True
    
    def _all_inputs_ready(self, node_plan: NodeExecutionPlan, execution_id: str) -> bool:
        """Check if all inputs for a fan-in node are ready."""
        plan = self._execution_plans.get(execution_id)
        if not plan:
            return False
        
        incoming = [e for e in plan.edges if e["to"] == node_plan.node_id]
        if not incoming:
            return True
        
        context = self._active_executions.get(execution_id)
        if not context:
            return False
        
        for edge in incoming:
            source_id = edge["from"]
            if source_id not in context.node_results:
                return False
            source_result = context.node_results[source_id]
            if source_result.status != NodeRunStatus.SUCCEEDED:
                return False
        
        return True
    
    async def _emit_event(self, execution_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit an execution event."""
        event = ExecutionEvent(
            execution_id=execution_id,
            event_type=event_type,
            payload=payload,
        )
        
        # In a real implementation, this would persist to DB and/or publish to message bus
        logger.debug("Execution event", execution_id=execution_id, event_type=event_type, payload=payload)
    
    async def _fail_execution(self, execution_id: str, error: str) -> None:
        """Mark execution as failed."""
        db = next(get_db())
        try:
            execution = await self._get_execution(execution_id)
            if execution:
                execution.status = WorkflowExecutionStatus.FAILED
                execution.completed_at = datetime.now(timezone.utc)
                execution.error_message = error
                execution.error_code = "EXECUTION_FAILED"
                await db.commit()
        finally:
            await db.close()
    
    async def _complete_execution(self, execution_id: str) -> None:
        """Mark execution as completed successfully."""
        db = next(get_db())
        try:
            execution = await self._get_execution(execution_id)
            if execution:
                execution.status = WorkflowExecutionStatus.COMPLETED
                execution.completed_at = datetime.now(timezone.utc)
                await db.commit()
        finally:
            await db.close()
    
    async def _get_workflow(self, organization_id: str, workflow_id: str) -> Optional[Workflow]:
        """Get workflow by ID."""
        db = next(get_db())
        try:
            result = await db.execute(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.organization_id == organization_id,
                    Workflow.deleted_at.is_(None),
                )
            )
            return result.scalar_one_or_none()
        finally:
            await db.close()
    
    async def _get_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get execution by ID."""
        db = next(get_db())
        try:
            result = await db.execute(
                select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
            )
            return result.scalar_one_or_none()
        finally:
            await db.close()
    
    async def _get_workflow_version(self, version_id: str) -> Optional[WorkflowVersion]:
        """Get workflow version by ID."""
        db = next(get_db())
        try:
            result = await db.execute(
                select(WorkflowVersion).where(WorkflowVersion.id == version_id)
            )
            return result.scalar_one_or_none()
        finally:
            await db.close()
    
    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running execution."""
        context = self._active_executions.get(execution_id)
        if context:
            context.cancelled = True
            return True
        return False
    
    async def pause_execution(self, execution_id: str) -> bool:
        """Pause a running execution."""
        # Implementation for pause/resume would go here
        return False
    
    async def resume_execution(self, execution_id: str, resume_token: str) -> bool:
        """Resume a paused/waiting execution."""
        # Implementation for resume would go here
        return False


# Global runtime instance (initialized by worker)
_runtime: Optional[ExecutionRuntime] = None


def get_runtime() -> ExecutionRuntime:
    """Get the global runtime instance."""
    global _runtime
    if _runtime is None:
        raise RuntimeError("Runtime not initialized")
    return _runtime


def initialize_runtime(db_session: AsyncSession, worker_id: str = "runtime") -> ExecutionRuntime:
    """Initialize the global runtime."""
    global _runtime
    _runtime = ExecutionRuntime(db_session, worker_id)
    return _runtime