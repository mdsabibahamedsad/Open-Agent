"""Built-in orchestration templates using real orchestration primitives."""

from __future__ import annotations

from openagent.orchestration.types import (
    AggregationStrategy,
    DependencyPolicy,
    PlannedTask,
    TaskPlan,
    TaskPriority,
)


def research_team_template(objective: str) -> TaskPlan:
    return TaskPlan(
        objective=objective,
        tasks=[
            PlannedTask(task_id="web_research", title="Web research",
                        required_capabilities=["research.web"], priority=TaskPriority.HIGH),
            PlannedTask(task_id="competitor_research", title="Competitor research",
                        required_capabilities=["research.market"], priority=TaskPriority.HIGH),
            PlannedTask(task_id="analysis", title="Analysis",
                        description="Consolidate findings",
                        dependencies=["web_research", "competitor_research"],
                        dependency_policy=DependencyPolicy.ALL_SUCCESS,
                        required_capabilities=["data.analysis"],
                        aggregation_strategy=AggregationStrategy.SUMMARIZE),
        ],
        metadata={"template": "research_team"},
    )


def software_team_template(objective: str) -> TaskPlan:
    return TaskPlan(
        objective=objective,
        tasks=[
            PlannedTask(task_id="backend", title="Backend",
                        required_capabilities=["coding.python"], priority=TaskPriority.HIGH),
            PlannedTask(task_id="frontend", title="Frontend",
                        required_capabilities=["coding.react"], priority=TaskPriority.HIGH),
            PlannedTask(task_id="testing", title="Testing",
                        dependencies=["backend", "frontend"],
                        dependency_policy=DependencyPolicy.ALL_SUCCESS,
                        required_capabilities=["testing.automation"],
                        aggregation_strategy=AggregationStrategy.VALIDATE),
            PlannedTask(task_id="security_review", title="Security review",
                        dependencies=["testing"],
                        required_capabilities=["security.audit"]),
        ],
        metadata={"template": "software_team"},
    )


def content_team_template(objective: str) -> TaskPlan:
    return TaskPlan(
        objective=objective,
        tasks=[
            PlannedTask(task_id="research", title="Research",
                        required_capabilities=["research.web"]),
            PlannedTask(task_id="draft", title="Draft",
                        dependencies=["research"],
                        required_capabilities=["content.writing"]),
            PlannedTask(task_id="seo", title="SEO pass",
                        dependencies=["draft"],
                        required_capabilities=["seo.research"]),
            PlannedTask(task_id="review", title="Review",
                        dependencies=["seo"],
                        required_capabilities=["content.writing"],
                        aggregation_strategy=AggregationStrategy.VALIDATE),
        ],
        metadata={"template": "content_team"},
    )


TEMPLATES = {
    "research_team": research_team_template,
    "software_team": software_team_template,
    "content_team": content_team_template,
}
