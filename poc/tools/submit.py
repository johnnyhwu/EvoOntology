"""Submit the final answer of a test run.

Usage: submit.py --run ID "<answer>"
Appends one line to poc/eval/answers.jsonl. Call exactly once, as the last step.
"""
import json
import os
import sys
import time

import _common as c


def main():
    argv = sys.argv[1:]
    run_id = c.pop_run_id(argv)
    if not run_id or len(argv) != 1:
        sys.exit(__doc__)
    os.makedirs(os.path.join(c.POC, "eval"), exist_ok=True)
    entry = {"run": run_id, "answer": argv[0], "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(os.path.join(c.POC, "eval", "answers.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    c.log_call(run_id, "submit", {"answer": argv[0]}, {"status": "recorded"})
    print("recorded")


if __name__ == "__main__":
    main()
