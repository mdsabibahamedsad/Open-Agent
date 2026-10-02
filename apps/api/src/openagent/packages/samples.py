"""MP22: official sample workforce packages.

Real manifests (not execution fakes): installing one creates the declared
agents/workflows/skills graph and wires it to the *existing* runtimes
(Tool Runtime, Model Router, Memory, Browser/Code/Sandbox, approvals).
Execution itself always flows through those engines — nothing here executes
anything directly.
"""

from __future__ import annotations

from typing import Any


def _base(package_id: str, name: str, version: str, description: str,
          categories: list[str], tags: list[str]) -> dict[str, Any]:
    return {
        "format": "openagent-package",
        "format_version": "1",
        "package": {"id": package_id, "name": name, "version": version,
                    "type": "WORKFORCE"},
        "author": {"name": "OpenAgent", "email": "packages@openagent.dev",
                   "url": "https://openagent.dev"},
        "license": "Apache-2.0",
        "visibility": "PUBLIC",
        "trust": "CORE",
        "description": description,
        "categories": categories,
        "tags": tags,
        "dependencies": [],
        "resources": [],
        "configuration": {"inputs": {}},
        "security": {"required_approvals": [], "network": "restricted",
                     "sandbox_profile": "", "risk_notes": ""},
        "compatibility": {"openagent_version": ">=0.1.0", "api_version": "v1",
                          "runtime_version": "*", "feature_requirements": []},
        "evaluation": {"minimum_quality_score": 0.7,
                       "required_checks": ["factuality", "completeness"]},
        "changelog": f"{version}: initial official release.",
    }


def research_workforce() -> dict[str, Any]:
    manifest = _base(
        "openagent.research-workforce", "Research Workforce", "1.0.0",
        "Manager-led research team: web research, browser deep-dives and "
        "sourced reporting with human approval before external sharing.",
        ["Research", "AI & Agents"], ["research", "browser", "reporting"],
    )
    manifest["dependencies"] = [
        {"type": "tool", "package": "browser-search", "version": "^1.0.0"},
        {"type": "connector", "package": "slack", "version": ">=1.0.0", "optional": True},
    ]
    manifest["resources"] = [
        {"kind": "SKILL", "slug": "web-research",
         "name": "Web Research",
         "payload": {
             "instructions": "Search authoritative sources, cross-check at least two independent sources, record citations.",
             "input_schema": {"type": "object", "properties": {"topic": {"type": "string"}}},
             "output_schema": {"type": "object", "properties": {"findings": {"type": "array"}}},
             "required_tools": ["browser-search"], "required_connectors": [],
             "evaluation_criteria": ["factuality", "citation requirement"],
         }},
        {"kind": "AGENT", "slug": "research-manager", "name": "Research Manager",
         "payload": {"system_prompt": "You coordinate research workers and synthesize cited reports.",
                     "model_preset": "BALANCED", "skills": ["web-research"],
                     "memory": {"memory_mode": "team-shared", "retention": "project"},
                     "handoff_rules": ["browser-agent -> report-agent"]}},
        {"kind": "AGENT", "slug": "browser-agent", "name": "Browser Research Agent",
         "payload": {"system_prompt": "You browse allow-listed domains and extract evidence.",
                     "model_preset": "FAST", "skills": ["web-research"],
                     "browser": {"domains": [], "download_allowed": False}}},
        {"kind": "AGENT", "slug": "report-agent", "name": "Report Agent",
         "payload": {"system_prompt": "You write sourced reports from verified findings.",
                     "model_preset": "HIGH_QUALITY", "skills": ["web-research"]}},
        {"kind": "WORKFLOW", "slug": "research-pipeline", "name": "Research Pipeline",
         "payload": {"triggers": ["manual"], "agents": ["research-manager", "browser-agent", "report-agent"],
                     "approvals": ["publish_content"]}},
    ]
    manifest["security"] = {"required_approvals": ["publish_content"],
                            "network": "restricted", "sandbox_profile": "",
                            "risk_notes": "External sharing requires approval."}
    manifest["configuration"] = {"inputs": {
        "topic": {"type": "text", "required": True, "label": "Research topic"},
        "depth": {"type": "enum", "options": ["quick", "standard", "deep"], "default": "standard"},
        "notify_channel": {"type": "connector_reference", "required": False,
                           "credential_type": "slack", "required_scope": "chat:write"},
    }}
    return manifest


def swe_workforce() -> dict[str, Any]:
    manifest = _base(
        "openagent.swe-workforce", "Software Engineering Workforce", "1.0.0",
        "Planner, coder, tester and reviewer agents operating through the "
        "Code Agent and Sandbox with approvals on merge and production changes.",
        ["Coding", "Developer Tools"], ["coding", "review", "sandbox"],
    )
    manifest["dependencies"] = [
        {"type": "tool", "package": "code-search", "version": "^1.0.0"},
    ]
    manifest["resources"] = [
        {"kind": "SKILL", "slug": "python-development", "name": "Python Development",
         "payload": {
             "instructions": "Write typed, tested Python. Never commit secrets. Run tests before review.",
             "input_schema": {"type": "object", "properties": {"task": {"type": "string"}}},
             "output_schema": {"type": "object", "properties": {"patch": {"type": "string"}}},
             "required_tools": ["code-search"], "required_connectors": [],
             "evaluation_criteria": ["schema compliance", "completeness"],
         }},
        {"kind": "AGENT", "slug": "planner", "name": "Planner",
         "payload": {"system_prompt": "You decompose engineering tasks into safe, testable steps.",
                     "model_preset": "REASONING", "skills": ["python-development"]}},
        {"kind": "AGENT", "slug": "coder", "name": "Coder",
         "payload": {"system_prompt": "You implement code changes inside the sandbox only.",
                     "model_preset": "CODING", "skills": ["python-development"],
                     "sandbox": {"profile": "BUILD"}}},
        {"kind": "AGENT", "slug": "tester", "name": "Tester",
         "payload": {"system_prompt": "You run tests and report failures with reproductions.",
                     "model_preset": "CODING", "skills": ["python-development"],
                     "sandbox": {"profile": "TEST"}}},
        {"kind": "AGENT", "slug": "reviewer", "name": "Reviewer",
         "payload": {"system_prompt": "You review patches for safety and correctness.",
                     "model_preset": "REASONING", "skills": ["python-development"]}},
        {"kind": "WORKFLOW", "slug": "issue-to-pr", "name": "Issue to PR",
         "payload": {"triggers": ["manual"], "agents": ["planner", "coder", "tester", "reviewer"],
                     "approvals": ["merge_code", "modify_production"]}},
    ]
    manifest["security"] = {"required_approvals": ["merge_code", "modify_production"],
                            "network": "restricted", "sandbox_profile": "BUILD",
                            "risk_notes": "All code runs in the sandbox; merges need approval."}
    manifest["code_requirements"] = {"language": "python", "sandbox_profile": "BUILD",
                                     "test_commands": ["pytest -q"]}
    return manifest


def marketing_workforce() -> dict[str, Any]:
    manifest = _base(
        "openagent.marketing-workforce", "Marketing Workforce", "1.0.0",
        "Research, content, SEO and analytics agents producing on-brand "
        "content with approval before anything is published.",
        ["Marketing", "Content", "SEO"], ["marketing", "seo", "content"],
    )
    manifest["resources"] = [
        {"kind": "SKILL", "slug": "seo-research", "name": "SEO Research",
         "payload": {
             "instructions": "Analyze keywords, intent and competition; cite search data.",
             "input_schema": {"type": "object", "properties": {"keyword": {"type": "string"}}},
             "output_schema": {"type": "object", "properties": {"brief": {"type": "string"}}},
             "required_tools": ["browser-search"], "required_connectors": [],
             "evaluation_criteria": ["completeness", "tone"],
         }},
        {"kind": "SKILL", "slug": "content-writing", "name": "Content Writing",
         "payload": {
             "instructions": "Write original, on-brand content. Verify factual claims against research.",
             "input_schema": {"type": "object", "properties": {"brief": {"type": "string"}}},
             "output_schema": {"type": "object", "properties": {"draft": {"type": "string"}}},
             "required_tools": [], "required_connectors": [],
             "evaluation_criteria": ["tone", "factuality"],
         }},
        {"kind": "AGENT", "slug": "research", "name": "Market Researcher",
         "payload": {"system_prompt": "You research markets and audiences.",
                     "model_preset": "BALANCED", "skills": ["seo-research"]}},
        {"kind": "AGENT", "slug": "content", "name": "Content Writer",
         "payload": {"system_prompt": "You write and revise marketing content.",
                     "model_preset": "HIGH_QUALITY", "skills": ["content-writing"]}},
        {"kind": "AGENT", "slug": "seo", "name": "SEO Specialist",
         "payload": {"system_prompt": "You optimize content for search without keyword stuffing.",
                     "model_preset": "BALANCED", "skills": ["seo-research", "content-writing"]}},
        {"kind": "AGENT", "slug": "analytics", "name": "Analytics Reviewer",
         "payload": {"system_prompt": "You check content against performance data.",
                     "model_preset": "BALANCED", "skills": []}},
        {"kind": "WORKFLOW", "slug": "content-pipeline", "name": "Content Pipeline",
         "payload": {"triggers": ["manual"], "agents": ["research", "content", "seo", "analytics"],
                     "approvals": ["publish_content"]}},
    ]
    manifest["security"] = {"required_approvals": ["publish_content"],
                            "network": "restricted", "sandbox_profile": "",
                            "risk_notes": "Publishing requires human approval."}
    manifest["configuration"] = {"inputs": {
        "company_name": {"type": "text", "required": True},
        "target_market": {"type": "text", "required": True},
        "tone": {"type": "text", "default": "professional"},
    }}
    return manifest


def all_samples() -> dict[str, dict[str, Any]]:
    return {
        "openagent.research-workforce": research_workforce(),
        "openagent.swe-workforce": swe_workforce(),
        "openagent.marketing-workforce": marketing_workforce(),
        "openagent.support-workforce": support_workforce(),
        "openagent.data-analysis-workforce": data_analysis_workforce(),
    }


def support_workforce() -> dict[str, Any]:
    manifest = _base(
        "openagent.support-workforce", "Customer Support Workforce", "1.0.0",
        "Triage, knowledge-base and escalation agents resolving support "
        "tickets with human approval before external replies.",
        ["Customer Support", "AI & Agents"], ["support", "triage", "escalation"],
    )
    manifest["dependencies"] = [
        {"type": "connector", "package": "gmail", "version": ">=1.0.0", "optional": True},
    ]
    manifest["resources"] = [
        {"kind": "SKILL", "slug": "ticket-triage", "name": "Ticket Triage",
         "payload": {
             "instructions": "Classify urgency and topic. Never invent account facts; cite sources.",
             "input_schema": {"type": "object", "properties": {"ticket": {"type": "string"}}},
             "output_schema": {"type": "object", "properties": {"priority": {"type": "string"}}},
             "required_tools": [], "required_connectors": [],
             "evaluation_criteria": ["completeness", "tone"],
         }},
        {"kind": "AGENT", "slug": "triage", "name": "Triage Agent",
         "payload": {"system_prompt": "You triage incoming support tickets by urgency and topic.",
                     "model_preset": "FAST", "skills": ["ticket-triage"]}},
        {"kind": "AGENT", "slug": "support", "name": "Support Agent",
         "payload": {"system_prompt": "You draft accurate, empathetic replies grounded in cited sources.",
                     "model_preset": "BALANCED", "skills": ["ticket-triage"]}},
        {"kind": "AGENT", "slug": "escalation", "name": "Escalation Manager",
         "payload": {"system_prompt": "You escalate sensitive or unresolved cases to humans with context.",
                     "model_preset": "BALANCED", "skills": ["ticket-triage"]}},
        {"kind": "WORKFLOW", "slug": "support-pipeline", "name": "Support Pipeline",
         "payload": {"triggers": ["manual"], "agents": ["triage", "support", "escalation"],
                     "approvals": ["send_email"]}},
    ]
    manifest["security"] = {"required_approvals": ["send_email"],
                            "network": "restricted", "sandbox_profile": "",
                            "risk_notes": "External replies require human approval."}
    manifest["configuration"] = {"inputs": {
        "support_email": {"type": "text", "required": True},
        "sla_hours": {"type": "text", "default": "24"},
    }}
    return manifest


def data_analysis_workforce() -> dict[str, Any]:
    manifest = _base(
        "openagent.data-analysis-workforce", "Data Analysis Workforce", "1.0.0",
        "Ingest, analyze and report agents turning datasets into reviewed "
        "insights inside the sandbox.",
        ["Data", "AI & Agents"], ["data", "analysis", "reporting"],
    )
    manifest["resources"] = [
        {"kind": "SKILL", "slug": "data-analysis", "name": "Data Analysis",
         "payload": {
             "instructions": "Profile datasets, run reproducible analyses, report methods and limits.",
             "input_schema": {"type": "object", "properties": {"dataset": {"type": "string"}}},
             "output_schema": {"type": "object", "properties": {"insights": {"type": "array"}}},
             "required_tools": [], "required_connectors": [],
             "evaluation_criteria": ["factuality", "completeness"],
         }},
        {"kind": "AGENT", "slug": "ingest", "name": "Ingest Agent",
         "payload": {"system_prompt": "You validate and profile input datasets.",
                     "model_preset": "FAST", "skills": ["data-analysis"],
                     "sandbox": {"profile": "DATA_PROCESSING"}}},
        {"kind": "AGENT", "slug": "analyst", "name": "Analyst",
         "payload": {"system_prompt": "You run reproducible analyses and quantify uncertainty.",
                     "model_preset": "REASONING", "skills": ["data-analysis"],
                     "sandbox": {"profile": "DATA_PROCESSING"}}},
        {"kind": "AGENT", "slug": "reporter", "name": "Insights Reporter",
         "payload": {"system_prompt": "You write decision-ready reports with methods and limits.",
                     "model_preset": "HIGH_QUALITY", "skills": ["data-analysis"]}},
        {"kind": "WORKFLOW", "slug": "analysis-pipeline", "name": "Analysis Pipeline",
         "payload": {"triggers": ["manual"], "agents": ["ingest", "analyst", "reporter"],
                     "approvals": ["publish_content"]}},
    ]
    manifest["security"] = {"required_approvals": ["publish_content"],
                            "network": "restricted", "sandbox_profile": "DATA_PROCESSING",
                            "risk_notes": "Analysis runs in the sandbox; sharing needs approval."}
    manifest["configuration"] = {"inputs": {
        "dataset": {"type": "text", "required": True, "label": "Dataset reference"},
    }}
    return manifest
