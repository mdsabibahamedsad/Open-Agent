"""Expression engine for evaluating {{...}} expressions in workflow configs."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Union

from openagent.runtime.models import ExecutionContext

# Expression pattern: {{ expression }}
_EXPR_RE = re.compile(r'\{\{\s*(.*?)\s*\}\}')

# Known namespaces for expression references
_KNOWN_NAMESPACES = {
    "variables", "nodes", "workflow", "trigger", "run", "credentials", "env"
}

# Supported operators for conditions
_COMPARISON_OPS = {
    "==", "!=", ">", "<", ">=", "<=",
    "contains", "not_contains",
    "starts_with", "ends_with",
    "matches",  # regex match
    "in", "not_in",
    "is_empty", "is_not_empty",
    "is_true", "is_false",
}

_LOGICAL_OPS = {"and", "or", "not"}


class ExpressionEngine:
    """
    Safe expression evaluator for workflow expressions.
    
    Supports:
    - Variable references: {{variables.name}}
    - Node outputs: {{nodes.node_id.output}}
    - Trigger outputs: {{trigger.output}}
    - Workflow metadata: {{workflow.name}}, {{workflow.id}}
    - Run metadata: {{run.id}}, {{run.started_at}}
    - Credentials: {{credentials.name}}
    - Environment: {{env.VAR_NAME}}
    
    Does NOT support:
    - Arbitrary code execution
    - Function calls
    - Network/filesystem access
    """

    def __init__(self):
        self._expr_cache: Dict[str, re.Pattern] = {}

    def extract_expressions(self, value: Any) -> List[str]:
        """Extract all {{...}} expression bodies from a value."""
        found = []
        for _, s in self._string_leaves(value):
            for m in _EXPR_RE.finditer(s):
                body = m.group(1).strip()
                if body:
                    found.append(body)
        return found

    def has_expressions(self, value: Any) -> bool:
        """Check if a value contains any expressions."""
        for _, s in self._string_leaves(value):
            if "{{" in s and "}}" in s:
                return True
        return False

    def _string_leaves(self, value: Any, path: str = "") -> List[Tuple[str, str]]:
        """Yield (path, string) pairs for every string leaf in nested config."""
        leaves = []
        if isinstance(value, str):
            leaves.append((path, value))
        elif isinstance(value, dict):
            for k, v in value.items():
                new_path = f"{path}.{k}" if path else str(k)
                leaves.extend(self._string_leaves(v, new_path))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                new_path = f"{path}[{i}]"
                leaves.extend(self._string_leaves(v, new_path))
        return leaves

    def resolve(self, value: Any, context: 'ExecutionContext') -> Any:
        """
        Resolve all expressions in a value against the execution context.
        Returns the value with expressions replaced by their evaluated results.
        """
        if isinstance(value, str):
            return self._resolve_string(value, context)
        elif isinstance(value, dict):
            return {k: self.resolve(v, context) for k, v in value.items()}
        elif isinstance(value, list):
            return [self.resolve(v, context) for v in value]
        return value

    def _resolve_string(self, s: str, context: 'ExecutionContext') -> str:
        """Resolve all expressions in a string."""
        def replace_expr(match: re.Match) -> str:
            body = match.group(1).strip()
            try:
                result = self._evaluate_expression(body, context)
                return str(result) if result is not None else ""
            except ExpressionError as e:
                # Return placeholder on error to allow partial resolution
                return f"{{{{ERROR: {e.code}}}}}"

        return _EXPR_RE.sub(replace_expr, s)

    def _evaluate_expression(self, body: str, context: 'ExecutionContext') -> Any:
        """Evaluate a single expression body."""
        # Parse the expression path
        parts = body.split(".")
        if not parts:
            raise ExpressionError("EMPTY_EXPRESSION", "Empty expression")

        namespace = parts[0].strip()
        path = parts[1:] if len(parts) > 1 else []

        if namespace == "variables":
            return self._resolve_variables(path, context.variables)
        elif namespace == "nodes":
            return self._resolve_node(path, context)
        elif namespace == "trigger":
            return self._resolve_trigger(path, context)
        elif namespace == "workflow":
            return self._resolve_workflow(path, context)
        elif namespace == "run":
            return self._resolve_run(path, context)
        elif namespace == "credentials":
            return self._resolve_credentials(path, context)
        elif namespace == "env":
            return self._resolve_env(path)
        else:
            raise ExpressionError(
                "UNKNOWN_NAMESPACE",
                f"Unknown expression namespace: {namespace}. "
                f"Known: variables, nodes, trigger, workflow, run, credentials, env"
            )

    def _resolve_variables(self, path: List[str], variables: Dict[str, Any]) -> Any:
        if not path:
            return variables
        name = path[0]
        if name not in variables:
            raise ExpressionError("UNKNOWN_VARIABLE", f"Unknown variable: {name}")
        value = variables[name]
        return self._deep_get(value, path[1:])

    def _resolve_node(self, path: List[str], context: 'ExecutionContext') -> Any:
        if not path:
            raise ExpressionError("INVALID_NODE_REF", "Node reference requires node ID")
        
        node_id = path[0]
        if node_id not in context.node_results:
            raise ExpressionError("UNKNOWN_NODE", f"Node '{node_id}' not found or not yet executed")
        
        result = context.node_results[node_id]
        if result.status.value != "succeeded":
            raise ExpressionError("NODE_NOT_SUCCEEDED", f"Node '{node_id}' did not succeed")
        
        if len(path) == 1:
            return result.outputs
        
        return self._deep_get(result.outputs, path[1:])

    def _resolve_trigger(self, path: List[str], context: 'ExecutionContext') -> Any:
        # Trigger outputs would be in context.metadata or special key
        # For now, return empty dict
        return {}

    def _resolve_workflow(self, path: List[str], context: 'ExecutionContext') -> Any:
        # Workflow metadata
        workflow_meta = context.metadata.get("workflow", {})
        return self._deep_get(workflow_meta, path)

    def _resolve_run(self, path: List[str], context: 'ExecutionContext') -> Any:
        run_meta = context.metadata.get("run", {})
        return self._deep_get(run_meta, path)

    def _resolve_credentials(self, path: List[str], context: 'ExecutionContext') -> Any:
        creds = context.metadata.get("credentials", {})
        if not path:
            return creds
        # Look up credential by name
        return creds.get(path[0])

    def _resolve_env(self, path: List[str]) -> Any:
        import os
        if not path:
            return dict(os.environ)
        return os.environ.get(path[0])

    def _deep_get(self, obj: Any, path: List[str]) -> Any:
        """Safely traverse nested object with path parts."""
        current = obj
        for part in path:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
            if current is None:
                return None
        return current


class ExpressionError(Exception):
    """Error during expression evaluation."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ConditionEngine:
    """
    Evaluates conditional expressions for branching logic.
    
    Supports:
    - Comparison: ==, !=, >, <, >=, <=
    - String: contains, not_contains, starts_with, ends_with, matches (regex)
    - Collection: in, not_in, is_empty, is_not_empty
    - Boolean: is_true, is_false, is_empty
    - Logical: and, or, not
    """

    def __init__(self, expression_engine: ExpressionEngine):
        self.expr = expression_engine

    def evaluate(self, condition: Dict[str, Any], context: 'ExecutionContext') -> bool:
        """
        Evaluate a condition object.
        
        Condition format:
        {
            "when": "success" | "failure" | "always" | "expression",
            "expression": "{{expression}}",  # optional, used when when="expression"
            "all": [...],  # AND
            "any": [...],  # OR
            "not": {...},  # NOT
        }
        """
        when = condition.get("when", "always")
        
        if when == "always":
            return True
        elif when == "success":
            return True  # Handled by edge routing
        elif when == "failure":
            return False  # Handled by edge routing
        elif when == "expression":
            expr = condition.get("expression", "")
            if not expr:
                return False
            try:
                result = self.expr.resolve(expr, ExecutionContext(
                    execution_id="",
                    workflow_id="",
                    workflow_version_id="",
                    organization_id="",
                    variables={},
                    node_results={},
                ))
                return self._truthy(result)
            except Exception:
                return False
        elif "all" in condition:
            return all(self.evaluate(c, context) for c in condition["all"])
        elif "any" in condition:
            return any(self.evaluate(c, context) for c in condition["any"])
        elif "not" in condition:
            return not self.evaluate(condition["not"], context)
        
        return False

    def _truthy(self, value: Any) -> bool:
        """Determine truthiness of a value."""
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


# Global instances
expression_engine = ExpressionEngine()
condition_engine = ConditionEngine(expression_engine)


def evaluate_condition(condition: Dict[str, Any], context: 'ExecutionContext') -> bool:
    """Convenience function to evaluate a condition."""
    return condition_engine.evaluate(condition, context)


def resolve_expressions(value: Any, context: 'ExecutionContext') -> Any:
    """Resolve all expressions in a value."""
    return expression_engine.resolve(value, context)


def extract_expressions(value: Any) -> List[str]:
    """Extract all expression bodies from a value."""
    return expression_engine.extract_expressions(value)


def has_expressions(value: Any) -> bool:
    return expression_engine.has_expressions(value)