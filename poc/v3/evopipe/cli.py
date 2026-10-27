"""Command line entry points:  python -m evopipe.cli <command>

    build                     B0-B4   create ontology_v0 in the workspace
    use [--version V]         run the 40 production tasks with the active version; record trajectories (feeds the trigger)
    evolve                    E0-E5   one evolution run
    test --version V --arm A  run the 16 fresh test questions (never seen by Build/Use/Evolve) for the final audit
    cost                      print the LLM cost ledger summary
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

from . import config
from .core import op
from .llm import ledger
from .runner import run_questions


def cmd_build(args):
    from .build import run_build
    print(json.dumps(run_build(), ensure_ascii=False, indent=1))


def cmd_use(args):
    from evoontology.ontology.store import SemanticStore
    from evoontology.trajectory.trajectory import TrajectoryStore
    version = args.version or SemanticStore.active_version(config.WORKSPACE)
    questions = json.load(open(config.STREAM_Q, encoding="utf-8"))
    runs = run_questions(questions, version=version, arm="ontology", out_dir=os.path.join(config.RUNS, "use", version), stage="use")
    store = TrajectoryStore(config.WORKSPACE)
    known = {t["task_id"] for t in store.list_since(None)}
    base = datetime.datetime(2026, 10, 27, 1, 0, 0, tzinfo=datetime.timezone.utc)
    added = 0
    for i, q in enumerate(questions):                       # stream order = arrival order
        trajectory = runs[q["id"]]
        if trajectory["task_id"] not in known:
            store.append(trajectory, recorded_at=(base + datetime.timedelta(minutes=3 * i)).isoformat())
            added += 1
    print("recorded %d trajectories (%d completed)" % (added, sum(r["task_status"] == "completed" for r in runs.values())))
    print(json.dumps(op(config.WORKSPACE, "evolution_status")["check"], ensure_ascii=False))


def cmd_evolve(args):
    from .evolve import EvolveRun
    report = EvolveRun(max_rounds=args.max_rounds).run()
    print(json.dumps(report, ensure_ascii=False, indent=1))


def cmd_test(args):
    questions = json.load(open(config.TEST_Q, encoding="utf-8"))
    runs = run_questions(questions, version=args.version, arm=args.arm,
                         out_dir=os.path.join(config.RUNS, "test", "%s_%s" % (args.arm, args.version)), stage="audit.test")
    print("ran %d test questions" % len(runs))


def cmd_cost(args):
    from collections import defaultdict
    totals = defaultdict(lambda: [0, 0, 0, 0.0])
    for line in open(os.path.join(config.RUNS, "ledger.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        key = r["stage"].split(".")[0] + "." + (r["stage"].split(".")[1] if "." in r["stage"] else "")
        t = totals[(key, r["model"])]
        t[0] += 1; t[1] += r["input_tokens"]; t[2] += r["output_tokens"]; t[3] += r["cost_usd"]
    for (stage, model), (n, i, o, c) in sorted(totals.items()):
        print("%-22s %-20s calls=%4d in=%8d out=%7d $%.4f" % (stage, model, n, i, o, c))
    print("TOTAL $%.4f (cap $%.2f)" % (ledger().total, config.BUDGET_USD))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="evopipe")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    p = sub.add_parser("use"); p.add_argument("--version"); p.set_defaults(fn=cmd_use)
    p = sub.add_parser("evolve"); p.add_argument("--max-rounds", type=int, default=config.MAX_ROUNDS); p.set_defaults(fn=cmd_evolve)
    p = sub.add_parser("test"); p.add_argument("--version", required=True); p.add_argument("--arm", choices=["ontology", "none"], default="ontology"); p.set_defaults(fn=cmd_test)
    sub.add_parser("cost").set_defaults(fn=cmd_cost)
    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
