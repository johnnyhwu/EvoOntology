"""Use phase: run the Data Agent on one question and normalise the run into a core trajectory.

The Data Agent runtime is on the *adapter side* in EvoOntology (trajectory-format.md): after each task it builds a
trajectory with ``trajectory.from_message_trace`` and appends it to ``trajectories/``. We do exactly that.
Evaluation re-runs (Parent/Candidate comparisons) are NOT appended to ``trajectories/`` — they would count as new
tasks for the evolution trigger — they are stored under the evolution run instead.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

from evoontology.trajectory.trajectory import TrajectoryStore, from_message_trace

from . import config
from .agent import ToolSpec, run_agent
from .llm import LLM
from .prompts import render
from .semantic import TunedSemanticLayer
from .tools_data import schema_tool, sql_tool

SEMANTIC_TOOLS = {"browse_semantics", "resolve_semantics"}


def _semantic_tools(layer: TunedSemanticLayer) -> List[ToolSpec]:
    def browse(args):
        return layer.execute("browse_semantics", {"query": args.get("query", ""), "kind": args.get("kind", "term"),
                                                  "limit": args.get("limit", 6)})

    def resolve(args):
        mentions = args.get("mentions")
        if isinstance(mentions, str):
            mentions = [mentions]
        return layer.execute("resolve_semantics", {"mentions": mentions or [], "context": args.get("context", "")})

    return [
        ToolSpec("browse_semantics", "在語意層中搜尋與某個分析需求相關的項目（最多 6 筆；需提供具體 query）",
                 '{"query": "<關鍵詞>", "kind": "term|mapping|relation|constraint|all", "limit": 6}', browse),
        ToolSpec("resolve_semantics", "把你要用的業務概念解析成資料表欄位、關聯、規則(constraint)與證據（最多 5 個概念）。"
                 "context 請寫出完整的分析需求（可直接貼上原問題）。",
                 '{"mentions": ["<概念1>", "<概念2>"], "context": "<分析需求>"}', resolve),
    ]


def build_agent(arm: str, workspace: str, version: str):
    """Return (system_prompt, tools) for arm 'ontology' (with semantic layer) or 'none' (baseline)."""
    tools = [sql_tool(), schema_tool()]
    if arm == "ontology":
        layer = TunedSemanticLayer.load_tuned(workspace, version)
        tools = _semantic_tools(layer) + tools
        system = render("data_agent.md",
                        semantic_intro="公司另外提供一個「語意層（ontology）」工具，協助你理解業務名詞、欄位對應與業務規則。",
                        semantic_step="先用 `resolve_semantics` 解析你要用的業務概念（必要時用 `browse_semantics` 探索），"
                                      "並注意回傳的 constraint（rule）；語意層是指引不是答案，仍需用 SQL 驗證。",
                        manifest_block="\n## 語意層說明（session manifest）\n\n" + layer.manifest())
    elif arm == "none":
        system = render("data_agent.md", semantic_intro="", semantic_step="先用 `get_schema` 了解資料表結構。", manifest_block="")
    else:
        raise ValueError(arm)
    tools.append(ToolSpec("submit_answer", "交付最終答案（最後一步，只呼叫一次）",
                          '{"answer": "<單一值>", "basis": "<採用的定義與依據>"}', lambda a: None))
    return system, tools


def run_task(*, question_id: str, question: str, workspace: str, version: str, arm: str, llm: LLM,
             stage: str = "use") -> Dict[str, Any]:
    system, tools = build_agent(arm, workspace, version)
    result = run_agent(llm, stage=stage, system=system, task="問題：" + question, tools=tools, final_tool="submit_answer")
    messages: List[Dict[str, Any]] = []
    for ev in result.events:
        messages.append({"tool_call": {"tool": ev["tool"], "arguments": ev["arguments"]}})
        messages.append({"tool_result": ev["result"]})
    final = None
    if result.final is not None:
        final = {"answer": result.final.get("answer"), "basis": result.final.get("basis", "")}
    ok_native = any(not e["error"] for e in result.events if e["tool"] not in SEMANTIC_TOOLS)
    status = "completed" if final is not None and ok_native else "failed"
    trajectory = from_message_trace(
        task_id="task_" + uuid.uuid4().hex[:12], question=question, ontology_version=version, split="production",
        messages=messages, final_answer=final, task_status=status,
        errors=[{"tool": e["tool"]} for e in result.events if e["error"]])
    trajectory.update(question_id=question_id, arm=arm, steps=result.steps, ended_by=result.ended_by)
    return trajectory


def save_run(path: str, trajectory: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(trajectory, stream, ensure_ascii=False, indent=1)


def append_trajectory(workspace: str, trajectory: Dict[str, Any], recorded_at: str) -> str:
    return TrajectoryStore(workspace).append(trajectory, recorded_at=recorded_at)
