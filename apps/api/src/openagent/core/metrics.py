import time
import asyncio
try:
    import psutil
except ImportError:  # optional: only SystemMetricsCollector needs it
    psutil = None
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from functools import wraps

from openagent.core.config import get_settings


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class Metric:
    name: str
    type: MetricType
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    help_text: str = ""


class MetricsCollector:
    """In-memory metrics collector for Prometheus-compatible metrics."""
    
    def __init__(self):
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._summaries: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._labels: Dict[str, Dict[str, str]] = {}
        self._help_text: Dict[str, str] = {}
        self._lock = asyncio.Lock()
    
    def counter(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
        help_text: str = "",
    ) -> None:
        """Increment a counter."""
        key = self._make_key(name, labels)
        self._counters[key] += value
        self._labels[key] = labels or {}
        self._help_text[key] = help_text
    
    def gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        help_text: str = "",
    ) -> None:
        """Set a gauge value."""
        key = self._make_key(name, labels)
        self._gauges[key] = value
        self._labels[key] = labels or {}
        self._help_text[key] = help_text
    
    def histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        help_text: str = "",
        buckets: Optional[List[float]] = None,
    ) -> None:
        """Record a histogram value."""
        key = self._make_key(name, labels)
        self._histograms[key].append(value)
        self._labels[key] = labels or {}
        self._help_text[key] = help_text
    
    def summary(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        help_text: str = "",
    ) -> None:
        """Record a summary value."""
        key = self._make_key(name, labels)
        self._summaries[key].append(value)
        self._labels[key] = labels or {}
        self._help_text[key] = help_text
    
    def timing(
        self,
        name: str,
        duration_seconds: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record a timing measurement."""
        self.histogram(name, duration_seconds, labels, buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
    
    def _make_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    
    def get_all(self) -> Dict[str, Any]:
        """Get all metrics in Prometheus format."""
        result = {}
        
        for key, value in self._counters.items():
            result[key] = {
                "type": "counter",
                "value": value,
                "labels": self._labels.get(key, {}),
                "help": self._help_text.get(key, ""),
            }
        
        for key, value in self._gauges.items():
            result[key] = {
                "type": "gauge",
                "value": value,
                "labels": self._labels.get(key, {}),
                "help": self._help_text.get(key, ""),
            }
        
        for key, values in self._histograms.items():
            if values:
                result[key] = {
                    "type": "histogram",
                    "count": len(values),
                    "sum": sum(values),
                    "min": min(values),
                    "max": max(values),
                    "avg": sum(values) / len(values),
                    "labels": self._labels.get(key, {}),
                    "help": self._help_text.get(key, ""),
                }
        
        for key, values in self._summaries.items():
            if values:
                sorted_values = sorted(values)
                count = len(sorted_values)
                result[key] = {
                    "type": "summary",
                    "count": count,
                    "sum": sum(sorted_values),
                    "min": sorted_values[0],
                    "max": sorted_values[-1],
                    "p50": sorted_values[int(count * 0.5)],
                    "p90": sorted_values[int(count * 0.9)],
                    "p99": sorted_values[int(count * 0.99)],
                    "labels": self._labels.get(key, {}),
                    "help": self._help_text.get(key, ""),
                }
        
        return result
    
    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        
        for key, value in self._counters.items():
            labels = self._format_labels(self._labels.get(key, {}))
            lines.append(f"# TYPE {key} counter")
            lines.append(f"# HELP {key} {self._help_text.get(key, '')}")
            lines.append(f"{key}{labels} {value}")
        
        for key, value in self._gauges.items():
            labels = self._format_labels(self._labels.get(key, {}))
            lines.append(f"# TYPE {key} gauge")
            lines.append(f"# HELP {key} {self._help_text.get(key, '')}")
            lines.append(f"{key}{labels} {value}")
        
        for key, values in self._histograms.items():
            if values:
                labels = self._format_labels(self._labels.get(key, {}))
                lines.append(f"# TYPE {key} histogram")
                lines.append(f"# HELP {key} {self._help_text.get(key, '')}")
                lines.append(f"{key}_count{labels} {len(values)}")
                lines.append(f"{key}_sum{labels} {sum(values)}")
        
        for key, values in self._summaries.items():
            if values:
                labels = self._format_labels(self._labels.get(key, {}))
                lines.append(f"# TYPE {key} summary")
                lines.append(f"# HELP {key} {self._help_text.get(key, '')}")
                sorted_values = sorted(values)
                count = len(sorted_values)
                lines.append(f"{key}_count{labels} {count}")
                lines.append(f"{key}_sum{labels} {sum(values)}")
        
        return "\n".join(lines) + "\n"
    
    def _format_labels(self, labels: Dict[str, str]) -> str:
        if not labels:
            return ""
        return "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"


# Global metrics collector
metrics = MetricsCollector()


# System metrics collection
class SystemMetricsCollector:
    """Collects system-level metrics (requires the optional psutil package)."""

    def __init__(self):
        if psutil is None:
            raise RuntimeError(
                "SystemMetricsCollector requires the optional 'psutil' "
                "package, which is not installed."
            )
        self._process = psutil.Process(os.getpid())
        self._last_cpu_times = None
        self._last_cpu_time = time.time()
    
    async def collect(self) -> Dict[str, float]:
        """Collect system metrics."""
        metrics = {}
        
        # CPU usage
        cpu_percent = self._process.cpu_percent()
        metrics["process_cpu_percent"] = cpu_percent
        
        # Memory usage
        memory_info = self._process.memory_info()
        metrics["process_memory_rss_bytes"] = memory_info.rss
        metrics["process_memory_vms_bytes"] = memory_info.vms
        metrics["process_memory_percent"] = self._process.memory_percent()
        
        # Thread count
        metrics["process_thread_count"] = self._process.num_threads()
        
        # File descriptors (Unix only)
        try:
            metrics["process_open_fds"] = self._process.num_fds()
        except AttributeError:
            pass
        
        # System CPU
        metrics["system_cpu_percent"] = psutil.cpu_percent()
        
        # System memory
        sys_mem = psutil.virtual_memory()
        metrics["system_memory_total_bytes"] = sys_mem.total
        metrics["system_memory_available_bytes"] = sys_mem.available
        metrics["system_memory_percent"] = sys_mem.percent
        
        # Disk usage
        disk = psutil.disk_usage("/")
        metrics["disk_total_bytes"] = disk.total
        metrics["disk_free_bytes"] = disk.free
        metrics["disk_used_percent"] = (disk.used / disk.total) * 100
        
        # Network I/O
        net_io = psutil.net_io_counters()
        metrics["network_bytes_sent"] = net_io.bytes_sent
        metrics["network_bytes_recv"] = net_io.bytes_recv
        
        return metrics
    
    def record_metrics(self, collector: MetricsCollector) -> None:
        """Record metrics to collector."""
        metrics = asyncio.run(self.collect())
        for name, value in metrics.items():
            collector.gauge(name, value)


# Global system metrics collector (None when the optional psutil package
# is unavailable — HTTP request metrics are unaffected).
try:
    system_metrics = SystemMetricsCollector()
except RuntimeError:
    system_metrics = None


# Decorator for timing functions
def timed(name: str, labels: Optional[Dict[str, str]] = None):
    """Decorator to time async function execution."""
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                duration = time.perf_counter() - start
                metrics.timing(name, duration, labels)
        return wrapper
    return decorator


# Decorator for counting calls
def counted(name: str, labels: Optional[Dict[str, str]] = None, increment: float = 1.0):
    """Decorator to count function calls."""
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            finally:
                metrics.counter(name, increment, labels)
        return wrapper
    return decorator


# Context manager for timing
@asynccontextmanager
async def timed_context(name: str, labels: Optional[Dict[str, str]] = None):
    """Context manager for timing operations."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        metrics.timing(name, duration, labels)


# Middleware for automatic request metrics
class MetricsMiddleware:
    """Middleware to collect HTTP request metrics."""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.perf_counter()
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        
        # Normalize path for cardinality control
        normalized_path = self._normalize_path(path)
        
        status_code = 500
        
        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)
        
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status_code = 500
            raise
        finally:
            duration = time.perf_counter() - start
            
            # Record metrics
            labels = {
                "method": method,
                "path": normalized_path,
                "status": str(status_code),
            }
            
            metrics.counter("http_requests_total", 1.0, labels)
            metrics.timing("http_request_duration_seconds", time.perf_counter() - start_time, labels)
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path to reduce cardinality."""
        # Replace UUIDs and IDs with placeholders
        import re
        path = re.sub(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '/{uuid}', path)
        path = re.sub(r'/\d+', '/{id}', path)
        return path


# Health check metrics
async def record_health_metrics():
    """Record health check metrics."""
    # This would be called periodically
    pass


# Prometheus metrics endpoint
async def metrics_endpoint() -> str:
    """Return metrics in Prometheus format."""
    return metrics.to_prometheus()


# Health check with metrics
async def health_check_with_metrics():
    """Health check that also records metrics."""
    start = time.perf_counter()
    try:
        # Perform health checks
        # ... health check logic ...
        duration = time.perf_counter() - start
        metrics.counter("health_check_duration_seconds", duration, {"status": "success"})
        return {"status": "healthy"}
    except Exception as e:
        duration = time.perf_counter() - start
        metrics.counter("health_check_duration_seconds", duration, {"status": "failure"})
        return {"status": "unhealthy", "error": str(e)}


# Dependency for metrics
def get_metrics() -> MetricsCollector:
    return metrics


# Import needed modules
import asyncio
import time