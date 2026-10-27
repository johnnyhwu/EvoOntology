"""Deterministic handling of ontology records: integrity checks, evidence materialisation, patch operations.

Everything an LLM proposes passes through here before it can touch a version directory:

* ``check_records``      — schema rules from ontology-schema.md that code can verify
                           (controlled vocabularies, id references, real tables/columns, no SQL templates ...)
* ``materialize_evidence`` — the LLM supplies *which* query / document quote supports a claim; CODE runs the query
                           (or verifies the quote is in the document) and writes the observed result itself,
                           so Evidence can never contain a hallucinated result.
* ``apply_patch``        — Evolve patches are lists of typed operations applied to a copy of the Parent's records.
"""
from __future__ import annotations

import copy
import json
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .semantic import ALLOWED_KEYS, DEFAULT_TOOL_CONFIG
from .tools_data import run_sql

FAMILIES = ("terms", "mappings", "relations", "constraints", "evidence")
TERM_TYPES = {"concept", "metric", "entity", "dimension", "category"}
RELATION_TYPES = {"association", "hierarchy", "composition", "equivalence", "derivation"}
CONSTRAINT_TYPES = {"enum_semantics", "data_quality", "business_rule", "unit", "scope"}
SEVERITIES = {"block", "warning", "info"}
CONFIDENCES = {"high", "medium", "low"}
SQL_TEMPLATE = re.compile(r"\bselect\b.{0,200}\bfrom\b|\bwhere\b.{0,80}(=|>|<)", re.I | re.S)
ALLOWED_FIELDS = {   # "Semantic objects MUST contain only the fields defined in ontology-schema.md" (build SKILL.md)
    "terms": {"id", "name", "type", "definition", "scope", "aliases", "evidence"},
    "mappings": {"id", "term_id", "database_source", "table", "column", "semantic_filter", "aggregation_semantics", "grain", "validation"},
    "relations": {"id", "source", "relation_type", "target", "connection_condition", "description", "evidence"},
    "constraints": {"id", "target", "constraint_type", "trigger_keywords", "severity", "scope", "confidence", "description", "evidence"},
    "evidence": {"id", "source", "query", "result", "validation_method", "timestamp"},
}
NEEDS_MAPPING = {"entity", "dimension", "metric"}      # these Term types must be grounded in a table/column
TEXT_FIELDS = ("definition", "scope", "description", "semantic_filter", "aggregation_semantics", "connection_condition", "grain")
DOC_NORMALISE = re.compile(r"\s+")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def db_columns(db_path: str = config.DB_PATH) -> Dict[str, set]:
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        return {t: {c[1] for c in conn.execute('PRAGMA table_info("%s")' % t)}
                for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


# ----------------------------------------------------------------------------- integrity
def missing_mappings(records: Dict[str, List[Dict[str, Any]]]) -> List[Tuple[str, str]]:
    """(term_id, type) of entity/dimension/metric Terms that no Mapping grounds."""
    grounded = {m.get("term_id") for m in records["mappings"] if isinstance(m, dict)}
    return [(t["id"], t.get("type")) for t in records["terms"]
            if isinstance(t, dict) and t.get("type") in NEEDS_MAPPING and t.get("id") not in grounded]


def unreachable_constraints(records: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    """Constraints whose target is a Mapping.  The schema allows that, but the repo's ``resolve_semantics`` only returns constraints whose
    target IS the resolved Term, so these are invisible to the Data Agent (audit finding: 15 of v0's 28 constraints, incl. the timezone rule).
    A lint (warning), not part of check_records, because the schema itself permits it."""
    mapping_ids = {m["id"] for m in records["mappings"]}
    return [c["id"] for c in records["constraints"] if c.get("target") in mapping_ids]


def check_records(records: Dict[str, List[Dict[str, Any]]], db_path: str = config.DB_PATH) -> List[str]:
    errors: List[str] = []
    for fam in FAMILIES:
        if not isinstance(records.get(fam), list):
            return ["records[%r] must be a list" % fam]
    ids: Dict[str, str] = {}
    for fam in FAMILIES:
        for r in records[fam]:
            if not isinstance(r, dict) or not r.get("id"):
                errors.append("%s: record without id: %r" % (fam, str(r)[:80]))
                continue
            if r["id"] in ids:
                errors.append("duplicate id %r (in %s and %s)" % (r["id"], ids[r["id"]], fam))
            ids[r["id"]] = fam
    term_ids = {r["id"] for r in records["terms"] if isinstance(r, dict) and "id" in r}
    mapping_ids = {r["id"] for r in records["mappings"] if isinstance(r, dict) and "id" in r}
    evidence_ids = {r["id"] for r in records["evidence"] if isinstance(r, dict) and "id" in r}
    cols = db_columns(db_path)
    for fam in FAMILIES:
        for r in records[fam]:
            extra = set(r) - ALLOWED_FIELDS[fam] if isinstance(r, dict) else set()
            if extra:
                errors.append("%s %s: fields not defined by the schema: %s" % (fam, r.get("id"), sorted(extra)))
    errors += ["term %s (type %s) has no Mapping; every entity/dimension/metric must be grounded in a table column" % (t, ty)
               for t, ty in missing_mappings(records)]

    def refs(r, where):
        value = r.get("evidence", [])
        if not isinstance(value, list):
            errors.append("%s: 'evidence' must be a list of evidence ids" % where)
            return
        for e in value:
            if e not in evidence_ids:
                errors.append("%s: unknown evidence id %r" % (where, e))

    for r in records["terms"]:
        w = "term %s" % r.get("id")
        if r.get("type") not in TERM_TYPES:
            errors.append("%s: type must be one of %s" % (w, sorted(TERM_TYPES)))
        for f in ("name", "definition"):
            if not str(r.get(f, "")).strip():
                errors.append("%s: missing %s" % (w, f))
        if not isinstance(r.get("aliases", []), list):
            errors.append("%s: aliases must be a list" % w)
        if not r.get("evidence"):
            errors.append("%s: every Term needs at least one evidence id (grounding)" % w)
        refs(r, w)
    for r in records["mappings"]:
        w = "mapping %s" % r.get("id")
        if r.get("term_id") not in term_ids:
            errors.append("%s: term_id %r is not a Term" % (w, r.get("term_id")))
        t, c = r.get("table"), r.get("column")
        if t not in cols:
            errors.append("%s: table %r does not exist in the database" % (w, t))
        elif c not in cols[t]:
            errors.append("%s: column %r does not exist in table %r" % (w, c, t))
        if not str(r.get("database_source", "")).strip():
            errors.append("%s: missing database_source" % w)
    for r in records["relations"]:
        w = "relation %s" % r.get("id")
        if r.get("relation_type") not in RELATION_TYPES:
            errors.append("%s: relation_type must be one of %s" % (w, sorted(RELATION_TYPES)))
        for f in ("source", "target"):
            if r.get(f) not in term_ids:
                errors.append("%s: %s %r is not a Term" % (w, f, r.get(f)))
        refs(r, w)
    for r in records["constraints"]:
        w = "constraint %s" % r.get("id")
        if r.get("target") not in term_ids | mapping_ids:
            errors.append("%s: target %r is not a Term or Mapping" % (w, r.get("target")))
        if not (isinstance(r.get("trigger_keywords"), list) and r["trigger_keywords"]):
            errors.append("%s: trigger_keywords must be a non-empty list" % w)
        if r.get("severity") not in SEVERITIES:
            errors.append("%s: severity must be one of %s" % (w, sorted(SEVERITIES)))
        if r.get("confidence") not in CONFIDENCES:
            errors.append("%s: confidence must be one of %s" % (w, sorted(CONFIDENCES)))
        if r.get("constraint_type") not in CONSTRAINT_TYPES:
            errors.append("%s: constraint_type must be one of %s" % (w, sorted(CONSTRAINT_TYPES)))
        if not str(r.get("description", "")).strip():
            errors.append("%s: missing description" % w)
        refs(r, w)
    for r in records["evidence"]:
        w = "evidence %s" % r.get("id")
        for f in ("source", "query", "result", "validation_method", "timestamp"):
            if not str(r.get(f, "")).strip():
                errors.append("%s: missing %s" % (w, f))
    for fam in FAMILIES:
        for r in records[fam]:
            for f in TEXT_FIELDS:
                if isinstance(r.get(f), str) and SQL_TEMPLATE.search(r[f]):
                    errors.append("%s %s.%s looks like a SQL template (forbidden by the schema: describe meaning, not queries)"
                                  % (fam, r.get("id"), f))
    return errors


# ----------------------------------------------------------------------------- evidence
def materialize_evidence(item: Dict[str, Any], doc_text: str, db_path: str = config.DB_PATH) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Turn an LLM evidence *proposal* into a real Evidence record, or return an error string.

    SQL evidence: the query is executed here and the observed rows become ``result``.
    Document evidence: ``doc_quote`` must be a verbatim excerpt of the business document.
    """
    eid = str(item.get("id", "")).strip()
    method = str(item.get("validation_method", "")).strip()
    note = str(item.get("interpretation", item.get("claim", ""))).strip()
    if not eid or not method:
        return None, "evidence proposal needs 'id' and 'validation_method'"
    if item.get("query"):
        out = run_sql(str(item["query"]), db_path=db_path, max_rows=20)
        if "error" in out:
            return None, "evidence %s: query failed: %s" % (eid, out["error"])
        if not out["rows"]:
            return None, "evidence %s: query returned no rows" % eid
        observed = json.dumps({"columns": out["columns"], "rows": out["rows"]}, ensure_ascii=False)
        if len(observed) > 900:
            observed = observed[:900] + "…"
        return {"id": eid, "source": "shop_v2", "query": str(item["query"]).strip(),
                "result": observed + (" | 解讀: " + note if note else ""),
                "validation_method": method, "timestamp": now_iso()}, None
    quote = str(item.get("doc_quote", "")).strip()
    if quote:
        if DOC_NORMALISE.sub("", quote) not in DOC_NORMALISE.sub("", doc_text):
            return None, "evidence %s: doc_quote is not a verbatim excerpt of the business document" % eid
        return {"id": eid, "source": "domain_knowledge.md", "query": "(document excerpt)",
                "result": quote + (" | 解讀: " + note if note else ""),
                "validation_method": method, "timestamp": now_iso()}, None
    return None, "evidence %s: provide either 'query' (SQL) or 'doc_quote'" % eid


# ----------------------------------------------------------------------------- patch operations
PATCH_OPS = {
    "add_alias": "{op, term_id, alias}  — add an alternative name to an existing Term",
    "add_term": "{op, term:{id,name,type,definition,scope,aliases,evidence:[ids]}}",
    "add_mapping": "{op, mapping:{id,term_id,database_source,table,column,grain,semantic_filter?,aggregation_semantics?,validation?}}",
    "add_relation": "{op, relation:{id,source,relation_type,target,connection_condition?,description,evidence:[ids]}}",
    "add_constraint": "{op, constraint:{id,target,constraint_type,trigger_keywords:[...],severity,scope,confidence,description,evidence:[ids]}}",
    "update_field": "{op, family, id, field, value}  — family in terms|mappings|relations|constraints; field in definition|scope|description|grain|semantic_filter|aggregation_semantics|connection_condition|trigger_keywords|aliases|severity|confidence",
    "add_evidence": "{op, evidence:{id, query | doc_quote, validation_method, interpretation}}  — code runs the query / checks the quote",
    "set_tool_config": "{op, section, key, value}  — Tool Layer knobs: resolve.trigger_keyword_constraints (bool), resolve.fuzzy_fallback (bool), manifest.pinned_constraint_ids (list of constraint ids)",
}
UPDATABLE = {"definition", "scope", "description", "grain", "semantic_filter", "aggregation_semantics", "connection_condition",
             "trigger_keywords", "aliases", "severity", "confidence"}


def apply_patch(parent: Dict[str, List[Dict[str, Any]]], parent_tool_config: Dict[str, Any], operations: List[Dict[str, Any]],
                doc_text: str, db_path: str = config.DB_PATH):
    """Apply operations to a deep copy of the Parent. Returns (records, tool_config, touched_ids, errors).

    ``touched_ids`` are the object ids created/changed — used afterwards to check whether the patch was *activated*
    (did the changed objects actually show up in agent runs).
    """
    records = copy.deepcopy(parent)
    tool_config = copy.deepcopy(parent_tool_config)
    touched: List[str] = []
    errors: List[str] = []
    for i, op in enumerate(operations):
        name = op.get("op") if isinstance(op, dict) else None
        where = "op[%d] %s" % (i, name)
        try:
            if name == "add_alias":
                term = next((t for t in records["terms"] if t["id"] == op["term_id"]), None)
                if term is None:
                    errors.append("%s: unknown term %r" % (where, op.get("term_id")))
                elif op["alias"] not in term.setdefault("aliases", []):
                    term["aliases"].append(op["alias"])
                    touched.append(term["id"])
            elif name in ("add_term", "add_mapping", "add_relation", "add_constraint"):
                key = name[4:]
                fam = key + "s"
                obj = copy.deepcopy(op[key])
                records[fam].append(obj)
                touched.append(obj["id"])
            elif name == "update_field":
                if op["family"] not in ("terms", "mappings", "relations", "constraints") or op["field"] not in UPDATABLE:
                    errors.append("%s: family/field not updatable" % where)
                    continue
                obj = next((r for r in records[op["family"]] if r["id"] == op["id"]), None)
                if obj is None:
                    errors.append("%s: unknown %s id %r" % (where, op["family"], op["id"]))
                else:
                    obj[op["field"]] = op["value"]
                    touched.append(obj["id"])
            elif name == "add_evidence":
                record, err = materialize_evidence(op["evidence"], doc_text, db_path)
                if err:
                    errors.append("%s: %s" % (where, err))
                else:
                    records["evidence"].append(record)
            elif name == "set_tool_config":
                if (op["section"], op["key"]) not in ALLOWED_KEYS:
                    errors.append("%s: unknown knob %s.%s" % (where, op.get("section"), op.get("key")))
                else:
                    tool_config.setdefault(op["section"], {})[op["key"]] = op["value"]
                    touched.append("tool_config:%s.%s" % (op["section"], op["key"]))
            else:
                errors.append("%s: unknown operation (allowed: %s)" % (where, sorted(PATCH_OPS)))
        except (KeyError, TypeError) as exc:
            errors.append("%s: malformed (%s: %s)" % (where, type(exc).__name__, exc))
    return records, tool_config, touched, errors


def diff_records(old: Dict[str, List[Dict[str, Any]]], new: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Human-readable difference between two versions (for the report and the run record)."""
    out: Dict[str, Any] = {"added": {}, "changed": {}}
    for fam in FAMILIES:
        before = {r["id"]: r for r in old[fam]}
        after = {r["id"]: r for r in new[fam]}
        added = sorted(set(after) - set(before))
        changed = sorted(i for i in before if i in after and before[i] != after[i])
        if added:
            out["added"][fam] = added
        if changed:
            out["changed"][fam] = {i: {k: {"from": before[i].get(k), "to": after[i].get(k)}
                                       for k in set(before[i]) | set(after[i]) if before[i].get(k) != after[i].get(k)} for i in changed}
    return out
