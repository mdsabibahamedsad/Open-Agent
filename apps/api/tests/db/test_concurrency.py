import pytest
import pytest_asyncio
import asyncio
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from openagent.core.concurrency import (
    DistributedLockManager, RateLimiter, Semaphore, RetryPolicy, BackoffStrategy,
    Lock, LockType, LockState,
)
from openagent.core.resilience import (
    CircuitBreaker, CircuitBreakerConfig, CircuitState, CircuitBreakerRegistry,
    CircuitBreakerOpenError, CircuitBreakerConfigs,
    call_with_circuit_breaker, circuit_breaker,
)


class TestDistributedLockManager:
    @pytest_asyncio.fixture
    async def redis_mock(self):
        mock = AsyncMock()
        mock.set = AsyncMock(return_value=True)
        mock.get = AsyncMock(return_value=None)
        mock.delete = AsyncMock(return_value=1)
        mock.ttl = AsyncMock(return_value=30)
        mock.setnx = AsyncMock(return_value=True)
        mock.eval = AsyncMock(return_value=1)
        mock.hset = AsyncMock(return_value=True)
        mock.hgetall = AsyncMock(return_value={})
        mock.expire = AsyncMock(return_value=True)
        return mock

    async def test_acquire_lock(self, redis_mock):
        manager = DistributedLockManager(redis_mock)
        
        lock = await manager.acquire(
            resource="test-resource",
            owner_id="user-123",
            ttl=30.0,
        )
        
        assert lock is not None
        assert lock.resource == "test-resource"
        assert lock.owner_id == "user-123"
        assert lock.lock_type == LockType.EXCLUSIVE
        assert lock.state == LockState.ACQUIRED
        assert lock.expires_at is not None
        
        # Verify Redis calls
        redis_mock.set.assert_called_once()
        redis_mock.hset.assert_called_once()

    async def test_acquire_lock_timeout(self, redis_mock):
        redis_mock.set = AsyncMock(return_value=False)
        redis_mock.ttl = AsyncMock(return_value=30)
        
        manager = DistributedLockManager(redis_mock)
        
        lock = await manager.acquire(
            resource="busy-resource",
            owner_id="user-1",
            timeout=0.1,  # Very short timeout
        )
        
        assert lock is None

    async def test_release_lock(self, redis_mock):
        redis_mock.eval = AsyncMock(return_value=1)
        
        manager = DistributedLockManager(redis_mock)
        
        result = await manager.release("test-resource", "user-123")
        
        assert result is True
        redis_mock.eval.assert_called_once()
        redis_mock.delete.assert_called_once()

    async def test_release_lock_not_owner(self, redis_mock):
        redis_mock.eval = AsyncMock(return_value=0)
        
        manager = DistributedLockManager(redis_mock)
        
        result = await manager.release("test-resource", "different-user")
        
        assert result is False

    async def test_extend_lock(self, redis_mock):
        redis_mock.eval = AsyncMock(return_value=1)
        
        manager = DistributedLockManager(redis_mock)
        
        result = await manager.extend("test-resource", "user-123", 60.0)
        
        assert result is True

    async def test_force_release(self, redis_mock):
        redis_mock.delete = AsyncMock(return_value=1)
        
        manager = DistributedLockManager(redis_mock)
        
        result = await manager.force_release("test-resource")
        
        assert result is True
        assert redis_mock.delete.call_count == 2


class TestRateLimiter:
    @pytest_asyncio.fixture
    async def redis_mock(self):
        mock = AsyncMock()
        mock.zremrangebyscore = AsyncMock(return_value=0)
        mock.zcard = AsyncMock(return_value=0)
        mock.zadd = AsyncMock(return_value=1)
        mock.expire = AsyncMock(return_value=True)
        mock.zrange = AsyncMock(return_value=[])
        return mock

    async def test_check_rate_limit_allowed(self, redis_mock):
        limiter = RateLimiter(redis_mock)
        
        allowed, remaining, retry_after = await limiter.check_rate_limit(
            identifier="user-123",
            endpoint="/api/test",
            limit=10,
            window_seconds=60,
        )
        
        assert allowed is True
        assert remaining == 9
        assert retry_after == 0
        redis_mock.zadd.assert_called_once()

    async def test_check_rate_limit_exceeded(self, redis_mock):
        redis_mock.zcard = AsyncMock(return_value=10)
        redis_mock.zrange = AsyncMock(return_value=[(b"1234567890:abc", 1234567890.0)])
        
        limiter = RateLimiter(redis_mock)
        
        allowed, remaining, retry_after = await limiter.check_rate_limit(
            identifier="user-123",
            endpoint="/api/test",
            limit=10,
            window_seconds=60,
        )
        
        assert allowed is False
        assert remaining == 0
        assert retry_after > 0


class TestSemaphore:
    @pytest_asyncio.fixture
    async def redis_mock(self):
        mock = AsyncMock()
        mock.scard = AsyncMock(return_value=0)
        mock.sadd = AsyncMock(return_value=1)
        mock.srem = AsyncMock(return_value=1)
        mock.eval = AsyncMock(return_value="slot_abc123")
        return mock

    async def test_acquire_semaphore(self, redis_mock):
        semaphore = Semaphore(redis_mock, "test-sem", limit=5)
        
        async with semaphore.acquire() as slot:
            assert slot is not None
            assert slot.startswith("slot_")
        
        # Verify release was called
        redis_mock.srem.assert_called_once()

    async def test_semaphore_limit(self, redis_mock):
        redis_mock.scard = AsyncMock(return_value=5)  # At limit
        redis_mock.eval = AsyncMock(return_value=None)
        
        semaphore = Semaphore(redis_mock, "full-sem", limit=5)
        
        slot = await semaphore._try_acquire()
        assert slot is None

    async def test_semaphore_available(self, redis_mock):
        redis_mock.scard = AsyncMock(return_value=3)
        
        semaphore = Semaphore(redis_mock, "test", limit=5)
        
        available = await semaphore.get_available()
        assert available == 2
        
        current = await semaphore.get_current()
        assert current == 3


class TestRetryPolicy:
    def test_fixed_backoff(self):
        policy = RetryPolicy(
            max_attempts=3,
            base_delay_seconds=1.0,
            strategy=BackoffStrategy.FIXED,
        )
        
        from openagent.worker.queue import Job
        job = Job(payload={}, retry_policy=policy)
        job.attempts = 1
        
        delay = job.calculate_next_retry_delay()
        assert delay == 1.0
        
        job.attempts = 2
        delay = job.calculate_next_retry_delay()
        assert delay == 1.0
        
        job.attempts = 3
        delay = job.calculate_next_retry_delay()
        assert delay == 1.0

    def test_linear_backoff(self):
        policy = RetryPolicy(
            max_attempts=3,
            base_delay_seconds=2.0,
            strategy=BackoffStrategy.LINEAR,
        )
        
        from openagent.worker.queue import Job
        job = Job(payload={}, retry_policy=policy)
        job.attempts = 1
        
        delay = job.calculate_next_retry_delay()
        assert delay == 2.0  # 2 * 1
        
        job.attempts = 2
        delay = job.calculate_next_retry_delay()
        assert delay == 4.0  # 2 * 2

    def test_exponential_backoff(self):
        policy = RetryPolicy(
            max_attempts=3,
            base_delay_seconds=1.0,
            strategy=BackoffStrategy.EXPONENTIAL,
        )
        
        from openagent.worker.queue import Job
        job = Job(payload={}, retry_policy=policy)
        job.attempts = 1
        
        delay = job.calculate_next_retry_delay()
        assert delay == 1.0  # 1 * 2^0
        
        job.attempts = 2
        delay = job.calculate_next_retry_delay()
        assert delay == 2.0  # 1 * 2^1
        
        job.attempts = 3
        delay = job.calculate_next_retry_delay()
        assert delay == 4.0  # 1 * 2^2

    def test_exponential_jitter(self):
        policy = RetryPolicy(
            max_attempts=3,
            base_delay_seconds=1.0,
            strategy=BackoffStrategy.EXPONENTIAL_JITTER,
        )
        
        from openagent.worker.queue import Job
        job = Job(payload={}, retry_policy=policy)
        job.attempts = 1
        
        delay = job.calculate_next_retry_delay()
        # With jitter: 1.0 * (0.5 + random) = between 0.5 and 1.5
        assert 0.5 <= delay <= 1.5
        
        job.attempts = 2
        delay = job.calculate_next_retry_delay()
        assert 1.0 <= delay <= 3.0  # 2 * (0.5 to 1.5)


class TestCircuitBreaker:
    @pytest_asyncio.fixture
    async def circuit_breaker(self):
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            timeout_seconds=1.0,  # Short timeout for testing
        )
        return CircuitBreaker("test-breaker", config)

    async def test_circuit_closed_initial(self, circuit_breaker):
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.is_available is True

    async def test_circuit_opens_after_failures(self, circuit_breaker):
        async def failing_func():
            raise Exception("Service unavailable")
        
        # Fail 3 times to reach threshold
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(failing_func)
        
        assert circuit_breaker.state == CircuitState.OPEN
        assert circuit_breaker.is_available is False

    async def test_circuit_half_open_after_timeout(self, circuit_breaker):
        async def failing_func():
            raise Exception("Service unavailable")
        
        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(failing_func)
        
        assert circuit_breaker.state == CircuitState.OPEN
        
        # Wait for timeout
        await asyncio.sleep(1.1)
        
        # Should be half-open now
        assert circuit_breaker.is_available is True

    async def test_circuit_closes_after_successes(self, circuit_breaker):
        # Open the circuit
        async def failing_func():
            raise Exception("Service unavailable")
        
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(failing_func)
        
        assert circuit_breaker.state == CircuitState.OPEN
        
        # Wait for half-open
        await asyncio.sleep(1.1)
        
        # Succeed twice to close
        async def success_func():
            return "ok"
        
        await circuit_breaker.call(success_func)
        await circuit_breaker.call(success_func)
        
        assert circuit_breaker.state == CircuitState.CLOSED

    async def test_circuit_opens_from_half_open_on_failure(self, circuit_breaker):
        # Open the circuit
        async def failing_func():
            raise Exception("Service unavailable")
        
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(failing_func)
        
        await asyncio.sleep(1.1)  # Half-open
        
        # Fail again - should go back to open
        with pytest.raises(Exception):
            await circuit_breaker.call(lambda: (_ for _ in ()).throw(Exception("Failed")))
        
        assert circuit_breaker.state == CircuitState.OPEN

    async def test_excluded_exceptions(self, circuit_breaker):
        config = CircuitBreakerConfig(
            failure_threshold=2,
            excluded_exceptions=(ValueError,),
        )
        breaker = CircuitBreaker("test-excluded", config)
        
        async def value_error_func():
            raise ValueError("Invalid value")
        
        async def runtime_error_func():
            raise RuntimeError("Runtime error")
        
        # ValueError should not count as failure
        with pytest.raises(ValueError):
            await breaker.call(value_error_func)
        
        assert breaker.state == CircuitState.CLOSED
        
        # RuntimeError should count
        with pytest.raises(RuntimeError):
            await breaker.call(runtime_error_func)
        
        with pytest.raises(RuntimeError):
            await breaker.call(runtime_error_func)
        
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerRegistry:
    def test_get_or_create(self):
        registry = CircuitBreakerRegistry()
        
        breaker1 = registry.get_or_create("test-breaker")
        breaker2 = registry.get_or_create("test-breaker")
        
        assert breaker1 is breaker2
        assert "test-breaker" in registry._breakers

    def test_get_existing(self):
        registry = CircuitBreakerRegistry()
        registry.get_or_create("existing")
        
        breaker = registry.get("existing")
        assert breaker is not None
        
        not_found = registry.get("not-exist")
        assert not_found is None

    def test_remove(self):
        registry = CircuitBreakerRegistry()
        registry.get_or_create("to-remove")
        
        result = registry.remove("to-remove")
        assert result is True
        assert registry.get("to-remove") is None
        
        result = registry.remove("not-exist")
        assert result is False

    def test_get_all_stats(self):
        registry = CircuitBreakerRegistry()
        registry.get_or_create("breaker1")
        registry.get_or_create("breaker2")
        
        stats = registry.get_all_stats()
        
        assert "breaker1" in stats
        assert "breaker2" in stats
        assert stats["breaker1"]["state"] == "closed"

    def test_reset_all(self):
        registry = CircuitBreakerRegistry()
        registry.get_or_create("breaker1")
        registry.get_or_create("breaker2")
        
        # Open one
        breaker1 = registry.get("breaker1")
        breaker1.state = CircuitState.OPEN
        
        registry.reset_all()
        
        assert registry.get("breaker1").state == CircuitState.CLOSED
        assert registry.get("breaker2").state == CircuitState.CLOSED


class TestCircuitBreakerDecorator:
    @pytest.mark.asyncio
    async def test_circuit_breaker_decorator(self):
        config = CircuitBreakerConfig(failure_threshold=2, timeout_seconds=1.0)
        
        @circuit_breaker("decorated-func", config)
        async def failing_func():
            raise Exception("Always fails")
        
        # First failure
        with pytest.raises(Exception):
            await failing_func()
        
        # Second failure - should open
        with pytest.raises(Exception):
            await failing_func()
        
        # Third call - circuit open
        with pytest.raises(CircuitBreakerOpenError):
            await failing_func()

    @pytest.mark.asyncio
    async def test_circuit_breaker_decorator_success(self):
        config = CircuitBreakerConfig(failure_threshold=2, timeout_seconds=1.0)
        
        call_count = 0
        
        @circuit_breaker("success-func", config)
        async def sometimes_fails():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return "success"
        
        # Fail twice
        for _ in range(2):
            with pytest.raises(Exception):
                await sometimes_fails()
        
        # Wait for half-open
        await asyncio.sleep(1.1)
        
        # Should succeed now
        result = await sometimes_fails()
        assert result == "success"


class TestCircuitBreakerConfigs:
    def test_http_api_config(self):
        config = CircuitBreakerConfigs.HTTP_API
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout_seconds == 30.0
        assert asyncio.CancelledError in config.excluded_exceptions

    def test_database_config(self):
        config = CircuitBreakerConfigs.DATABASE
        assert config.failure_threshold == 3
        assert config.timeout_seconds == 10.0

    def test_external_api_config(self):
        config = CircuitBreakerConfigs.EXTERNAL_API
        assert config.failure_threshold == 10
        assert config.timeout_seconds == 60.0

    def test_redis_config(self):
        config = CircuitBreakerConfigs.REDIS
        assert config.failure_threshold == 3
        assert config.timeout_seconds == 5.0


class TestCallWithCircuitBreaker:
    @pytest.mark.asyncio
    async def test_call_with_circuit_breaker(self):
        async def success_func():
            return "success"
        
        result = await call_with_circuit_breaker(
            "test-func",
            success_func,
            config=CircuitBreakerConfig(failure_threshold=2),
        )
        
        assert result == "success"

    @pytest.mark.asyncio
    async def test_call_with_circuit_breaker_failure(self):
        async def fail_func():
            raise Exception("Failed")
        
        with pytest.raises(Exception):
            await call_with_circuit_breaker(
                "fail-func",
                fail_func,
                config=CircuitBreakerConfig(failure_threshold=1),
            )