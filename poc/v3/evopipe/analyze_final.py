"""Final audit tables for the report (reads private GT; never part of Build/Use/Evolve).   python -m evopipe.analyze_final"""
from __future__ import annotations

import glob
import json
import os
from collections import Counter

from evoontology.evaluation.evaluation import EvaluationGate

from . import config
from .analyze import _acc, _load_dir
from .audit import load_gt, score_run
from .judge import regression_rule

RUN = os.path.join(config.WORKSPACE, "evolution", "run_1")
CAND = {1: "v0-c1", 2: "v0-c2"}


def main():
    gt = load_gt()
    out = {}
    # ---- 1. every gate repetition: judge verdict vs what the ground truth says
    conf = Counter()
    gate_rows = []
    for rnd in (1, 2):
        g = json.load(open(os.path.join(RUN, "gate_round%d.json" % rnd), encoding="utf-8"))
        reps = []
        for k, rep in enumerate(g["repetitions"], 1):
            P, C = _load_dir(os.path.join(rep["dir"], "parent")), _load_dir(os.path.join(rep["dir"], "candidate"))
            rows = []
            for v in rep["verdicts"]:
                q = v["case_id"].split(":")[1]
                pc, cc = score_run(gt, q, P[q]), score_run(gt, q, C[q])
                truth = "candidate" if cc and not pc else "parent" if pc and not cc else "tie"
                conf[(truth, v["winner"])] += 1
                rows.append({"q": q, "family": gt[q]["family"], "parent_ok": pc, "cand_ok": cc, "gt_winner": truth, "judge": v["winner"],
                             "parse_failed": v.get("reason") == "unparseable judge output",
                             "both_correct": pc and cc})
            reps.append({"rep": k, "judge": rep["decision"], "parent_correct": sum(r["parent_ok"] for r in rows),
                         "cand_correct": sum(r["cand_ok"] for r in rows), "rows": rows})
        gate_rows.append({"round": rnd, "candidate": CAND[rnd], "reps": reps})
    out["gate"] = gate_rows
    out["judge_vs_gt"] = {"%s|%s" % k: v for k, v in sorted(conf.items())}

    # ---- 2. the decision under alternative rules (same recorded evidence)
    decisions = []
    for rnd in (1, 2):
        g = json.load(open(os.path.join(RUN, "gate_round%d.json" % rnd), encoding="utf-8"))
        verdicts = [v for r in g["repetitions"] for v in r["verdicts"]]
        reps_ok = [r["decision"]["accept"] for r in g["repetitions"]]
        gt_scores = [(sum(x["parent_ok"] for x in r["rows"]) / 12, sum(x["cand_ok"] for x in r["rows"]) / 12) for r in gate_rows[rnd - 1]["reps"]]
        decisions.append({
            "round": rnd, "candidate": CAND[rnd],
            "official(frozen policy: bare rule + both reps + regression veto)": "reject",
            "bare repo rule on rep1 only": "accept" if reps_ok[0] else "reject",
            "bare repo rule on both reps pooled": "accept" if EvaluationGate.decide_judge(verdicts)["accept"] else "reject",
            "bare rule, every rep must accept": "accept" if all(reps_ok) and len(reps_ok) == 2 else "reject",
            "regression veto would fire": regression_rule(verdicts),
            "ground-truth gate (decide_gt) per rep": ["accept" if c > p else "reject" for p, c in gt_scores]})
    out["decisions"] = decisions

    # ---- 3. mechanism check recomputed with whole-id matching (the logged value used substring matching)
    mech = []
    for rnd in (1, 2):
        diff = json.load(open(os.path.join(RUN, "diff_round%d.json" % rnd), encoding="utf-8"))
        ids = [i for fam in diff["added"].values() for i in fam] + [i for fam in diff["changed"].values() for i in fam]
        knobs = json.load(open(os.path.join(config.WORKSPACE, "versions", CAND[rnd], "tool_config.json"), encoding="utf-8"))
        for d in sorted(glob.glob(os.path.join(RUN, "artifacts", "round%d" % rnd, "mechanism_attempt*"))):
            runs = _load_dir(d)
            act_old = act_new = 0
            for q, r in runs.items():
                blob = json.dumps(r.get("semantic_calls", []), ensure_ascii=False)
                tool = knobs["resolve"]["trigger_keyword_constraints"] or knobs["resolve"]["fuzzy_fallback"] or knobs["manifest"]["pinned_constraint_ids"]
                extra = tool and ("triggered_constraints" in blob or "fuzzy match" in blob or bool(knobs["manifest"]["pinned_constraint_ids"]))
                act_old += any(i in blob for i in ids) or bool(extra)
                act_new += any(('"%s"' % i) in blob for i in ids) or bool(extra)
            a = _acc(gt, runs)
            use = _load_dir(os.path.join(config.RUNS, "use", "ontology_v0"))
            ua = _acc(gt, use, list(runs))
            mech.append({"round": rnd, "dir": os.path.basename(d), "tasks": len(runs), "activated_substring_rule": act_old, "activated_whole_id_rule": act_new,
                         "gt_candidate_correct": a["correct"], "gt_parent_correct_same_tasks": ua["correct"], "questions": sorted(runs)})
    out["mechanism"] = mech

    # ---- 4. fresh test set
    out["test"] = {os.path.basename(d): _acc(gt, _load_dir(d)) for d in sorted(glob.glob(os.path.join(config.RUNS, "test", "*")))}

    # ---- 5. cost by stage
    cost = {}
    for line in open(os.path.join(config.RUNS, "ledger.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        key = (r["stage"], r["model"])
        c = cost.setdefault(key, [0, 0, 0, 0.0]); c[0] += 1; c[1] += r["input_tokens"]; c[2] += r["output_tokens"]; c[3] += r["cost_usd"]
    out["cost"] = [{"stage": k[0], "model": k[1], "calls": v[0], "in": v[1], "out": v[2], "usd": round(v[3], 4)} for k, v in sorted(cost.items())]
    out["cost_total"] = round(sum(v[3] for v in cost.values()), 4)
    json.dump(out, open(os.path.join(config.RUNS, "analysis_final.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    o = main()
    print("judge vs GT (rows=GT winner, cols=judge):", o["judge_vs_gt"])
    for g in o["gate"]:
        for r in g["reps"]:
            print(g["candidate"], "rep", r["rep"], "judge", {k: r["judge"][k] for k in ("candidate_wins", "parent_wins", "ties")}, "| GT parent_ok", r["parent_correct"], "cand_ok", r["cand_correct"],
                  "| GT-winners", Counter(x["gt_winner"] for x in r["rows"]))
    print(json.dumps(o["decisions"], ensure_ascii=False, indent=1))
    for m in o["mechanism"]:
        print(m)
    print("TOTAL cost", o["cost_total"])
