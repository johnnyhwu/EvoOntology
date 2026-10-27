"""COUNTERFACTUAL (not the official result): replay the Accept path on a COPY of the workspace.

The official run ended `incomplete` because the frozen regression policy (D9) vetoed round 2 although the repo's bare gate rule
(E_c == 0 and W_c > W_p) accepted it. To show what the Accept path produces on real artefacts - ontology_v1 on disk, active.json
switched, checkpoint advanced, explorer rendered - this script starts a NEW run inside a copy of the workspace, feeds it the
recorded round-2 judge verdicts and declares "no unacceptable regression" (in the repo this is the Evolver's call), then calls
the repo's own accept_evolution / finalize_evolution_run. No LLM call, no cost, the real workspace is never modified.

    python -m evopipe.counterfactual
"""
from __future__ import annotations

import json
import os
import shutil

from evoontology.ontology.store import SemanticStore

from . import config
from .core import op

COPY = os.path.join(config.RUNS, "counterfactual_ws")


def main() -> None:
    if os.path.isdir(COPY):
        shutil.rmtree(COPY)
    ws = os.path.join(COPY, ".evoontology")
    shutil.copytree(config.WORKSPACE, ws)
    shutil.rmtree(os.path.join(ws, "evolution"))
    os.makedirs(os.path.join(ws, "evolution"))
    gate = json.load(open(os.path.join(config.WORKSPACE, "evolution", "run_1", "gate_round2.json"), encoding="utf-8"))
    verdicts = [{"winner": v["winner"], "critical_error": v["critical_error"]} for r in gate["repetitions"] for v in r["verdicts"]]
    op(ws, "start_evolution_run", parent_version="ontology_v0", adapter="counterfactual", max_rounds=2,
       acceptance={"protocol": "llm_judge", "note": "COUNTERFACTUAL: regression policy D9 not applied"})
    op(ws, "begin_evolution_round", hypothesis="(counterfactual replay of round-2 candidate v0-c2)", candidate_version="v0-c2")
    op(ws, "record_evolution_evaluation", subject="v0-c2", role="candidate", result={
        "metrics": {"note": "recorded round-2 verdicts"}, "cases": [], "provenance": "synthetic",
        "gate_input": {"protocol": "llm_judge", "verdicts": verdicts, "unacceptable_regressions": False}})
    accepted = op(ws, "accept_evolution")
    op(ws, "finalize_evolution_run")
    print(json.dumps({"accepted": accepted, "active": SemanticStore.active_version(ws), "versions": SemanticStore.list_versions(ws),
                      "state": json.load(open(os.path.join(ws, "state.json")))}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
