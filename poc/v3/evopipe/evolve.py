"""EVOLVE — one self-evolution run (docs: evolve-ontology skill; state machine: evoontology.evolution.session).

    E0  trigger check, freeze batch, split Pool/Reserve, start_evolution_run         (code, core ops)
    loop until Accept / budget spent:
      E1  Diagnose   → problem map          LLM agent loop (probe/sql/doc tools)       [Pool only]
      E2  Attribute  → competing hypotheses LLM agent loop                             [Pool only]
      E3  Patch      → typed operations     LLM + code applies them to a Parent copy   [Pool only]
          save Candidate `vN-cK`, validate, annotate; mechanism check = replay Pool failures with the Candidate
      E4  Gate       → Parent vs Candidate on the Validation Reserve, anonymous LLM Judge,
                       EvaluationGate (+ a confirmation repetition, as the skill requires for small validation sets)
          Accept → accept_evolution (publish ontology_vN+1, switch active.json, advance checkpoint)
          Reject → record_evolution_round, next Candidate in the same run
    E5  finalize_evolution_run (render HTML) + run report

The Validation Reserve is only ever touched inside ``gate``; every Evolver-facing function receives Pool data only.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from evoontology.evolution.session import EvolutionBudgetExhausted, EvolutionSession
from evoontology.evaluation.evaluation import EvaluationGate
from evoontology.ontology.store import SemanticStore
from evoontology.trajectory.trajectory import TrajectoryStore

from . import config, use
from .agent import ToolSpec, run_agent
from .core import op
from .judge import build_prompt, judge_pair, recover_from_log, regression_rule
from .llm import LLM, extract_json
from .prompts import read_repo_text, render, section
from .records import FAMILIES, PATCH_OPS, apply_patch, check_records, diff_records
from .runner import run_questions
from .semantic import TunedSemanticLayer, load_tool_config, save_tool_config, validate_tool_config
from .tools_data import doc_tool, sql_tool

LOG = os.path.join(config.RUNS, "evolve.log")


def log(message: str) -> None:
    line = "%s %s" % (time.strftime("%H:%M:%S"), message)
    print(line, flush=True)
    os.makedirs(config.RUNS, exist_ok=True)
    open(LOG, "a", encoding="utf-8").write(line + "\n")


def read_json(path, default=None):
    return json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else default


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(value, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# =============================================================================== E0: freeze the batch
def _shingles(text: str, n: int = 3) -> set:
    text = re.sub(r"\s+", "", text)
    return {text[i:i + n] for i in range(max(1, len(text) - n + 1))}


def group_near_duplicates(trajs: List[Dict[str, Any]], threshold: float = config.NEAR_DUP_JACCARD) -> List[List[Dict[str, Any]]]:
    """Data-boundary doc: group duplicate/near-duplicate questions *before* the chronological split so related replays
    cannot sit on both sides of the Pool/Reserve boundary."""
    groups: List[List[Dict[str, Any]]] = []
    for t in trajs:
        sh = _shingles(t["question"])
        for g in groups:
            ref = _shingles(g[0]["question"])
            if len(sh & ref) / len(sh | ref) >= threshold:
                g.append(t)
                break
        else:
            groups.append([t])
    return groups


def freeze_batch(workspace: str):
    state = read_json(os.path.join(workspace, "state.json"), {})
    store = TrajectoryStore(workspace)
    batch = [t for t in store.list_since(state.get("checkpoint_trajectory")) if t.get("split") == "production"]
    batch.sort(key=lambda t: t["recorded_at"])
    groups = group_near_duplicates(batch)
    cut = round(len(batch) * config.POOL_FRACTION)
    pool: List[Dict[str, Any]] = []
    reserve: List[Dict[str, Any]] = []
    for g in groups:                    # groups are in first-appearance (chronological) order
        (pool if len(pool) < cut else reserve).extend(g)
    return batch, pool, reserve, groups


# =============================================================================== prompt material
def render_trajectory(t: Dict[str, Any]) -> str:
    lines = ["### %s｜%s" % (t["question_id"], t["question"])]
    for c in t.get("semantic_calls", []):
        inp, res = c["input"], c.get("result", {})
        if c["tool"] == "resolve_semantics":
            parts = []
            for r in res.get("results", []):
                cons = [x["id"] for x in r.get("constraints", [])]
                parts.append("%s→%s%s" % (r.get("query"), r.get("status"), (" 規則=" + ",".join(cons)) if cons else ""))
            if res.get("triggered_constraints"):
                parts.append("triggered=" + ",".join(x["id"] for x in res["triggered_constraints"]))
            lines.append("語意 resolve(mentions=%s, context=%s) → %s" % (inp.get("mentions"), str(inp.get("context", ""))[:60], "; ".join(parts)))
        else:
            lines.append("語意 browse(query=%s) → %d 筆 %s" % (inp.get("query"), len(res.get("items", [])), [i["id"] for i in res.get("items", [])][:5]))
    for c in t.get("native_tool_calls", []):
        inp = c["input"]
        q = inp.get("query") or json.dumps(inp.get("queries"), ensure_ascii=False) if isinstance(inp, dict) else str(inp)
        lines.append("SQL: %s → %s" % (str(q)[:260].replace("\n", " "), str(c.get("result_summary") or c.get("result"))[:90].replace("\n", " ")))
    fa = t.get("final_answer") or {}
    lines.append("最終答案: %s｜依據: %s｜狀態: %s" % (fa.get("answer"), str(fa.get("basis", ""))[:200], t.get("task_status")))
    return "\n".join(lines)


def render_catalog(records: Dict[str, List[Dict[str, Any]]], tool_config: Dict[str, Any], constraint_chars: int = 110) -> str:
    out = ["## 目前語意層（%d terms / %d mappings / %d relations / %d constraints / %d evidence）" % tuple(len(records[f]) for f in FAMILIES)]
    out.append("### Terms（id｜名稱｜型別｜別名）")
    for t in records["terms"]:
        out.append("- %s｜%s｜%s｜%s" % (t["id"], t["name"], t["type"], t.get("aliases", [])[:10]))
    out.append("### Mappings")
    out += ["- %s: %s → %s.%s" % (m["id"], m["term_id"], m["table"], m["column"]) for m in records["mappings"]]
    out.append("### Constraints（id｜target｜severity｜trigger_keywords｜說明）")
    for c in records["constraints"]:
        out.append("- %s｜%s｜%s｜%s｜%s" % (c["id"], c["target"], c["severity"], c["trigger_keywords"][:10], c["description"][:constraint_chars]))
    out.append("### Tool Layer 設定\n" + json.dumps(tool_config, ensure_ascii=False))
    return "\n".join(out)


def load_records(workspace: str, version: str) -> Dict[str, List[Dict[str, Any]]]:
    _, records = SemanticStore.load_records(workspace, version)
    return records


def evolve_common(skill: str, step_heading: str, next_heading: Optional[str]) -> str:
    principles = section(skill, "## Core Principles", "## Before Evolution") + "\n\n" + section(skill, "## Prohibited Actions", "## Final Deliverable")
    stage_text = section(skill, step_heading, next_heading)
    return render("evolve_common.md", principles=principles, stage_text=stage_text)


def probe_tool(workspace: str, version: str) -> ToolSpec:
    layer = TunedSemanticLayer.load_tuned(workspace, version)

    def fn(args):
        if args.get("tool") == "browse":
            return layer.execute("browse_semantics", {"query": args.get("query", ""), "kind": args.get("kind", "all"), "limit": 6})
        mentions = args.get("mentions") or []
        return layer.execute("resolve_semantics", {"mentions": [mentions] if isinstance(mentions, str) else mentions,
                                                   "context": args.get("context", "")})
    return ToolSpec("probe_semantics", "用 Parent 版本的語意工具實際試打（探測檢索行為）",
                    '{"tool": "resolve", "mentions": ["<說法>"], "context": "<分析需求>"} 或 {"tool": "browse", "query": "<關鍵詞>", "kind": "all"}', fn)


# =============================================================================== E1-E3
def diagnose(evolver: LLM, skill: str, workspace: str, parent: str, pool: List[Dict[str, Any]], profile_text: str, doc_text: str):
    records = load_records(workspace, parent)
    system = render("evolve_diagnose.md", common=evolve_common(skill, "### Step 1", "### Step 2"))
    task = ("## Evolution Pool 軌跡（%d 筆）\n\n" % len(pool) + "\n\n".join(render_trajectory(t) for t in pool)
            + "\n\n" + render_catalog(records, load_tool_config(workspace, parent))
            + "\n\n## 業務說明文件\n" + doc_text + "\n\n請開始診斷（資料表結構與內容可用 sql_query 查）。")
    submit = ToolSpec("submit_problem_map", "交付問題地圖（最終工具）", "{problem_map: [...], summary: str}", lambda a: None)
    result = run_agent(evolver, stage="evolve.diagnose", system=system, task=task,
                       tools=[probe_tool(workspace, parent), sql_tool(), doc_tool(), submit], final_tool="submit_problem_map", max_steps=10)
    if result.final is None:
        raise RuntimeError("diagnose ended without a problem map (%s)" % result.ended_by)
    pool_ids = {t["question_id"] for t in pool}
    for p in result.final.get("problem_map", []):               # code enforces the data boundary on the LLM's output
        p["affected_tasks"] = [q for q in p.get("affected_tasks", []) if q in pool_ids]
    return result.final, result.events


def attribute(evolver: LLM, skill: str, workspace: str, parent: str, problem_map: Dict[str, Any], rejected: List[Dict[str, Any]]):
    records = load_records(workspace, parent)
    system = render("evolve_attribute.md", common=evolve_common(skill, "### Step 2", "### Step 3"))
    task = ("## 問題地圖\n" + json.dumps(problem_map, ensure_ascii=False, indent=1) + "\n\n"
            + render_catalog(records, load_tool_config(workspace, parent)))
    if rejected:
        task += ("\n\n## 本次 run 中已被正式驗證拒絕的 Candidate（只提供假說與維度；驗證集的題目、評審理由與結果不得被使用）\n"
                 + json.dumps(rejected, ensure_ascii=False, indent=1) + "\n請提出不同於上述的機制，或修正先前的歸因。")
    submit = ToolSpec("submit_attribution", "交付歸因結果（最終工具）", "{hypotheses: [...], primary: str, reasoning: str}", lambda a: None)
    result = run_agent(evolver, stage="evolve.attribute", system=system, task=task,
                       tools=[probe_tool(workspace, parent), sql_tool(), submit], final_tool="submit_attribution", max_steps=8)
    if result.final is None:
        raise RuntimeError("attribute ended without a result (%s)" % result.ended_by)
    return result.final, result.events


def design_patch(evolver: LLM, skill: str, workspace: str, parent: str, attribution: Dict[str, Any], doc_text: str,
                 profile_text: str, feedback: List[str]):
    records = load_records(workspace, parent)
    tool_config = load_tool_config(workspace, parent)
    ops_text = "\n".join("- `%s`: %s" % (k, v) for k, v in PATCH_OPS.items())
    system = render("evolve_patch.md", common=evolve_common(skill, "### Step 3", "### Step 4"), ops=ops_text)
    primary = next((h for h in attribution["hypotheses"] if h["id"] == attribution.get("primary")), attribution["hypotheses"][0])
    task = ("## 主要假說\n" + json.dumps(primary, ensure_ascii=False, indent=1)
            + "\n\n## Parent 的語意物件（目錄；既有 id 都列在這裡，新 id 不可與之重複）\n" + render_catalog(records, tool_config, constraint_chars=400)
            + "\n\n## 既有證據 id\n" + ", ".join(e["id"] for e in records["evidence"])
            + "\n\n## 業務說明文件\n" + doc_text)
    if feedback:
        task += "\n\n## 上一次嘗試的問題（請修正後重新輸出完整 JSON）\n" + "\n".join("- " + f for f in feedback)
    reply = evolver.chat(stage="evolve.patch", system=system, messages=[{"role": "user", "content": task}])
    return extract_json(reply), primary


def build_candidate(patch: Dict[str, Any], workspace: str, parent: str, doc_text: str):
    """Apply the proposed operations to a copy of the Parent and run every deterministic check."""
    parent_records = load_records(workspace, parent)
    records, tool_config, touched, errors = apply_patch(parent_records, load_tool_config(workspace, parent),
                                                        patch.get("operations", []), doc_text)
    if not errors:
        errors += check_records(records)
        errors += validate_tool_config(tool_config, {c["id"] for c in records["constraints"]})
        if not touched:
            errors.append("the patch changed nothing (no-op); a Candidate must modify the system")
    return records, tool_config, touched, errors, parent_records


def save_candidate(workspace: str, name: str, records, tool_config, parent: str, hypothesis: str) -> Dict[str, Any]:
    op(workspace, "save_version", version=name, records=records)
    save_tool_config(workspace, name, tool_config)
    validation = op(workspace, "validate_semantics", version=name)
    report = read_json(os.path.join(workspace, "reports", parent + ".json"), {})
    valid_ids = {r["id"] for fam in FAMILIES for r in records[fam]}
    links = [{"question_id": l["question_id"], "object_ids": [o for o in l["object_ids"] if o in valid_ids]} for l in report.get("links", [])]
    op(workspace, "annotate_ontology_version", version=name, summary="%s｜演化自 %s：%s" % (report.get("summary", ""), parent, hypothesis),
       limitations=report.get("limitations", []), links=links)
    return validation


# =============================================================================== mechanism check (Step 3.6)
def targets_for(pool: List[Dict[str, Any]], problem_map: Dict[str, Any], hypothesis: Dict[str, Any], limit: int = 6) -> List[Dict[str, Any]]:
    """Pool tasks affected by the problems THIS hypothesis is about.  (Audit finding: the first version used the union of all problems, so the
    round-2 timezone patch was 'checked' on cancel-rate/delivery tasks it was never meant to change.)"""
    wanted = set(hypothesis.get("problems", []))
    problems = [p for p in problem_map.get("problem_map", []) if not wanted or p.get("id") in wanted]
    ids = {q for p in problems for q in p.get("affected_tasks", [])}
    return [t for t in pool if t["question_id"] in ids][:limit]


def mechanism_check(workspace: str, candidate: str, touched: List[str], targets: List[Dict[str, Any]], out_dir: str) -> Dict[str, Any]:
    if not targets:
        return {"tested": 0, "activation_rate": None, "answer_changed_rate": None, "tasks": []}
    runs = run_questions([{"id": t["question_id"], "question": t["question"]} for t in targets], version=candidate, arm="ontology",
                         out_dir=out_dir, workspace=workspace, stage="evolve.replay")
    tasks, tool_knobs = [], [t for t in touched if t.startswith("tool_config:")]
    ids = [t for t in touched if not t.startswith("tool_config:")]
    for t in targets:
        r = runs[t["question_id"]]
        blob = json.dumps(r.get("semantic_calls", []), ensure_ascii=False)
        activated = any(('"%s"' % i) in blob for i in ids) or (bool(tool_knobs) and ("triggered_constraints" in blob or "fuzzy match" in blob
                                                                           or any("pinned" in k for k in tool_knobs)))
        before, after = (t.get("final_answer") or {}).get("answer"), (r.get("final_answer") or {}).get("answer")
        tasks.append({"question_id": t["question_id"], "activated": activated, "answer_before": before, "answer_after": after,
                      "changed": str(before) != str(after)})
    n = len(tasks)
    return {"tested": n, "activation_rate": sum(x["activated"] for x in tasks) / n,
            "answer_changed_rate": sum(x["changed"] for x in tasks) / n, "tasks": tasks}


# =============================================================================== E4: the gate
def gate_repetition(workspace: str, run_dir: str, rnd: int, rep: int, parent: str, candidate: str, reserve: List[Dict[str, Any]],
                    agent: LLM, judge: LLM, seed: str) -> Dict[str, Any]:
    questions = [{"id": t["question_id"], "question": t["question"]} for t in reserve]
    base = os.path.join(run_dir, "artifacts", "round%d" % rnd, "rep%d" % rep)
    with ThreadPoolExecutor(max_workers=2) as ex:        # same questions, same agent model, same settings for both sides
        fp = ex.submit(run_questions, questions, version=parent, arm="ontology", out_dir=os.path.join(base, "parent"),
                       workspace=workspace, stage="evolve.gate.parent", llm=agent)
        fc = ex.submit(run_questions, questions, version=candidate, arm="ontology", out_dir=os.path.join(base, "candidate"),
                       workspace=workspace, stage="evolve.gate.candidate", llm=agent)
        parent_runs, cand_runs = fp.result(), fc.result()

    def one(q):
        cache = os.path.join(base, "judge_cache", q["id"] + ".json")
        pair_seed = "%s-r%d-rep%d-%s" % (seed, rnd, rep, q["id"])
        if not os.path.isfile(cache):                       # a resumed run: restore a verdict already paid for, if the log has it
            prompt, _ = build_prompt(q["question"], parent_runs[q["id"]], cand_runs[q["id"]], pair_seed)
            if recover_from_log(cache, prompt):
                log("recovered judge verdict for %s from the call log" % q["id"])
        return q["id"], judge_pair(judge, question=q["question"], parent_run=parent_runs[q["id"]], candidate_run=cand_runs[q["id"]],
                                   seed=pair_seed, cache_path=cache)
    with ThreadPoolExecutor(max_workers=config.CONCURRENCY) as ex:
        verdicts = dict(ex.map(one, questions))
    ordered = [dict(verdicts[q["id"]], case_id="rep%d:%s" % (rep, q["id"])) for q in questions]
    decision = EvaluationGate.decide_judge(ordered)
    return {"verdicts": ordered, "decision": decision, "dir": base}


# =============================================================================== the run
class EvolveRun:
    def __init__(self, workspace: str = config.WORKSPACE, max_rounds: int = config.MAX_ROUNDS):
        self.ws, self.max_rounds = workspace, max_rounds
        self.skill = read_repo_text(config.EVOLVE_SKILL)
        self.evolver, self.agent, self.judge = LLM("evolver"), LLM("agent"), LLM("judge")
        self.doc_text = open(config.DOC_PATH, encoding="utf-8").read()
        self.profile_text = open(os.path.join(config.RUNS, "build", "profile.md"), encoding="utf-8").read()

    def run(self) -> Dict[str, Any]:
        status = op(self.ws, "evolution_status")
        log("trigger: %s" % json.dumps(status["check"], ensure_ascii=False))
        if not status["check"]["evolution_due"]:
            raise RuntimeError("evolution is not due: %s" % status["check"]["reason"])
        parent = SemanticStore.active_version(self.ws)
        batch, pool, reserve, groups = freeze_batch(self.ws)
        log("frozen batch: %d tasks, %d near-dup groups -> pool %d / reserve %d" % (len(batch), len(groups), len(pool), len(reserve)))

        existing = EvolutionSession(self.ws).latest_run()
        resume = existing is not None and existing["status"] == "running"
        latest = lambda: EvolutionSession(self.ws).latest_run()      # always re-read: ops write state through their own sessions
        if resume:                                                   # continue an interrupted run (budget cap, crash, ...)
            run = existing
            run_dir = os.path.join(self.ws, "evolution", run["run_id"])
            frozen = read_json(os.path.join(run_dir, "frozen_batch.json"))
            assert [x["task_id"] for x in frozen["pool"]] == [t["task_id"] for t in pool], "frozen batch changed since the run started"
            assert [x["task_id"] for x in frozen["validation_reserve"]] == [t["task_id"] for t in reserve], "frozen batch changed"
            parent = run["parent_version"]
            log("RESUMING %s: round %d, candidate %s" % (run["run_id"], run["round"], run.get("current_candidate")))
        else:
            run = op(self.ws, "start_evolution_run", parent_version=parent, adapter="evopipe-sqlite-v1", max_rounds=self.max_rounds,
                     acceptance={"protocol": "llm_judge", "rule": "E_c == 0 and W_c > W_p (EvaluationGate.decide_judge)",
                                 "confirmation": "a second independent repetition must also accept",
                                 "regression_policy": "critical error, or Parent wins > 1/3 as often as Candidate",
                                 "judge_role": "judge", "validation_reserve_size": len(reserve), "pool_size": len(pool)})
            run_dir = os.path.join(self.ws, "evolution", run["run_id"])
            write_json(os.path.join(run_dir, "frozen_batch.json"), {
                "parent": parent, "rule": "chronological %d%%/%d%% split after near-duplicate grouping" % (config.POOL_FRACTION * 100, 100 - config.POOL_FRACTION * 100),
                "pool": [{"task_id": t["task_id"], "question_id": t["question_id"]} for t in pool],
                "validation_reserve": [{"task_id": t["task_id"], "question_id": t["question_id"]} for t in reserve]})
            op(self.ws, "confirm_trajectory_sources", sources=[{"path": os.path.join(self.ws, "trajectories"),
                                                        "scope": "%d production tasks since the last checkpoint (frozen)" % len(batch),
                                                        "purpose": "pool -> diagnosis/design; reserve -> Parent/Candidate gate only"}])

        problem_map = attribution = None
        rejected: List[Dict[str, Any]] = []
        tried: set = set()
        rounds: List[Dict[str, Any]] = []
        open_round = False
        if resume:                                                   # rebuild the in-memory state from what the run persisted
            pm = read_json(os.path.join(run_dir, "problem_map.json"))
            problem_map = pm["problem_map"] if pm else None
            files = sorted(glob.glob(os.path.join(run_dir, "attribution_round*.json")))
            attribution = read_json(files[-1]) if files else None
            recorded = []
            rpath = os.path.join(run_dir, "rounds.jsonl")
            if os.path.isfile(rpath):
                recorded = [json.loads(l) for l in open(rpath, encoding="utf-8") if l.strip()]
            rejected = [{"hypothesis": r["hypothesis"], "why": "rejected by the formal gate"} for r in recorded]
            open_round = run["round"] > 0 and run["round"] not in {r["round"] for r in recorded}
        while latest()["status"] == "running":
            if not open_round and latest()["round"] >= self.max_rounds:
                op(self.ws, "mark_evolution_incomplete", reason="budget_exhausted")
                log("budget exhausted -> incomplete")
                break
            rnd = latest()["round"] if open_round else latest()["round"] + 1
            log("=== round %d (parent %s)%s ===" % (rnd, parent, " [resumed at the gate]" if open_round else ""))
            if open_round:
                # The Candidate was already designed, saved and begun. Rebuild it from the persisted patch (deterministic, no LLM;
                # Pool replays are read back from their cache) and go straight to the gate.
                cur = latest()
                candidate_name = cur["current_candidate"]
                attempts = sorted(glob.glob(os.path.join(run_dir, "patch_round%d_attempt*.json" % rnd)))
                patch = read_json(attempts[-1])
                records, tool_config, touched, errors, parent_records = build_candidate(patch, self.ws, parent, self.doc_text)
                assert not errors, errors
                targets = [t for t in pool if t["question_id"] in {q for p in problem_map.get("problem_map", []) for q in p.get("affected_tasks", [])}][:6]
                check = mechanism_check(self.ws, candidate_name, touched, targets,
                                        os.path.join(run_dir, "artifacts", "round%d" % rnd, "mechanism_attempt%d" % len(attempts)))
                primary = {"mechanism": cur.get("current_hypothesis", "")}
                log("round %d state restored: candidate %s, touched %s" % (rnd, candidate_name, touched))
            else:
                if problem_map is None:
                    problem_map, ev = diagnose(self.evolver, self.skill, self.ws, parent, pool, self.profile_text, self.doc_text)
                    write_json(os.path.join(run_dir, "problem_map.json"), {"problem_map": problem_map, "probe_calls": [
                        {"tool": e["tool"], "arguments": e["arguments"]} for e in ev]})
                    log("diagnosis: %d problems" % len(problem_map.get("problem_map", [])))
                if attribution is None or all(h["id"] in tried for h in attribution["hypotheses"]):
                    attribution, ev = attribute(self.evolver, self.skill, self.ws, parent, problem_map, rejected)
                    tried = set()
                    write_json(os.path.join(run_dir, "attribution_round%d.json" % rnd), attribution)
                    log("attribution: primary=%s; %s" % (attribution.get("primary"), [(h["id"], h["dimension"]) for h in attribution["hypotheses"]]))
                current = dict(attribution)
                untried = [h for h in sorted(attribution["hypotheses"], key=lambda h: h.get("priority", 99)) if h["id"] not in tried]
                primary = next((h for h in untried if h["id"] == attribution.get("primary")), untried[0])
                current["primary"] = primary["id"]
                tried.add(primary["id"])

                # ---- E3: design the Candidate (with deterministic checks and up to 3 attempts)
                feedback: List[str] = []
                candidate_name = "v%d-c%d" % (int(parent.rsplit("_v", 1)[1]), rnd)
                patch = records = tool_config = touched = parent_records = None
                check = None
                for attempt in range(1, 4):
                    patch, primary = design_patch(self.evolver, self.skill, self.ws, parent, current, self.doc_text, self.profile_text, feedback)
                    write_json(os.path.join(run_dir, "patch_round%d_attempt%d.json" % (rnd, attempt)), patch)
                    records, tool_config, touched, errors, parent_records = build_candidate(patch, self.ws, parent, self.doc_text)
                    if errors:
                        feedback = errors[:25]
                        log("patch attempt %d rejected by code checks: %s" % (attempt, errors[:3]))
                        continue
                    save_candidate(self.ws, candidate_name, records, tool_config, parent, patch.get("hypothesis", ""))
                    targets = targets_for(pool, problem_map, primary)
                    check = mechanism_check(self.ws, candidate_name, touched, targets,
                                            os.path.join(run_dir, "artifacts", "round%d" % rnd, "mechanism_attempt%d" % attempt))
                    log("mechanism check attempt %d: %s" % (attempt, {k: v for k, v in check.items() if k != "tasks"}))
                    if check["tested"] == 0 or check["activation_rate"] > 0:
                        break
                    feedback = ["Candidate was saved and replayed on Pool tasks %s but none of the touched objects/knobs %s was activated "
                                "(never appeared in the agent's semantic results). Redesign so the changed mechanism is actually reached." % (
                                    [t["question_id"] for t in targets], touched)]
                else:
                    if records is None or check is None or errors:
                        raise RuntimeError("could not produce a valid Candidate in 3 attempts: %s" % feedback)
            diff = diff_records(parent_records, records)
            write_json(os.path.join(run_dir, "diff_round%d.json" % rnd), diff)

            if not open_round:
                session_round = op(self.ws, "begin_evolution_round", hypothesis=patch.get("hypothesis", primary["mechanism"]), candidate_version=candidate_name)
                assert session_round["round"] == rnd
            open_round = False

            if check["tested"] and check["activation_rate"] == 0:
                summary = {"round": rnd, "candidate": candidate_name, "dimension": patch.get("dimension"), "decision": "reject",
                           "reason": "mechanism never activated on Pool replay; formal gate skipped", "mechanism": check}
                op(self.ws, "record_evolution_round", decision="reject", metrics={"mechanism_activation_rate": 0.0}, notes=summary["reason"])
                rejected.append({"hypothesis": patch.get("hypothesis"), "dimension": patch.get("dimension"), "why": summary["reason"]})
                rounds.append(summary)
                continue

            # ---- E4: formal gate on the Validation Reserve (+ confirmation repetition)
            seed = "%s-%s" % (run["run_id"], candidate_name)
            reps = []
            for rep in (1, 2):
                result = gate_repetition(self.ws, run_dir, rnd, rep, parent, candidate_name, reserve, self.agent, self.judge, seed)
                reps.append(result)
                d = result["decision"]
                log("gate rep%d: cand_wins=%d parent_wins=%d ties=%d cand_critical=%d -> %s" % (
                    rep, d["candidate_wins"], d["parent_wins"], d["ties"], d["candidate_critical_errors"], "ACCEPT" if d["accept"] else "reject"))
                if not d["accept"]:
                    break                                    # no point confirming a failed first repetition
            verdicts = [v for r in reps for v in r["verdicts"]]
            pooled = EvaluationGate.decide_judge(verdicts)
            all_reps_accept = len(reps) == 2 and all(r["decision"]["accept"] for r in reps)
            regressions = regression_rule(verdicts)
            gate_input = {"protocol": "llm_judge", "verdicts": [{k: v[k] for k in ("winner", "critical_error")} for v in verdicts],
                          "unacceptable_regressions": bool(regressions or not all_reps_accept)}
            metrics = {"candidate_wins": pooled["candidate_wins"], "parent_wins": pooled["parent_wins"], "ties": pooled["ties"],
                       "candidate_critical_errors": pooled["candidate_critical_errors"], "repetitions": len(reps),
                       "per_repetition": [r["decision"] for r in reps], "mechanism": {k: v for k, v in check.items() if k != "tasks"}}
            cases = [{"id": v["case_id"], "status": v["winner"], "score": None} for v in verdicts]
            arts = [r["dir"] for r in reps]
            op(self.ws, "record_evolution_evaluation", subject=parent, role="parent", result={"metrics": {"note": "baseline for the pairwise comparison"},
               "cases": [], "artifact_paths": [os.path.join(a, "parent") for a in arts], "provenance": "synthetic"})
            op(self.ws, "record_evolution_evaluation", subject=candidate_name, role="candidate", result={
                "metrics": metrics, "cases": cases, "artifact_paths": [os.path.join(a, "candidate") for a in arts],
                "provenance": "synthetic", "gate_input": gate_input})
            write_json(os.path.join(run_dir, "gate_round%d.json" % rnd), {"repetitions": reps, "pooled": pooled, "gate_input": gate_input})

            accept = pooled["accept"] and all_reps_accept and not gate_input["unacceptable_regressions"]
            summary = {"round": rnd, "candidate": candidate_name, "dimension": patch.get("dimension"), "hypothesis": patch.get("hypothesis"),
                       "touched": touched, "pooled": pooled, "decision": "accept" if accept else "reject"}
            rounds.append(summary)
            if accept:
                result = op(self.ws, "accept_evolution")
                log("ACCEPTED -> %s" % result["accepted_version"])
                parent = result["accepted_version"]
            else:
                op(self.ws, "record_evolution_round", decision="reject", metrics=metrics, artifact_refs=arts,
                   notes="gate rejected: pooled %s; every repetition accepted=%s; regressions=%s" % (
                       {k: pooled[k] for k in ("candidate_wins", "parent_wins", "ties", "candidate_critical_errors")}, all_reps_accept, regressions))
                rejected.append({"hypothesis": patch.get("hypothesis"), "dimension": patch.get("dimension"), "why": "rejected by the formal gate"})
                log("rejected (round %d)" % rnd)

        final = op(self.ws, "finalize_evolution_run")
        report = {"run": {k: v for k, v in final.items() if k != "presentation"}, "rounds": rounds,
                  "frozen": {"batch": len(batch), "pool": len(pool), "reserve": len(reserve)}}
        write_json(os.path.join(run_dir, "report.json"), report)
        return report
