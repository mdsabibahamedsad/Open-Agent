import time
import secrets
from typing import Optional, Dict, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import structlog
from fastapi import Request

from openagent.core.config import get_settings

logger = structlog.get_logger("openagent.rate_limit")


@dataclass
class RateLimitBucket:
    """Token bucket for rate limiting."""
    tokens: float
    last_update: float
    limit: int
    window_seconds: int


class InMemoryRateLimiter:
    """In-memory rate limiter using token bucket algorithm."""
    
    def __init__(self):
        self.buckets: Dict[str, RateLimitBucket] = {}
    
    def _get_bucket_key(self, identifier: str, endpoint: str) -> str:
        return f"{identifier}:{endpoint}"
    
    def _refill_bucket(self, bucket: RateLimitBucket) -> None:
        now = time.time()
        elapsed = now - bucket.last_update
        refill_rate = bucket.limit / bucket.window_seconds
        bucket.tokens = min(bucket.limit, bucket.tokens + elapsed * refill_rate)
        bucket.last_update = now
    
    def check_rate_limit(
        self,
        identifier: str,
        endpoint: str,
        limit: int,
        window_seconds: int,
    ) -> Tuple[bool, int, int]:
        """
        Check if request is within rate limit.
        Returns (allowed, remaining_tokens, retry_after_seconds).
        """
        key = self._get_bucket_key(identifier, endpoint)
        now = time.time()
        
        if key not in self.buckets:
            self.buckets[key] = RateLimitBucket(
                tokens=limit - 1,
                last_update=now,
                limit=limit,
                window_seconds=window_seconds,
            )
            return True, limit - 1, 0
        
        bucket = self.buckets[key]
        
        # Update limit and window if changed
        if bucket.limit != limit or bucket.window_seconds != window_seconds:
            bucket.limit = limit
            bucket.window_seconds = window_seconds
        
        self._refill_bucket(bucket)
        
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True, int(bucket.tokens), 0
        
        # Calculate retry after
        retry_after = int((1 - bucket.tokens) * bucket.window_seconds / bucket.limit) + 1
        return False, 0, retry_after
    
    def cleanup_expired(self, max_age_seconds: int = 3600) -> None:
        """Clean up expired buckets."""
        now = time.time()
        expired_keys = [
            key for key, bucket in self.buckets.items()
            if now - bucket.last_update > max_age_seconds
        ]
        for key in expired_keys:
            del self.buckets[key]


class RedisRateLimiter:
    """Redis-based rate limiter for distributed deployments."""
    
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis = None
    
    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as redis
            self._redis = redis.from_url(self.redis_url)
        return self._redis
    
    async def check_rate_limit(
        self,
        identifier: str,
        endpoint: str,
        limit: int,
        window_seconds: int,
    ) -> Tuple[bool, int, int]:
        """Check rate limit using Redis sorted set."""
        redis = await self._get_redis()
        key = f"ratelimit:{identifier}:{endpoint}"
        now = time.time()
        window_start = now - window_seconds
        
        # Remove expired entries
        await redis.zremrangebyscore(key, 0, window_start)
        
        # Count current requests
        current_count = await redis.zcard(key)
        
        if current_count >= limit:
            # Get oldest entry to calculate retry after
            oldest = await redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry_after = int(oldest[0][1] + window_seconds - now) + 1
            else:
                retry_after = window_seconds
            return False, 0, retry_after
        
        # Add current request
        await redis.zadd(key, {f"{now}:{secrets.token_hex(8)}": now})
        await redis.expire(key, window_seconds + 1)
        
        return True, limit - current_count - 1, 0


import secrets


def get_rate_limiter() -> InMemoryRateLimiter | RedisRateLimiter:
    """Get rate limiter based on configuration."""
    settings = get_settings()
    
    if settings.REDIS_URL and not settings.is_development:
        return RedisRateLimiter(settings.REDIS_URL)
    
    return InMemoryRateLimiter()


async def rate_limit_dependency(
    identifier: str,
    endpoint: str,
    limit: int,
    window_seconds: int,
) -> None:
    """FastAPI dependency for rate limiting."""
    from fastapi import HTTPException, Request
    from starlette.responses import Response
    
    limiter = get_rate_limiter()
    allowed, remaining, retry_after = await limiter.check_rate_limit(
        identifier, endpoint, limit, window_seconds
    )
    
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "retry_after": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + retry_after),
            },
        )


# Rate limit configurations for auth endpoints
AUTH_RATE_LIMITS = {
    "login": {"limit": 10, "window": 60},  # 10 per minute
    "register": {"limit": 5, "window": 3600},  # 5 per hour
    "forgot_password": {"limit": 3, "window": 3600},  # 3 per hour
    "reset_password": {"limit": 5, "window": 3600},  # 5 per hour
    "verify_email": {"limit": 5, "window": 3600},  # 5 per hour
    "change_password": {"limit": 10, "window": 3600},  # 10 per hour
}


async def get_client_identifier(request: Request) -> str:
    """Get client identifier for rate limiting."""
    # Try to get real IP from headers (for proxied deployments)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to client host
    if request.client:
        return request.client.host
    
    return "unknown"


async def check_auth_rate_limit(
    request: Request,
    endpoint: str,
    email: Optional[str] = None,
) -> None:
    """Check rate limit for auth endpoints."""
    settings = get_settings()
    
    if not settings.RATE_LIMIT_ENABLED:
        return
    
    config = AUTH_RATE_LIMITS.get(endpoint)
    if not config:
        return
    
    # Use email + IP for more granular limiting
    client_id = await get_client_identifier(request)
    identifier = f"{client_id}:{email}" if email else client_id
    
    limiter = get_rate_limiter()
    allowed, remaining, retry_after = await limiter.check_rate_limit(
        identifier,
        f"auth:{endpoint}",
        config["limit"],
        config["window"],
    )
    
    if not allowed:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Too many requests. Please try again later.",
                "retry_after": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(config["limit"]),
                "X-RateLimit-Remaining": "0",
            },
        )