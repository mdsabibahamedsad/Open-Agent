"""MP25 unit: canonical execution + worker lifecycles."""

from openagent.cloud.types import (
    ExecutionState, WorkerState,
    is_valid_execution_transition, is_valid_worker_transition,
    TERMINAL_EXECUTION_STATES,
)


def test_valid_execution_paths():
    assert is_valid_execution_transition("QUEUED", "DISPATCHING")
    assert is_valid_execution_transition("RUNNING", "SUCCEEDED")
    assert is_valid_execution_transition("RUNNING", "FAILED")
    assert is_valid_execution_transition("RUNNING", "WAITING")
    assert is_valid_execution_transition("WAITING", "RUNNING")
    assert is_valid_execution_transition("RUNNING", "CANCELLED")
    assert is_valid_execution_transition("FAILED", "RETRYING")
    assert is_valid_execution_transition("RETRYING", "QUEUED")


def test_invalid_execution_transitions_rejected():
    # Skips are never allowed.
    assert not is_valid_execution_transition("QUEUED", "RUNNING")
    assert not is_valid_execution_transition("QUEUED", "SUCCEEDED")
    # Terminal states are final (except retry edges).
    assert not is_valid_execution_transition("SUCCEEDED", "RUNNING")
    assert not is_valid_execution_transition("CANCELLED", "QUEUED")
    assert not is_valid_execution_transition("FAILED", "SUCCEEDED")
    # Unknown states fail safe.
    assert not is_valid_execution_transition("NOPE", "QUEUED")
    assert not is_valid_execution_transition("QUEUED", "NOPE")


def test_idempotent_redelivery_allowed():
    assert is_valid_execution_transition("RUNNING", "RUNNING")
    assert is_valid_execution_transition("QUEUED", "QUEUED")


def test_terminal_set():
    assert "SUCCEEDED" in TERMINAL_EXECUTION_STATES
    assert "RUNNING" not in TERMINAL_EXECUTION_STATES


def test_worker_lifecycle():
    assert is_valid_worker_transition("REGISTERING", "STARTING")
    assert is_valid_worker_transition("READY", "BUSY")
    assert is_valid_worker_transition("BUSY", "DRAINING")
    assert is_valid_worker_transition("DRAINING", "OFFLINE")
    assert not is_valid_worker_transition("REGISTERING", "BUSY")
    assert not is_valid_worker_transition("TERMINATED", "READY")
    assert not is_valid_worker_transition("READY", "TERMINATED")
