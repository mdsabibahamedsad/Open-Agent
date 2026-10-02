"""Model Router API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, HTTPException, status, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.session import get_db
from openagent.db.models import (
    ModelProvider as ModelProviderModel,
    ModelConfig as ModelConfigModel,
    ModelAlias as ModelAliasModel,
    RoutingPolicy as RoutingPolicyModel,
    ModelAlias as ModelAliasModel,
)
from openagent.db.models.base import Base
from openagent.db.session import get_db
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse
from openagent.api.dependencies import get_current_org_context, require_permission
from openagent.runtime.model_registry import model_registry, ModelConfig, ModelAlias
from openagent.runtime.routing_policy import RoutingPolicyEngine, RoutingPolicy
from openagent.runtime.router import ModelRouter, ModelRoutingRequest, RoutingResult, get_router, initialize_router
from openagent.runtime.model_registry import model_registry, ModelConfig, ModelAlias
from openagent.runtime.model_adapters import model_provider_registry
from openagent.runtime.routing_policy import RoutingPolicyEngine
from openagent.runtime.router import ModelRouter, ModelRoutingRequest, RoutingResult
from openagent.lib.api import toUserMessage

router = APIRouter(prefix="/api/v1", tags=["model-router"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ModelProviderCreate(BaseModel):
    provider_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    base_url: Optional[str] = None
    config: Dict[str, Any] = {}
    enabled: bool = True


class ModelProviderUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    base_url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class ModelProviderResponse(BaseModel):
    id: str
    provider_id: str
    name: str
    display_name: str
    description: Optional[str] = None
    base_url: Optional[str] = None
    config: Dict[str, Any] = {}
    enabled: bool = True
    status: str = "healthy"
    model_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ModelProviderListResponse(BaseModel):
    data: List[ModelProviderResponse]
    total: int
    page: int
    page_size: int


class ModelCreate(BaseModel):
    provider_id: str
    model_identifier: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    enabled: bool = True
    is_default: bool = False
    configuration: Dict[str, Any] = {}


class ModelUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None
    configuration: Optional[Dict[str, Any]] = None


class ModelResponse(BaseModel):
    id: str
    provider_id: str
    model_identifier: str
    display_name: str
    description: Optional[str] = None
    enabled: bool = True
    is_default: bool = False
    configuration: Dict[str, Any] = {}
    capabilities: Dict[str, Any] = {}
    input_cost: float = 0.0
    output_cost: float = 0.0
    context_window: int = 4096
    max_output_tokens: int = 4096
    latency_class: str = "medium"
    quality_class: str = "standard"
    status: str = "enabled"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ModelDetailResponse(ModelResponse):
    provider: Optional[ModelProviderResponse] = None
    usage_stats: Optional[Dict[str, Any]] = None
    health_status: Optional[str] = None


class ModelListResponse(BaseModel):
    data: List[ModelResponse]
    total: int
    page: int
    page_size: int


class ModelRouteRequest(BaseModel):
    task_type: str = "general_chat"
    required_capabilities: List[str] = []
    context_tokens: int = 0
    estimated_output_tokens: int = 1000
    max_cost_per_request: Optional[float] = None
    max_cost_per_1k_tokens: Optional[float] = None
    latency_target_ms: Optional[int] = None
    max_latency_ms: Optional[int] = None
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    preferred_model_id: Optional[str] = None
    streaming: bool = True
    local_only: bool = False
    privacy_mode: str = "standard"
    tool_calling: bool = False
    structured_output: bool = False
    streaming: bool = True
    preferred_model: Optional[str] = None
    preferred_model_id: Optional[str] = None
    model_alias: Optional[str] = None
    model_hint: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    workflow_id: Optional[str] = None
    execution_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    deterministic: bool = False
    seed: Optional[int] = None


class ModelRouteResponse(BaseModel):
    success: bool
    selected_model: Optional[dict] = None
    selected_provider: Optional[dict] = None
    fallback_models: List[dict] = []
    strategy_used: str = ""
    candidate_count: int = 0
    filtered_count: int = 0
    estimated_cost: float = 0.0
    estimated_latency_ms: int = 0
    estimated_tokens: int = 0
    routing_reason_codes: List[str] = []
    metadata: Dict[str, Any] = {}
    error: Optional[str] = None
    error_code: Optional[str] = None
    request_id: str = ""
    timestamp: datetime
    trace: Dict[str, Any] = {}


class ModelAliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=100)
    model_id: str
    description: Optional[str] = None


class ModelAliasResponse(BaseModel):
    id: str
    alias: str
    model_id: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RoutingPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    scope: str = Field(default="organization", pattern="^(platform|organization|team|agent|workflow|request)$")
    scope_id: Optional[str] = None
    priority: int = 0
    provider_policy: Dict[str, Any] = {}
    model_policy: Dict[str, Any] = {}
    capability_policy: Dict[str, Any] = {}
    cost_policy: Dict[str, Any] = {}
    latency_policy: Dict[str, Any] = {}
    privacy_policy: Dict[str, Any] = {}
    strategy: str = "hybrid"
    fallback_models: List[str] = []
    model_aliases: Dict[str, str] = {}
    strategy_config: Dict[str, Any] = {}


class RoutingPolicyResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    scope: str
    scope_id: Optional[str] = None
    priority: int = 0
    provider_policy: Dict[str, Any] = {}
    model_policy: Dict[str, Any] = {}
    capability_policy: Dict[str, Any] = {}
    cost_policy: Dict[str, Any] = {}
    latency_policy: Dict[str, Any] = {}
    privacy_policy: Dict[str, Any] = {}
    strategy: str = "hybrid"
    fallback_models: List[str] = []
    model_aliases: Dict[str, str] = {}
    strategy_config: Dict[str, Any] = {}
    enforce_capabilities: bool = True
    enforce_cost: bool = True
    enforce_latency: bool = True
    enforce_privacy: bool = True
    is_active: bool = True
    version: int = 1
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_provider_or_404(db: AsyncSession, organization_id: UUID, provider_id: str):
    result = await db.execute(
        select(ModelProviderModel).where(
            ModelProviderModel.provider_id == provider_id,
            ModelProviderModel.organization_id == organization_id,
        )
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Provider not found", "code": "PROVIDER_NOT_FOUND"},
        )
    return provider


# ---------------------------------------------------------------------------
# Provider Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/organizations/{organization_id}/providers",
    response_model=ModelProviderResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def create_provider(
    request: Request,
    organization_id: UUID,
    data: ModelProviderCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a model provider."""
    await require_permission("providers:create")(request, db)
    
    existing = await db.execute(
        select(ModelProviderModel).where(
            ModelProviderModel.provider_id == data.provider_id,
            ModelProviderModel.organization_id == organization_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"Provider '{data.provider_id}' already exists", "code": "PROVIDER_EXISTS"},
        )
    
    provider = ModelProviderModel(
        organization_id=organization_id,
        provider_id=data.provider_id,
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        base_url=data.base_url,
        config=data.config,
        enabled=data.enabled,
    )
    
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    
    return ModelProviderResponse.model_validate(provider)


@router.get(
    "/organizations/{organization_id}/providers",
    response_model=ModelProviderListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_providers(
    request: Request,
    organization_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    enabled: Optional[bool] = Query(None),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List model providers."""
    await require_permission("providers:read")(request, db)
    
    query = select(ModelProviderModel).where(
        ModelProviderModel.organization_id == organization_id,
    )
    
    if enabled is not None:
        query = query.where(ModelProviderModel.enabled == enabled)
    
    total = (await db.execute(
        select(func.count(ModelProviderModel.id)).where(
            ModelProviderModel.organization_id == organization_id,
            *([ModelProviderModel.enabled == enabled] if enabled is not None else [])
        )
    )).scalar_one()
    
    query = query.order_by(ModelProviderModel.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
    providers = list((await db.execute(query)).scalars().all())
    
    return ModelProviderListResponse(
        data=[ModelProviderResponse.model_validate(p) for p in providers],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/organizations/{organization_id}/providers/{provider_id}",
    response_model=ModelProviderResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_provider(
    request: Request,
    organization_id: UUID,
    provider_id: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get provider details."""
    await require_permission("providers:read")(request, db)
    provider = await _get_provider_or_404(db, organization_id, provider_id)
    
    # Count models
    model_count = (await db.execute(
        select(func.count(ModelConfigModel.id)).where(
            ModelConfigModel.provider_id == provider.provider_id,
            ModelConfigModel.organization_id == organization_id,
        )
    )).scalar_one()
    
    resp = ModelProviderResponse.model_validate(provider)
    resp.model_count = model_count
    return resp


@router.patch(
    "/organizations/{organization_id}/providers/{provider_id}",
    response_model=ModelProviderResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def update_provider(
    request: Request,
    organization_id: UUID,
    provider_id: str,
    data: ModelProviderUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update a provider."""
    await require_permission("providers:update")(request, db)
    provider = await _get_provider_or_404(db, organization_id, provider_id)
    
    if data.name is not None:
        provider.name = data.name
    if data.display_name is not None:
        provider.display_name = data.display_name
    if data.description is not None:
        provider.description = data.description
    if data.base_url is not None:
        provider.base_url = data.base_url
    if data.config is not None:
        provider.config = data.config
    if data.enabled is not None:
        provider.enabled = data.enabled
    
    await db.commit()
    await db.refresh(provider)
    return ModelProviderResponse.model_validate(provider)


@router.delete(
    "/organizations/{organization_id}/providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_provider(
    request: Request,
    organization_id: UUID,
    provider_id: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete a provider."""
    await require_permission("providers:delete")(request, db)
    provider = await _get_provider_or_404(db, organization_id, provider_id)
    
    # Check for associated models
    model_count = (await db.execute(
        select(func.count(ModelConfigModel.id)).where(
            ModelConfigModel.provider_id == provider.provider_id,
            ModelConfigModel.organization_id == organization_id,
        )
    )).scalar_one()
    
    if model_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Cannot delete provider with associated models", "code": "PROVIDER_HAS_MODELS"},
        )
    
    await db.delete(provider)
    await db.commit()


# ---------------------------------------------------------------------------
# Model Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/organizations/{organization_id}/models",
    response_model=ModelResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def create_model(
    request: Request,
    organization_id: UUID,
    data: ModelCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a model configuration."""
    await require_permission("models:create")(request, db)
    
    # Verify provider exists
    provider = await _get_provider_or_404(db, organization_id, data.provider_id)
    
    # Check for duplicate
    existing = await db.execute(
        select(ModelConfigModel).where(
            ModelConfigModel.provider_id == data.provider_id,
            ModelConfigModel.model_identifier == data.model_identifier,
            ModelConfigModel.organization_id == organization_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"Model '{data.model_identifier}' already exists for provider", "code": "MODEL_EXISTS"},
        )
    
    model = ModelConfigModel(
        organization_id=organization_id,
        provider_id=data.provider_id,
        model_identifier=data.model_identifier,
        display_name=data.display_name,
        description=data.description,
        enabled=data.enabled,
        is_default=data.is_default,
        configuration=data.configuration,
    )
    
    db.add(model)
    await db.commit()
    await db.refresh(model)
    
    return ModelResponse.model_validate(model)


@router.get(
    "/organizations/{organization_id}/models",
    response_model=ModelListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_models(
    request: Request,
    organization_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    provider_id: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    status: Optional[str] = Query(None),
    capability: Optional[str] = Query(None),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List models."""
    await require_permission("models:read")(request, db)
    
    query = select(ModelConfigModel).where(
        ModelConfigModel.organization_id == organization_id,
    )
    count_query = select(func.count(ModelConfigModel.id)).where(
        ModelConfigModel.organization_id == organization_id,
    )
    
    if provider_id:
        query = query.where(ModelConfigModel.provider_id == provider_id)
        count_query = count_query.where(ModelConfigModel.provider_id == provider_id)
    
    if enabled is not None:
        query = query.where(ModelConfigModel.enabled == enabled)
        count_query = count_query.where(ModelConfigModel.enabled == enabled)
    
    if status:
        query = query.where(ModelConfigModel.status == status)
        count_query = count_query.where(ModelConfigModel.status == status)
    
    if capability:
        # Filter by capability - simplified
        pass
    
    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(ModelConfigModel.updated_at.desc()).limit(page_size).offset((page - 1) * page_size)
    models = list((await db.execute(query)).scalars().all())
    
    return ModelListResponse(
        data=[ModelResponse.model_validate(m) for m in models],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/organizations/{organization_id}/models/{model_id}",
    response_model=ModelDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_model(
    request: Request,
    organization_id: UUID,
    model_id: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get model details."""
    await require_permission("models:read")(request, db)
    
    result = await db.execute(
        select(ModelConfigModel).where(
            ModelConfigModel.id == model_id,
            ModelConfigModel.organization_id == organization_id,
        )
    )
    model = result.scalar_one_or_none()
    
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Model not found", "code": "MODEL_NOT_FOUND"},
        )
    
    # Get provider
    provider_result = await db.execute(
        select(ModelProviderModel).where(ModelProviderModel.provider_id == model.provider_id)
    )
    provider = provider_result.scalar_one_or_none()
    
    # Build response
    resp = ModelDetailResponse(
        **ModelResponse.model_validate(model).model_dump(),
        provider=ModelProviderResponse.model_validate(model.provider) if model.provider else None,
    )
    
    return resp


@router.patch(
    "/organizations/{organization_id}/models/{model_id}",
    response_model=ModelResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def update_model(
    request: Request,
    organization_id: UUID,
    model_id: str,
    data: ModelUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update a model."""
    await require_permission("models:update")(request, db)
    
    result = await db.execute(
        select(ModelConfigModel).where(
            ModelConfigModel.id == model_id,
            ModelConfigModel.organization_id == organization_id,
        )
    )
    model = result.scalar_one_or_none()
    
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Model not found", "code": "MODEL_NOT_FOUND"},
        )
    
    if data.display_name is not None:
        model.display_name = data.display_name
    if data.description is not None:
        model.description = data.description
    if data.enabled is not None:
        model.enabled = data.enabled
    if data.is_default is not None:
        if data.is_default:
            # Unset other defaults
            await db.execute(
                ModelConfigModel.__table__.update()
                .where(ModelConfigModel.provider_id == model.provider_id)
                .where(ModelConfigModel.id != model.id)
                .values(is_default=False)
            )
        model.is_default = data.is_default
    if data.configuration is not None:
        model.configuration = data.configuration
    
    await db.commit()
    await db.refresh(model)
    
    return ModelResponse.model_validate(model)


@router.delete(
    "/organizations/{organization_id}/models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_model(
    request: Request,
    organization_id: UUID,
    model_id: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete a model."""
    await require_permission("models:delete")(request, db)
    
    result = await db.execute(
        select(ModelConfigModel).where(
            ModelConfigModel.id == model_id,
            ModelConfigModel.organization_id == organization_id,
        )
    )
    model = result.scalar_one_or_none()
    
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Model not found", "code": "MODEL_NOT_FOUND"},
        )
    
    await db.delete(model)
    await db.commit()


# ---------------------------------------------------------------------------
# Model Aliases
# ---------------------------------------------------------------------------

@router.post(
    "/organizations/{organization_id}/model-aliases",
    response_model=ModelAliasResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def create_model_alias(
    request: Request,
    organization_id: UUID,
    data: ModelAliasCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a model alias."""
    await require_permission("models:update")(request, db)
    
    # Verify model exists
    result = await db.execute(
        select(ModelConfigModel).where(
            ModelConfigModel.id == data.model_id,
            ModelConfigModel.organization_id == organization_id,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Model not found", "code": "MODEL_NOT_FOUND"},
        )
    
    # Check alias uniqueness
    existing = await db.execute(
        select(ModelAliasModel).where(
            ModelAliasModel.alias == data.alias,
            ModelAliasModel.organization_id == organization_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"Alias '{data.alias}' already exists", "code": "ALIAS_EXISTS"},
        )
    
    alias = ModelAliasModel(
        organization_id=organization_id,
        alias=data.alias,
        model_id=data.model_id,
        description=data.description,
    )
    
    db.add(alias)
    await db.commit()
    await db.refresh(alias)
    
    return ModelAliasResponse.model_validate(alias)


@router.get(
    "/organizations/{organization_id}/model-aliases",
    response_model=List[ModelAliasResponse],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_model_aliases(
    request: Request,
    organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List model aliases."""
    await require_permission("models:read")(request, db)
    
    result = await db.execute(
        select(ModelAliasModel).where(
            ModelAliasModel.organization_id == organization_id,
        ).order_by(ModelAliasModel.created_at.desc())
    )
    
    return [ModelAliasResponse.model_validate(a) for a in result.scalars().all()]


@router.delete(
    "/organizations/{organization_id}/model-aliases/{alias}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_model_alias(
    request: Request,
    organization_id: UUID,
    alias: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete a model alias."""
    await require_permission("models:update")(request, db)
    
    result = await db.execute(
        select(ModelAliasModel).where(
            ModelAliasModel.organization_id == organization_id,
            ModelAliasModel.alias == alias,
        )
    )
    alias_obj = result.scalar_one_or_none()
    
    if not alias_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Alias not found", "code": "ALIAS_NOT_FOUND"},
        )
    
    await db.delete(alias_obj)
    await db.commit()


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

@router.post(
    "/organizations/{organization_id}/models/route",
    response_model=ModelRouteResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def route_model(
    request: Request,
    organization_id: UUID,
    data: ModelRouteRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Route a request to the best model."""
    await require_permission("models:route")(request, db)
    
    # Verify workflow execution exists if provided
    if data.workflow_id:
        from openagent.db.models import WorkflowExecution
        result = await db.execute(
            select(WorkflowExecution).where(
                WorkflowExecution.id == data.workflow_id,
                WorkflowExecution.organization_id == organization_id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Workflow execution not found", "code": "WORKFLOW_EXECUTION_NOT_FOUND"},
            )
    
    # Build routing request
    routing_request = ModelRoutingRequest(
        task_type=data.task_type,
        required_capabilities=data.required_capabilities,
        context_tokens=data.context_tokens,
        estimated_output_tokens=data.estimated_output_tokens,
        max_cost_per_request=data.max_cost_per_request,
        max_cost_per_1k_tokens=data.max_cost_per_1k_tokens,
        latency_target_ms=data.latency_target_ms,
        max_latency_ms=data.max_latency_ms,
        preferred_provider=data.preferred_provider,
        preferred_model=data.preferred_model,
        preferred_model_id=data.preferred_model_id,
        streaming=data.streaming,
        local_only=data.local_only,
        privacy_mode=data.privacy_mode,
        tool_calling=data.tool_calling,
        structured_output=data.structured_output,
        streaming=data.streaming,
        preferred_model=data.preferred_model,
        preferred_model_id=data.preferred_model_id,
        model_alias=data.model_alias,
        model_hint=data.model_hint,
        organization_id=str(organization_id),
        user_id=data.user_id,
        agent_id=data.agent_id,
        workflow_id=str(data.workflow_id) if data.workflow_id else None,
        execution_id=str(data.execution_id) if data.execution_id else None,
        metadata=data.metadata,
        deterministic=data.deterministic,
        seed=data.seed,
    )
    
    # Get router and route
    router = get_router()
    result = await router.route(
        request=routing_request,
        organization_id=organization_id,
        team_id=None,
        agent_id=data.agent_id,
        workflow_id=data.workflow_id,
    )
    
    return ModelRouteResponse(
        success=result.success,
        selected_model=result.selected_model.__dict__ if result.selected_model else None,
        selected_provider=result.selected_provider.__dict__ if result.selected_provider else None,
        fallback_models=result.fallback_models,
        strategy_used=result.strategy_used,
        candidate_count=result.candidate_count,
        filtered_count=result.filtered_count,
        estimated_cost=result.estimated_cost,
        estimated_latency_ms=result.estimated_latency_ms,
        estimated_tokens=result.estimated_tokens,
        routing_reason_codes=result.routing_reason_codes,
        metadata=result.metadata,
        error=result.error,
        error_code=result.error_code,
        request_id=result.request_id,
        timestamp=result.timestamp,
        trace=result.trace,
    )


@router.get(
    "/organizations/{organization_id}/routing/policies",
    response_model=List[RoutingPolicyResponse],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_routing_policies(
    request: Request,
    organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List routing policies."""
    await require_permission("routing:read")(request, db)
    
    result = await db.execute(
        select(RoutingPolicyModel).where(
            RoutingPolicyModel.organization_id == organization_id,
        ).order_by(RoutingPolicyModel.priority.desc())
    )
    
    return [RoutingPolicyResponse.model_validate(p) for p in result.scalars().all()]


@router.post(
    "/organizations/{organization_id}/routing/policies",
    response_model=RoutingPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def create_routing_policy(
    request: Request,
    organization_id: UUID,
    data: RoutingPolicyCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a routing policy."""
    await require_permission("routing:create")(request, db)
    
    policy = RoutingPolicyModel(
        organization_id=organization_id,
        name=data.name,
        description=data.description,
        scope=data.scope,
        scope_id=data.scope_id,
        priority=data.priority,
        provider_policy=data.provider_policy,
        model_policy=data.model_policy,
        capability_policy=data.capability_policy,
        cost_policy=data.cost_policy,
        latency_policy=data.latency_policy,
        privacy_policy=data.privacy_policy,
        strategy=data.strategy,
        fallback_models=data.fallback_models,
        model_aliases=data.model_aliases,
        strategy_config=data.strategy_config,
    )
    
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    
    return RoutingPolicyResponse.model_validate(policy)


@router.patch(
    "/organizations/{organization_id}/routing/policies/{policy_id}",
    response_model=RoutingPolicyResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def update_routing_policy(
    request: Request,
    organization_id: UUID,
    policy_id: UUID,
    data: Dict[str, Any],
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update a routing policy."""
    await require_permission("routing:update")(request, db)
    
    result = await db.execute(
        select(RoutingPolicyModel).where(
            RoutingPolicyModel.id == policy_id,
            RoutingPolicyModel.organization_id == organization_id,
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Policy not found", "code": "POLICY_NOT_FOUND"},
        )
    
    for key, value in data.items():
        if hasattr(policy, key) and key not in ("id", "organization_id", "created_at"):
            setattr(policy, key, value)
    
    policy.updated_at = datetime.now(timezone.utc)
    policy.version += 1
    
    await db.commit()
    await db.refresh(policy)
    
    return RoutingPolicyResponse.model_validate(policy)


@router.delete(
    "/organizations/{organization_id}/routing/policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_routing_policy(
    request: Request,
    organization_id: UUID,
    policy_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete a routing policy."""
    await require_permission("routing:delete")(request, db)
    
    result = await db.execute(
        select(RoutingPolicyModel).where(
            RoutingPolicyModel.id == policy_id,
            RoutingPolicyModel.organization_id == organization_id,
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Policy not found", "code": "POLICY_NOT_FOUND"},
        )
    
    await db.delete(policy)
    await db.commit()


# ---------------------------------------------------------------------------
# Model Aliases
# ---------------------------------------------------------------------------

@router.get(
    "/organizations/{organization_id}/model-aliases",
    response_model=List[ModelAliasResponse],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_model_aliases(
    request: Request,
    organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List model aliases."""
    await require_permission("models:read")(request, db)
    
    result = await db.execute(
        select(ModelAliasModel).where(
            ModelAliasModel.organization_id == organization_id,
        ).order_by(ModelAliasModel.created_at.desc())
    )
    
    return [ModelAliasResponse.model_validate(a) for a in result.scalars().all()]


@router.delete(
    "/organizations/{organization_id}/model-aliases/{alias}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_model_alias(
    request: Request,
    organization_id: UUID,
    alias: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete a model alias."""
    await require_permission("models:update")(request, db)
    
    result = await db.execute(
        select(ModelAliasModel).where(
            ModelAliasModel.organization_id == organization_id,
            ModelAliasModel.alias == alias,
        )
    )
    alias_obj = result.scalar_one_or_none()
    
    if not alias_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Alias not found", "code": "ALIAS_NOT_FOUND"},
        )
    
    await db.delete(alias_obj)
    await db.commit()


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@router.post(
    "/organizations/{organization_id}/models/{model_id}/health-check",
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def health_check_model(
    request: Request,
    organization_id: UUID,
    model_id: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Perform health check on a model."""
    await require_permission("models:test")(request, db)
    
    result = await db.execute(
        select(ModelConfigModel).where(
            ModelConfigModel.id == model_id,
            ModelConfigModel.organization_id == organization_id,
        )
    )
    model = result.scalar_one_or_none()
    
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Model not found", "code": "MODEL_NOT_FOUND"},
        )
    
    # Get provider
    provider_result = await db.execute(
        select(ModelProviderModel).where(ModelProviderModel.provider_id == model.provider_id)
    )
    provider = provider_result.scalar_one_or_none()
    
    if not provider:
        return {"healthy": False, "error": "Provider not found"}
    
    # In a real implementation, this would call the provider's health check
    return {
        "healthy": True,
        "model_id": model.id,
        "model_name": model.display_name,
        "provider": provider.provider_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# Helper function
async def _get_provider_or_404(db: AsyncSession, organization_id: UUID, provider_id: str):
    result = await db.execute(
        select(ModelProviderModel).where(
            ModelProviderModel.provider_id == provider_id,
            ModelProviderModel.organization_id == organization_id,
        )
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Provider not found", "code": "PROVIDER_NOT_FOUND"},
        )
    return provider