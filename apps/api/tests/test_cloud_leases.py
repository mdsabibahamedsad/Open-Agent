"""MP25 unit: leases (optimistic concurrency) + distributed locks."""

import pytest

from openagent.cloud.errors import LeaseConflict
from openagent.cloud.leases import (
    InMemoryDistributedLock, InMemoryLeaseBackend,
)


@pytest.mark.asyncio
async def test_lease_acquire_renew_release():
    backend = InMemoryLeaseBackend()
    lease = await backend.acquire("execution:cexe_1", "worker-1", 300)
    assert lease.owner_id == "worker-1" and lease.version == 1
    renewed = await backend.renew(lease, 300)
    assert renewed.version == 2
    await backend.release(renewed)
    # After release another worker may acquire (version increments).
    second = await backend.acquire("execution:cexe_1", "worker-2", 300)
    assert second.owner_id == "worker-2"


@pytest.mark.asyncio
async def test_two_workers_cannot_hold_same_lease():
    backend = InMemoryLeaseBackend()
    await backend.acquire("execution:cexe_2", "worker-1", 300)
    with pytest.raises(LeaseConflict):
        await backend.acquire("execution:cexe_2", "worker-2", 300)


@pytest.mark.asyncio
async def test_expired_lease_becomes_recoverable():
    backend = InMemoryLeaseBackend()
    lease = await backend.acquire("execution:cexe_3", "worker-1", 1)
    # Force expiry.
    from datetime import datetime, timezone
    lease_record = await backend.get("execution:cexe_3")
    assert lease_record is not None
    lease_record.expires_at = datetime.now(timezone.utc)
    recovered = await backend.acquire("execution:cexe_3", "worker-2", 300)
    assert recovered.owner_id == "worker-2"


@pytest.mark.asyncio
async def test_lease_renew_requires_ownership_and_version():
    backend = InMemoryLeaseBackend()
    lease = await backend.acquire("resource-1", "worker-1", 300)
    impostor = type(lease)(lease_id=lease.lease_id, resource=lease.resource,
                           owner_id="worker-2", version=lease.version,
                           created_at=lease.created_at,
                           renewed_at=lease.renewed_at,
                           expires_at=lease.expires_at)
    with pytest.raises(LeaseConflict):
        await backend.renew(impostor, 300)


@pytest.mark.asyncio
async def test_distributed_lock_ownership():
    first = InMemoryDistributedLock("sched-tick", "scheduler-A")
    second = InMemoryDistributedLock("sched-tick", "scheduler-B")
    assert await first.acquire(30) is True
    assert await second.acquire(30) is False
    assert await second.renew(30) is False
    assert await first.renew(30) is True
    await first.release()
    assert await second.acquire(30) is True
    await second.release()
