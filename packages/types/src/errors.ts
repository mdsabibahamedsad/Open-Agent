export interface ApiErrorDetail {
  field?: string;
  code: string;
  message: string;
}

export interface ApiError {
  code: string;
  message: string;
  request_id: string;
  details?: ApiErrorDetail[];
  status_code: number;
}

export interface ApiErrorResponse {
  error: ApiError;
}

export const ERROR_CODES = {
  VALIDATION_ERROR: "VALIDATION_ERROR",
  NOT_FOUND: "NOT_FOUND",
  UNAUTHORIZED: "UNAUTHORIZED",
  FORBIDDEN: "FORBIDDEN",
  INTERNAL_ERROR: "INTERNAL_ERROR",
  CONFLICT: "CONFLICT",
  RATE_LIMITED: "RATE_LIMITED",
  SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
  BAD_REQUEST: "BAD_REQUEST",
  UNPROCESSABLE_ENTITY: "UNPROCESSABLE_ENTITY",
} as const;

export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

export function createApiError(
  code: ErrorCode,
  message: string,
  requestId: string,
  statusCode: number,
  details?: ApiErrorDetail[],
): ApiError {
  return {
    code,
    message,
    request_id: requestId,
    status_code: statusCode,
    details,
  };
}

export function isApiError(error: unknown): error is ApiError {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    "message" in error &&
    "request_id" in error &&
    "status_code" in error
  );
}
