"""Agent Runtime models and state machines."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID


class AgentRunStatus(str, enum.Enum):
    """Agent execution lifecycle states."""
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    BUDGET_EXCEEDED = "budget_exceeded"


class AgentLoopState(str, enum.Enum):
    """Agent loop internal states."""
    IDLE = "idle"
    BUILDING_CONTEXT = "building_context"
    CALLING_MODEL = "calling_model"
    PARSING_RESPONSE = "parsing_response"
    EXECUTING_TOOL = "executing_tool"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_APPROVAL = "waiting_for_approval"  # MP19: human approval gate
    VALIDATING_OUTPUT = "validating_output"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# State transition rules
VALID_AGENT_RUN_TRANSITIONS: Dict[AgentRunStatus, Set[AgentRunStatus]] = {
    AgentRunStatus.QUEUED: {AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED},
    AgentRunStatus.RUNNING: {
        AgentRunStatus.WAITING,
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.TIMED_OUT,
        AgentRunStatus.PAUSED,
        AgentRunStatus.BUDGET_EXCEEDED,
    },
    AgentRunStatus.WAITING: {AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED},
    AgentRunStatus.PAUSED: {AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED},
    AgentRunStatus.SUCCEEDED: set(),
    AgentRunStatus.FAILED: set(),
    AgentRunStatus.CANCELLED: set(),
    AgentRunStatus.TIMED_OUT: set(),
    AgentRunStatus.BUDGET_EXCEEDED: set(),
}

VALID_LOOP_TRANSITIONS: Dict[AgentLoopState, Set[AgentLoopState]] = {
    AgentLoopState.IDLE: {AgentLoopState.BUILDING_CONTEXT, AgentLoopState.CANCELLED},
    AgentLoopState.BUILDING_CONTEXT: {AgentLoopState.CALLING_MODEL, AgentLoopState.CANCELLED},
    AgentLoopState.CALLING_MODEL: {AgentLoopState.PARSING_RESPONSE, AgentLoopState.FAILED, AgentLoopState.CANCELLED},
    AgentLoopState.PARSING_RESPONSE: {AgentLoopState.EXECUTING_TOOL, AgentLoopState.VALIDATING_OUTPUT, AgentLoopState.COMPLETED, AgentLoopState.FAILED, AgentLoopState.CANCELLED},
    AgentLoopState.EXECUTING_TOOL: {AgentLoopState.WAITING_FOR_TOOL, AgentLoopState.WAITING_FOR_APPROVAL, AgentLoopState.FAILED, AgentLoopState.CANCELLED},
    AgentLoopState.WAITING_FOR_TOOL: {AgentLoopState.PARSING_RESPONSE, AgentLoopState.FAILED, AgentLoopState.CANCELLED},
    AgentLoopState.WAITING_FOR_APPROVAL: {AgentLoopState.EXECUTING_TOOL, AgentLoopState.FAILED, AgentLoopState.CANCELLED},
    AgentLoopState.VALIDATING_OUTPUT: {AgentLoopState.COMPLETED, AgentLoopState.FAILED, AgentLoopState.CANCELLED},
    AgentLoopState.COMPLETED: set(),
    AgentLoopState.FAILED: set(),
    AgentLoopState.CANCELLED: set(),
}


def can_transition_agent_run(from_status: AgentRunStatus, to_status: AgentRunStatus) -> bool:
    """Check if an agent run status transition is valid."""
    return to_status in VALID_AGENT_RUN_TRANSITIONS.get(from_status, set())


def can_transition_loop(from_state: AgentLoopState, to_state: AgentLoopState) -> bool:
    """Check if an agent loop state transition is valid."""
    return to_state in VALID_LOOP_TRANSITIONS.get(from_state, set())


@dataclass
class AgentStep:
    """A single step in the agent execution loop."""
    step_number: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    model_request: Optional[Dict[str, Any]] = None
    model_response: Optional[Dict[str, Any]] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    status: str = "pending"  # pending, running, succeeded, failed
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentBudget:
    """Budget limits for agent execution."""
    max_steps: int = 10
    max_tool_calls: int = 20
    max_duration_seconds: int = 300
    max_output_tokens: int = 4096
    max_total_tokens: int = 8192
    
    # Current usage tracking
    steps_used: int = 0
    tool_calls_used: int = 0
    duration_seconds: float = 0.0
    output_tokens_used: int = 0
    total_tokens_used: int = 0


@dataclass
class AgentCapabilities:
    """Capabilities granted to the agent."""
    model_invoke: bool = True
    tool_invoke: bool = True
    network_request: bool = False
    browser_control: bool = False
    code_execution: bool = False
    filesystem_read: bool = False
    filesystem_write: bool = False
    credential_use: bool = True
    memory_read: bool = False
    memory_write: bool = False
    mcp_invoke: bool = False


@dataclass
class AgentConfig:
    """Agent configuration from the agent version."""
    name: str
    description: Optional[str] = None
    instructions: str = ""
    model: str = "gpt-4"
    model_config: Dict[str, Any] = field(default_factory=dict)
    tools: List[Dict[str, Any]] = field(default_factory=list)
    output_config: Dict[str, Any] = field(default_factory=dict)
    budget: AgentBudget = field(default_factory=AgentBudget)
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentLoopContext:
    """Context for the agent execution loop."""
    execution_id: str
    agent_id: str
    agent_version_id: str
    organization_id: str
    workflow_execution_id: Optional[str] = None
    node_execution_id: Optional[str] = None
    
    # Input from workflow
    input: Dict[str, Any] = field(default_factory=dict)
    
    # Agent configuration
    config: Optional[AgentConfig] = None
    
    # Runtime state
    budget: AgentBudget = field(default_factory=AgentBudget)
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    current_step: int = 0
    max_steps: int = 10
    
    # Execution state
    steps: List[AgentStep] = field(default_factory=list)
    current_state: AgentLoopState = AgentLoopState.IDLE
    status: AgentRunStatus = AgentRunStatus.QUEUED
    cancelled: bool = False
    cancelled_reason: Optional[str] = None
    
    # Context for model
    system_prompt: str = ""
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)
    
    # Tool execution
    pending_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    
    # Output
    final_output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # Timing
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    step_started_at: Optional[datetime] = None
    
    # Cancellation
    cancelled: bool = False
    cancelled_reason: Optional[str] = None


@dataclass
class AgentRunResult:
    """Result of an agent run."""
    status: AgentRunStatus
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    steps: List[AgentStep] = field(default_factory=list)
    total_steps: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# Import required modules
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Dict
from uuid import UUID
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID