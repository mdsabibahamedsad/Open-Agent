"""Manager prompt architecture: bounded context, summaries, compression.

Never place every worker message into the manager prompt. Build from
summaries, references, structured state, artifacts, results, and selected
messages. Long-term memory extends this in MP15 via ContextProvider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openagent.management.providers import ContextProvider
from openagent.orchestration.security import sanitize_dict


@dataclass
class ManagerPromptContext:
    system_policy: str = ""
    manager_role: str = "manager"
    objective: str = ""
    team_summary: str = ""
    active_tasks: List[Dict[str, Any]] = field(default_factory=list)
    contracts: List[Dict[str, Any]] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    budget_summary: str = ""
    execution_metadata: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    selected_messages: List[Dict[str, Any]] = field(default_factory=list)


def build_manager_prompt(
    context: ManagerPromptContext,
    *,
    context_provider: Optional[ContextProvider] = None,
    max_tasks: int = 20,
    max_messages: int = 10,
    max_chars: int = 24_000,
) -> str:
    """Assemble a bounded manager prompt. Caps tasks/messages/chars so large
    teams cannot blow up the context window."""
    sections: List[str] = []
    if context.system_policy:
        sections.append(f"## Policy\n{context.system_policy}")
    sections.append(f"## Role\nYou are the {context.manager_role}.")
    sections.append(f"## Objective\n{context.objective}")
    if context.team_summary:
        sections.append(f"## Team\n{context.team_summary}")
    tasks = context.active_tasks[:max_tasks]
    if tasks:
        lines = [
            f"- {t.get('title', t.get('id', '?'))} [{t.get('status', '?')}]"
            for t in tasks
        ]
        sections.append("## Active tasks\n" + "\n".join(lines))
        if len(context.active_tasks) > max_tasks:
            sections.append(
                f"_({len(context.active_tasks) - max_tasks} more tasks available by reference)_"
            )
    if context.constraints:
        sections.append("## Constraints\n" + "\n".join(f"- {c}" for c in context.constraints))
    if context.budget_summary:
        sections.append(f"## Budget\n{context.budget_summary}")
    if context.outputs:
        sections.append(f"## Results ({len(context.outputs)} referenced)")
    messages = context.selected_messages[:max_messages]
    if messages:
        lines = []
        for m in messages:
            raw_payload = m.get("payload", "")
            if isinstance(raw_payload, dict):
                # Sanitize structured payloads BEFORE rendering so secret
                # values under secret keys are redacted, not stringified raw.
                payload = sanitize_dict(dict(raw_payload))
            else:
                payload = raw_payload
            lines.append(f"- [{m.get('message_type', '?')}] {str(payload)[:300]}")
        sections.append("## Selected signals\n" + "\n".join(lines))
    if context_provider is not None:
        extra = context_provider.summarize(
            {"tasks": len(context.active_tasks), "messages": len(context.selected_messages)}
        )
        if extra:
            sections.append(f"## Memory\n{extra}")
    # Sanitize + hard cap.
    prompt = "\n\n".join(sections)
    cleaned = sanitize_dict({"prompt": prompt})["prompt"]
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "\n_[truncated]_"
    return cleaned


def compress_messages(messages: List[Dict[str, Any]], *, keep: int = 10) -> Dict[str, Any]:
    """Compress history into head/tail + counts per type (no raw dump)."""
    by_type: Dict[str, int] = {}
    for message in messages:
        key = str(message.get("message_type", "unknown"))
        by_type[key] = by_type.get(key, 0) + 1
    return {
        "total": len(messages),
        "by_type": by_type,
        "head": messages[:2],
        "tail": messages[-keep:] if len(messages) > keep else messages[2:],
    }
