"""Evaluation without ground truth: anonymous pairwise LLM Judge (docs/evaluation-protocol.md).

``judge_fn(question, answer_A, answer_B) -> {winner, reason, critical_error}`` with A/B randomly assigned so the judge
never knows which side is the Parent. Decoding and the accept/reject aggregate are the repo's own
``EvaluationGate`` (deterministic); this module only builds the judge input and calls the (independent) judge model.

Judge input = question + each side's final answer + basis + the SQL it executed (tool evidence is optional in the
protocol; without it the judge sees nothing but two numbers). Semantic-tool calls are NOT shown, so the judge cannot
tell which side used the ontology.
"""
from __future__ import annotations

import glob
import json
import os
import random
from typing import Any, Dict, List, Optional

from evoontology.evaluation.evaluation import EvaluationGate

from . import config
from .llm import LLM, extract_json
from .prompts import render


def render_side(run: Dict[str, Any], max_sql: int = 6) -> str:
    final = run.get("final_answer") or {}
    lines = ["最終答案: %s" % final.get("answer"), "採用的定義與依據: %s" % final.get("basis", "(未提供)")]
    queries = [c for c in run.get("native_tool_calls", []) if c.get("tool") == "sql_query"][:max_sql]
    for i, call in enumerate(queries, 1):
        inp = call["input"]
        text = inp.get("query") or json.dumps(inp.get("queries"), ensure_ascii=False)
        result = str(call.get("result_summary") or call.get("result"))[:300].replace("\n", " ")
        lines.append("SQL %d: %s\n  結果: %s" % (i, text.strip()[:700], result))
    if run.get("task_status") != "completed":
        lines.append("(此次執行未成功完成：%s)" % run.get("ended_by"))
    return "\n".join(lines)


MAX_JUDGE_ATTEMPTS = 3


class JudgeError(RuntimeError):
    pass


def _valid_judgment(raw: str):
    """The parsed verdict, or None when the reply is not the required JSON object."""
    try:
        value = extract_json(raw or "")
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get("winner") in ("A", "B", "tie") else None


def build_prompt(question: str, parent_run: Dict[str, Any], candidate_run: Dict[str, Any], seed: str):
    """Deterministic: the same (runs, seed) always give the same prompt and the same A/B assignment."""
    mapping = EvaluationGate.anonymize(render_side(parent_run), render_side(candidate_run),
                                       swap=random.Random(seed).random() < 0.5)
    prompt = "## 問題\n%s\n\n## 回答 A\n%s\n\n## 回答 B\n%s" % (question, mapping["A"], mapping["B"])
    return prompt, mapping


def judge_pair(judge: LLM, *, question: str, parent_run: Dict[str, Any], candidate_run: Dict[str, Any], seed: str,
               stage: str = "evolve.judge", cache_path: Optional[str] = None) -> Dict[str, Any]:
    """Judge one pair. ``cache_path`` makes a resumed run reuse the verdict it already paid for (keyed by the exact prompt)."""
    prompt, mapping = build_prompt(question, parent_run, candidate_run, seed)
    raw = judgment = None
    if cache_path and os.path.isfile(cache_path):
        cached = json.load(open(cache_path, encoding="utf-8"))
        if cached.get("prompt") == prompt:
            raw = cached["raw"]
            judgment = _valid_judgment(raw)                 # an old cache entry may hold an invalid reply: then ask again
    if judgment is None:
        messages = [{"role": "user", "content": prompt}]
        for attempt in range(1, MAX_JUDGE_ATTEMPTS + 1):    # a reply that is not the required JSON is NEVER silently turned into a tie
            raw = judge.chat(stage=stage, system=render("judge.md"), messages=messages)
            judgment = _valid_judgment(raw)
            if judgment is not None:
                break
            messages += [{"role": "assistant", "content": raw or "(空白回覆)"},
                         {"role": "user", "content": "你的回覆不是要求的格式。請只回覆一個 JSON 物件：{\"winner\": \"A\"|\"B\"|\"tie\", \"reason\": \"...\", \"critical_error\": \"A\"|\"B\"|false}，不要有其他文字。"}]
        else:
            raise JudgeError("judge gave no valid verdict after %d attempts for seed %s" % (MAX_JUDGE_ATTEMPTS, seed))
        if cache_path:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            json.dump({"prompt": prompt, "raw": raw, "judge_model": judge.model, "attempts": attempt}, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    decoded = EvaluationGate.decode(judgment, mapping)
    decoded.update(A_is=mapping["A_is"], B_is=mapping["B_is"], raw_winner=judgment.get("winner"))
    return decoded


def recover_from_log(cache_path: str, prompt: str) -> bool:
    """Find an earlier judge call with exactly this prompt in runs/llm_log and restore its reply into the cache."""
    for path in sorted(glob.glob(os.path.join(config.RUNS, "llm_log", "*.json"))):
        entry = json.load(open(path, encoding="utf-8"))
        if entry.get("stage") == "evolve.judge" and entry["messages"][0]["content"] == prompt:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            json.dump({"prompt": prompt, "raw": entry["response"], "judge_model": entry["model"], "recovered_from": entry["call_id"]},
                      open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
            return True
    return False


def regression_rule(verdicts: List[Dict[str, Any]]) -> bool:
    """Pipeline policy (the repo leaves 'unacceptable regression' to the agent): True if the Candidate has any critical
    error, or the Parent wins more than one third as often as the Candidate does."""
    w_c = sum(v["winner"] == "candidate" for v in verdicts)
    w_p = sum(v["winner"] == "parent" for v in verdicts)
    e_c = sum(bool(v["critical_error"]) for v in verdicts)
    return e_c > 0 or (w_p > 0 and 3 * w_p > w_c)
