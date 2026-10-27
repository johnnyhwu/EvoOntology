"""Ontology interaction tool: a thin CLI over evoontology.runtime.SemanticLayer.

Usage:
  ontology.py [--run ID] manifest
  ontology.py [--run ID] browse "<query>" [--kind term|mapping|relation|constraint|all] [--limit N]
  ontology.py [--run ID] resolve "<mention>" ["<mention>" ...] [--context "<text>"]

Always serves the pinned version below; no write operation is exposed here.
"""
import json
import sys

import _common as c
from evoontology.runtime.runtime import SemanticLayer

VERSION = "ontology_v0"


def main():
    argv = sys.argv[1:]
    run_id = c.pop_run_id(argv)
    if not argv:
        sys.exit(__doc__)
    layer = SemanticLayer.load(c.WORKSPACE, version=VERSION)
    cmd, rest = argv[0], argv[1:]
    if cmd == "manifest":
        arguments, result = {}, layer.manifest()
        print(result)
    elif cmd == "browse":
        arguments = {"query": rest[0] if rest else ""}
        for flag in ("--kind", "--limit"):
            if flag in rest:
                value = rest[rest.index(flag) + 1]
                arguments[flag[2:]] = int(value) if flag == "--limit" else value
        result = layer.execute("browse_semantics", arguments)
        print(json.dumps(result, ensure_ascii=False))
    elif cmd == "resolve":
        context = ""
        if "--context" in rest:
            i = rest.index("--context")
            context = rest[i + 1]
            del rest[i:i + 2]
        arguments = {"mentions": rest, "context": context}
        result = layer.execute("resolve_semantics", arguments)
        print(json.dumps(result, ensure_ascii=False))
    else:
        sys.exit(__doc__)
    c.log_call(run_id, "ontology." + cmd, arguments, result)


if __name__ == "__main__":
    main()
