import asyncio
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable, Optional, TypeVar
from dataclasses import dataclass, field
from collections import deque

from openagent.core.config import get_settings

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 30.0
    excluded_exceptions: tuple = ()
    expected_exceptions: tuple = (Exception,)


@dataclass
class CircuitBreakerStats:
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    state_changes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.stats = CircuitBreakerStats()
        self._last_state_change = time.time()
        self._failure_times = deque(maxlen=100)
        self._lock = asyncio.Lock()

    @property
    def is_available(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if time.time() - self._last_state_change >= self.config.timeout_seconds:
                return True
            return False

        return True

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args,
        **kwargs,
    ) -> T:
        async with self._lock:
            if not self._can_execute():
                self.stats.rejected_calls += 1
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' is OPEN"
                )

            self.stats.total_calls += 1

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except self.config.excluded_exceptions:
            raise
        except self.config.expected_exceptions as e:
            await self._on_failure()
            raise
        except Exception as e:
            await self._on_failure()
            raise

    def _can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if time.time() - self._last_state_change >= self.config.timeout_seconds:
                self._transition_to_half_open()
                return True
            return False

        return True

    async def _on_success(self) -> None:
        async with self._lock:
            self.stats.successful_calls += 1
            self.stats.last_success_time = time.time()
            self.stats.consecutive_successes += 1
            self.stats.consecutive_failures = 0

            if self.state == CircuitState.HALF_OPEN:
                if self.stats.consecutive_successes >= self.config.success_threshold:
                    self._transition_to_closed()

    async def _on_failure(self) -> None:
        async with self._lock:
            self.stats.failed_calls += 1
            self.stats.last_failure_time = time.time()
            self.stats.consecutive_failures += 1
            self.stats.consecutive_successes = 0
            self._failure_times.append(time.time())

            if self.state == CircuitState.HALF_OPEN:
                self._transition_to_open()
            elif self.state == CircuitState.CLOSED:
                if self.stats.consecutive_failures >= self.config.failure_threshold:
                    self._transition_to_open()

    def _transition_to_open(self) -> None:
        self.state = CircuitState.OPEN
        self._last_state_change = time.time()
        self.stats.state_changes += 1

    def _transition_to_half_open(self) -> None:
        self.state = CircuitState.HALF_OPEN
        self._last_state_change = time.time()
        self.stats.state_changes += 1
        self.stats.consecutive_successes = 0
        self.stats.consecutive_failures = 0

    def _transition_to_closed(self) -> None:
        self.state = CircuitState.CLOSED
        self._last_state_change = time.time()
        self.stats.state_changes += 1
        self.stats.consecutive_failures = 0
        self.stats.consecutive_successes = 0

    def get_stats(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "stats": {
                "total_calls": self.stats.total_calls,
                "successful_calls": self.stats.successful_calls,
                "failed_calls": self.stats.failed_calls,
                "rejected_calls": self.stats.rejected_calls,
                "consecutive_failures": self.stats.consecutive_failures,
                "consecutive_successes": self.stats.consecutive_successes,
                "state_changes": self.stats.state_changes,
                "last_failure_time": (
                    datetime.fromtimestamp(self.stats.last_failure_time, tz=timezone.utc).isoformat()
                    if self.stats.last_failure_time else None
                ),
                "last_success_time": (
                    datetime.fromtimestamp(self.stats.last_success_time, tz=timezone.utc).isoformat()
                    if self.stats.last_success_time else None
                ),
            }

    def reset(self) -> None:
        self.state = CircuitState.CLOSED
        self.stats = CircuitBreakerStats()
        self._last_state_change = time.time()
        self._failure_times.clear()


class CircuitBreakerOpenError(Exception):
    pass


class CircuitBreakerRegistry:
    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        return self._breakers.get(name)

    def remove(self, name: str) -> bool:
        if name in self._breakers:
            del self._breakers[name]
            return True
        return False

    def get_all_stats(self) -> dict[str, dict]:
        return {name: breaker.get_stats() for name, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        for breaker in self._breakers.values():
            breaker.reset()

    async def call_with_breaker(
        self,
        name: str,
        func: Callable[..., Awaitable[T]],
        *args,
        config: Optional[CircuitBreakerConfig] = None,
        **kwargs,
    ) -> T:
        breaker = self.get_or_create(name, config)
        return await breaker.call(func, *args, **kwargs)


circuit_breaker_registry = CircuitBreakerRegistry()


async def call_with_circuit_breaker(
    name: str,
    func: Callable[..., Awaitable[T]],
    *args,
    config: Optional[CircuitBreakerConfig] = None,
    **kwargs,
) -> T:
    return await circuit_breaker_registry.call_with_breaker(name, func, *args, config=config, **kwargs)


def circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None,
):
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapper(*args, **kwargs) -> T:
            return await call_with_circuit_breaker(name, func, *args, config=config, **kwargs)
        return wrapper
    return decorator


class CircuitBreakerConfigs:
    HTTP_API = CircuitBreakerConfig(
        failure_threshold=5,
        success_threshold=2,
        timeout_seconds=30.0,
        excluded_exceptions=(asyncio.CancelledError,),
    )

    DATABASE = CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout_seconds=10.0,
        expected_exceptions=(Exception,),
    )

    EXTERNAL_API = CircuitBreakerConfig(
        failure_threshold=10,
        success_threshold=3,
        timeout_seconds=60.0,
        excluded_exceptions=(asyncio.CancelledError,),
    )

    REDIS = CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout_seconds=5.0,
        expected_exceptions=(Exception,),
    )


def get_circuit_breaker(name: str) -> Optional[CircuitBreaker]:
    return circuit_breaker_registry.get(name)