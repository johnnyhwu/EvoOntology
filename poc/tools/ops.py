"""Builder-side operations: call the same functions the plugin's MCP server exposes.

Usage:
  ops.py [--run ID] <operation_name> '<json arguments>'
  ops.py [--run ID] <operation_name> @path/to/arguments.json

`workspace` defaults to poc/workspace/.evoontology when omitted. This is the
exact registry the plugin's MCP server dispatches to (evoontology.runtime.ops).
"""
import json
import sys

import _common as c
from evoontology.runtime import ops


def main():
    argv = sys.argv[1:]
    run_id = c.pop_run_id(argv)
    if len(argv) != 2:
        sys.exit(__doc__)
    name, raw = argv
    if raw.startswith("@"):
        with open(raw[1:], "r", encoding="utf-8") as f:
            raw = f.read()
    arguments = json.loads(raw)
    arguments.setdefault("workspace", c.WORKSPACE)
    try:
        result = ops.execute(name, arguments)
    except Exception as exc:  # surface errors the same way the MCP server does
        result = {"status": "error", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, default=str))
    summary_args = {k: v for k, v in arguments.items() if k != "records"}
    c.log_call(run_id, "ops." + name, summary_args, result)


if __name__ == "__main__":
    main()
