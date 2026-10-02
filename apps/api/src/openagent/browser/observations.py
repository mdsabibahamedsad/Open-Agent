"""Observation compression: token-budgeted, pruned browser observations for the model."""

from __future__ import annotations

from typing import Any, Literal

Strategy = Literal["minimal", "standard", "detailed", "visual", "custom"]

BUDGETS: dict[str, int] = {
    "minimal": 1500,
    "standard": 6000,
    "detailed": 15000,
    "visual": 6000,
    "custom": 6000,
}


def compress_observation(
    url: str,
    title: str,
    elements: list[dict[str, Any]],
    text: str = "",
    strategy: Strategy = "standard",
    max_chars: int | None = None,
) -> str:
    budget = max_chars or BUDGETS.get(strategy, 6000)
    lines: list[str] = [f"Current URL: {url}", f"Page title: {title}", "", "Visible interactive elements:"]
    seen: set[str] = set()
    for i, el in enumerate(elements):
        if not isinstance(el, dict):
            continue
        if el.get("visible") is False:
            continue
        sig = f"{el.get('role')}:{el.get('name')}:{el.get('selector')}"
        if sig in seen:
            continue
        seen.add(sig)
        name = str(el.get("name") or el.get("selector") or el.get("role"))[:80]
        lines.append(f"- {el.get('role', 'element')}: {name}")
        if strategy == "minimal" and len(lines) > 20:
            break
        if strategy == "standard" and len(lines) > 60:
            break
        if strategy in ("detailed", "visual") and len(lines) > 120:
            break
    if strategy != "minimal" and text:
        lines += ["", "Relevant text:", _truncate(_dedup_lines(text), max(500, budget // 2))]
    out = "\n".join(lines)
    return _truncate(out, budget)


def _dedup_lines(text: str) -> str:
    seen: set[str] = set()
    kept: list[str] = []
    for line in text.splitlines():
        s = " ".join(line.split())
        if not s or s in seen:
            continue
        seen.add(s)
        kept.append(s)
    return "\n".join(kept)


def _truncate(s: str, budget: int) -> str:
    if len(s) <= budget:
        return s
    return s[:budget] + "... [truncated]"
