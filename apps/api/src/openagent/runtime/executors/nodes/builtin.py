"""Built-in node executors for core workflow node types."""

from __future__ import annotations

import json
import re
import asyncio
import time
import hashlib
import hmac
import base64
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse
from dataclasses import field

import aiohttp

from openagent.runtime.executors.base import (
    NodeExecutor,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeRunStatus,
)
from openagent.runtime.models import NodeResult
from openagent.runtime.engine import expression_engine, resolve_expressions


class ManualTriggerExecutor(NodeExecutor):
    """Executor for manual trigger - produces initial workflow input."""
    
    node_type = "manual"
    default_timeout = 5
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        # Manual trigger produces no outputs - it's the entry point
        # The actual input comes from the execution trigger
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={},
            metadata={"trigger_type": "manual"}
        )


class SetNodeExecutor(NodeExecutor):
    """Executor for set node - assigns static values to variables."""
    
    node_type = "set"
    default_timeout = 10
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        values = node_config.get("values", {})
        if not isinstance(values, dict):
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Set node requires 'values' object in config",
                error_code="INVALID_CONFIG"
            )
        
        # Resolve expressions in values
        resolved_values = {}
        for key, value in values.items():
            try:
                resolved_values[key] = resolve_expressions(value, context)
            except Exception as e:
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error=f"Failed to resolve value for '{key}': {e}",
                    error_code="EXPRESSION_ERROR"
                )
        
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"values": resolved_values},
            metadata={"set_keys": list(resolved_values.keys())}
        )


class TransformNodeExecutor(NodeExecutor):
    """Executor for transform node - maps/transforms data using expressions."""
    
    node_type = "transform"
    default_timeout = 30
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        mapping = node_config.get("mapping")
        expression = node_config.get("expression")
        
        if not mapping and not expression:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Transform node requires 'mapping' or 'expression' in config",
                error_code="INVALID_CONFIG"
            )
        
        # Build input context for expressions
        input_data = {
            "input": context.inputs,
            "variables": context.variables,
        }
        
        if expression:
            # Use expression for transformation
            try:
                result = resolve_expressions(expression, context)
                return NodeExecutionResult(
                    status=NodeRunStatus.SUCCEEDED,
                    outputs={"result": result},
                    metadata={"mode": "expression"}
                )
            except Exception as e:
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error=f"Transform expression failed: {e}",
                    error_code="EXPRESSION_ERROR"
                )
        
        if mapping:
            # Use mapping for transformation
            try:
                resolved_mapping = resolve_expressions(mapping, context)
                return NodeExecutionResult(
                    status=NodeRunStatus.SUCCEEDED,
                    outputs=resolved_mapping,
                    metadata={"mode": "mapping"}
                )
            except Exception as e:
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error=f"Transform mapping failed: {e}",
                    error_code="EXPRESSION_ERROR"
                )
        
        return NodeExecutionResult(
            status=NodeRunStatus.FAILED,
            error="No valid transform configuration",
            error_code="INVALID_CONFIG"
        )


class FilterNodeExecutor(NodeExecutor):
    """Executor for filter node - filters collection items by predicate."""
    
    node_type = "filter"
    default_timeout = 30
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        items_expr = node_config.get("items")
        predicate_expr = node_config.get("predicate")
        
        if not items_expr:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Filter node requires 'items' expression in config",
                error_code="INVALID_CONFIG"
            )
        
        if not predicate_expr:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Filter node requires 'predicate' expression in config",
                error_code="INVALID_CONFIG"
            )
        
        try:
            # Resolve the collection to filter
            items = resolve_expressions(items_expr, context)
            
            if not isinstance(items_expr, str) or not items_expr.strip().startswith("{{"):
                # Direct value
                items = items_expr
            
            if not isinstance(items, list):
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error="Filter 'items' must resolve to a list",
                    error_code="INVALID_INPUT"
                )
            
            # Filter items
            filtered = []
            for item in items:
                # Create context with item as current item
                item_context = self._create_item_context(context, item)
                try:
                    result = resolve_expressions(predicate_expr, item_context)
                    if self._truthy(result):
                        filtered.append(item)
                except Exception:
                    # If predicate fails for an item, skip it
                    pass
            
            return NodeExecutionResult(
                status=NodeRunStatus.SUCCEEDED,
                outputs={"items": filtered, "count": len(filtered)},
                metadata={"original_count": len(items_expr) if isinstance(items_expr, list) else "unknown"}
            )
        except Exception as e:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error=f"Filter failed: {e}",
                error_code="EXPRESSION_ERROR"
            )
    
    def _truthy(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() not in ("", "false", "0", "no", "off")
        if isinstance(value, (list, dict, set)):
            return len(value) > 0
        return True
    
    def _create_item_context(self, context: 'NodeExecutionContext', item: Any) -> 'NodeExecutionContext':
        # Create a minimal context for item evaluation
        class ItemContext:
            def __init__(self, base_context, item):
                self.variables = {**base_context.variables, "item": item}
                self.node_results = base_context.node_results
                self.inputs = base_context.inputs
                self.credentials = base_context.credentials
                self.execution_id = base_context.execution_id
                self.workflow_id = base_context.workflow_id
                self.workflow_version_id = base_context.workflow_version_id
                self.organization_id = base_context.organization_id
                self.cancelled = base_context.cancelled
                self.timeout_at = base_context.timeout_at
        
        return ItemContext(context, {})


class MapNodeExecutor(NodeExecutor):
    """Executor for map node - transforms each item in a collection."""
    
    node_type = "map"
    default_timeout = 60
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        items_expr = node_config.get("items")
        expression = node_config.get("expression")
        
        if not items_expr:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Map node requires 'items' expression in config",
                error_code="INVALID_CONFIG"
            )
        
        if not expression:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Map node requires 'expression' in config",
                error_code="INVALID_CONFIG"
            )
        
        try:
            items = resolve_expressions(items_expr, context)
            
            if not isinstance(items, list):
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error="Map 'items' must resolve to a list",
                    error_code="INVALID_INPUT"
                )
            
            results = []
            for item in items:
                item_context = self._create_item_context(context, item)
                try:
                    result = resolve_expressions(expression, item_context)
                    results.append(result)
                except Exception as e:
                    return NodeExecutionResult(
                        status=NodeRunStatus.FAILED,
                        error=f"Map expression failed for item: {e}",
                        error_code="EXPRESSION_ERROR"
                    )
            
            return NodeExecutionResult(
                status=NodeRunStatus.SUCCEEDED,
                outputs={"items": results, "count": len(results)},
                metadata={"original_count": len(items)}
            )
        except Exception as e:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error=f"Map failed: {e}",
                error_code="EXPRESSION_ERROR"
            )


class VariableNodeExecutor(NodeExecutor):
    """Executor for variable node - read/write workflow variables."""
    
    node_type = "variable"
    default_timeout = 5
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        mode = node_config.get("mode", "set")
        name = node_config.get("name")
        value_expr = node_config.get("value")
        
        if not name:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Variable node requires 'name' in config",
                error_code="INVALID_CONFIG"
            )
        
        if mode == "set":
            if value_expr is None:
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error="Variable node in 'set' mode requires 'value' expression",
                    error_code="INVALID_CONFIG"
                )
            
            try:
                value = resolve_expressions(value_expr, context)
                # In a real implementation, this would update the workflow variables
                # For now, we return the value as output
                return NodeExecutionResult(
                    status=NodeRunStatus.SUCCEEDED,
                    outputs={"variable": name, "value": value},
                    metadata={"mode": "set", "variable_name": name}
                )
            except Exception as e:
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error=f"Failed to resolve value: {e}",
                    error_code="EXPRESSION_ERROR"
                )
        
        elif mode == "get":
            # Get variable from context
            if name not in context.variables:
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error=f"Variable '{name}' not found",
                    error_code="VARIABLE_NOT_FOUND"
                )
            
            value = context.variables[name]
            return NodeExecutionResult(
                status=NodeRunStatus.SUCCEEDED,
                outputs={"variable": name, "value": value},
                metadata={"mode": "get", "variable_name": name}
            )
        
        return NodeExecutionResult(
            status=NodeRunStatus.FAILED,
            error=f"Unknown variable mode: {mode}",
            error_code="INVALID_CONFIG"
        )


class DelayNodeExecutor(NodeExecutor):
    """Executor for delay node - pauses execution for a specified duration."""
    
    node_type = "delay"
    default_timeout = 3600  # 1 hour max
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        duration = node_config.get("duration_seconds")
        
        if not isinstance(duration, (int, float)) or duration <= 0:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Delay node requires positive 'duration_seconds' in config",
                error_code="INVALID_CONFIG"
            )
        
        # Cap duration at reasonable max
        max_duration = 86400  # 24 hours
        duration = min(duration, max_duration)
        
        # Calculate resume time
        resume_at = datetime.now(timezone.utc) + timedelta(seconds=duration)
        resume_token = f"delay_{context.node_id}_{int(time.time())}"
        
        return NodeExecutionResult(
            status=NodeRunStatus.WAITING,
            outputs={},
            resume_at=resume_at,
            resume_token=resume_token,
            metadata={
                "duration_seconds": duration,
                "resume_at": resume_at.isoformat(),
            }
        )


class ConditionNodeExecutor(NodeExecutor):
    """Executor for condition/if node - evaluates expression and routes to true/false branch."""
    
    node_type = "condition"
    default_timeout = 10
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        expression = node_config.get("expression")
        
        if not expression:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Condition node requires 'expression' in config",
                error_code="INVALID_CONFIG"
            )
        
        try:
            result = resolve_expressions(expression, context)
            truthy = self._truthy(result)
            
            return NodeExecutionResult(
                status=NodeRunStatus.SUCCEEDED,
                outputs={"condition_result": result, "branch": "true" if truthy else "false"},
                metadata={
                    "condition_value": result,
                    "branch_taken": "true" if truthy else "false"
                }
            )
        except Exception as e:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error=f"Condition evaluation failed: {e}",
                error_code="EXPRESSION_ERROR"
            )
    
    def _truthy(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() not in ("", "false", "0", "no", "off")
        if isinstance(value, (list, dict, set)):
            return len(value) > 0
        return True


class MergeNodeExecutor(NodeExecutor):
    """Executor for merge node - joins multiple branches."""
    
    node_type = "merge"
    default_timeout = 10
    supports_parallel = True
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        mode = node_config.get("mode", "first")
        
        # Get all inputs from upstream nodes
        inputs = context.inputs
        
        if not inputs:
            return NodeExecutionResult(
                status=NodeRunStatus.SUCCEEDED,
                outputs={"merged": {}},
                metadata={"mode": mode, "merged_count": 0}
            )
        
        if mode == "first":
            # Return first available input
            for key, value in inputs.items():
                if value is not None:
                    return NodeExecutionResult(
                        status=NodeRunStatus.SUCCEEDED,
                        outputs={"merged": value, "source": key},
                        metadata={"mode": "first", "source": key}
                    )
        
        elif mode == "all":
            # Merge all inputs
            merged = {}
            for key, value in inputs.items():
                if value is not None:
                    if isinstance(value, dict):
                        merged.update(value)
                    else:
                        merged[key] = value
            return NodeExecutionResult(
                status=NodeRunStatus.SUCCEEDED,
                outputs={"merged": merged},
                metadata={"mode": "all", "merged_keys": list(merged.keys())}
            )
        
        elif mode == "concat":
            # Concatenate arrays
            result = []
            for key, value in inputs.items():
                if isinstance(value, list):
                    result.extend(value)
                elif value is not None:
                    result.append(value)
            return NodeExecutionResult(
                status=NodeRunStatus.SUCCEEDED,
                outputs={"merged": result},
                metadata={"mode": "concat", "count": len(result)}
            )
        
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"merged": {}},
            metadata={"mode": mode}
        )


class LoopNodeExecutor(NodeExecutor):
    """Executor for loop node - iterates over a collection."""
    
    node_type = "loop"
    default_timeout = 3600
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        items_expr = node_config.get("items")
        max_iterations = node_config.get("max_iterations", 100)
        
        if not items_expr:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Loop node requires 'items' expression in config",
                error_code="INVALID_CONFIG"
            )
        
        try:
            items = resolve_expressions(items_expr, context)
            
            if not isinstance(items, list):
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED,
                    error="Loop 'items' must resolve to a list",
                    error_code="INVALID_INPUT"
                )
            
            # Cap iterations
            items = items[:max_iterations]
            
            # For now, just return the items to be iterated
            # In a real implementation, this would create sub-executions
            return NodeExecutionResult(
                status=NodeRunStatus.SUCCEEDED,
                outputs={"items": items, "count": len(items)},
                metadata={
                    "total_items": len(items),
                    "max_iterations": max_iterations,
                }
            )
        except Exception as e:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error=f"Loop items resolution failed: {e}",
                error_code="EXPRESSION_ERROR"
            )


class SwitchNodeExecutor(NodeExecutor):
    """Executor for switch/router node - routes based on expression matching."""
    
    node_type = "switch"
    default_timeout = 10
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        routes = node_config.get("routes", [])
        
        if not isinstance(routes, list) or not routes:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Switch node requires non-empty 'routes' list in config",
                error_code="INVALID_CONFIG"
            )
        
        # Find matching route
        for route in routes:
            if not isinstance(route, dict):
                continue
            
            expression = route.get("expression")
            if not expression:
                continue
            
            try:
                result = resolve_expressions(expression, context)
                if self._truthy(result):
                    return NodeExecutionResult(
                        status=NodeRunStatus.SUCCEEDED,
                        outputs={"matched_route": route.get("name"), "matched_value": result},
                        metadata={
                            "matched_route": route.get("name"),
                            "matched_expression": route.get("expression"),
                        }
                    )
            except Exception:
                continue
        
        # Check for default route
        for route in routes:
            if isinstance(route, dict) and route.get("name") == "default":
                return NodeExecutionResult(
                    status=NodeRunStatus.SUCCEEDED,
                    outputs={"matched_route": "default", "matched_value": True},
                    metadata={"matched_route": "default", "is_default": True}
                )
        
        # No match
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"matched_route": None, "matched_value": False},
            metadata={"matched_route": None, "no_match": True}
        )
    
    def _truthy(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() not in ("", "false", "0", "no", "off")
        if isinstance(value, (list, dict, set)):
            return len(value) > 0
        return True


class ApprovalNodeExecutor(NodeExecutor):
    """Executor for approval node - pauses for human approval."""
    
    node_type = "approval"
    default_timeout = 86400  # 24 hours
    required_capabilities = ["approval"]
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        approvers = node_config.get("approvers", [])
        message = node_config.get("message", "Approval required")
        
        if not isinstance(approvers, list) or not approvers:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Approval node requires non-empty 'approvers' list",
                error_code="INVALID_CONFIG"
            )
        
        # Generate resume token
        resume_token = f"approval_{context.node_id}_{int(time.time())}"
        
        return NodeExecutionResult(
            status=NodeRunStatus.WAITING,
            outputs={},
            resume_at=None,  # No auto-resume for approval
            resume_token=resume_token,
            metadata={
                "approvers": approvers,
                "message": message,
                "resume_token": resume_token,
            }
        )


class WebhookNodeExecutor(NodeExecutor):
    """Executor for webhook/HTTP request node."""
    
    node_type = "webhook"
    default_timeout = 30
    required_capabilities = ["network"]
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        url = node_config.get("url")
        method = node_config.get("method", "POST").upper()
        headers = node_config.get("headers", {})
        body = node_config.get("body")
        credential_id = node_config.get("credential_id")
        
        if not url:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Webhook node requires 'url' in config",
                error_code="INVALID_CONFIG"
            )
        
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error=f"Invalid HTTP method: {method}",
                error_code="INVALID_CONFIG"
            )
        
        # Security: validate URL
        if not self._is_url_allowed(url):
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="URL not allowed by security policy",
                error_code="URL_NOT_ALLOWED"
            )
        
        # Resolve URL and body
        try:
            resolved_url = resolve_expressions(url, context)
            resolved_headers = resolve_expressions(headers, context)
            resolved_body = resolve_expressions(body, context) if body else None
        except Exception as e:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error=f"Expression resolution failed: {e}",
                error_code="EXPRESSION_ERROR"
            )
        
        # Resolve credentials if provided
        resolved_headers = dict(resolved_headers)
        if credential_id:
            # In real implementation, fetch credential from secure store
            # For now, just note it
            resolved_headers["Authorization"] = f"Bearer {{credential:{credential_id}}}"
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method,
                    resolved_url,
                    headers=resolved_headers,
                    json=resolved_body if isinstance(resolved_body, dict) else None,
                    data=resolved_body if isinstance(resolved_body, str) else None,
                ) as response:
                    response_body = await response.text()
                    try:
                        response_json = json.loads(response_body)
                    except json.JSONDecodeError:
                        response_json = response_body
                    
                    return NodeExecutionResult(
                        status=NodeRunStatus.SUCCEEDED if response.status < 400 else NodeRunStatus.FAILED,
                        outputs={
                            "status_code": response.status,
                            "body": response_json,
                            "headers": dict(response.headers),
                        },
                        error=None if response.status < 400 else f"HTTP {response.status}",
                        error_code=f"HTTP_{response.status}" if response.status >= 400 else None,
                        metadata={
                            "url": resolved_url,
                            "method": method,
                            "response_size": len(response_body),
                        }
                    )
        except asyncio.TimeoutError:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Request timeout",
                error_code="TIMEOUT"
            )
        except Exception as e:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error=f"Request failed: {e}",
                error_code="REQUEST_FAILED"
            )
    
    def _is_url_allowed(self, url: str) -> bool:
        """Check if URL is allowed by security policy."""
        try:
            parsed = urlparse(url)
            
            # Only allow HTTP/HTTPS
            if parsed.scheme not in ("http", "https"):
                return False
            
            # Block localhost and private IPs
            hostname = parsed.hostname or ""
            if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                return False
            
            # Block private IP ranges
            if self._is_private_ip(hostname):
                return False
            
            # Block metadata endpoints
            if hostname in ("169.254.169.254", "metadata.google.internal"):
                return False
            
            return True
        except Exception:
            return False
    
    def _is_private_ip(self, hostname: str) -> bool:
        """Check if hostname resolves to private IP."""
        # Simplified check - in production, would resolve DNS
        private_patterns = [
            "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
            "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
            "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
            "192.168.",
        ]
        for pattern in private_patterns:
            if hostname.startswith(pattern):
                return True
        return False


class ToolNodeExecutor(NodeExecutor):
    """Executor for tool node - invokes a registered tool."""
    
    node_type = "tool"
    default_timeout = 60
    required_capabilities = ["tool_execution"]
    
    async def execute(self, node_config: Dict[str, Any], context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        tool_id = node_config.get("tool_id")
        tool_name = node_config.get("tool_name")
        arguments = node_config.get("arguments", {})
        credential_id = node_config.get("credential_id")
        
        if not tool_id and not tool_name:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error="Tool node requires 'tool_id' or 'tool_name' in config",
                error_code="INVALID_CONFIG"
            )
        
        # Resolve arguments
        try:
            resolved_args = resolve_expressions(arguments, context)
        except Exception as e:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                error=f"Failed to resolve arguments: {e}",
                error_code="EXPRESSION_ERROR"
            )
        
        # In a real implementation, this would call the tool registry
        # For now, return a placeholder result
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={
                "tool_id": tool_id,
                "tool_name": tool_name,
                "result": {"message": "Tool execution placeholder"},
            },
            metadata={
                "tool_id": tool_id,
                "tool_name": tool_name,
                "arguments": resolved_args,
            }
        )


# Import required modules
from datetime import datetime, timedelta, timezone
import time
from typing import Optional, Dict, List, Any, Tuple, Set
from dataclasses import field
from collections import defaultdict
from uuid import uuid4
import aiohttp
import json

# Import resolve_expressions
from openagent.runtime.engine import resolve_expressions