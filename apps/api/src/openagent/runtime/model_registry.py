"""Model Registry: Central registry for model configurations and capabilities."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from openagent.runtime.model_adapters import model_provider_registry


class ModelCapability(str, enum.Enum):
    """Model capabilities."""
    TEXT = "text"
    VISION = "vision"
    AUDIO = "audio"
    VIDEO = "video"
    TOOLS = "tools"
    STRUCTURED_OUTPUT = "structured_output"
    STREAMING = "streaming"
    REASONING = "reasoning"
    EMBEDDINGS = "embeddings"
    CODE_GENERATION = "code_generation"
    LONG_CONTEXT = "long_context"
    LOCAL_EXECUTION = "local_execution"
    JSON_MODE = "json_mode"


class ModelStatus(str, enum.Enum):
    """Model status."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"
    INTERNAL = "internal"


class LatencyClass(str, enum.Enum):
    """Latency classification."""
    FAST = "fast"  # < 1s
    MEDIUM = "medium"  # 1-5s
    SLOW = "slow"  # > 5s


class QualityClass(str, enum.Enum):
    """Quality classification."""
    STANDARD = "standard"
    HIGH = "high"
    PREMIUM = "premium"


class PrivacyClass(str, enum.Enum):
    """Data privacy classification."""
    PUBLIC = "public"
    STANDARD = "standard"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass
class ModelCapabilities:
    """Model capabilities and features."""
    text: bool = True
    vision: bool = False
    audio: bool = False
    video: bool = False
    tools: bool = False
    structured_output: bool = False
    streaming: bool = True
    reasoning: bool = False
    embeddings: bool = False
    code_generation: bool = False
    long_context: bool = False  # > 32k tokens
    local_execution: bool = False
    json_mode: bool = False


@dataclass
class ModelConfig:
    """Model configuration."""
    id: UUID
    provider_id: str
    model_identifier: str
    display_name: str
    description: str = ""
    
    enabled: bool = True
    is_default: bool = False
    
    # Capabilities
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    
    # Context window
    context_window: int = 4096
    max_output_tokens: int = 4096
    
    # Cost (per 1k tokens in USD)
    input_cost: float = 0.0
    output_cost: float = 0.0
    cached_input_cost: float = 0.0
    
    # Performance
    latency_class: str = "medium"  # fast, medium, slow
    quality_class: str = "standard"  # standard, high, premium
    
    # Regional/Privacy
    region: str = "global"
    data_residency: str = "global"
    local_only: bool = False
    privacy_class: str = "standard"  # public, standard, confidential, restricted
    
    # Metadata
    status: str = "enabled"  # enabled, disabled, deprecated, internal
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Version tracking
    version: str = "1.0"
    deprecated_at: Optional[datetime] = None
    
    # Model identifier for API calls
    model_identifier: str = ""
    
    # Default parameters
    default_temperature: float = 0.7
    default_max_tokens: int = 4096
    default_top_p: float = 1.0
    
    # Supported features
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_json_mode: bool = False
    supports_system_prompt: bool = True
    supports_parallel_tools: bool = False
    supports_parallel_tool_calls: bool = False
    max_tool_calls: int = 0
    
    # Vision/Audio/Video
    supports_text: bool = True
    supports_image: bool = False
    supports_audio: bool = False
    supports_video: bool = False
    
    # Embeddings/Reasoning
    supports_embeddings: bool = False
    supports_reasoning: bool = False
    supports_code_generation: bool = False
    
    # Local execution
    local_only: bool = False
    privacy_class: str = "standard"


@dataclass
class ModelAlias:
    """Model alias for logical model names."""
    id: UUID
    alias: str
    model_id: UUID
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Resolution
    resolution_strategy: str = "best_match"  # best_match, exact, latest
    fallback_model_id: Optional[UUID] = None


@dataclass
class ModelUsageRecord:
    """Model usage record for cost/latency tracking."""
    id: UUID
    model_id: UUID
    organization_id: UUID
    provider_id: str
    model_identifier: str
    
    # Usage
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    total_tokens: int = 0
    
    # Cost (in USD)
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    
    # Latency (ms)
    latency_ms: int = 0
    time_to_first_token_ms: int = 0
    
    # Metadata
    status: str = "success"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    # Context
    request_id: Optional[str] = None
    execution_id: Optional[str] = None
    agent_run_id: Optional[str] = None
    user_id: Optional[str] = None
    
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ModelRegistry:
    """Central registry for model configurations."""
    
    def __init__(self):
        self._models: Dict[UUID, ModelConfig] = {}
        self._models_by_provider: Dict[str, List[UUID]] = {}
        self._models_by_identifier: Dict[str, UUID] = {}
        self._aliases: Dict[str, UUID] = {}
        self._aliases_reverse: Dict[UUID, List[UUID]] = {}
        self._initialized = False
    
    def register(self, config: ModelConfig) -> UUID:
        """Register a model configuration."""
        if config.id in self._models:
            raise ValueError(f"Model with id {config.id} already exists")
        
        self._models[config.id] = config
        
        if config.provider_id not in self._models_by_provider:
            self._models_by_provider[config.provider_id] = []
        self._models_by_provider[config.provider_id].append(config.id)
        
        if config.model_identifier:
            self._models_by_identifier[config.model_identifier] = config.id
        
        return config.id
    
    def unregister(self, model_id: UUID) -> bool:
        """Unregister a model."""
        if model_id not in self._models:
            return False
        
        model = self._models.pop(model_id)
        
        if model.provider_id in self._models_by_provider:
            self._models_by_provider[model.provider_id] = [
                mid for mid in self._models_by_provider[model.provider_id]
                if mid != model_id
            ]
        
        if model.model_identifier in self._models_by_identifier:
            del self._models_by_identifier[model.model_identifier]
        
        # Remove aliases
        for alias, mid in list(self._aliases.items()):
            if mid == model_id:
                del self._aliases[alias]
        
        if model_id in self._aliases_reverse:
            del self._aliases_reverse[model_id]
        
        return True
    
    def get(self, model_id: UUID) -> Optional[ModelConfig]:
        """Get model by ID."""
        return self._models.get(model_id)
    
    def get_by_identifier(self, identifier: str) -> Optional[ModelConfig]:
        """Get model by provider identifier."""
        model_id = self._models_by_identifier.get(identifier)
        if model_id:
            return self._models.get(model_id)
        return None
    
    def get_by_alias(self, alias: str) -> Optional[ModelConfig]:
        """Get model by alias."""
        model_id = self._aliases.get(alias)
        if model_id:
            return self._models.get(model_id)
        return None
    
    def list(self, 
             provider_id: Optional[str] = None,
             enabled_only: bool = True,
             capabilities: Optional[List[str]] = None,
             status: Optional[str] = None) -> List[ModelConfig]:
        """List models with optional filters."""
        models = list(self._models.values())
        
        if provider_id:
            models = [m for m in models if m.provider_id == provider_id]
        
        if enabled_only:
            models = [m for m in models if m.enabled and m.status == "enabled"]
        
        if status:
            models = [m for m in models if m.status == status]
        
        if capabilities:
            models = [m for m in models if self._has_capabilities(m, capabilities)]
        
        return models
    
    def _has_capabilities(self, model: ModelConfig, capabilities: List[str]) -> bool:
        caps = model.capabilities
        for cap in capabilities:
            if not getattr(caps, cap, False):
                return False
        return True
    
    def filter_by_context_window(self, models: List[ModelConfig], required_tokens: int) -> List[ModelConfig]:
        """Filter models that can handle the required context window."""
        return [m for m in models if m.context_window >= required_tokens]
    
    def filter_by_cost(self, models: List[ModelConfig], max_cost_per_1k: float) -> List[ModelConfig]:
        """Filter models by maximum cost per 1k tokens."""
        return [
            m for m in models 
            if (m.input_cost + m.output_cost) / 2 <= max_cost_per_1k
        ]
    
    def filter_by_latency(self, models: List[ModelConfig], latency_class: str) -> List[ModelConfig]:
        """Filter models by latency class."""
        return [m for m in models if m.latency_class == latency_class]
    
    def filter_by_quality(self, models: List[ModelConfig], quality_class: str) -> List[ModelConfig]:
        """Filter models by quality class."""
        return [m for m in models if m.quality_class == quality_class]
    
    def filter_local_only(self, models: List[ModelConfig]) -> List[ModelConfig]:
        """Filter for local-only models."""
        return [m for m in models if m.local_only]
    
    def filter_by_privacy(self, models: List[ModelConfig], required_privacy: str) -> List[ModelConfig]:
        """Filter models by privacy class."""
        privacy_order = {"public": 0, "standard": 1, "confidential": 2, "restricted": 3}
        required_level = privacy_order.get(required_privacy, 1)
        return [
            m for m in models 
            if privacy_order.get(m.privacy_class, 1) >= required_level
        ]
    
    def register_alias(self, alias: str, model_id: UUID, description: str = "") -> ModelAlias:
        """Register a model alias."""
        if alias in self._aliases:
            raise ValueError(f"Alias '{alias}' already exists")
        
        if model_id not in self._models:
            raise ValueError(f"Model {model_id} not found")
        
        alias_obj = ModelAlias(
            id=uuid4(),
            alias=alias,
            model_id=model_id,
        )
        
        self._aliases[alias] = model_id
        if model_id not in self._aliases_reverse:
            self._aliases_reverse[model_id] = []
        self._aliases_reverse[model_id].append(alias_obj.id)
        
        return alias_obj
    
    def unregister_alias(self, alias: str) -> bool:
        if alias in self._aliases:
            model_id = self._aliases.pop(alias)
            if model_id in self._aliases_reverse:
                self._aliases_reverse[model_id] = [
                    aid for aid in self._aliases_reverse[model_id]
                    if aid != alias
                ]
            return True
        return False
    
    def resolve_alias(self, alias: str) -> Optional[UUID]:
        return self._aliases.get(alias)
    
    def get_aliases(self, model_id: UUID) -> List[ModelAlias]:
        alias_ids = self._aliases_reverse.get(model_id, [])
        return [ModelAlias(id=aid, alias=alias, model_id=model_id) 
                for alias, aid in self._aliases.items() if aid in alias_ids]


# Global model registry
model_registry = ModelRegistry()


def get_model_registry() -> ModelRegistry:
    return model_registry


# Import required modules
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from datetime import datetime, timezone