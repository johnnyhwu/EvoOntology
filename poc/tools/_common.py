"""Shared helpers for PoC tools: repo-local paths and per-run call logging.

Every tool call can be logged to poc/eval/runs/<run_id>.jsonl so trajectories are
recorded by the tools themselves, not by the agent's self-report.
"""
import json
import os
import sys
import time

sys.dont_write_bytecode = True  # never write __pycache__ into the repo

POC = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPO = os.path.dirname(POC)
DB_PATH = os.path.join(POC, "data", "shop_v2.sqlite")
WORKSPACE = os.path.join(POC, "workspace", ".evoontology")
RUNS_DIR = os.path.join(POC, "eval", "runs")

if REPO not in sys.path:
    sys.path.insert(0, REPO)


def pop_run_id(argv):
    """Remove `--run ID` from argv and return ID (or '')."""
    if "--run" in argv:
        i = argv.index("--run")
        run_id = argv[i + 1]
        del argv[i:i + 2]
        return run_id
    return ""


def log_call(run_id, tool, arguments, result):
    if not run_id:
        return
    os.makedirs(RUNS_DIR, exist_ok=True)
    text = json.dumps(result, ensure_ascii=False, default=str)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, "arguments": arguments,
             "result_preview": text[:1500], "result_chars": len(text)}
    with open(os.path.join(RUNS_DIR, run_id + ".jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
