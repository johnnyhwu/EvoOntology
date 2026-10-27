"""Read-only SQL tool for the shop database.

Usage:
  sql.py [--run ID] --schema          # print CREATE TABLE statements
  sql.py [--run ID] "SELECT ..."      # run one read-only query (max 200 rows)
"""
import json
import sqlite3
import sys

import _common as c

ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
           sqlite3.SQLITE_RECURSIVE}


def run_query(query):
    conn = sqlite3.connect("file:%s?mode=ro" % c.DB_PATH, uri=True)

    def authorize(action, a1, a2, db, trigger):
        if action == sqlite3.SQLITE_FUNCTION and str(a2).lower() == "load_extension":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in ALLOWED else sqlite3.SQLITE_DENY

    conn.set_authorizer(authorize)
    calls = [0]

    def progress():
        calls[0] += 1
        return int(calls[0] > 100000)  # ~100M VM steps; v2 tables are large and unindexed

    conn.set_progress_handler(progress, 1000)
    try:
        cur = conn.execute(query)
        rows = cur.fetchmany(201)
        return {"columns": [d[0] for d in cur.description or []],
                "rows": [list(r) for r in rows[:200]], "truncated": len(rows) > 200}
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    finally:
        conn.close()


def main():
    argv = sys.argv[1:]
    run_id = c.pop_run_id(argv)
    if argv == ["--schema"]:
        query = "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
        result = run_query(query)
        log_call_args = {"schema": True}
        if "rows" in result:
            print("\n\n".join(r[0] for r in result["rows"]))
        else:
            print(json.dumps(result, ensure_ascii=False))
    elif len(argv) == 1:
        result = run_query(argv[0])
        log_call_args = {"query": argv[0]}
        print(json.dumps(result, ensure_ascii=False, default=str))
    else:
        sys.exit("usage: sql.py [--run ID] (--schema | \"SELECT ...\")")
    c.log_call(run_id, "sql", log_call_args, result)


if __name__ == "__main__":
    main()
