"""Executor registry initialization."""

from openagent.runtime.executors.base import executor_registry
from openagent.runtime.executors.nodes.builtin import (
    ManualTriggerExecutor,
    SetNodeExecutor,
    TransformNodeExecutor,
    FilterNodeExecutor,
    MapNodeExecutor,
    VariableNodeExecutor,
    DelayNodeExecutor,
    ConditionNodeExecutor,
    MergeNodeExecutor,
    LoopNodeExecutor,
    SwitchNodeExecutor,
    ApprovalNodeExecutor,
    WebhookNodeExecutor,
    ToolNodeExecutor,
)

# Register all built-in executors
def register_builtin_executors() -> None:
    """Register all built-in node executors."""
    # Lazy imports: agent/orchestration executors depend back on this package.
    from openagent.runtime.agent_executor import AgentNodeExecutor
    from openagent.orchestration.workflow_node import OrchestrationNodeExecutor
    from openagent.runtime.executors.nodes.browser import (
        BrowserActionNodeExecutor,
        BrowserAgentNodeExecutor,
        BrowserExtractNodeExecutor,
    )
    from openagent.runtime.executors.nodes.code import (
        CodeAgentNodeExecutor,
        CodeLintNodeExecutor,
        CodePatchNodeExecutor,
        CodeReadNodeExecutor,
        CodeReviewNodeExecutor,
        CodeSearchNodeExecutor,
        CodeTestNodeExecutor,
        CreatePRNodeExecutor,
        GitCommitNodeExecutor,
    )
    from openagent.runtime.executors.nodes.quality import (
        AssertNodeExecutor,
        CorrectNodeExecutor,
        EvaluateNodeExecutor,
        QualityGateNodeExecutor,
        RetryNodeExecutor,
        VerifyNodeExecutor,
    )
    from openagent.runtime.executors.nodes.connectors import (
        ConnectorActionNodeExecutor,
        ConnectorTriggerNodeExecutor,
        ConnectorSearchNodeExecutor,
        ConnectorResourceNodeExecutor,
    )
    executor_registry.register(ManualTriggerExecutor())
    executor_registry.register(SetNodeExecutor())
    executor_registry.register(TransformNodeExecutor())
    executor_registry.register(FilterNodeExecutor())
    executor_registry.register(MapNodeExecutor())
    executor_registry.register(VariableNodeExecutor())
    executor_registry.register(DelayNodeExecutor())
    executor_registry.register(ConditionNodeExecutor())
    executor_registry.register(MergeNodeExecutor())
    executor_registry.register(LoopNodeExecutor())
    executor_registry.register(SwitchNodeExecutor())
    executor_registry.register(ApprovalNodeExecutor())
    executor_registry.register(WebhookNodeExecutor())
    executor_registry.register(ToolNodeExecutor())
    executor_registry.register(AgentNodeExecutor())
    executor_registry.register(OrchestrationNodeExecutor())
    executor_registry.register(BrowserAgentNodeExecutor())
    executor_registry.register(BrowserActionNodeExecutor())
    executor_registry.register(BrowserExtractNodeExecutor())
    executor_registry.register(CodeAgentNodeExecutor())
    executor_registry.register(CodeSearchNodeExecutor())
    executor_registry.register(CodeReadNodeExecutor())
    executor_registry.register(CodePatchNodeExecutor())
    executor_registry.register(CodeTestNodeExecutor())
    executor_registry.register(CodeLintNodeExecutor())
    executor_registry.register(CodeReviewNodeExecutor())
    executor_registry.register(GitCommitNodeExecutor())
    executor_registry.register(CreatePRNodeExecutor())
    executor_registry.register(VerifyNodeExecutor())
    executor_registry.register(EvaluateNodeExecutor())
    executor_registry.register(AssertNodeExecutor())
    executor_registry.register(QualityGateNodeExecutor())
    executor_registry.register(RetryNodeExecutor())
    executor_registry.register(CorrectNodeExecutor())
    executor_registry.register(ConnectorActionNodeExecutor())
    executor_registry.register(ConnectorTriggerNodeExecutor())
    executor_registry.register(ConnectorSearchNodeExecutor())
    executor_registry.register(ConnectorResourceNodeExecutor())


# Auto-register on import
register_builtin_executors()