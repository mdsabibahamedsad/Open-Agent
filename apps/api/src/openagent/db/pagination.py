from typing import TypeVar, Generic, List, Optional
from pydantic import BaseModel, Field
from math import ceil

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=20, ge=1, le=100, description="Number of items per page")


class CursorPaginationParams(BaseModel):
    cursor: Optional[str] = Field(default=None, description="Cursor for next page")
    limit: int = Field(default=20, ge=1, le=100, description="Number of items per page")


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class CursorPaginationMeta(BaseModel):
    next_cursor: Optional[str] = None
    has_next: bool = False
    limit: int


class PaginatedResponse(BaseModel, Generic[T]):
    data: List[T]
    meta: PaginationMeta


class CursorPaginatedResponse(BaseModel, Generic[T]):
    data: List[T]
    meta: CursorPaginationMeta


def create_pagination_meta(
    page: int,
    page_size: int,
    total_items: int
) -> PaginationMeta:
    total_pages = ceil(total_items / page_size) if total_items > 0 else 1
    return PaginationMeta(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def create_cursor_pagination_meta(
    items: List[T],
    limit: int,
    cursor_field: str = "id"
) -> CursorPaginationMeta:
    has_next = len(items) > limit
    if has_next:
        items = items[:limit]
        next_cursor = getattr(items[-1], cursor_field, None)
        if next_cursor is not None:
            next_cursor = str(next_cursor)
    else:
        next_cursor = None
    
    return CursorPaginationMeta(
        next_cursor=next_cursor,
        has_next=has_next,
        limit=limit,
    )


def paginate_query(
    query,
    pagination: PaginationParams,
    session,
    count_query=None
):
    """Apply offset/limit pagination to a query."""
    offset = (pagination.page - 1) * pagination.page_size
    query = query.limit(pagination.page_size).offset(offset)
    return query


async def execute_paginated(
    session,
    select_query,
    count_query,
    pagination: PaginationParams
):
    """Execute a paginated query and return results with metadata."""
    # Get total count
    total_result = await session.execute(count_query)
    total_items = total_result.scalar_one()
    
    # Get paginated results
    offset = (pagination.page - 1) * pagination.page_size
    select_query = select_query.limit(pagination.page_size).offset(offset)
    result = await session.execute(select_query)
    items = list(result.scalars().all())
    
    meta = create_pagination_meta(pagination.page, pagination.page_size, total_items)
    return items, meta


async def execute_cursor_paginated(
    session,
    query,
    cursor: Optional[str],
    limit: int,
    cursor_column
):
    """Execute a cursor-based paginated query."""
    if cursor:
        query = query.where(cursor_column > cursor)
    
    # Fetch limit + 1 to check if there's a next page
    query = query.limit(limit + 1)
    result = await session.execute(query)
    items = list(result.scalars().all())
    
    meta = create_cursor_pagination_meta(items, limit)
    if meta.has_next:
        items = items[:limit]
    
    return items, meta