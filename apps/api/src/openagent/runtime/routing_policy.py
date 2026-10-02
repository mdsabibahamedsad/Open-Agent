"""Routing Policy Engine: Policy evaluation and enforcement for model routing."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from openagent.runtime.model_registry import ModelConfig, ModelAlias


class PolicyScope(str, enum.Enum):
    """Policy scope hierarchy."""
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    TEAM = "team"
    AGENT = "agent"
    WORKFLOW = "workflow"
    REQUEST = "request"


class PolicyAction(str, enum.Enum):
    """Policy action types."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class ProviderPolicy:
    """Provider-level policy."""
    allowed_providers: Set[str] = field(default_factory=set)
    blocked_providers: Set[str] = field(default_factory=set)
    require_approval_for: Set[str] = field(default_factory=set)


@dataclass
class ModelPolicy:
    """Model-level policy."""
    allowed_models: Set[str] = field(default_factory=set)
    blocked_models: Set[str] = field(default_factory=set)
    require_approval_for: Set[str] = field(default_factory=set)


@dataclass
class CapabilityPolicy:
    """Capability requirements."""
    required_capabilities: List[str] = field(default_factory=list)
    forbidden_capabilities: List[str] = field(default_factory=list)


@dataclass
class CostPolicy:
    """Cost constraints."""
    max_cost_per_request: Optional[float] = None
    max_cost_per_1k_tokens: Optional[float] = None
    max_monthly_cost: Optional[float] = None
    warn_at_cost: Optional[float] = None


@dataclass
class LatencyPolicy:
    """Latency constraints."""
    max_latency_ms: Optional[int] = None
    max_time_to_first_token_ms: Optional[int] = None
    latency_class: Optional[str] = None  # fast, medium, slow


@dataclass
class PrivacyPolicy:
    """Privacy and data residency requirements."""
    local_only: bool = False
    allowed_regions: List[str] = field(default_factory=list)
    blocked_regions: List[str] = field(default_factory=list)
    required_privacy_class: Optional[str] = None  # public, standard, confidential, restricted
    require_data_residency: bool = False


@dataclass
class RoutingPolicy:
    """Complete routing policy."""
    id: UUID = field(default_factory=lambda: uuid4())
    name: str = ""
    description: str = ""
    
    scope: str = "organization"  # platform, organization, team, agent, workflow, request
    scope_id: Optional[str] = None
    
    priority: int = 0  # Higher priority wins
    
    # Provider policies
    provider_policy: ProviderPolicy = field(default_factory=ProviderPolicy)
    
    # Model policies
    model_policy: ModelPolicy = field(default_factory=ModelPolicy)
    
    # Capability requirements
    capability_policy: CapabilityPolicy = field(default_factory=CapabilityPolicy)
    
    # Cost constraints
    cost_policy: CostPolicy = field(default_factory=CostPolicy)
    
    # Latency constraints
    latency_policy: LatencyPolicy = field(default_factory=LatencyPolicy)
    
    # Privacy requirements
    privacy_policy: PrivacyPolicy = field(default_factory=PrivacyPolicy)
    
    # Routing strategy
    strategy: str = "hybrid"  # fixed, capability_match, fallback_chain, cost_optimized, latency_optimized, quality_optimized, local_first, hybrid
    
    # Fallback chain
    fallback_models: List[str] = field(default_factory=list)
    
    # Model aliases
    model_aliases: Dict[str, str] = field(default_factory=dict)
    
    # Strategy-specific config
    strategy_config: Dict[str, Any] = field(default_factory=dict)
    
    # Enforcement
    enforce_capabilities: bool = True
    enforce_cost: bool = True
    enforce_latency: bool = True
    enforce_privacy: bool = True
    
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[str] = None
    is_active: bool = True
    version: int = 1
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


class RoutingPolicyEngine:
    """Engine for evaluating and enforcing routing policies."""
    
    def __init__(self):
        self._policies: Dict[UUID, RoutingPolicy] = {}
        self._policies_by_scope: Dict[str, List[UUID]] = {}
    
    def register(self, policy: RoutingPolicy) -> UUID:
        """Register a routing policy."""
        self._policies[policy.id] = policy
        
        if policy.scope not in self._policies_by_scope:
            self._policies_by_scope[policy.scope] = []
        if policy.id not in self._policies_by_scope[policy.scope]:
            self._policies_by_scope[policy.scope].append(policy.id)
        
        return policy.id
    
    def unregister(self, policy_id: UUID) -> bool:
        if policy_id not in self._policies:
            return False
        
        policy = self._policies.pop(policy_id)
        
        if policy.scope in self._policies_by_scope:
            if policy.id in self._policies_by_scope[policy.scope]:
                self._policies_by_scope[policy.scope].remove(policy_id)
        
        return True
    
    def get(self, policy_id: UUID) -> Optional[RoutingPolicy]:
        return self._policies.get(policy_id)
    
    def get_applicable_policies(
        self,
        organization_id: UUID,
        team_id: Optional[UUID] = None,
        agent_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> List[RoutingPolicy]:
        """Get all applicable policies ordered by priority."""
        applicable = []
        
        # Platform policies (always apply)
        for pid in self._policies_by_scope.get("platform", []):
            policy = self._policies.get(pid)
            if policy and policy.is_active:
                applicable.append(policy)
        
        # Organization policies
        for pid in self._policies_by_scope.get("organization", []):
            policy = self._policies.get(pid)
            if policy and policy.is_active and policy.scope_id == str(organization_id):
                applicable.append(policy)
        
        # Team policies
        if team_id:
            for pid in self._policies_by_scope.get("team", []):
                policy = self._policies.get(pid)
                if policy and policy.is_active and policy.scope_id == str(team_id):
                    applicable.append(policy)
        
        # Agent policies
        if agent_id:
            for pid in self._policies_by_scope.get("agent", []):
                policy = self._policies.get(pid)
                if policy and policy.is_active and policy.scope_id == agent_id:
                    applicable.append(policy)
        
        # Workflow policies
        if workflow_id:
            for pid in self._policies_by_scope.get("workflow", []):
                policy = self._policies.get(pid)
                if policy and policy.is_active and policy.scope_id == workflow_id:
                    applicable.append(policy)
        
        # Request policies (highest priority)
        for pid in self._policies_by_scope.get("request", []):
            policy = self._policies.get(pid)
            if policy and policy.is_active:
                applicable.append(policy)
        
        # Sort by priority (highest first)
        applicable.sort(key=lambda p: p.priority, reverse=True)
        return applicable
    
    def evaluate(
        self,
        organization_id: UUID,
        request: 'RoutingRequest',
        team_id: Optional[UUID] = None,
        agent_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> 'PolicyEvaluationResult':
        """Evaluate all applicable policies and return combined result."""
        
        policies = self.get_applicable_policies(
            organization_id=organization_id,
            team_id=team_id,
            agent_id=agent_id,
            workflow_id=workflow_id,
        )
        
        if not policies:
            return PolicyEvaluationResult(
                allowed=True,
                effective_policy=None,
                provider_policy=ProviderPolicy(),
                model_policy=ModelPolicy(),
                capability_policy=CapabilityPolicy(),
                cost_policy=CostPolicy(),
                latency_policy=LatencyPolicy(),
                privacy_policy=PrivacyPolicy(),
            )
        
        # Merge policies (highest priority wins for each attribute)
        merged = self._merge_policies(policies)
        
        return PolicyEvaluationResult(
            allowed=True,
            effective_policy=policies[0] if policies else None,
            provider_policy=merged.provider_policy,
            model_policy=merged.model_policy,
            capability_policy=merged.capability_policy,
            cost_policy=merged.cost_policy,
            latency_policy=merged.latency_policy,
            privacy_policy=merged.privacy_policy,
            strategy=merged.strategy,
            fallback_models=merged.fallback_models,
            model_aliases=merged.model_aliases,
        )
    
    def _merge_policies(self, policies: List[RoutingPolicy]) -> RoutingPolicy:
        """Merge multiple policies (highest priority wins)."""
        if not policies:
            return RoutingPolicy()
        
        # Start with lowest priority
        merged = policies[-1]
        
        for policy in reversed(policies[:-1]):
            # Merge each attribute (higher priority overrides)
            merged.provider_policy.allowed_providers.update(policy.provider_policy.allowed_providers)
            merged.provider_policy.blocked_providers.update(policy.provider_policy.blocked_providers)
            merged.provider_policy.require_approval_for.update(policy.provider_policy.require_approval_for)
            
            merged.model_policy.allowed_models.update(policy.model_policy.allowed_models)
            merged.model_policy.blocked_models.update(policy.model_policy.blocked_models)
            merged.model_policy.require_approval_for.update(policy.model_policy.require_approval_for)
            
            merged.capability_policy.required_capabilities.extend(
                c for c in policy.capability_policy.required_capabilities 
                if c not in merged.capability_policy.required_capabilities
            )
            merged.capability_policy.forbidden_capabilities.update(
                policy.capability_policy.forbidden_capabilities
            )
            
            if policy.cost_policy.max_cost_per_request is not None:
                if merged.cost_policy.max_cost_per_request is None or \
                   policy.cost_policy.max_cost_per_request < merged.cost_policy.max_cost_per_request:
                    merged.cost_policy.max_cost_per_request = policy.cost_policy.max_cost_per_request
            
            if policy.latency_policy.max_latency_ms is not None:
                if merged.latency_policy.max_latency_ms is None or \
                   policy.latency_policy.max_latency_ms < merged.latency_policy.max_latency_ms:
                    merged.latency_policy.max_latency_ms = policy.latency_policy.max_latency_ms
            
            if policy.privacy_policy.local_only:
                merged.privacy_policy.local_only = True
            
            # Strategy: use highest priority
            if policy.priority > merged.priority:
                merged.strategy = policy.strategy
                merged.strategy_config = policy.strategy_config
                merged.fallback_models = policy.fallback_models
                merged.model_aliases = policy.model_aliases
        
        return merged


@dataclass
class PolicyEvaluationResult:
    """Result of policy evaluation."""
    allowed: bool
    effective_policy: Optional[RoutingPolicy]
    denial_reason: Optional[str] = None
    denial_code: Optional[str] = None
    
    # Effective policies
    provider_policy: ProviderPolicy = field(default_factory=ProviderPolicy)
    model_policy: ModelPolicy = field(default_factory=ModelPolicy)
    capability_policy: CapabilityPolicy = field(default_factory=CapabilityPolicy)
    cost_policy: CostPolicy = field(default_factory=CostPolicy)
    latency_policy: LatencyPolicy = field(default_factory=LatencyPolicy)
    privacy_policy: PrivacyPolicy = field(default_factory=PrivacyPolicy)
    
    # Strategy
    strategy: str = "hybrid"
    fallback_models: List[str] = field(default_factory=list)
    model_aliases: Dict[str, str] = field(default_factory=dict)
    
    # Denied items
    denied_providers: List[str] = field(default_factory=list)
    denied_models: List[str] = field(default_factory=list)


# Import required modules
import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from datetime import datetime, timezone