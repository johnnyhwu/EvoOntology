"""Runtime access to an ontology version = the repo's ``SemanticLayer`` + a versioned *tool config*.

Why the extra file?  In EvoOntology the Tool Layer (manifest + browse/resolve behaviour) is evolvable, and the
repo's evolve skill lets an agent edit runtime code. A deterministic pipeline must not let an LLM rewrite Python,
so PoC 2 exposes the Tool Layer as a small set of *declarative knobs* stored next to the five record files:

    versions/<v>/tool_config.json
      resolve.trigger_keyword_constraints  bool  also return constraints whose trigger_keywords occur in the
                                                 mentions/context (the repo's resolve ignores trigger_keywords)
      resolve.fuzzy_fallback               bool  when a mention is unresolved, try substring/bigram matching
                                                 against names and aliases
      manifest.pinned_constraint_ids       [id]  constraints printed in the manifest (always visible)

``SemanticStore.publish`` copies the whole version directory, so the config is versioned with the ontology
without touching the core. This is a deliberate extension (documented in the report), not repo behaviour.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional

from evoontology.runtime.runtime import SemanticLayer, _is_active, _tokens
from evoontology.ontology.store import SemanticStore
from evoontology.workspace import resolve_workspace

TOOL_CONFIG_FILE = "tool_config.json"
DEFAULT_TOOL_CONFIG: Dict[str, Any] = {
    "resolve": {"trigger_keyword_constraints": False, "fuzzy_fallback": False},
    "manifest": {"pinned_constraint_ids": []},
}
ALLOWED_KEYS = {("resolve", "trigger_keyword_constraints"): bool, ("resolve", "fuzzy_fallback"): bool,
                ("manifest", "pinned_constraint_ids"): list}


def load_tool_config(workspace: str, version: str) -> Dict[str, Any]:
    path = os.path.join(resolve_workspace(workspace), "versions", version, TOOL_CONFIG_FILE)
    config = copy.deepcopy(DEFAULT_TOOL_CONFIG)
    if os.path.isfile(path):
        stored = json.load(open(path, encoding="utf-8"))
        for section, values in stored.items():
            config.setdefault(section, {}).update(values)
    return config


def save_tool_config(workspace: str, version: str, config: Dict[str, Any]) -> str:
    path = os.path.join(resolve_workspace(workspace), "versions", version, TOOL_CONFIG_FILE)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(config, stream, ensure_ascii=False, indent=2)
    return path


def validate_tool_config(config: Dict[str, Any], constraint_ids: set) -> List[str]:
    errors = []
    for section, values in config.items():
        for key, value in values.items():
            expected = ALLOWED_KEYS.get((section, key))
            if expected is None:
                errors.append("unknown tool_config key %s.%s (allowed: %s)" % (section, key, sorted("%s.%s" % k for k in ALLOWED_KEYS)))
            elif not isinstance(value, expected):
                errors.append("tool_config %s.%s must be %s" % (section, key, expected.__name__))
    for cid in config.get("manifest", {}).get("pinned_constraint_ids", []):
        if cid not in constraint_ids:
            errors.append("pinned constraint %r does not exist" % cid)
    return errors


class TunedSemanticLayer(SemanticLayer):
    def __init__(self, store: SemanticStore, tool_config: Dict[str, Any]):
        super().__init__(store)
        self.tool_config = tool_config

    @classmethod
    def load_tuned(cls, workspace: str, version: Optional[str] = None) -> "TunedSemanticLayer":
        base = SemanticLayer.load(str(workspace), version)
        return cls(base.store, load_tool_config(workspace, base.store.version))

    # ---- Tool Layer: manifest ------------------------------------------------------------------
    def manifest(self, exposed_tools=None) -> str:
        text = super().manifest(exposed_tools)
        pinned = [self.store.constraints[c] for c in self.tool_config["manifest"]["pinned_constraint_ids"]
                  if c in self.store.constraints]
        if pinned:
            text += "\n\n### Pinned rules (always apply)\n" + "\n".join(
                "- [%s] %s" % (c.severity, c.description) for c in pinned)
        return text

    # ---- Tool Layer: resolve -------------------------------------------------------------------
    def resolve(self, mentions=None, context=None) -> Dict[str, Any]:
        result = super().resolve(mentions, context)
        cfg = self.tool_config["resolve"]
        if cfg["fuzzy_fallback"]:
            for i, item in enumerate(result["results"]):
                if item.get("status") == "unresolved":
                    term = self._fuzzy_term(item["query"])
                    if term is not None:
                        fixed = self._build_resolve_result(item["query"], term, "fuzzy match: term '%s'" % term.name, "resolved")
                        fixed["coverage_status"] = "partial" if not (fixed.get("mappings") or fixed.get("constraints")) else "supported"
                        result["results"][i] = fixed
        if cfg["trigger_keyword_constraints"]:
            text = (" ".join(str(m) for m in (mentions or [])) + " " + str(context or "")).lower()
            seen = {c["id"] for r in result["results"] for c in r.get("constraints", [])}
            triggered = []
            for c in self.store.constraints.values():
                if _is_active(c) and c.id not in seen and any(k and k.lower() in text for k in c.trigger_keywords):
                    triggered.append({"id": c.id, "target": c.target, "severity": c.severity,
                                      "description": c.description, "matched_by": "trigger_keywords"})
            if triggered:
                result["triggered_constraints"] = triggered
        return result

    def _fuzzy_term(self, mention: str):
        mention = mention.lower().strip()
        grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)} or {s}
        best, best_score = None, 0.0
        for term in self.store.terms.values():
            if not _is_active(term):
                continue
            names = [term.name.lower(), *[a.lower() for a in term.aliases], *term.name.lower().split()]
            for name in names:
                if len(name) < 2:
                    continue
                if name in mention or mention in name:
                    score = min(len(name), len(mention)) / max(len(name), len(mention))   # how much of the longer string is covered
                else:
                    a, b = grams(mention), grams(name)
                    score = 2 * len(a & b) / (len(a) + len(b))
                if score > best_score:
                    best, best_score = term, score
        return best if best_score >= 0.6 else None
