export interface PaginationParams {
  page: number;
  page_size: number;
}

export interface PaginationMeta {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface PaginatedResponse<T> {
  data: T[];
  meta: PaginationMeta;
}

export const DEFAULT_PAGE = 1;
export const DEFAULT_PAGE_SIZE = 20;
export const MAX_PAGE_SIZE = 100;

export function normalizePagination(
  params: Partial<PaginationParams>,
): PaginationParams {
  return {
    page: Math.max(1, params.page ?? DEFAULT_PAGE),
    page_size: Math.min(
      MAX_PAGE_SIZE,
      Math.max(1, params.page_size ?? DEFAULT_PAGE_SIZE),
    ),
  };
}

export function createPaginationMeta(
  params: PaginationParams,
  totalItems: number,
): PaginationMeta {
  const totalPages = Math.ceil(totalItems / params.page_size);
  return {
    page: params.page,
    page_size: params.page_size,
    total_items: totalItems,
    total_pages: totalPages,
    has_next: params.page < totalPages,
    has_prev: params.page > 1,
  };
}
