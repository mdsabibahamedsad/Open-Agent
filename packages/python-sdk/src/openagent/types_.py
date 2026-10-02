"""Shared data shapes returned by the OpenAgent API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict


@dataclass
class PaginatedResult:
    """One page of a collection plus cursor metadata for iteration."""

    items: List[Any] = field(default_factory=list)
    total: Optional[int] = None
    next_cursor: Optional[str] = None
    has_more: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.items)


@dataclass
class Agent:
    id: str = ""
    name: str = ""
    description: Optional[str] = None
    model: Optional[str] = None
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRun:
    id: str = ""
    agent_id: str = ""
    status: str = ""
    input: Optional[Any] = None
    output: Optional[Any] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    id: str = ""
    name: str = ""
    description: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Workflow:
    id: str = ""
    name: str = ""
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowExecution:
    id: str = ""
    workflow_id: str = ""
    status: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Connector:
    id: str = ""
    name: str = ""
    connector_type: Optional[str] = None
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPServer:
    id: str = ""
    name: str = ""
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Skill:
    id: str = ""
    name: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtensionManifest:
    name: str = ""
    version: str = ""
    kind: Optional[str] = None
    description: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Extension:
    id: str = ""
    name: str = ""
    kind: Optional[str] = None
    status: Optional[str] = None
    manifest: Optional[ExtensionManifest] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtensionVersion:
    id: str = ""
    extension_id: str = ""
    version: str = ""
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Deployment:
    id: str = ""
    extension_id: Optional[str] = None
    environment: Optional[str] = None
    status: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Project:
    id: str = ""
    name: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    id: str = ""
    event: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Webhook:
    id: str = ""
    url: str = ""
    events: List[str] = field(default_factory=list)
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Model:
    id: str = ""
    name: str = ""
    provider: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Evaluation:
    id: str = ""
    name: str = ""
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Sandbox:
    id: str = ""
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Approval:
    id: str = ""
    subject: Optional[str] = None
    action: Optional[str] = None
    status: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Listing:
    id: str = ""
    name: str = ""
    kind: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Publisher:
    id: str = ""
    name: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Review:
    id: str = ""
    listing_id: str = ""
    rating: Optional[int] = None
    body: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Invoice:
    id: str = ""
    status: Optional[str] = None
    amount: Optional[Any] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class CreateAgentRequest(TypedDict, total=False):
    name: str
    description: str
    model: str
    instructions: str


class CreateExtensionRequest(TypedDict, total=False):
    name: str
    kind: str
    description: str
    manifest: Dict[str, Any]


__all__ = [
    "PaginatedResult",
    "Agent",
    "AgentRun",
    "Tool",
    "Workflow",
    "WorkflowExecution",
    "Connector",
    "MCPServer",
    "Skill",
    "ExtensionManifest",
    "Extension",
    "ExtensionVersion",
    "Deployment",
    "Project",
    "Event",
    "Webhook",
    "Model",
    "Evaluation",
    "Sandbox",
    "Approval",
    "Listing",
    "Publisher",
    "Review",
    "Invoice",
    "CreateAgentRequest",
    "CreateExtensionRequest",
]
