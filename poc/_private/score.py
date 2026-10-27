"""Score submitted answers (v2 held-out set) and summarise trajectories.

PRIVATE. Run: PYTHONDONTWRITEBYTECODE=1 poc/.venv/bin/python poc/_private/score.py [--per-question]
Run ids look like  <ARM>_<QID>_r<N>  e.g. B_H07_r1.
Arms: A = no ontology, B = ontology tools, C = business doc pasted in the prompt (no ontology).
"""
import collections
import itertools
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POC = os.path.join(HERE, "..")
GT = {}
for name in ("heldout_v2.json", "construction_gt_v2.json"):
    for q in json.load(open(os.path.join(HERE, name), encoding="utf-8")):
        GT[q["id"]] = q
GROUPS = ["near", "far_combo", "far_unseen"]


def parse_number(text):
    cleaned = str(text).replace(",", "").replace("，", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group()) if match else None


def tolerance(want):
    if abs(want) >= 1000:
        return max(1.0, abs(want) * 0.0005)   # money: 0.05% relative
    if float(want).is_integer():
        return 0.5                            # counts: exact
    return 0.06                               # rates / averages rounded to 1-2 decimals


def is_correct(q, answer):
    if q["kind"] == "number":
        got = parse_number(answer)
        return got is not None and abs(got - float(q["answer"])) <= tolerance(float(q["answer"]))
    text = str(answer).strip().lower()
    return any(str(a).strip().lower() in text for a in q["accept"])


def load_answers():
    path = os.path.join(POC, "eval", "answers.jsonl")
    latest = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            row = json.loads(line)
            latest[row["run"]] = row["answer"]  # last submission wins
    return latest


def trajectory(run_id):
    path = os.path.join(POC, "eval", "runs", run_id + ".jsonl")
    stats = collections.Counter()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            row = json.loads(line)
            tool, preview = row["tool"], row["result_preview"]
            stats[tool.split(".")[0]] += 1
            if tool == "sql" and preview.startswith('{"error"'):
                stats["sql_error"] += 1
            if tool == "ontology.browse" and '"items": []' in preview:
                stats["browse_empty"] += 1
            if tool == "ontology.resolve" and '"status": "unresolved"' in preview:
                stats["resolve_unresolved"] += 1
    return stats


def sign_test_p(b_only, a_only):
    n = b_only + a_only
    if n == 0:
        return 1.0
    k = min(b_only, a_only)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main():
    per_question = "--per-question" in sys.argv
    answers = load_answers()
    result = collections.defaultdict(dict)  # (arm, qid) -> {rep: (ok, answer)}
    traj = collections.defaultdict(collections.Counter)
    for run_id, answer in sorted(answers.items()):
        arm, qid, rep = run_id.split("_")
        if qid not in GT:
            continue
        result[(arm, qid)][rep] = (is_correct(GT[qid], answer), answer)
        traj[arm].update(trajectory(run_id))
    arms = sorted({a for a, _ in result})
    qids = sorted({q for _, q in result})

    def frac(arm, qid):  # share of repetitions correct
        reps = result.get((arm, qid), {})
        return sum(v[0] for v in reps.values()) / len(reps) if reps else None

    if per_question:
        for qid in qids:
            cells = ["%s=%s" % (arm, "%.2f" % frac(arm, qid) if frac(arm, qid) is not None else "-") for arm in arms]
            wrong = [(arm, v[1]) for arm in arms for v in result.get((arm, qid), {}).values() if not v[0]]
            print("%s [%s] gt=%s | %s | wrong: %s" % (qid, GT[qid].get("group", "build"), GT[qid]["answer"],
                                                      "  ".join(cells), wrong[:3]))
        print()
    print("== 各組正確率（以題目為單位，重複次數取平均）==")
    header = "%-6s" % "組別" + "".join("%-14s" % g for g in ["全部"] + GROUPS)
    print(header)
    for arm in arms:
        row = "%-6s" % arm
        for label in ["全部"] + GROUPS:
            qs = [q for q in qids if label == "全部" or GT[q].get("group") == label]
            vals = [frac(arm, q) for q in qs if frac(arm, q) is not None]
            row += "%-14s" % ("%.0f%% (n=%d)" % (100 * sum(vals) / len(vals), len(vals)) if vals else "-")
        print(row)
    print("\n== 配對比較（同一題的兩組結果；只算兩組都有跑的題；sign test 雙尾）==")
    for x, y in itertools.permutations(arms, 2):
        if x > y:
            continue
        common = [q for q in qids if frac(x, q) is not None and frac(y, q) is not None]
        x_only = sum(1 for q in common if frac(x, q) > frac(y, q))
        y_only = sum(1 for q in common if frac(y, q) > frac(x, q))
        print("%s vs %s: n=%d  只有%s對=%d  只有%s對=%d  p=%.3f" % (
            x, y, len(common), x, x_only, y, y_only, sign_test_p(x_only, y_only)))
    print("\n== 軌跡統計（各組工具呼叫總數）==")
    for arm in arms:
        print(arm, dict(traj[arm]))


if __name__ == "__main__":
    main()
