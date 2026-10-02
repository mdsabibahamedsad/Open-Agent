from typing import Optional, Callable, Awaitable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.datastructures import Headers

from openagent.core.config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware for adding security headers to responses."""
    
    def __init__(
        self,
        app: ASGIApp,
        csp_policy: Optional[str] = None,
        hsts_max_age: int = 31536000,
        hsts_include_subdomains: bool = True,
        hsts_preload: bool = False,
        referrer_policy: str = "strict-origin-when-cross-origin",
        frame_options: str = "DENY",
        content_type_options: str = "nosniff",
        permissions_policy: Optional[str] = None,
        cross_origin_embedder_policy: Optional[str] = None,
        cross_origin_opener_policy: str = "same-origin",
        cross_origin_resource_policy: str = "same-origin",
    ):
        super().__init__(app)
        self.csp_policy = csp_policy
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains
        self.hsts_preload = hsts_preload
        self.referrer_policy = referrer_policy
        self.frame_options = frame_options
        self.content_type_options = content_type_options
        self.permissions_policy = permissions_policy
        self.cross_origin_embedder_policy = cross_origin_embedder_policy
        self.cross_origin_opener_policy = cross_origin_opener_policy
        self.cross_origin_resource_policy = cross_origin_resource_policy
    
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        
        # Add security headers
        headers = response.headers
        
        # Content Security Policy
        if self.csp_policy:
            headers["Content-Security-Policy"] = self.csp_policy
        
        # HSTS (only for HTTPS)
        if request.url.scheme == "https":
            hsts_value = f"max-age={self.hsts_max_age}"
            if self.hsts_include_subdomains:
                hsts_value += "; includeSubDomains"
            if self.hsts_preload:
                hsts_value += "; preload"
            headers["Strict-Transport-Security"] = hsts_value
        
        # Referrer Policy
        headers["Referrer-Policy"] = self.referrer_policy
        
        # X-Frame-Options
        headers["X-Frame-Options"] = self.frame_options
        
        # X-Content-Type-Options
        headers["X-Content-Type-Options"] = self.content_type_options
        
        # Permissions Policy
        if self.permissions_policy:
            headers["Permissions-Policy"] = self.permissions_policy
        
        # Cross-Origin policies
        if self.cross_origin_embedder_policy:
            headers["Cross-Origin-Embedder-Policy"] = self.cross_origin_embedder_policy
        if self.cross_origin_opener_policy:
            headers["Cross-Origin-Opener-Policy"] = self.cross_origin_opener_policy
        if self.cross_origin_resource_policy:
            headers["Cross-Origin-Resource-Policy"] = self.cross_origin_resource_policy
        
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to limit request body size."""
    
    def __init__(
        self,
        app: ASGIApp,
        max_size: int = 10 * 1024 * 1024,  # 10MB default
        max_form_size: int = 10 * 1024 * 1024,  # 10MB default for forms
        max_field_size: int = 1024 * 1024,  # 1MB default for individual fields
    ):
        super().__init__(app)
        self.max_size = max_size
        self.max_form_size = max_form_size
        self.max_field_size = max_field_size
    
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Check Content-Length header
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > self.max_size:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": f"Request body exceeds maximum size of {self.max_size} bytes",
                                "max_size": self.max_size,
                            }
                        },
                    )
            except ValueError:
                pass
        
        # For multipart/form-data, we can't easily check without reading
        # The actual body reading will be handled by FastAPI's form parser
        
        response = await call_next(request)
        return response


class TrustedHostMiddleware(BaseHTTPMiddleware):
    """Middleware to validate Host header against allowed hosts."""
    
    def __init__(
        self,
        app: ASGIApp,
        allowed_hosts: list[str],
        www_redirect: bool = True,
    ):
        super().__init__(app)
        self.allowed_hosts = allowed_hosts
        self.www_redirect = www_redirect
    
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        host = request.headers.get("host", "").split(":")[0]
        
        if host not in self.allowed_hosts:
            # Check if it's a www redirect case
            if self.www_redirect and host.startswith("www."):
                redirect_host = host[4:]
                if redirect_host in self.allowed_hosts:
                    from starlette.responses import RedirectResponse
                    url = request.url.replace(netloc=redirect_host)
                    return RedirectResponse(url=url, status_code=301)
            
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_HOST",
                        "message": "Invalid host header",
                    }
                },
            )
        
        return await call_next(request)


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce request timeout."""
    
    def __init__(
        self,
        app: ASGIApp,
        timeout: float = 30.0,
    ):
        super().__init__(app)
        self.timeout = timeout
    
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        import asyncio
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout)
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=504,
                content={
                    "error": {
                        "code": "REQUEST_TIMEOUT",
                        "message": f"Request timed out after {self.timeout} seconds",
                    }
                },
            )


def get_default_csp_policy() -> str:
    """Get default CSP policy for production."""
    return (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https: wss:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )


def get_development_csp_policy() -> str:
    """Get relaxed CSP policy for development."""
    return (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https: wss: ws:; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )


def create_security_middleware(app: ASGIApp) -> ASGIApp:
    """Create and configure security middleware stack."""
    settings = get_settings()
    
    # Add security headers middleware
    if settings.is_production:
        csp_policy = get_default_csp_policy()
    else:
        csp_policy = get_development_csp_policy()
    
    # Add middleware in reverse order (last added = first executed)
    from starlette.middleware import Middleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware as StarletteTrustedHostMiddleware
    
    middlewares = [
        Middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.ALLOWED_HOSTS if hasattr(settings, "ALLOWED_HOSTS") else ["*"],
        ),
        Middleware(RequestSizeLimitMiddleware, max_size=50 * 1024 * 1024),  # 50MB
        Middleware(RequestTimeoutMiddleware, timeout=60.0),
        Middleware(SecurityHeadersMiddleware, csp_policy=csp_policy),
    ]
    
    return middlewares


# Import needed for ASGIApp
from starlette.types import ASGIApp
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware as StarletteTrustedHostMiddleware