"""BUILD — create ontology_v0.  Mirrors the build-ontology skill (Step 0 → Step 1 → Step 2 → Publish).

    B0  configure project + load workload                core ops                         (code)
    B1  data profiling                                   profile.py                       (code)
    B2  explore & verify the business document           LLM agent loop (sql/doc tools)   (LLM)  + code runs every query
    B3  semantic design (two calls) + repair loop        LLM + records.check_records      (LLM + code)
    B4  save_version → validate → annotate → publish     core ops                         (code)

Every stage writes its artefact under runs/build/ and is skipped on re-run if the artefact exists (resumable).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from . import config
from .agent import ToolSpec, run_agent
from .core import op
from .llm import LLM, extract_json
from .profile import profile_db, render_profile
from .prompts import read_repo_text, render, section
from .records import FAMILIES, check_records, materialize_evidence, missing_mappings
from .tools_data import doc_tool, schema_tool, sql_tool

BUILD_DIR = os.path.join(config.RUNS, "build")


def _cached(name: str, make):
    path = os.path.join(BUILD_DIR, name)
    if os.path.isfile(path):
        return json.load(open(path, encoding="utf-8"))
    value = make()
    os.makedirs(BUILD_DIR, exist_ok=True)
    json.dump(value, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return value


def b0_configure() -> List[Dict[str, str]]:
    project = {"schema_version": 1, "mode": "rolling_trajectory",
               "data_source": {"type": "sqlite", "path": config.DB_PATH},
               "workload_source": {"type": "project_workload", "path": config.CONSTRUCTION_Q,
                                   "note": "user-supplied exhaustive construction workload; domain_knowledge.md is a data-environment document"},
               "evaluation": {"type": "llm_judge"}, "boundary": {"strategy": "rolling_trajectory"}}
    op(config.WORKSPACE, "configure_ontology_project", project=project)
    questions = json.load(open(config.CONSTRUCTION_Q, encoding="utf-8"))
    op(config.WORKSPACE, "prepare_ontology_workload", questions=[{"id": q["id"], "question": q["question"]} for q in questions],
       supplied_only=True, limit=100)
    return questions


def b2_explore(llm: LLM, questions, profile_text: str, doc_text: str) -> Dict[str, Any]:
    skill = read_repo_text(config.BUILD_SKILL)
    system = render("build_explore.md", skill_step1=section(skill, "## Step 1", "## Step 2"))
    task = ("## 建構題（工作負載）\n" + "\n".join("- %s：%s" % (q["id"], q["question"]) for q in questions)
            + "\n\n## 業務說明文件（domain_knowledge.md）\n" + doc_text + "\n\n" + profile_text
            + "\n\n請開始探勘；完成後呼叫 submit_evidence。")
    submit = ToolSpec("submit_evidence", "交付證據提案（最終工具）", '{"evidence": [ ... ]}', lambda a: None)
    result = run_agent(llm, stage="build.explore", system=system, task=task,
                       tools=[sql_tool(), doc_tool(), schema_tool(), submit], final_tool="submit_evidence", max_steps=16)
    if result.final is None:
        raise RuntimeError("explore agent ended without submit_evidence (%s)" % result.ended_by)
    verified, rejected = [], []
    for item in result.final.get("evidence", []):
        record, error = materialize_evidence(item, doc_text)
        if error:
            rejected.append({"proposal": item, "error": error})
        elif any(e["id"] == record["id"] for e in verified):
            rejected.append({"proposal": item, "error": "duplicate evidence id"})
        else:
            record["_claim"] = item.get("claim", "")
            verified.append(record)
    return {"verified": verified, "rejected": rejected, "steps": result.steps,
            "tool_calls": [{"tool": e["tool"], "arguments": e["arguments"], "error": e["error"]} for e in result.events]}


def _evidence_listing(evidence: List[Dict[str, Any]]) -> str:
    return "\n".join("- %s | 主張: %s | 觀察: %s" % (e["id"], e.get("_claim", ""), e["result"][:260].replace("\n", " "))
                     for e in evidence)


def _design_system() -> str:
    skill = read_repo_text(config.BUILD_SKILL)
    return render("build_design.md", skill_step2=section(skill, "## Step 2", "### Publish"),
                  schema_md=read_repo_text(config.SCHEMA_MD))


def _design_context(questions, doc_text, profile_text, evidence) -> str:
    return ("## 建構題（工作負載）\n" + "\n".join("- %s：%s" % (q["id"], q["question"]) for q in questions)
            + "\n\n## 業務說明文件\n" + doc_text + "\n\n" + profile_text
            + "\n\n## 已驗證證據（可引用的 evidence id；內容為程式實際執行查詢後的觀察）\n" + _evidence_listing(evidence))


def b3_design(llm: LLM, questions, doc_text, profile_text, evidence) -> Dict[str, Any]:
    system = _design_system()
    context = _design_context(questions, doc_text, profile_text, evidence)
    # call (a): terms + mappings
    reply_a = llm.chat(stage="build.design_a", system=system, messages=[{"role": "user", "content": context + (
        "\n\n---\n## 本次要產生：Terms 與 Mappings\n回覆 JSON：{\"terms\": [...], \"mappings\": [...]}\n"
        "Term 欄位：id,name,type,definition,scope,aliases,evidence；Mapping 欄位：id,term_id,database_source(\"shop_v2\"),table,column,"
        "semantic_filter(可省略),aggregation_semantics(可省略),grain,validation(引用的 evidence id 以逗號分隔的字串)。\n"
        "涵蓋所有建構題需要的概念；一個 Term 可以有多個 Mapping（不同表/欄位承載不同角色）；跨表衍生指標以最主要的欄位建 Mapping，"
        "其計算語意寫在 aggregation_semantics 與 Relation(derivation)。")}])
    part_a = extract_json(reply_a)
    # call (b): relations + constraints + limitations
    reply_b = llm.chat(stage="build.design_b", system=system, messages=[{"role": "user", "content": context + (
        "\n\n---\n## 已產生的 Terms 與 Mappings\n" + json.dumps(part_a, ensure_ascii=False)
        + "\n\n---\n## 本次要產生：Relations、Constraints、限制與摘要\n"
        "回覆 JSON：{\"relations\": [...], \"constraints\": [...], \"known_limitations\": [\"...\"], \"summary\": \"...\"}\n"
        "Relation 欄位：id,source,relation_type,target,connection_condition,description,evidence；"
        "Constraint 欄位：id,target,constraint_type,trigger_keywords,severity,scope,confidence,description,evidence。\n"
        "重點：把所有「用錯會得到錯誤結果」的業務規則（有效訂單的定義、時間換算、金額單位、代碼意義、各指標的歸屬方式等）寫成 Constraint，"
        "severity 用 block；文件有寫但資料無法佐證的主張寫進 known_limitations，不要建成 Constraint。")}])
    part_b = extract_json(reply_b)
    return {"terms": part_a["terms"], "mappings": part_a["mappings"], "relations": part_b["relations"],
            "constraints": part_b["constraints"], "known_limitations": part_b.get("known_limitations", []),
            "summary": part_b.get("summary", "")}


def b3_repair(llm: LLM, design: Dict[str, Any], evidence, errors: List[str]) -> Dict[str, Any]:
    system = _design_system()
    body = {k: design[k] for k in ("terms", "mappings", "relations", "constraints")}
    reply = llm.chat(stage="build.repair", system=system, messages=[{"role": "user", "content": (
        "你先前產生的語意物件沒有通過程式檢查。\n\n## 錯誤清單\n" + "\n".join("- " + e for e in errors[:60])
        + "\n\n## 可引用的 evidence id\n" + ", ".join(e["id"] for e in evidence)
        + "\n\n## 目前內容\n" + json.dumps(body, ensure_ascii=False)
        + "\n\n請修正所有錯誤並回覆完整的 JSON：{\"terms\":[...],\"mappings\":[...],\"relations\":[...],\"constraints\":[...]}（不要省略未改動的物件）")}])
    fixed = extract_json(reply)
    return dict(design, **{k: fixed[k] for k in ("terms", "mappings", "relations", "constraints")})


def b3_fill_mappings(llm: LLM, design: Dict[str, Any], evidence, missing, profile_text: str) -> Dict[str, Any]:
    """Targeted repair: ask only for the Mappings of Terms that no Mapping grounds (much smaller than a full rewrite)."""
    system = _design_system()
    terms = [t for t in design["terms"] if t["id"] in {m[0] for m in missing}]
    reply = llm.chat(stage="build.fill_mappings", system=system, messages=[{"role": "user", "content": (
        "以下 Term 已建立，但還沒有任何 Mapping 把它們對應到資料庫的表與欄位。請為每一個 Term 產生至少一個 Mapping。\n\n## 需要 Mapping 的 Terms\n"
        + json.dumps(terms, ensure_ascii=False) + "\n\n" + profile_text + "\n\n## 已驗證證據\n" + _evidence_listing(evidence)
        + "\n\n已存在的 Mapping id（不可重複）: " + ", ".join(m["id"] for m in design["mappings"])
        + "\n\n回覆 JSON：{\"mappings\": [...]}。Mapping 欄位：id,term_id,database_source(\"shop_v2\"),table,column,semantic_filter(可省略),"
        "aggregation_semantics(可省略),grain,validation。table／column 必須真實存在。")}])
    return dict(design, mappings=design["mappings"] + extract_json(reply)["mappings"])


def links_for(questions, records) -> List[Dict[str, Any]]:
    """Question → object links by name/alias matching (code; the skill says LLM only needs to review)."""
    links = []
    for q in questions:
        text = q["question"].lower()
        term_ids = {t["id"] for t in records["terms"]
                    if any(n and n.lower() in text for n in [t["name"].split(" ")[0], *t.get("aliases", [])])}
        ids = set(term_ids)
        ids |= {m["id"] for m in records["mappings"] if m["term_id"] in term_ids}
        ids |= {c["id"] for c in records["constraints"] if c["target"] in term_ids}
        ids |= {r["id"] for r in records["relations"] if r["source"] in term_ids or r["target"] in term_ids}
        if ids:
            links.append({"question_id": q["id"], "object_ids": sorted(ids)})
    return links


def run_build() -> Dict[str, Any]:
    questions = b0_configure()
    doc_text = open(config.DOC_PATH, encoding="utf-8").read()
    profile = _cached("profile.json", profile_db)
    profile_text = render_profile(profile)
    open(os.path.join(BUILD_DIR, "profile.md"), "w", encoding="utf-8").write(profile_text)

    builder = LLM("builder")
    explored = _cached("evidence.json", lambda: b2_explore(builder, questions, profile_text, doc_text))
    evidence = explored["verified"]
    design = _cached("design.json", lambda: b3_design(builder, questions, doc_text, profile_text, evidence))

    clean_evidence = [{k: v for k, v in e.items() if not k.startswith("_")} for e in evidence]
    fills = 0
    while True:                                    # targeted repair first: Terms nobody grounded
        missing = missing_mappings({f: design[f] for f in ("terms", "mappings")})
        if not missing or fills >= 2:
            break
        fills += 1
        design = b3_fill_mappings(builder, design, evidence, missing, profile_text)
        json.dump(design, open(os.path.join(BUILD_DIR, "design.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    repairs = 0
    while True:
        records = {fam: design[fam] for fam in ("terms", "mappings", "relations", "constraints")}
        records["evidence"] = clean_evidence
        errors = check_records(records)
        if not errors or repairs >= 2:
            break
        repairs += 1
        design = b3_repair(builder, design, evidence, errors)
        json.dump(design, open(os.path.join(BUILD_DIR, "design.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if errors:
        raise RuntimeError("design still invalid after %d repairs: %s" % (repairs, errors[:10]))

    op(config.WORKSPACE, "save_version", version="ontology_v0", records=records)
    validation = op(config.WORKSPACE, "validate_semantics", version="ontology_v0")
    links = links_for(questions, records)
    op(config.WORKSPACE, "annotate_ontology_version", version="ontology_v0", summary=design.get("summary", ""),
       limitations=design.get("known_limitations", []), links=links)
    published = op(config.WORKSPACE, "publish_ontology_build", version="ontology_v0")
    report = {"counts": {f: len(records[f]) for f in FAMILIES}, "repairs": repairs, "mapping_fills": fills, "validation": validation,
              "evidence_rejected": len(explored["rejected"]), "questions_linked": len(links), "questions_total": len(questions),
              "uncovered_questions": [q["id"] for q in questions if q["id"] not in {l["question_id"] for l in links}],
              "published": {k: v for k, v in published.items() if k != "presentation"}}
    json.dump(report, open(os.path.join(BUILD_DIR, "build_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return report
