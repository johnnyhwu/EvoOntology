"""Post-run analysis against the private ground truth (never imported by Build / Use / Evolve).

    python -m evopipe.analyze            -> writes runs/analysis.json and prints the tables used in the report
"""
from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from typing import Any, Dict, List

from evoontology.evaluation.evaluation import EvaluationGate

from . import config
from .audit import load_gt, score_run


def _load_dir(path: str) -> Dict[str, Dict[str, Any]]:
    return {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(path, "*.json")))}


def _acc(gt, runs: Dict[str, Dict[str, Any]], ids=None) -> Dict[str, Any]:
    ids = [i for i in (ids if ids is not None else runs) if i in runs]
    ok = [i for i in ids if score_run(gt, i, runs[i])]
    by_kind: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    by_family: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for i in ids:
        for table, key in ((by_kind, gt[i]["kind"]), (by_family, gt[i]["family"])):
            table[key][1] += 1
            table[key][0] += i in ok
    return {"correct": len(ok), "n": len(ids), "wrong": [i for i in ids if i not in ok],
            "by_kind": {k: v for k, v in by_kind.items()}, "by_family": {k: v for k, v in by_family.items()}}


def analyze() -> Dict[str, Any]:
    gt = load_gt()
    out: Dict[str, Any] = {}
    ws = config.WORKSPACE
    run_dirs = sorted(glob.glob(os.path.join(ws, "evolution", "run_*")))
    frozen = json.load(open(os.path.join(run_dirs[-1], "frozen_batch.json"), encoding="utf-8")) if run_dirs else None
    pool_ids = [x["question_id"] for x in frozen["pool"]] if frozen else None
    reserve_ids = [x["question_id"] for x in frozen["validation_reserve"]] if frozen else None

    use = _load_dir(os.path.join(config.RUNS, "use", "ontology_v0"))
    if use:
        out["use_v0_all"] = _acc(gt, use)
        if frozen:
            out["use_v0_pool"], out["use_v0_reserve"] = _acc(gt, use, pool_ids), _acc(gt, use, reserve_ids)

    out["test"] = {}
    for d in sorted(glob.glob(os.path.join(config.RUNS, "test", "*"))):
        out["test"][os.path.basename(d)] = _acc(gt, _load_dir(d))

    out["gate"] = []
    for run_dir in run_dirs:
        for gate_file in sorted(glob.glob(os.path.join(run_dir, "gate_round*.json"))):
            g = json.load(open(gate_file, encoding="utf-8"))
            for r, rep in enumerate(g["repetitions"], 1):
                parent_runs, cand_runs = _load_dir(os.path.join(rep["dir"], "parent")), _load_dir(os.path.join(rep["dir"], "candidate"))
                rows, p_scores, c_scores = [], [], []
                for v in rep["verdicts"]:
                    qid = v["case_id"].split(":")[1]
                    pc, cc = score_run(gt, qid, parent_runs[qid]), score_run(gt, qid, cand_runs[qid])
                    truth = "candidate" if cc and not pc else "parent" if pc and not cc else "tie"
                    rows.append({"qid": qid, "family": gt[qid]["family"], "parent_correct": pc, "candidate_correct": cc,
                                 "judge": v["winner"], "judge_critical_error": v["critical_error"], "gt_winner": truth,
                                 "judge_agrees": v["winner"] == truth, "reason": v.get("reason", "")})
                    p_scores.append(float(pc)); c_scores.append(float(cc))
                out["gate"].append({"file": os.path.basename(gate_file), "repetition": r, "judge_decision": rep["decision"],
                                    "gt_decision": EvaluationGate.decide_gt(p_scores, c_scores), "rows": rows})
    json.dump(out, open(os.path.join(config.RUNS, "analysis.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def show(out: Dict[str, Any]) -> None:
    for key in ("use_v0_all", "use_v0_pool", "use_v0_reserve"):
        if key in out:
            a = out[key]
            print("%-16s %d/%d  wrong=%s" % (key, a["correct"], a["n"], a["wrong"]))
            print("   by_kind:", a["by_kind"])
            print("   by_family:", a["by_family"])
    for name, a in out.get("test", {}).items():
        print("test %-22s %d/%d  wrong=%s" % (name, a["correct"], a["n"], a["wrong"]))
        print("   by_family:", a["by_family"])
    for g in out.get("gate", []):
        d, t = g["judge_decision"], g["gt_decision"]
        agree = sum(r["judge_agrees"] for r in g["rows"])
        print("gate %s rep%d: judge cand=%d parent=%d tie=%d crit=%d accept=%s | GT parent=%.2f cand=%.2f accept=%s | judge==GT on %d/%d" % (
            g["file"], g["repetition"], d["candidate_wins"], d["parent_wins"], d["ties"], d["candidate_critical_errors"], d["accept"],
            t["parent_score"], t["candidate_score"], t["accept"], agree, len(g["rows"])))


if __name__ == "__main__":
    show(analyze())
