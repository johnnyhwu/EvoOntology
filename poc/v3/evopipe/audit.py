"""Ground-truth audit — used ONLY after the pipeline has finished, never by Build / Use / Evolve.

The production setting being simulated has no ground truth (rolling_trajectory + LLM Judge). The SQL-computed answers
in _private/gt.json let us check, from the outside, whether the Judge-gated decisions were actually right.
Tolerances follow PoC 1: counts exact, money within 0.05 %, ratios within 0.06 (GT is rounded to 1-2 decimals).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from . import config

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def load_gt() -> Dict[str, Any]:
    return json.load(open(config.GT_PATH, encoding="utf-8"))


def parse_number(answer: Any) -> Optional[float]:
    if isinstance(answer, (int, float)):
        return float(answer)
    m = _NUM.search(str(answer or "").replace("％", "%"))
    return float(m.group().replace(",", "")) if m else None


def is_correct(gt_item: Dict[str, Any], answer: Any) -> bool:
    value = parse_number(answer)
    if value is None:
        return False
    gt, tol = float(gt_item["gt"]), gt_item["tolerance"]
    if tol == "count":
        return round(value) == round(gt) and abs(value - round(value)) < 1e-6
    if tol == "money":
        return abs(value - gt) <= max(0.01, abs(gt) * 0.0005)
    return abs(value - gt) <= 0.06


def score_run(gt: Dict[str, Any], qid: str, run: Dict[str, Any]) -> bool:
    final = run.get("final_answer") or {}
    return run.get("task_status") == "completed" and is_correct(gt[qid], final.get("answer"))
