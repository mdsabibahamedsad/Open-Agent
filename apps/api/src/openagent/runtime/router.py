"""Model Router: Main routing service."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

import structlog

from openagent.runtime.model_registry import (
    ModelConfig,
    ModelAlias,
    model_registry,
)
from openagent.runtime.model_adapters import model_provider_registry, ModelProvider
from openagent.runtime.routing_policy import (
    RoutingPolicyEngine,
    PolicyEvaluationResult,
)
from openagent.runtime.router import (
    ModelRoutingRequest,
    RoutingCandidate,
    RoutingResult,
    ModelRoutingRequest,
    RoutingStrategy,
    CapabilityMatchStrategy,
    routing_strategy_registry,
    ModelConfig,
)
from openagent.runtime.model_registry import model_registry
from openagent.runtime.routing_policy import RoutingPolicyEngine
from openagent.runtime.model_adapters import model_provider_registry, ModelProvider
from openagent.runtime.engine import expression_engine
from openagent.runtime.routing_policy import RoutingPolicyEngine

logger = structlog.get_logger("runtime.router")


@dataclass
class ModelRouter:
    """Main model router service."""
    
    def __init__(
        self,
        policy_engine: Optional[RoutingPolicyEngine] = None,
        model_registry: Optional['ModelRegistry'] = None,
        provider_registry: Optional['ModelProviderRegistry'] = None,
        strategy_registry: Optional['RoutingStrategyRegistry'] = None,
    ):
        self.policy_engine = policy_engine or RoutingPolicyEngine()
        self.model_registry = model_registry or model_registry
        self.provider_registry = provider_registry or model_provider_registry
        self.strategy_registry = routing_strategy_registry
        
        # Metrics
        self._metrics = {
            "total_requests": 0,
            "successful_routes": 0,
            "failed_routes": 0,
            "fallback_used": 0,
            "total_latency_ms": 0,
        }
        
        # Caches
        self._candidate_cache: Dict[str, List[RoutingCandidate]] = {}
        self._cache_ttl = 300  # 5 minutes
    
    async def route(
        self,
        request: ModelRoutingRequest,
        organization_id: UUID,
        team_id: Optional[UUID] = None,
        agent_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> RoutingResult:
        """
        Route a request to the best model.
        
        This is the main entry point for model routing.
        """
        start_time = time.time()
        request_id = request.request_id
        
        self._metrics["total_requests"] += 1
        
        try:
            # 1. Evaluate policies
            policy_engine = RoutingPolicyEngine()
            policy_result = self.policy_engine.evaluate(
                organization_id=organization_id,
                request=request,
                team_id=team_id,
                agent_id=agent_id,
                workflow_id=workflow_id,
            )
            
            if not policy_result.allowed:
                return RoutingResult(
                    success=False,
                    error="Request blocked by policy",
                    error_code="POLICY_BLOCKED",
                    request_id=request_id,
                    routing_reason_codes=[policy_result.denial_code] if policy_result.denial_code else [],
                )
            
            # 2. Build candidate set
            candidates = await self._build_candidates(
                request=request,
                policy_result=policy_result,
                organization_id=organization_id,
            )
            
            if not candidates:
                return RoutingResult(
                    success=False,
                    error="No compatible models found",
                    error_code="NO_COMPATIBLE_MODEL",
                    request_id=request_id,
                    candidate_count=0,
                    filtered_count=0,
                )
            
            # 3. Apply routing strategy
            strategy_name = policy_result.strategy
            strategy = routing_strategy_registry.get(strategy_name)
            
            if not strategy:
                logger.warning("Strategy not found, using hybrid", strategy=strategy_name)
                strategy = routing_strategy_registry.get("hybrid")
            
            # 4. Execute routing strategy
            selected = await self._execute_strategy(
                request=request,
                candidates=policy_result.filtered_candidates,
                strategy=policy_result.strategy,
                policy_result=policy_result,
            )
            
            if not selected:
                # Try fallback chain
                return await self._try_fallback_chain(
                    request=request,
                    candidates=policy_result.filtered_candidates,
                    policy_result=policy_result,
                    request_id=request_id,
                )
            
            # 5. Estimate metrics
            estimated_cost = self._estimate_cost(selected.model, request)
            estimated_latency = self._estimate_latency(selected.model, request)
            
            # 6. Record metrics
            self._metrics["successful_routes"] += 1
            self._metrics["total_latency_ms"] += int((time.time() - start_time) * 1000)
            
            return RoutingResult(
                success=True,
                selected_model=selected.model,
                selected_provider=selected.provider,
                fallback_models=self._build_fallback_chain(policy_result, request),
                strategy_used=policy_result.strategy,
                candidate_count=len(policy_result.filtered_candidates),
                filtered_count=len(policy_result.filtered_candidates) - len(selected),
                estimated_cost=estimated_cost,
                estimated_latency_ms=estimated_latency,
                estimated_tokens=self._estimate_tokens(request),
                routing_reason_codes=selected.match_reasons,
                request_id=request_id,
                trace={
                    "strategy": policy_result.strategy,
                    "candidates_evaluated": len(policy_result.filtered_candidates),
                    "policy_evaluation_ms": 0,
                    "routing_ms": 0,
                },
            )
            
        except Exception as e:
            logger.error("Routing failed", request_id=request_id, error=str(e))
            self._metrics["failed_routes"] += 1
            
            return RoutingResult(
                success=False,
                error=str(e),
                error_code="ROUTING_ERROR",
                request_id=request_id,
            )
    
    async def _build_candidates(
        self,
        request: ModelRoutingRequest,
        policy_result: Any,
        organization_id: UUID,
    ) -> List[RoutingCandidate]:
        """Build candidate models from registry."""
        # Get all models
        all_models = model_registry.list(
            provider_id=None,
            enabled_only=True,
        )
        
        # Apply policy filters
        filtered = []
        for model in all_models:
            # Check if provider is allowed
            if policy_result.provider_policy.blocked_providers:
                if model.provider_id in policy_result.provider_policy.blocked_providers:
                    continue
            
            if policy_result.provider_policy.allowed_providers:
                if model.provider_id not in policy_result.provider_policy.allowed_providers:
                    continue
            
            # Check model policy
            if model.id in policy_result.model_policy.blocked_models:
                continue
            
            if policy_result.model_policy.allowed_models:
                if model.id not in policy_result.model_policy.allowed_models:
                    continue
            
            # Check capabilities
            model_caps = model.capabilities
            missing = []
            for cap in request.required_capabilities:
                if not getattr(model.capabilities, cap, False):
                    missing.append(cap)
            
            if missing:
                continue
            
            # Check context window
            if request.context_tokens > 0:
                if model.context_window < request.context_tokens:
                    continue
            
            # Check cost
            if request.max_cost_per_request:
                estimated = self._estimate_cost(model, request)
                if estimated > request.max_cost_per_request:
                    continue
            
            # Check latency
            if request.max_latency_ms:
                estimated_lat = self._estimate_latency(model, request)
                if estimated_lat > request.max_latency_ms:
                    continue
            
            # Check privacy
            if request.local_only and not model.local_only:
                continue
            
            if request.privacy_mode != "standard":
                privacy_order = {"public": 0, "standard": 1, "confidential": 2, "restricted": 3}
                model_level = {"public": 0, "standard": 1, "confidential": 2, "restricted": 3}.get(
                    getattr(model, 'privacy_class', 'standard'), 1)
                request_level = {"standard": 1, "confidential": 2, "restricted": 3}.get(request.privacy_mode, 1)
                if model_level < request_level:
                    continue
            
            # Check health
            if not model.enabled or model.status != "enabled":
                continue
            
            # Get provider
            provider = model_provider_registry.get(model.provider_id)
            if not provider:
                continue
            
            # Check availability
            healthy = await self._check_provider_health(provider)
            
            filtered.append(RoutingCandidate(
                model=model,
                provider=provider,
                match_reasons=["passed all filters"],
            ))
        
        return filtered
    
    async def _execute_strategy(
        self,
        request: ModelRoutingRequest,
        candidates: List[RoutingCandidate],
        strategy_name: str,
        policy_result: Any,
    ) -> Optional[Any]:
        """Execute routing strategy."""
        strategy = routing_strategy_registry.get(strategy_name)
        if not strategy:
            logger.warning("Strategy not found, using hybrid", strategy=strategy_name)
            strategy = routing_strategy_registry.get("hybrid")
        
        if not strategy:
            return None
        
        # Create a mock policy result for strategy
        class MockPolicyResult:
            def __init__(self, pr):
                self.strategy = pr.strategy
                self.fallback_models = pr.fallback_models
                self.model_policy = pr.model_policy
                self.cost_policy = pr.cost_policy
                self.latency_policy = pr.latency_policy
        
        mock_result = MockPolicyResult(policy_result)
        return await strategy.select(request, candidates, mock_result)
    
    async def _try_fallback_chain(
        self,
        request: ModelRoutingRequest,
        candidates: List[Any],
        policy_result: Any,
        request_id: str,
    ) -> RoutingResult:
        """Try fallback chain if primary selection failed."""
        fallback_models = policy_result.fallback_models
        
        for model_id in fallback_models:
            # Find in candidates
            for c in candidates:
                if c.model.id == model_id or c.model.model_identifier == model_id:
                    if c.is_available and c.health_status == "healthy":
                        estimated_cost = self._estimate_cost(c.model, request)
                        estimated_latency = self._estimate_latency(c.model, request)
                        
                        return RoutingResult(
                            success=True,
                            selected_model=c.model,
                            selected_provider=c.provider,
                            fallback_models=[],
                            strategy_used="fallback_chain",
                            candidate_count=len(candidates),
                            filtered_count=0,
                            estimated_cost=estimated_cost,
                            estimated_latency_ms=estimated_latency,
                            estimated_tokens=self._estimate_tokens(request),
                            routing_reason_codes=[f"fallback:{c.model.model_identifier}"],
                            request_id=request_id,
                        )
        
        return RoutingResult(
            success=False,
            error="All fallbacks exhausted",
            error_code="ALL_FALLBACKS_FAILED",
            request_id=request_id,
            candidate_count=len(candidates),
        )
    
    def _build_fallback_chain(self, policy_result: Any, request: Any) -> List[Tuple[str, Any]]:
        """Build fallback chain from policy."""
        fallbacks = []
        for model_id in policy_result.fallback_models:
            # Resolve model
            model = model_registry.get_by_identifier(model_id) or model_registry.get(model_id)
            if model:
                provider = model_provider_registry.get(model.provider_id)
                if provider:
                    fallbacks.append((model_id, provider))
        return fallbacks
    
    def _estimate_cost(self, model: Any, request: ModelRoutingRequest) -> float:
        """Estimate cost for a request."""
        input_tokens = request.context_tokens
        output_tokens = request.estimated_output_tokens
        
        input_cost = (input_tokens / 1000) * model.input_cost
        output_cost = (output_tokens / 1000) * model.output_cost
        
        return input_cost + output_cost
    
    def _estimate_latency(self, model: Any, request: ModelRoutingRequest) -> int:
        """Estimate latency in ms."""
        # Simple estimation based on model class and tokens
        base_latency = {
            "fast": 500,
            "medium": 1500,
            "slow": 5000,
        }.get(model.latency_class, 1500)
        
        # Add token-based latency
        token_latency = (request.context_tokens + request.estimated_output_tokens) / 1000 * 10
        
        return base_latency + int(token_latency)
    
    def _estimate_tokens(self, request: ModelRoutingRequest) -> int:
        return request.context_tokens + request.estimated_output_tokens
    
    def _build_fallback_chain(self, policy_result: Any, request: ModelRoutingRequest) -> List[Tuple[str, Any]]:
        """Build fallback chain from policy."""
        fallbacks = []
        for model_id in policy_result.fallback_models:
            model = model_registry.get_by_identifier(model_id) or model_registry.get(model_id)
            if model:
                provider = model_provider_registry.get(model.provider_id)
                if provider:
                    fallbacks.append((model_id, provider))
        return fallbacks
    
    def _estimate_tokens(self, request: ModelRoutingRequest) -> int:
        return request.context_tokens + request.estimated_output_tokens
    
    def _check_provider_health(self, provider) -> bool:
        """Check if provider is healthy."""
        # In real implementation, check health endpoint
        return True
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get router metrics."""
        return self._metrics.copy()
    
    def get_candidates(
        self,
        request: ModelRoutingRequest,
        organization_id: UUID,
    ) -> List[RoutingCandidate]:
        """Get candidate models for a request (for testing/debugging)."""
        # This would be called internally by route()
        pass


# Global router instance
_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def initialize_router(
    policy_engine: Optional[RoutingPolicyEngine] = None,
    model_registry: Optional['ModelRegistry'] = None,
    provider_registry: Optional['ModelProviderRegistry'] = None,
    strategy_registry: Optional['RoutingStrategyRegistry'] = None,
) -> ModelRouter:
    global _router
    _router = ModelRouter(
        policy_engine=policy_engine,
        model_registry=model_registry,
        provider_registry=provider_registry,
        strategy_registry=strategy_registry,
    )
    return _router


# Import required modules
import time
import uuid
import structlog
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from datetime import datetime, timezone

logger = structlog.get_logger("runtime.router")