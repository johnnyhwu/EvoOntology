"""Thin wrapper over the repo's deterministic core operations (``evoontology.runtime.ops``).

The Claude Code plugin exposes these 28 functions through an MCP server; a pipeline can call them directly.
Every state-changing step of the ontology lifecycle goes through here, so the on-disk workspace is exactly what the
official plugin would have produced.
"""
from __future__ import annotations

from typing import Any, Dict

from evoontology.runtime import ops

from . import config


def op(workspace: str, name: str, **arguments: Any) -> Dict[str, Any]:
    """``workspace`` is deliberately a required argument: a default would let a test or dry run write into the real workspace."""
    arguments["workspace"] = workspace
    if name in ("publish_ontology_build", "finalize_evolution_run", "visualize_ontology"):
        arguments.setdefault("open_browser", False)        # headless: never pop a browser
    return ops.execute(name, arguments)
