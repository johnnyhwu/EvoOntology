"""End-to-end dry run of the Evolve pipeline with a scripted (fake) LLM — zero cost.

It runs the real control flow on a COPY of the real workspace (with the 40 recorded production trajectories):
trigger → freeze/split → diagnose → attribute → patch → mechanism check → gate (2 repetitions) → accept → publish → finalize.
The fake LLM answers by recognising which stage's system prompt it received; the Candidate's agent answers 'CAND', the Parent's 'PARENT',
and the fake Judge prefers the side that says 'CAND', so the run must end in Accept and publish ontology_v1.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import evopipe  # noqa: E402,F401
from evopipe import config  # noqa: E402

config.RUNS = tempfile.mkdtemp(prefix="evopipe_dry_runs_")
from evopipe import llm as llm_module  # noqa: E402
from evopipe.llm import Completion  # noqa: E402

REAL_WS = os.path.join(config.V3, "workspace", ".evoontology")
REAL_PROFILE = os.path.join(config.V3, "runs", "build", "profile.md")


class ScriptedBackend:
    name = "mock"

    def complete(self, *, model, system, messages, max_tokens, temperature=None):
        return Completion(text=self.reply(system, messages), input_tokens=1, output_tokens=1, cost_usd=0.0, model=model)

    def reply(self, system, messages):
        tool_results = sum(m["content"].startswith("TOOL_RESULT") for m in messages if m["role"] == "user")
        call = lambda name, **args: json.dumps({"thought": "t", "tool": name, "args": args}, ensure_ascii=False)
        if "獨立的評審" in system:
            text = messages[0]["content"]
            a, b = text.split("## 回答 B")[0], text.split("## 回答 B")[1]
            winner = "A" if "CAND" in a else "B"
            return json.dumps({"winner": winner, "reason": "candidate states the Taipei conversion", "critical_error": False})
        if "Step 1 — 診斷" in system:
            if tool_results == 0:
                return call("probe_semantics", tool="resolve", mentions=["訂單日期"], context="7 月有效訂單")
            return call("submit_problem_map", problem_map=[{"id": "P1", "category": "tool_limitation", "symptom": "alias miss",
                        "affected_tasks": ["S01", "S02", "S03", "NOT_IN_POOL"], "evidence": "probe", "causal_hypothesis": "h", "uncertainty": "u"}], summary="s")
        if "Step 2 — 歸因" in system:
            return call("submit_attribution", hypotheses=[{"id": "H1", "problems": ["P1"], "dimension": "content", "nature": "missing_capability_or_coverage",
                        "mechanism": "m", "test_performed": "t", "predicted_effect": "p", "priority": 1}], primary="H1", reasoning="r")
        if "Step 3 — 修補" in system:
            return json.dumps({"hypothesis": "adding the alias and the trigger-keyword knob makes the timezone rule reachable", "dimension": "content+tool",
                               "operations": [{"op": "add_alias", "term_id": "term_order_time", "alias": "訂單日期"},
                                              {"op": "set_tool_config", "section": "resolve", "key": "trigger_keyword_constraints", "value": True}],
                               "expected_effect": "e", "rollback": "r"}, ensure_ascii=False)
        # --- Data Agent
        manifest = system.split("Ontology layer version:")[1].split("\n")[0].strip() if "Ontology layer version:" in system else ""
        answer = "CAND" if manifest.startswith("v0-c") else "PARENT"
        if tool_results == 0:
            return call("resolve_semantics", mentions=["訂單成立時間"], context="q")
        if tool_results == 1:
            return call("sql_query", query="SELECT COUNT(*) FROM orders")
        return call("submit_answer", answer=answer, basis="dry run")


class TestEvolveDryRun(unittest.TestCase):
    def test_full_evolve_run_ends_in_accept(self):
        self.assertTrue(os.path.isdir(REAL_WS), "run the Build and Use stages first")
        os.makedirs(os.path.join(config.RUNS, "build"), exist_ok=True)     # config.RUNS may be replaced by other test modules
        shutil.copy(REAL_PROFILE, os.path.join(config.RUNS, "build", "profile.md"))
        tmp = tempfile.mkdtemp(prefix="evopipe_dry_ws_", dir=os.path.join(config.V3, "runs"))
        ws = os.path.join(tmp, ".evoontology")
        shutil.copytree(REAL_WS, ws)
        shutil.rmtree(os.path.join(ws, "evolution"), ignore_errors=True)
        os.makedirs(os.path.join(ws, "evolution"))
        real_before = sorted(os.listdir(os.path.join(REAL_WS, "evolution")))
        try:
            llm_module.make_backend = lambda name=None: ScriptedBackend()
            from evopipe import evolve
            report = evolve.EvolveRun(workspace=ws, max_rounds=2).run()
            self.assertEqual(report["run"]["status"], "accepted")
            self.assertEqual(report["run"]["accepted_version"], "ontology_v1")
            self.assertEqual(report["rounds"][0]["decision"], "accept")
            self.assertEqual(report["frozen"], {"batch": 40, "pool": 28, "reserve": 12})
            run_dir = os.path.join(ws, "evolution", "run_1")
            for name in ("run.json", "frozen_batch.json", "problem_map.json", "gate_round1.json", "report.json", "diff_round1.json",
                         "trajectory-sources.json"):
                self.assertTrue(os.path.isfile(os.path.join(run_dir, name)), name)
            frozen = json.load(open(os.path.join(run_dir, "frozen_batch.json")))
            pool_q = {x["question_id"] for x in frozen["pool"]}
            reserve_q = {x["question_id"] for x in frozen["validation_reserve"]}
            self.assertFalse(pool_q & reserve_q)                                        # disjoint
            problem = json.load(open(os.path.join(run_dir, "problem_map.json")))["problem_map"]["problem_map"][0]
            self.assertTrue(set(problem["affected_tasks"]) <= pool_q)                   # boundary enforced on LLM output
            self.assertIn("NOT_IN_POOL", ["NOT_IN_POOL"]) and self.assertNotIn("NOT_IN_POOL", problem["affected_tasks"])
            active = json.load(open(os.path.join(ws, "active.json")))["active_version"]
            self.assertEqual(active, "ontology_v1")
            cfg = json.load(open(os.path.join(ws, "versions", "ontology_v1", "tool_config.json")))
            self.assertTrue(cfg["resolve"]["trigger_keyword_constraints"])              # tool config travels with the version
            state = json.load(open(os.path.join(ws, "state.json")))
            self.assertIsNotNone(state["checkpoint_trajectory"])                        # checkpoint advanced
            self.assertTrue(os.path.isdir(os.path.join(ws, "versions", "v0-c1")))       # Candidate kept for audit
            self.assertEqual(sorted(os.listdir(os.path.join(REAL_WS, "evolution"))), real_before)   # the real workspace was never touched
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
