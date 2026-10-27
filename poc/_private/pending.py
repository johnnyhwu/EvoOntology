"""List runs (arm x held-out question, rep 1) that have no submitted answer yet.
Usage: pending.py [N]   -> prints up to N missing run ids with question text.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
qs = json.load(open(os.path.join(HERE, "heldout_v2.json"), encoding="utf-8"))
done = set()
p = os.path.join(HERE, "..", "eval", "answers.jsonl")
if os.path.exists(p):
    done = {json.loads(l)["run"] for l in open(p, encoding="utf-8")}
missing = [("%s_%s_r1" % (a, q["id"]), q["question"]) for q in qs for a in "ABC" if "%s_%s_r1" % (a, q["id"]) not in done]
n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
print("submitted:", len(done), " missing:", len(missing))
for rid, text in missing[:n]:
    print(rid, "|", text)
