"""Native data tools handed to agents: read-only SQL on the target database and the business document."""
from __future__ import annotations

import sqlite3
from typing import Any, Dict

from . import config
from .agent import ToolSpec


def run_sql(query: str, db_path: str = config.DB_PATH, max_rows: int = config.SQL_MAX_ROWS,
            step_limit: int = config.SQL_STEP_LIMIT) -> Dict[str, Any]:
    """Execute one SELECT. Same safety model as the core's ``execute_query`` (read-only URI + authorizer),
    but with a much larger VM-step budget: the core's ~1M steps aborted legitimate aggregate queries in PoC 1."""
    connection = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

    def authorize(action, arg1, arg2, database_name, trigger):
        if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() == "load_extension":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

    calls = {"n": 0}

    def progress():
        calls["n"] += 1
        return int(calls["n"] > step_limit // 1000)

    connection.set_authorizer(authorize)
    connection.set_progress_handler(progress, 1000)
    try:
        cursor = connection.execute(query)
        rows = cursor.fetchmany(max_rows + 1)
        return {"columns": [c[0] for c in cursor.description or []],
                "rows": [list(r) for r in rows[:max_rows]], "truncated": len(rows) > max_rows}
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    finally:
        connection.close()


def schema_text(db_path: str = config.DB_PATH) -> str:
    connection = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        return "\n".join(r[0] for r in connection.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"))
    finally:
        connection.close()


def sql_tool() -> ToolSpec:
    def fn(args: Dict[str, Any]) -> Any:
        queries = args.get("queries")
        if queries is not None:
            if not isinstance(queries, list) or not 1 <= len(queries) <= 6:
                return {"error": "'queries' must be a list of 1-6 SELECT statements"}
            return [{"query": q, **run_sql(str(q))} for q in queries]
        if not str(args.get("query", "")).strip():
            return {"error": "provide 'query' (one SELECT) or 'queries' (list of up to 6)"}
        return run_sql(str(args["query"]))
    return ToolSpec("sql_query", "對公司 SQLite 資料庫執行唯讀 SELECT（每次最多回傳 %d 列，彙總請在 SQL 裡完成）" % config.SQL_MAX_ROWS,
                    '{"query": "<SELECT ...>"} 或 {"queries": ["<SELECT ...>", ...]}（最多 6 條）', fn)


def schema_tool() -> ToolSpec:
    return ToolSpec("get_schema", "取得所有資料表的 CREATE TABLE 定義（資料庫沒有宣告外鍵，也沒有欄位註解）", "{}",
                    lambda args: {"schema": schema_text()})


def doc_tool(doc_path: str = config.DOC_PATH) -> ToolSpec:
    return ToolSpec("read_doc", "讀取業務窗口提供的資料說明文件 domain_knowledge.md（資料環境中的文件）", "{}",
                    lambda args: {"document": open(doc_path, encoding="utf-8").read()})
