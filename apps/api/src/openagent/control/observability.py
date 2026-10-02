"""MP26: unified observability (§16-24) — correlation, structured logs,
centralized redaction, metrics catalog, OTel-compatible tracing,
platform events, SLI/SLO + error budgets.

Failure-safe by design: every emitter degrades to a no-op (never raises)
so monitoring outages cannot break execution (§100.14-15).
"""

from __future__ import annotations

import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# ------------------------------------------------------- correlation (§17) ---
_current_context: ContextVar[dict[str, str]] = ContextVar(
    "openagent_correlation", default={})

CORRELATION_KEYS = ("request_id", "trace_id", "span_id", "execution_id",
                    "task_id", "organization_id")


def new_ids() -> dict[str, str]:
    return {"request_id": f"req_{uuid.uuid4().hex[:16]}",
            "trace_id": uuid.uuid4().hex,
            "span_id": uuid.uuid4().hex[:16]}


def bind_context(**values: str) -> dict[str, str]:
    current = dict(_current_context.get())
    for key in CORRELATION_KEYS:
        if values.get(key):
            current[key] = str(values[key])
    _current_context.set(current)
    return current


def get_context() -> dict[str, str]:
    return dict(_current_context.get())


def clear_context() -> None:
    _current_context.set({})


def trace_chain() -> str:
    ctx = get_context()
    return " -> ".join(v for k, v in ctx.items()
                       if k in CORRELATION_KEYS and v)


# --------------------------------------------------------- redaction (§20) ---
_SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"id[_-]?token|refresh[_-]?token|auth|authorization|cookie|"
    r"set-cookie|private[_-]?key|oauth|client[_-]?secret|"
    r"webhook[_-]?secret|mfa[_-]?secret|recovery[_-]?code|credential|"
    r"session[_-]?token|(^|_)token(_|$))", re.IGNORECASE)

_SECRET_VALUE_RES = (
    re.compile(r"sk-(live|test)-[A-Za-z0-9]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)


def redact(value: Any) -> Any:
    """Redact secrets BEFORE persistence. Never returns secret material."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SECRET_KEY_RE.search(str(k)) else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        out = value
        for pattern in _SECRET_VALUE_RES:
            out = pattern.sub("[REDACTED]", out)
        return out
    return value


# --------------------------------------------------- structured logs (§19) ---
def log_event(service: str, event: str, level: str = "INFO",
              **fields: Any) -> dict[str, Any]:
    """Build a structured log record (redacted, correlation-attached)."""
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "level": level.upper(), "service": service, "event": event}
    record.update(get_context())
    record.update(redact(fields))
    return record


# ------------------------------------------------------ metrics (§21, §44) ---
# Canonical metric names. Real values come from the existing
# MetricsCollector / commerce usage; this catalog prevents metric-name
# sprawl and fake-metric invention.
METRIC_CATALOG: dict[str, dict[str, str]] = {
    "api.request.count": {"kind": "counter", "unit": "requests"},
    "api.request.latency_seconds": {"kind": "histogram", "unit": "seconds"},
    "api.error.rate": {"kind": "gauge", "unit": "ratio"},
    "api.rate_limit.count": {"kind": "counter", "unit": "events"},
    "workflow.execution.count": {"kind": "counter", "unit": "executions"},
    "workflow.failure.rate": {"kind": "gauge", "unit": "ratio"},
    "workflow.latency_seconds": {"kind": "histogram", "unit": "seconds"},
    "agent.runs": {"kind": "counter", "unit": "runs"},
    "agent.steps": {"kind": "counter", "unit": "steps"},
    "agent.failures": {"kind": "counter", "unit": "events"},
    "agent.tool.calls": {"kind": "counter", "unit": "calls"},
    "worker.count": {"kind": "gauge", "unit": "workers"},
    "worker.utilization": {"kind": "gauge", "unit": "ratio"},
    "worker.failures": {"kind": "counter", "unit": "events"},
    "worker.restarts": {"kind": "counter", "unit": "events"},
    "queue.depth": {"kind": "gauge", "unit": "messages"},
    "queue.latency_seconds": {"kind": "histogram", "unit": "seconds"},
    "queue.failure.rate": {"kind": "gauge", "unit": "ratio"},
    "artifact.count": {"kind": "gauge", "unit": "artifacts"},
    "storage.bytes": {"kind": "gauge", "unit": "bytes"},
    "storage.upload.latency_seconds": {"kind": "histogram", "unit": "seconds"},
    "storage.download.latency_seconds": {"kind": "histogram", "unit": "seconds"},
    "ratelimit.usage": {"kind": "gauge", "unit": "ratio"},
}


class Telemetry:
    """Failure-safe telemetry facade (metrics + events + spans).

    All methods swallow their own errors: a metrics/logging outage must
    never break execution or alerting paths.
    """

    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._observations: dict[str, list[float]] = {}
        self._spans: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self.disabled = False

    def _safe(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            if self.disabled:
                return None
            return fn(*args, **kwargs)
        except Exception:
            return None

    def counter(self, name: str, value: float = 1.0,
                labels: Optional[dict[str, str]] = None) -> None:
        def _do() -> None:
            key = f"{name}|{sorted((labels or {}).items())}"
            self._counters[key] = self._counters.get(key, 0.0) + value
        self._safe(_do)

    def gauge(self, name: str, value: float,
              labels: Optional[dict[str, str]] = None) -> None:
        def _do() -> None:
            key = f"{name}|{sorted((labels or {}).items())}"
            self._gauges[key] = value
        self._safe(_do)

    def observe(self, name: str, value: float) -> None:
        def _do() -> None:
            self._observations.setdefault(name, []).append(value)
            if len(self._observations[name]) > 5000:
                del self._observations[name][:1000]
        self._safe(_do)

    def snapshot(self) -> dict[str, Any]:
        try:
            return {"counters": dict(self._counters),
                    "gauges": dict(self._gauges),
                    "observations": {k: len(v) for k, v in self._observations.items()}}
        except Exception:
            return {"counters": {}, "gauges": {}, "observations": {}}

    def rate_limit_status(self, *, limit: int, used: int,
                          reset_at: datetime) -> dict[str, Any]:
        remaining = max(0, limit - used)
        return {"limit": limit, "used": used, "remaining": remaining,
                "reset": reset_at.isoformat(),
                "usage_ratio": (used / limit) if limit else 0.0}


# --------------------------------------------------------- tracing (§18) ---
TRACEABLE_SERVICES = ("api", "control_plane", "dispatcher", "queue",
                      "worker", "execution", "agent", "tool", "mcp",
                      "browser", "code_agent", "sandbox", "connector",
                      "model_provider", "storage")


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str = ""
    service: str = ""
    operation: str = ""
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "OK"

    def finish(self, status: str = "OK", **attrs: Any) -> "Span":
        self.ended_at = time.monotonic()
        self.status = status
        self.attributes.update(redact(attrs))
        return self

    @property
    def duration_ms(self) -> float:
        end = self.ended_at or time.monotonic()
        return max(0.0, (end - self.started_at) * 1000.0)

    def to_dict(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id, "span_id": self.span_id,
                "parent_id": self.parent_id, "service": self.service,
                "operation": self.operation,
                "duration_ms": round(self.duration_ms, 3),
                "status": self.status,
                "attributes": redact(self.attributes)}


class Tracer:
    """OTel-compatible span builder (dict export; real OTel optional)."""

    def __init__(self, telemetry: Optional[Telemetry] = None) -> None:
        self.telemetry = telemetry or Telemetry()

    def start(self, service: str, operation: str,
              parent: Optional[Span] = None, **attrs: Any) -> Span:
        ctx = get_context()
        trace_id = parent.trace_id if parent else ctx.get("trace_id") or uuid.uuid4().hex
        span = Span(trace_id=trace_id, span_id=uuid.uuid4().hex[:16],
                    parent_id=parent.span_id if parent else "",
                    service=service, operation=operation,
                    attributes=redact(attrs))
        return span

    def export(self, span: Span) -> None:
        self.telemetry._events.append({"kind": "span", **span.to_dict()})


# -------------------------------------------------- platform events (§85-86) ---
def platform_event(event_type: str, *, source: str, actor: str = "",
                   scope: str = "platform", payload: Optional[dict[str, Any]] = None,
                   request_id: str = "") -> dict[str, Any]:
    from openagent.control.types import PLATFORM_EVENTS
    if event_type not in PLATFORM_EVENTS:
        raise ValueError(f"unknown platform event {event_type}")
    ctx = get_context()
    return {"event_id": f"evt_{uuid.uuid4().hex[:16]}",
            "event_type": event_type, "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor, "scope": scope,
            "payload": redact(dict(payload or {})),
            "request_id": request_id or ctx.get("request_id", "")}


# ------------------------------------------------------- SLI / SLO (§22-24) ---
@dataclass
class SLIDefinition:
    name: str
    description: str
    unit: str  # "ratio" | "seconds" | "count"
    target: float = 0.0
    window: str = "30d"

    def evaluate(self, good: float, total: float) -> dict[str, Any]:
        if total <= 0:
            return {"sli": self.name, "value": None, "target": self.target,
                    "met": None, "reason": "no data (not claimed met)"}
        value = good / total
        return {"sli": self.name, "value": round(value, 5),
                "target": self.target, "met": value >= self.target,
                "window": self.window}


STANDARD_SLIS = (
    SLIDefinition("api.availability", "Successful API responses / total", "ratio", 0.999),
    SLIDefinition("execution.success", "Succeeded executions / terminal", "ratio", 0.99),
    SLIDefinition("queue.latency", "Queue wait within 60s / total dequeued", "ratio", 0.95),
    SLIDefinition("scheduler.delay", "On-time schedule fires / total", "ratio", 0.99),
    SLIDefinition("artifact.availability", "Successful downloads / attempts", "ratio", 0.999),
    SLIDefinition("worker.availability", "Healthy workers / registered", "ratio", 0.99),
    SLIDefinition("control_plane.availability", "Successful control ops / total", "ratio", 0.999),
)


@dataclass
class ErrorBudget:
    slo_target: float
    window: str = "30d"

    def allowed_error_ratio(self) -> float:
        return max(0.0, 1.0 - self.slo_target)

    def evaluate(self, good: float, total: float) -> dict[str, Any]:
        if total <= 0:
            return {"consumed": 0.0, "remaining": 1.0, "exhausted": False,
                    "reason": "no data"}
        error_ratio = 1.0 - (good / total)
        allowed = self.allowed_error_ratio()
        consumed = (error_ratio / allowed) if allowed > 0 else (1.0 if error_ratio > 0 else 0.0)
        return {"consumed": round(consumed, 4),
                "remaining": round(max(0.0, 1.0 - consumed), 4),
                "exhausted": consumed >= 1.0, "window": self.window}
