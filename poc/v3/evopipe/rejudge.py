"""Post-hoc: re-judge ONLY the pairs whose original judge reply was not valid JSON (and was silently scored as a tie by the run).

Counterfactual analysis, not part of the official record: the official gate decisions in evolution/run_1 stay exactly as recorded.
Uses the fixed judge (retry on invalid replies) with the current judge role model.

    python -m evopipe.rejudge   ->  runs/rejudge.json
"""
from __future__ import annotations

import glob
import json
import os

from evoontology.evaluation.evaluation import EvaluationGate

from . import config
from .analyze import _load_dir
from .judge import judge_pair, regression_rule
from .llm import LLM

RUN = os.path.join(config.WORKSPACE, "evolution", "run_1")
CANDIDATE = {1: "v0-c1", 2: "v0-c2"}


def main() -> None:
    questions = {q["id"]: q["question"] for q in json.load(open(config.STREAM_Q, encoding="utf-8"))}
    judge = LLM("judge")
    out = []
    for rnd in (1, 2):
        gate = json.load(open(os.path.join(RUN, "gate_round%d.json" % rnd), encoding="utf-8"))
        all_verdicts = []
        for rep_no, rep in enumerate(gate["repetitions"], 1):
            parent_runs, cand_runs = _load_dir(os.path.join(rep["dir"], "parent")), _load_dir(os.path.join(rep["dir"], "candidate"))
            fixed = []
            for v in rep["verdicts"]:
                qid = v["case_id"].split(":")[1]
                if v.get("reason") != "unparseable judge output":      # the old fallback marked its silent ties with this reason
                    fixed.append(dict(v, rejudged=False))
                    continue
                seed = "run_1-%s-r%d-rep%d-%s" % (CANDIDATE[rnd], rnd, rep_no, qid)
                new = judge_pair(judge, question=questions[qid], parent_run=parent_runs[qid], candidate_run=cand_runs[qid], seed=seed,
                                 stage="posthoc.rejudge", cache_path=os.path.join(rep["dir"], "judge_cache_rejudge", qid + ".json"))
                fixed.append(dict(v, **{"winner": new["winner"], "critical_error": new["critical_error"], "reason": new["reason"],
                                        "raw_winner": new["raw_winner"], "rejudged": True, "original_winner": v["winner"]}))
            all_verdicts += fixed
            out.append({"round": rnd, "rep": rep_no, "original": rep["decision"], "rejudged": EvaluationGate.decide_judge(fixed),
                        "changed": [{"case": f["case_id"], "from": v["winner"], "to": f["winner"], "critical_error": f["critical_error"]}
                                    for f, v in zip(fixed, rep["verdicts"]) if f["rejudged"]]})
        pooled = EvaluationGate.decide_judge(all_verdicts)
        out.append({"round": rnd, "pooled_rejudged": pooled, "regression_rule_triggers": regression_rule(all_verdicts),
                    "pooled_original": gate["pooled"]})
    json.dump(out, open(os.path.join(config.RUNS, "rejudge.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
