"""Build step B1 — data profiling. 100% deterministic Python, no LLM.

In PoC 1 the Builder agent hand-wrote ~60 SQL statements for this. PoC-1's Builder itself reported that
schema/distinct values/row counts/orphans/uniqueness/time ranges/timezone impact are fixed-code work.
The output is both machine-readable (profile.json) and rendered as compact text for the Builder prompt.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List

from . import config

TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}")


def _q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def profile_db(db_path: str = config.DB_PATH, enum_limit: int = 12) -> Dict[str, Any]:
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    tables: Dict[str, Any] = {}
    for (name,) in _q(conn, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        cols = _q(conn, 'PRAGMA table_info("%s")' % name)
        info: Dict[str, Any] = {"rows": _q(conn, 'SELECT COUNT(*) FROM "%s"' % name)[0][0], "columns": {}}
        for _, col, ctype, notnull, _, pk in cols:
            n_distinct, n_null = _q(conn, 'SELECT COUNT(DISTINCT "%s"), SUM("%s" IS NULL) FROM "%s"' % (col, col, name))[0]
            sample = [r[0] for r in _q(conn, 'SELECT "%s" FROM "%s" WHERE "%s" IS NOT NULL LIMIT 3' % (col, name, col))]
            entry: Dict[str, Any] = {"type": ctype, "pk": bool(pk), "distinct": n_distinct, "nulls": n_null or 0, "sample": sample,
                                     "unique": n_distinct == info["rows"] - (n_null or 0)}
            if 0 < n_distinct <= enum_limit:
                entry["values"] = [[v, c] for v, c in _q(conn, 'SELECT "%s", COUNT(*) FROM "%s" GROUP BY 1 ORDER BY 2 DESC' % (col, name))]
            elif sample and isinstance(sample[0], str):
                lo, hi = _q(conn, 'SELECT MIN("%s"), MAX("%s") FROM "%s"' % (col, col, name))[0]
                entry["min"], entry["max"] = lo, hi
                if TIME_RE.match(str(sample[0])):
                    entry["time_column"] = True
                    # how many rows would change calendar month if the stored value were UTC and reported in UTC+8
                    shifted = _q(conn, 'SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL AND substr("%s",1,7) != substr(datetime("%s","+8 hours"),1,7)'
                                 % (name, col, col, col))[0][0]
                    entry["month_shift_if_utc_plus8"] = shifted
            elif sample and isinstance(sample[0], (int, float)):
                lo, hi = _q(conn, 'SELECT MIN("%s"), MAX("%s") FROM "%s"' % (col, col, name))[0]
                entry["min"], entry["max"] = lo, hi
            info["columns"][col] = entry
        tables[name] = info
    # candidate joins: <x>_id columns that match a unique column named identically in another table
    joins: List[Dict[str, Any]] = []
    for t, info in tables.items():
        for col, entry in info["columns"].items():
            if not col.endswith("_id"):
                continue
            for other, oinfo in tables.items():
                target = oinfo["columns"].get(col)
                if other != t and target and target["unique"]:
                    orphans = _q(conn, 'SELECT COUNT(*) FROM "%s" a WHERE a."%s" IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "%s" b WHERE b."%s"=a."%s")'
                                 % (t, col, other, col, col))[0][0]
                    joins.append({"from": "%s.%s" % (t, col), "to": "%s.%s" % (other, col), "orphans": orphans,
                                  "from_rows": info["rows"]})
    conn.close()
    return {"database": "shop_v2", "tables": tables, "candidate_joins": joins}


def render_profile(profile: Dict[str, Any]) -> str:
    lines = ["# 資料剖析（程式自動產生，非 LLM）", ""]
    for t, info in profile["tables"].items():
        lines.append("## %s（%d 列）" % (t, info["rows"]))
        for col, e in info["columns"].items():
            bits = ["%s" % e["type"], "distinct=%d" % e["distinct"]]
            if e["nulls"]:
                bits.append("null=%d" % e["nulls"])
            if e["unique"]:
                bits.append("唯一")
            if "values" in e:
                bits.append("值: " + ", ".join("%s(%d)" % (v, c) for v, c in e["values"]))
            elif "min" in e:
                bits.append("範圍 %s ~ %s" % (e["min"], e["max"]))
            else:
                bits.append("例: %s" % ", ".join(map(str, e["sample"])))
            if "month_shift_if_utc_plus8" in e:
                bits.append("若為 UTC 並換算 UTC+8，有 %d 列會換月" % e["month_shift_if_utc_plus8"])
            lines.append("- `%s`: %s" % (col, "；".join(bits)))
        lines.append("")
    lines.append("## 可能的關聯（欄位同名且對方唯一；資料庫沒有宣告外鍵）")
    for j in profile["candidate_joins"]:
        lines.append("- %s → %s（孤兒 %d / %d）" % (j["from"], j["to"], j["orphans"], j["from_rows"]))
    return "\n".join(lines)


if __name__ == "__main__":
    p = profile_db()
    print(render_profile(p))
