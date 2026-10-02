"""MP25 unit: queue routing, priority fairness, retry policy, queue ops."""

import pytest

from openagent.cloud.errors import QueueFull
from openagent.cloud.providers import CloudMessage
from openagent.cloud.queues import (
    InMemoryQueueProvider, is_retryable_error, normalize_priority,
    retry_delay_seconds, route_queue,
)
from openagent.cloud.types import QueueName


def test_route_queue_policy():
    assert route_queue(execution_class="workflow", priority="NORMAL") == QueueName.WORKFLOW_DEFAULT
    assert route_queue(execution_class="workflow", priority="HIGH") == QueueName.WORKFLOW_PRIORITY
    assert route_queue(execution_class="agent", priority="CRITICAL") == QueueName.AGENT_PRIORITY
    assert route_queue(execution_class="browser", priority="NORMAL") == QueueName.BROWSER
    assert route_queue(execution_class="code", priority="NORMAL") == QueueName.CODE
    assert route_queue(execution_class="workflow", priority="NORMAL", memory_mb=16384) == QueueName.HIGH_MEMORY
    assert route_queue(execution_class="workflow", priority="NORMAL", cpu_millicores=8000) == QueueName.HIGH_CPU


def test_priority_cannot_be_escalated_without_entitlement():
    assert normalize_priority(requested="CRITICAL", plan_allows_high=True,
                              plan_allows_critical=False) == "HIGH"
    assert normalize_priority(requested="HIGH", plan_allows_high=False,
                              plan_allows_critical=False) == "NORMAL"
    assert normalize_priority(requested="CRITICAL", plan_allows_high=True,
                              plan_allows_critical=True) == "CRITICAL"
    assert normalize_priority(requested="BOGUS", plan_allows_high=True,
                              plan_allows_critical=True) == "NORMAL"


def test_retry_classification():
    assert is_retryable_error("temporary network error")
    assert is_retryable_error("worker unavailable")
    assert not is_retryable_error("invalid workflow definition")
    assert not is_retryable_error("permission denied for org")
    assert not is_retryable_error("policy violation: egress blocked")
    assert not is_retryable_error("quota exceeded")
    # Unknown errors default to non-destructive caution (retryable only if transient).
    assert retry_delay_seconds(1) < retry_delay_seconds(3) < 601


@pytest.mark.asyncio
async def test_inmemory_queue_publish_claim_ack():
    provider = InMemoryQueueProvider()
    message = CloudMessage(message_id="", queue="workflow.default",
                           execution_id="cexe_1", organization_id="org-1",
                           priority="NORMAL", payload={"a": 1})
    mid = await provider.publish("workflow.default", message)
    assert mid
    assert await provider.depth("workflow.default") == 1
    claimed = await provider.claim("workflow.default", "worker-1")
    assert claimed is not None and claimed.execution_id == "cexe_1"
    assert claimed.attempt == 1
    await provider.ack("workflow.default", claimed.message_id, "worker-1")
    assert await provider.depth("workflow.default") == 0


@pytest.mark.asyncio
async def test_queue_crash_recovery_requeues_expired_claim():
    provider = InMemoryQueueProvider()
    message = CloudMessage(message_id="", queue="q", execution_id="cexe_9",
                           organization_id="org-1", priority="NORMAL", payload={})
    await provider.publish("q", message)
    claimed = await provider.claim("q", "worker-A", visibility_seconds=0)
    assert claimed is not None
    # Worker A crashed (never acked). Next claim recovers the message.
    recovered = await provider.claim("q", "worker-B", visibility_seconds=60)
    assert recovered is not None and recovered.execution_id == "cexe_9"


@pytest.mark.asyncio
async def test_queue_backpressure_rejects_when_full():
    provider = InMemoryQueueProvider(max_depth=1)
    await provider.publish("q", CloudMessage(message_id="", queue="q",
                                             execution_id="a", organization_id="o",
                                             priority="NORMAL", payload={}))
    with pytest.raises(QueueFull):
        await provider.publish("q", CloudMessage(message_id="", queue="q",
                                                 execution_id="b", organization_id="o",
                                                 priority="NORMAL", payload={}))


@pytest.mark.asyncio
async def test_dead_letter_and_requeue():
    provider = InMemoryQueueProvider()
    await provider.publish("q", CloudMessage(message_id="", queue="q",
                                             execution_id="cexe_dlq",
                                             organization_id="org-1",
                                             priority="NORMAL", payload={"x": 1}))
    claimed = await provider.claim("q", "worker-1")
    assert claimed is not None
    await provider.dead_letter("q", claimed.message_id, "max attempts exceeded")
    entries = await provider.dlq_entries("q")
    assert len(entries) == 1 and entries[0]["reason"] == "max attempts exceeded"
    assert await provider.requeue_dlq("q", entries[0]["message_id"]) is True
    assert await provider.depth("q") == 1
