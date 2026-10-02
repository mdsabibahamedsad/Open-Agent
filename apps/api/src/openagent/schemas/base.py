from datetime import datetime
from typing import Generic, Optional, List, Dict, Any, TypeVar
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, EmailStr

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class PaginatedResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: List[T]
    meta: PaginationMeta


class ErrorDetail(BaseModel):
    field: Optional[str] = None
    code: str
    message: str


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str
    details: Optional[List[ErrorDetail]] = None
    status_code: int


class ApiErrorResponse(BaseModel):
    error: ApiError


class UserBase(BaseModel):
    email: EmailStr
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserCreate(UserBase):
    password: Optional[str] = Field(default=None, min_length=8)


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = None


class UserResponse(UserBase):
    id: UUID
    status: str
    is_superadmin: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UserWithMemberships(UserResponse):
    memberships: List["MembershipResponse"] = []


class OrganizationBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    settings: Dict[str, Any] = {}


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class OrganizationResponse(OrganizationBase):
    id: UUID
    status: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OrganizationWithMemberships(OrganizationResponse):
    memberships: List["MembershipResponse"] = []


class MembershipBase(BaseModel):
    role: str = Field(default="member", pattern="^(owner|admin|member|viewer)$")
    status: str = Field(default="pending", pattern="^(active|pending|suspended|revoked)$")


class MembershipCreate(MembershipBase):
    user_id: UUID
    organization_id: UUID


class MembershipUpdate(BaseModel):
    role: str = Field(pattern="^(owner|admin|member|viewer)$")
    status: str = Field(pattern="^(active|pending|suspended|revoked)$")


class MembershipResponse(MembershipBase):
    id: UUID
    user_id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime
    user: Optional[UserResponse] = None
    organization: Optional[OrganizationResponse] = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    permissions: List[str] = []
    expires_at: Optional[datetime] = None


class ApiKeyCreate(ApiKeyBase):
    pass


class ApiKeyResponse(ApiKeyBase):
    id: UUID
    key_prefix: str
    user_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyWithSecret(ApiKeyResponse):
    key: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "0.1.0"
    environment: str


class ReadyResponse(BaseModel):
    status: str
    service: str
    checks: Dict[str, bool]