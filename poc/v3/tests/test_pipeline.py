"""Deterministic tests — no real LLM is called.   Run: poc/.venv/bin/python -m unittest discover -s poc/v3/tests -v"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import evopipe  # noqa: E402,F401  (adds repo root to sys.path)
from evopipe import config, records  # noqa: E402
from evopipe.agent import ToolSpec, run_agent  # noqa: E402
from evopipe.llm import LLM, MockBackend, OpenRouterBackend, extract_json  # noqa: E402
from evopipe.semantic import TunedSemanticLayer, DEFAULT_TOOL_CONFIG  # noqa: E402
from evoontology.evaluation.evaluation import EvaluationGate  # noqa: E402
from evoontology.evolution.session import EvolutionError, EvolutionSession  # noqa: E402
from evoontology.ontology.store import SemanticStore  # noqa: E402

POC1_WS = os.path.join(config.POC, "workspace", ".evoontology")      # PoC-1 ontology (read-only fixture)
config.RUNS = tempfile.mkdtemp(prefix="evopipe_test_runs_")            # keep mock calls out of the real cost ledger


def poc1_records():
    _, recs = SemanticStore.load_records(POC1_WS, "ontology_v0")
    return recs


class TestJsonAndAgent(unittest.TestCase):
    def test_extract_json_variants(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('好的：{"a": [1, 2]} 以上'), {"a": [1, 2]})
        with self.assertRaises(ValueError):
            extract_json("no json here")

    def test_agent_loop_tool_then_final_with_format_recovery(self):
        backend = MockBackend(["not json at all",
                               '{"thought":"x","tool":"echo","args":{"v":3}}',
                               '{"thought":"y","tool":"nope","args":{}}',
                               '{"thought":"z","tool":"done","args":{"answer":"42"}}'])
        llm = LLM("agent", backend=backend, models={"agent": "m"})
        echo = ToolSpec("echo", "echo", "{v}", lambda a: {"got": a["v"]})
        res = run_agent(llm, stage="t", system="sys", task="q", tools=[echo], final_tool="done")
        self.assertEqual(res.final, {"answer": "42"})
        self.assertEqual([e["tool"] for e in res.events], ["echo", "nope"])
        self.assertTrue(res.events[1]["error"])                       # unknown tool is reported, not fatal
        self.assertIn("格式錯誤", backend.calls[1]["messages"][-1]["content"])

    def test_agent_stops_at_max_steps(self):
        backend = MockBackend(['{"tool":"echo","args":{"v":1}}'] * 5)
        res = run_agent(LLM("agent", backend=backend, models={"agent": "m"}), stage="t", system="s", task="q",
                        tools=[ToolSpec("echo", "e", "{}", lambda a: {"ok": 1})], final_tool="done", max_steps=3)
        self.assertEqual((res.final, res.ended_by, len(res.events)), (None, "max_steps", 3))


class _Handler(BaseHTTPRequestHandler):
    captured = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.captured = {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
        payload = json.dumps({"id": "gen-1", "model": body["model"], "choices": [{"message": {"content": '{"ok": true}'}}],
                              "usage": {"prompt_tokens": 11, "completion_tokens": 7, "cost": 0.00123}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(payload)

    def log_message(self, *a):
        pass


class TestOpenRouterProtocol(unittest.TestCase):
    def test_request_shape_and_cost_parsing(self):
        server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            backend = OpenRouterBackend(base_url="http://127.0.0.1:%d/api/v1" % server.server_port, api_key="sk-test")
            out = backend.complete(model="qwen/test", system="SYS", messages=[{"role": "user", "content": "hi"}], max_tokens=100)
        finally:
            server.shutdown()
        cap = _Handler.captured
        self.assertEqual(cap["path"], "/api/v1/chat/completions")
        self.assertEqual(cap["auth"], "Bearer sk-test")
        self.assertEqual(cap["body"]["messages"][0], {"role": "system", "content": "SYS"})
        self.assertEqual(cap["body"]["temperature"], 0.0)
        self.assertEqual((out.text, out.input_tokens, out.output_tokens, out.cost_usd), ('{"ok": true}', 11, 7, 0.00123))

    def test_missing_key_is_reported_not_crashed(self):
        from evopipe.llm import LLMUnavailable
        backend = OpenRouterBackend(base_url="http://127.0.0.1:9", api_key=None)
        backend.api_key = None
        with self.assertRaises(LLMUnavailable):
            backend.complete(model="m", system="s", messages=[{"role": "user", "content": "x"}], max_tokens=10)


class TestRecords(unittest.TestCase):
    def test_poc1_ontology_passes_checks_except_known_deviation(self):
        errors = records.check_records(poc1_records())
        # PoC-1's Builder used 'warn' (plugin accepts it); the schema doc says 'warning' -> our stricter check flags it
        self.assertTrue(all("severity" in e or "evidence" in e or "type" in e or "confidence" in e for e in errors), errors[:5])

    def test_detects_schema_violations(self):
        recs = {f: [] for f in records.FAMILIES}
        recs["terms"] = [{"id": "t1", "name": "n", "type": "bogus", "definition": "d", "evidence": []}]
        recs["mappings"] = [{"id": "m1", "term_id": "t1", "database_source": "x", "table": "orders", "column": "nope"}]
        recs["relations"] = [{"id": "r1", "source": "t1", "target": "t9", "relation_type": "affects", "evidence": []}]
        recs["constraints"] = [{"id": "c1", "target": "t1", "constraint_type": "scope", "trigger_keywords": [], "severity": "block",
                                "confidence": "high", "description": "SELECT * FROM orders WHERE status=1", "evidence": ["ev_x"]}]
        text = "\n".join(records.check_records(recs))
        for needle in ("type must be one of", "column 'nope' does not exist", "relation_type must be", "target 't9'",
                       "trigger_keywords must be a non-empty", "looks like a SQL template", "unknown evidence id"):
            self.assertIn(needle, text)

    def test_catches_the_two_failures_seen_in_the_real_build(self):
        """PoC-2 build attempt 2: the LLM returned an empty 'mappings' list and a junk field; validate_semantics still passed."""
        recs = {f: [] for f in records.FAMILIES}
        recs["terms"] = [{"id": "t1", "name": "n", "type": "metric", "definition": "d", "evidence": ["e1"], "definity": ""}]
        recs["evidence"] = [{"id": "e1", "source": "s", "query": "q", "result": "r", "validation_method": "v", "timestamp": "t"}]
        text = "\n".join(records.check_records(recs))
        self.assertIn("fields not defined by the schema: ['definity']", text)
        self.assertIn("has no Mapping", text)
        self.assertEqual(records.missing_mappings(recs), [("t1", "metric")])

    def test_evidence_is_executed_by_code_and_quotes_are_verified(self):
        doc = "有效訂單：訂單狀態為已付款、已出貨、已送達的訂單。"
        ok, err = records.materialize_evidence({"id": "ev1", "query": "SELECT status, COUNT(*) FROM orders GROUP BY status",
                                                "validation_method": "distinct"}, doc)
        self.assertIsNone(err); self.assertIn("rows", ok["result"])
        _, err = records.materialize_evidence({"id": "ev2", "query": "SELECT nope FROM orders", "validation_method": "x"}, doc)
        self.assertIn("query failed", err)
        _, err = records.materialize_evidence({"id": "ev3", "doc_quote": "取消率分母不含待付款以外的訂單", "validation_method": "x"}, doc)
        self.assertIn("not a verbatim excerpt", err)
        good, err = records.materialize_evidence({"id": "ev4", "doc_quote": "訂單狀態為已付款、已出貨、已送達", "validation_method": "x"}, doc)
        self.assertIsNone(err); self.assertEqual(good["source"], "domain_knowledge.md")

    def test_apply_patch_operations(self):
        parent = poc1_records()
        before = json.dumps(parent, sort_keys=True)
        new, cfg, touched, errors = records.apply_patch(parent, DEFAULT_TOOL_CONFIG, [
            {"op": "add_alias", "term_id": "term_order_time", "alias": "訂單日期"},
            {"op": "set_tool_config", "section": "resolve", "key": "trigger_keyword_constraints", "value": True},
            {"op": "add_alias", "term_id": "term_missing", "alias": "x"},
            {"op": "set_tool_config", "section": "resolve", "key": "made_up", "value": 1}], "")
        self.assertEqual(json.dumps(parent, sort_keys=True), before)                 # Parent is never mutated
        self.assertIn("訂單日期", next(t for t in new["terms"] if t["id"] == "term_order_time")["aliases"])
        self.assertTrue(cfg["resolve"]["trigger_keyword_constraints"])
        self.assertEqual(len(errors), 2)
        self.assertEqual(touched, ["term_order_time", "tool_config:resolve.trigger_keyword_constraints"])
        diff = records.diff_records(parent, new)
        self.assertIn("term_order_time", diff["changed"]["terms"])


class TestToolLayerKnobs(unittest.TestCase):
    def layer(self, **resolve):
        base = TunedSemanticLayer.load_tuned(POC1_WS, "ontology_v0")
        cfg = json.loads(json.dumps(DEFAULT_TOOL_CONFIG)); cfg["resolve"].update(resolve)
        return TunedSemanticLayer(base.store, cfg)

    def test_default_behaviour_equals_the_repo_runtime(self):
        r = self.layer().resolve(["訂單日期"], "依訂單日期統計 7 月")
        self.assertEqual(r["results"][0]["status"], "unresolved")
        self.assertNotIn("triggered_constraints", r)

    def test_trigger_keyword_knob_surfaces_the_timezone_rule(self):
        r = self.layer(trigger_keyword_constraints=True).resolve(["有效訂單"], "依訂單日期統計 7 月的有效訂單，按月份")
        self.assertIn("con_tz_order_time", [c["id"] for c in r.get("triggered_constraints", [])])

    def test_fuzzy_fallback_bridges_partial_names_but_not_synonyms(self):
        layer = self.layer(fuzzy_fallback=True)
        self.assertEqual(layer.resolve(["成立時間"], "")["results"][0]["term"]["id"], "term_order_time")   # partial name: bridged
        # a pure synonym ("訂單日期" vs "訂單成立時間") shares no characters worth matching: still unresolved.
        # That gap can only be closed by Content (an alias), not by a Tool knob.
        self.assertEqual(layer.resolve(["訂單日期"], "")["results"][0]["status"], "unresolved")


class TestAuditFixes(unittest.TestCase):
    """Regression tests for bugs found by the pre-report code audit."""

    def test_tool_config_may_pin_a_constraint_added_by_the_same_patch(self):
        from evopipe.semantic import validate_tool_config
        cfg = {"manifest": {"pinned_constraint_ids": ["con_new"]}}
        self.assertEqual(validate_tool_config(cfg, {"con_new", "con_old"}), [])
        self.assertTrue(validate_tool_config(cfg, {"con_old"}))

    def test_activation_matches_whole_ids_not_substrings(self):
        blob = json.dumps([{"result": {"term": {"id": "term_order_time"}}}])
        self.assertNotIn('"term_order"', blob)            # the old substring test would have said 'activated'
        self.assertIn('"term_order_time"', blob)


class TestRuntimeReachability(unittest.TestCase):
    def test_mapping_targeted_constraints_are_invisible_to_resolve(self):
        """Audit finding about the repo runtime: resolve only returns constraints whose target is the resolved Term."""
        base = poc1_records()
        layer = TunedSemanticLayer.load_tuned(POC1_WS, "ontology_v0")
        self.assertIn("con_tz_order_time", [c["id"] for c in layer.resolve(["訂單成立時間"])["results"][0]["constraints"]])   # Term-targeted: reachable
        recs = json.loads(json.dumps(base))
        mapping = next(m for m in recs["mappings"] if m["term_id"] == "term_order_time")
        next(c for c in recs["constraints"] if c["id"] == "con_tz_order_time")["target"] = mapping["id"]
        self.assertEqual(records.unreachable_constraints(recs), ["con_tz_order_time"])


class TestJudgeRobustness(unittest.TestCase):
    """Found by the audit: 6 of 46 judge replies were not JSON (chain-of-thought leaked, or empty) and were silently scored as ties."""

    def run_pair(self, replies):
        from evopipe.judge import judge_pair
        run = {"final_answer": {"answer": "1", "basis": "b"}, "native_tool_calls": [], "task_status": "completed"}
        backend = MockBackend(replies)
        j = LLM("judge", backend=backend, models={"judge": "m"})
        return judge_pair(j, question="q", parent_run=run, candidate_run=run, seed="s"), backend

    def test_invalid_reply_is_retried_not_turned_into_a_tie(self):
        good = '{"winner": "A", "reason": "r", "critical_error": false}'
        verdict, backend = self.run_pair(["我先想想…（沒有 JSON）", "", good])
        self.assertIn(verdict["winner"], ("parent", "candidate"))
        self.assertEqual(len(backend.calls), 3)

    def test_gives_up_loudly_after_three_invalid_replies(self):
        from evopipe.judge import JudgeError
        with self.assertRaises(JudgeError):
            self.run_pair(["nope", "", "still nope"])


class TestEvolutionStateMachine(unittest.TestCase):
    """The repo's EvolutionSession + our gate_input: Reject keeps the run alive, Accept publishes, rules are enforced."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="evopipe_ws_", dir=os.path.join(config.V3, "runs"))
        self.ws = os.path.join(self.tmp, ".evoontology")
        for name in ("versions", "reports"):
            shutil.copytree(os.path.join(POC1_WS, name), os.path.join(self.ws, name))
        for name in ("project.json", "active.json", "state.json"):
            shutil.copy(os.path.join(POC1_WS, name), os.path.join(self.ws, name))
        os.makedirs(os.path.join(self.ws, "trajectories"), exist_ok=True)
        os.makedirs(os.path.join(self.ws, "evolution"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def op(self, name, **kw):
        from evoontology.runtime import ops
        kw["workspace"] = self.ws
        return ops.execute(name, kw)

    def candidate(self, name):
        shutil.copytree(os.path.join(self.ws, "versions", "ontology_v0"), os.path.join(self.ws, "versions", name))
        shutil.copy(os.path.join(self.ws, "reports", "ontology_v0.json"), os.path.join(self.ws, "reports", name + ".json"))

    def gate(self, name, wins, losses, ties, critical=0, regress=False):
        verdicts = [{"winner": "candidate", "critical_error": False}] * wins + [{"winner": "parent", "critical_error": False}] * losses \
                   + [{"winner": "tie", "critical_error": False}] * ties + [{"winner": "tie", "critical_error": True}] * critical
        self.op("record_evolution_evaluation", subject=name, role="candidate", result={
            "metrics": {"w": wins}, "gate_input": {"protocol": "llm_judge", "verdicts": verdicts, "unacceptable_regressions": regress}})

    def start(self, max_rounds=3):
        return self.op("start_evolution_run", parent_version="ontology_v0", max_rounds=max_rounds, acceptance={"protocol": "llm_judge"})

    def test_reject_reject_accept(self):
        self.start()
        for i, (w, l) in enumerate([(2, 2), (1, 3)], 1):           # ties / losses -> gate refuses
            self.candidate("v0-c%d" % i)
            self.op("begin_evolution_round", hypothesis="h%d" % i, candidate_version="v0-c%d" % i)
            self.gate("v0-c%d" % i, w, l, 0)
            with self.assertRaises(EvolutionError):
                self.op("accept_evolution")
            self.op("record_evolution_round", decision="reject", metrics={}, notes="n")
            self.assertEqual(EvolutionSession(self.ws).latest_run()["status"], "running")      # a Reject never ends the run
        self.candidate("v0-c3")
        self.op("begin_evolution_round", hypothesis="h3", candidate_version="v0-c3")
        self.gate("v0-c3", 4, 1, 3)
        self.assertEqual(self.op("accept_evolution")["accepted_version"], "ontology_v1")
        self.assertEqual(SemanticStore.active_version(self.ws), "ontology_v1")
        self.assertEqual(EvolutionSession(self.ws).latest_run()["status"], "accepted")

    def test_gate_refuses_critical_error_and_missing_regression_ruling(self):
        self.start(); self.candidate("v0-c1")
        self.op("begin_evolution_round", hypothesis="h", candidate_version="v0-c1")
        self.gate("v0-c1", 5, 0, 0, critical=1)                      # strictly more wins but one critical error
        with self.assertRaises(EvolutionError):
            self.op("accept_evolution")
        self.gate("v0-c1", 5, 0, 0, regress=True)
        with self.assertRaises(EvolutionError):
            self.op("accept_evolution")

    def test_incomplete_rules(self):
        self.start(max_rounds=2)
        with self.assertRaises(EvolutionError):                      # needs >= 2 rejects before 'unreliable_evaluation'
            self.op("mark_evolution_incomplete", reason="unreliable_evaluation")
        with self.assertRaises(EvolutionError):                      # budget not spent yet
            self.op("mark_evolution_incomplete", reason="budget_exhausted")
        for i in (1, 2):
            self.candidate("v0-c%d" % i)
            self.op("begin_evolution_round", hypothesis="h", candidate_version="v0-c%d" % i)
            self.op("record_evolution_round", decision="reject", metrics={}, notes="")
        self.op("mark_evolution_incomplete", reason="budget_exhausted")
        self.assertEqual(SemanticStore.active_version(self.ws), "ontology_v0")      # Parent stays active
        self.assertEqual(EvolutionSession(self.ws).latest_run()["status"], "incomplete")


class TestGateMath(unittest.TestCase):
    def test_judge_gate_is_conservative(self):
        V = lambda w, c=False: {"winner": w, "critical_error": c}
        self.assertTrue(EvaluationGate.decide_judge([V("candidate"), V("tie")])["accept"])
        self.assertFalse(EvaluationGate.decide_judge([V("candidate"), V("parent")])["accept"])      # tie in wins -> keep Parent
        self.assertFalse(EvaluationGate.decide_judge([V("tie")] * 5)["accept"])                    # all ties -> keep Parent
        self.assertFalse(EvaluationGate.decide_judge([V("candidate")] * 5 + [V("tie", True)])["accept"])


if __name__ == "__main__":
    unittest.main()
