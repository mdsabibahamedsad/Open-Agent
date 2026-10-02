import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Callable, Awaitable, TypeVar
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager
from collections import defaultdict

from openagent.core.config import get_settings


class LockType(str, Enum):
    EXCLUSIVE = "exclusive"
    SHARED = "shared"


class LockState(str, Enum):
    ACQUIRED = "acquired"
    WAITING = "waiting"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass
class LockRequest:
    resource: str
    lock_type: LockType = LockType.EXCLUSIVE
    timeout: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Lock:
    id: str
    resource: str
    lock_type: LockType
    owner_id: str
    state: LockState
    acquired_at: datetime
    expires_at: Optional[datetime]
    metadata: Dict[str, Any] = field(default_factory=dict)


class DistributedLockManager:
    """Distributed lock manager using Redis."""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    
    async def acquire(
        self,
        resource: str,
        owner_id: str,
        lock_type: LockType = LockType.EXCLUSIVE,
        ttl: float = 30.0,
        timeout: float = 30.0,
    ) -> Optional[Lock]:
        """
        Acquire a distributed lock.
        
        Args:
            resource: Resource identifier to lock
            owner_id: Unique identifier for the lock owner
            lock_type: Type of lock (exclusive or shared)
            ttl: Time-to-live for the lock in seconds
            timeout: Maximum time to wait for lock acquisition
            
        Returns:
            Lock object if acquired, None if timeout
        """
        lock_key = f"lock:{resource}"
        lock_value = f"{owner_id}:{lock_type.value}"
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Try to acquire lock using Redis SET NX EX
            acquired = await self.redis.set(
                lock_key,
                lock_value,
                nx=True,
                ex=int(ttl) + 1,
            )
            
            if acquired:
                lock = Lock(
                    id=str(uuid.uuid4()),
                    resource=resource,
                    lock_type=lock_type,
                    owner_id=owner_id,
                    state=LockState.ACQUIRED,
                    acquired_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
                )
                
                # Store lock info for debugging
                await self.redis.hset(
                    f"lock:info:{resource}",
                    mapping={
                        "lock_id": lock.id,
                        "owner_id": owner_id,
                        "lock_type": lock_type.value,
                        "acquired_at": lock.acquired_at.isoformat(),
                        "expires_at": lock.expires_at.isoformat(),
                    }
                )
                await self.redis.expire(f"lock:info:{resource}", int(ttl) + 10)
                
                return lock
            
            # Check if lock expired
            ttl_remaining = await self.redis.ttl(lock_key)
            if ttl_remaining <= 0:
                # Lock expired, try again immediately
                continue
            
            # Wait a bit before retrying
            await asyncio.sleep(0.1)
        
        return None
    
    async def release(self, resource: str, owner_id: str) -> bool:
        """
        Release a distributed lock.
        
        Only the lock owner can release the lock.
        """
        lock_key = f"lock:{resource}"
        lock_value = f"{owner_id}:exclusive"  # We store both types as exclusive in Redis
        
        # Use Lua script for atomic check-and-delete
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        
        result = await self.redis.eval(lua_script, 1, lock_key, lock_value)
        
        if result:
            # Clean up lock info
            await self.redis.delete(f"lock:info:{resource}")
            return True
        
        return False
    
    async def extend(self, resource: str, owner_id: str, additional_ttl: float) -> bool:
        """Extend lock TTL."""
        lock_key = f"lock:{resource}"
        lock_value = f"{owner_id}:exclusive"
        
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        
        result = await self.redis.eval(lua_script, 1, lock_key, lock_value, int(additional_ttl))
        return result == 1
    
    async def get_lock_info(self, resource: str) -> Optional[Dict[str, Any]]:
        """Get lock information."""
        info = await self.redis.hgetall(f"lock:info:{resource}")
        if not info:
            return None
        return info
    
    async def is_locked(self, resource: str) -> bool:
        """Check if resource is locked."""
        lock_key = f"lock:{resource}"
        return await self.redis.exists(lock_key) > 0
    
    async def force_release(self, resource: str) -> bool:
        """Force release a lock (admin operation)."""
        lock_key = f"lock:{resource}"
        result = await self.redis.delete(lock_key)
        await self.redis.delete(f"lock:info:{resource}")
        return result > 0


class OptimisticLock:
    """Optimistic locking for database records."""
    
    def __init__(self, db_session):
        self.db = db_session
    
    @asynccontextmanager
    async def lock(self, resource_id: str, version_field: str = "version", max_retries: int = 3):
        """Context manager for optimistic locking."""
        for attempt in range(max_retries):
            try:
                yield
                return
            except Exception as e:
                if "version" in str(e).lower() or "concurrent" in str(e).lower():
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(0.1 * (attempt + 1))
                else:
                    raise


class RateLimiter:
    """Token bucket rate limiter with Redis backend."""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        """
        Check rate limit.
        
        Returns:
            (allowed, remaining, retry_after)
        """
        key = f"ratelimit:{key}"
        now = time.time()
        window_start = now - window_seconds
        
        # Remove expired entries
        await self.redis.zremrangebyscore(key, 0, window_start)
        
        # Count current requests
        current_count = await self.redis.zcard(key)
        
        if current_count >= limit:
            # Get oldest entry to calculate retry after
            oldest = await self.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry_after = int(oldest[0][1] + window_seconds - time.time()) + 1
            else:
                retry_after = window_seconds
            return False, 0, retry_after
        
        # Add current request
        request_id = f"{now}:{uuid.uuid4().hex[:8]}"
        await self.redis.zadd(key, {request_id: now})
        await self.redis.expire(key, window_seconds + 1)
        
        return True, limit - current_count - 1, 0


class Semaphore:
    """Distributed semaphore for limiting concurrent access."""
    
    def __init__(self, redis_client, name: str, limit: int):
        self.redis = redis_client
        self.name = name
        self.limit = limit
        self.key = f"semaphore:{name}"
    
    @asynccontextmanager
    async def acquire(self, timeout: float = 30.0):
        """Acquire semaphore slot."""
        start_time = time.time()
        slot = None
        
        while time.time() - start_time < timeout:
            # Try to acquire a slot
            slot = await self._try_acquire()
            if slot is not None:
                try:
                    yield slot
                    return
                finally:
                    await self.release(slot)
            
            await asyncio.sleep(0.1)
        
        raise TimeoutError(f"Could not acquire semaphore '{self.name}' within {timeout}s")
    
    async def _try_acquire(self) -> Optional[str]:
        """Try to acquire a semaphore slot."""
        # Use Lua script for atomic check-and-acquire
        lua_script = """
        local current = redis.call('scard', KEYS[1])
        if current < tonumber(ARGV[1]) then
            local slot = ARGV[2]
            redis.call('sadd', KEYS[1], slot)
            return slot
        else
            return nil
        end
        """
        
        slot = f"slot_{uuid.uuid4().hex[:16]}"
        result = await self.redis.eval(
            """
            local current = redis.call('scard', KEYS[1])
            if current < tonumber(ARGV[1]) then
                local slot = ARGV[2]
                redis.call('sadd', KEYS[1], slot)
                return slot
            else
                return nil
            end
            """,
            1,
            self.key,
            self.limit,
            slot,
        )
        
        return result
    
    async def release(self, slot: str) -> bool:
        """Release a semaphore slot."""
        result = await self.redis.srem(self.key, slot)
        return result > 0
    
    async def get_available(self) -> int:
        """Get number of available slots."""
        current = await self.redis.scard(self.key)
        return max(0, self.limit - current)
    
    async def get_current(self) -> int:
        """Get current usage."""
        return await self.redis.scard(self.key)


# Global instances (initialized on startup)
lock_manager: Optional[DistributedLockManager] = None
rate_limiter: Optional[RateLimiter] = None


def init_concurrency_control(redis_client) -> None:
    """Initialize concurrency control utilities."""
    global lock_manager, rate_limiter
    lock_manager = DistributedLockManager(redis_client)
    rate_limiter = RateLimiter(redis_client)


def get_lock_manager() -> Optional[DistributedLockManager]:
    return lock_manager


def get_rate_limiter() -> Optional[RateLimiter]:
    return rate_limiter