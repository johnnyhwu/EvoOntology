"""A tiny tool-using agent loop controlled by Python (not by an agent framework).

Protocol (plain text, works with any chat model): on every turn the model must reply with ONE JSON object

    {"thought": "<one short sentence>", "tool": "<tool name>", "args": {...}}

Python executes the tool, feeds the result back as the next user message, and stops when the model calls the
*final tool* (e.g. ``submit_answer``) or the step budget is spent. "thought" is shown to the model only to
make it plan; it is never stored (trajectory-format.md: no chain-of-thought in trajectories).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import config
from .llm import LLM, extract_json

PROTOCOL = """\
## 工具呼叫格式（非常重要）
每一輪你只能回覆「一個 JSON 物件」，不要加任何其他文字、不要用 markdown 圍欄：
{"thought": "<一句話說明你為什麼這樣做>", "tool": "<工具名稱>", "args": {<參數>}}
系統會執行該工具，並把結果在下一則訊息還給你。每一輪只能呼叫一個工具。
當你準備好交付結果時，呼叫最終工具 `%(final)s`；呼叫後對話即結束。

## 可用工具
%(tools)s
"""


@dataclass
class ToolSpec:
    name: str
    description: str
    args: str                      # human-readable argument description for the prompt
    fn: Callable[[Dict[str, Any]], Any]


@dataclass
class AgentResult:
    final: Optional[Dict[str, Any]]
    events: List[Dict[str, Any]] = field(default_factory=list)   # executed (non-final) tool calls, in order
    steps: int = 0
    ended_by: str = "final"                                      # final | max_steps | format_error


def describe(tools: List[ToolSpec], final_tool: str) -> str:
    lines = []
    for t in tools:
        lines.append("- `%s` — %s\n  args: %s" % (t.name, t.description, t.args))
    return PROTOCOL % {"final": final_tool, "tools": "\n".join(lines)}


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…[已截斷，共 %d 字元]" % len(text)


def run_agent(llm: LLM, *, stage: str, system: str, task: str, tools: List[ToolSpec], final_tool: str,
              max_steps: int = config.AGENT_MAX_STEPS, result_chars: int = config.TOOL_RESULT_CHARS_FOR_MODEL) -> AgentResult:
    registry = {t.name: t for t in tools}
    full_system = system.rstrip() + "\n\n" + describe(tools, final_tool)
    messages: List[Dict[str, str]] = [{"role": "user", "content": task}]
    events: List[Dict[str, Any]] = []
    format_errors = 0
    for step in range(1, max_steps + 1):
        reply = llm.chat(stage=stage, system=full_system, messages=messages)
        try:
            action = extract_json(reply)
            if not isinstance(action, dict) or "tool" not in action:
                raise ValueError("missing 'tool'")
            name, args = str(action["tool"]), action.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError("'args' must be an object")
        except ValueError as exc:
            format_errors += 1
            if format_errors >= 3:
                return AgentResult(None, events, step, "format_error")
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": "格式錯誤（%s）。請只回覆一個 JSON 物件：{\"thought\":..., \"tool\":..., \"args\":{...}}" % exc}]
            continue
        messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
        if name == final_tool:
            return AgentResult(args, events, step, "final")
        spec = registry.get(name)
        if spec is None:
            result: Any = {"error": "unknown tool %r; available: %s" % (name, sorted(registry) + [final_tool])}
        else:
            try:
                result = spec.fn(args)
            except Exception as exc:   # tool failure is information for the model, not a crash
                result = {"error": "%s: %s" % (type(exc).__name__, exc)}
        events.append({"tool": name, "arguments": args, "result": result,
                       "error": isinstance(result, dict) and "error" in result})
        shown = _clip(json.dumps(result, ensure_ascii=False), result_chars)
        messages.append({"role": "user", "content": "TOOL_RESULT %s:\n%s" % (name, shown)})
    return AgentResult(None, events, max_steps, "max_steps")
