"""
db_index_optimizer.py — Protocol Database Indexing Optimizer.

Points at a SQLite database (default: database.py's own argus_vault.db),
runs a set of representative queries through EXPLAIN QUERY PLAN plus
real wall-clock timing, and -- only when actually asked to apply, not
by default -- creates the indexes that would turn a detected full table
scan into an index search.

WHY THIS MATTERS FOR *THIS* DATABASE SPECIFICALLY: database.py's own
recall_fact() runs `WHERE fact_key LIKE ?` with a `%substring%` pattern
(a wildcard on BOTH ends). SQLite cannot use a normal B-tree index for a
leading-wildcard LIKE -- it has no choice but to scan every row, no
matter how many indexes exist on fact_key. A naive tool that only
checks "is this column indexed?" would suggest an index here anyway and
it would do nothing. This one checks the actual LIKE pattern and says
so instead -- the honest fix for that specific query is SQLite's FTS5
full-text search extension, or restructuring the lookup to a prefix
match, not a plain index. See _like_pattern_kind() below.

Defaults to REPORTING what it would do. Actually executing a CREATE
INDEX requires apply=True -- same "report first, act only when told"
posture as this project's other automation (scraping_vanguard.py,
self_dev.py): silently rewriting someone's database schema in the
background isn't that kind of decision.
"""

import re
import sqlite3
import time

DEFAULT_DB_PATH = "argus_vault.db"

# This project's own actual query shapes (see database.py) -- used as
# the default sample when the caller doesn't supply their own queries,
# so this is useful with zero configuration against argus_vault.db.
DEFAULT_SAMPLE_QUERIES = [
    ("SELECT fact_value FROM long_term_memories WHERE fact_key LIKE ?", ("%test%",)),
    ("SELECT fact_value FROM long_term_memories WHERE fact_key = ?", ("test",)),
    ("SELECT content FROM conversation_logs WHERE role = ? ORDER BY timestamp DESC LIMIT 20", ("user",)),
]


def _table_from_query(query: str):
    match = re.search(r"FROM\s+([A-Za-z_][A-Za-z0-9_]*)", query, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_where_columns(query: str):
    """Deliberately simple regex extraction of `column OP ?` comparisons
    from a WHERE clause -- good enough for the straightforward
    single-table lookups this project's own database.py issues (see
    module docstring). NOT a general SQL parser: no joins, no
    subqueries, no expressions on the left-hand side."""
    match = re.search(r"WHERE\s+(.*?)(?:ORDER BY|GROUP BY|LIMIT|$)", query, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    return re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|LIKE|>|<|>=|<=|IN)\s*\??", match.group(1))


def _like_pattern_kind(query: str, params) -> str:
    """Checks whether this query has a LIKE clause and, if so, whether
    its wildcard placement can actually use a standard index.
    Returns 'none' | 'prefix' (indexable) | 'infix_or_leading' (NOT
    indexable by a plain B-tree index)."""
    if "LIKE" not in query.upper():
        return "none"
    like_param = None
    if "?" in query and params:
        # Best-effort: assume the first %-containing param is the LIKE arg.
        for p in params:
            if isinstance(p, str) and "%" in p:
                like_param = p
                break
    else:
        literal_match = re.search(r"LIKE\s+'([^']*)'", query, re.IGNORECASE)
        if literal_match:
            like_param = literal_match.group(1)
    if like_param is None:
        return "infix_or_leading"  # can't tell from static text -- assume the worse case
    if like_param.startswith("%"):
        return "infix_or_leading"
    return "prefix"


def _existing_indexes(conn, table: str):
    indexes = []
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        idx_name = row[1]
        cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx_name})").fetchall()]
        indexes.append({"name": idx_name, "columns": cols})
    return indexes


def analyze_query(conn, query: str, params=(), timing_runs: int = 3) -> dict:
    plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {query}", params).fetchall()
    plan_text = " | ".join(str(row) for row in plan_rows)
    full_scan = any("SCAN" in str(row).upper() and "USING INDEX" not in str(row).upper()
                     for row in plan_rows)

    times = []
    for _ in range(timing_runs):
        t0 = time.perf_counter()
        conn.execute(query, params).fetchall()
        times.append(time.perf_counter() - t0)
    avg_time_ms = round((sum(times) / len(times)) * 1000, 4)

    table = _table_from_query(query)
    where_cols = _extract_where_columns(query)
    existing = _existing_indexes(conn, table) if table else []
    indexed_cols = {c for idx in existing for c in idx["columns"]}
    missing = [c for c in where_cols if c not in indexed_cols]
    like_kind = _like_pattern_kind(query, params)

    suggestion, note = None, None
    if full_scan and where_cols and table:
        if like_kind == "infix_or_leading":
            already_indexed = bool(set(where_cols) & indexed_cols)
            note = (f"'{where_cols[0]}' is scanned via a LIKE pattern with a wildcard at "
                     f"the start (or an undetermined position) -- SQLite can't use a "
                     f"normal index for that, no matter how many exist. ")
            if already_indexed:
                note += (f"'{where_cols[0]}' already has an index, which is exactly why "
                          f"adding another one wouldn't help: the wildcard position defeats "
                          f"it, not a missing index. ")
            note += ("If this needs to be fast at scale, look at SQLite's FTS5 full-text "
                      "search extension, or restrict the lookup to a prefix match "
                      "('term%') if your use case allows it.")
        elif missing:
            idx_name = f"idx_{table}_{'_'.join(missing)}"
            suggestion = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({', '.join(missing)})"

    return {
        "query": query, "table": table, "plan": plan_text,
        "full_table_scan": full_scan, "avg_time_ms": avg_time_ms,
        "where_columns": where_cols, "missing_index_columns": missing,
        "suggested_index_sql": suggestion, "note": note,
    }


def optimize_database(db_path: str = DEFAULT_DB_PATH, sample_queries=None,
                       apply: bool = False, slow_threshold_ms: float = 5.0) -> dict:
    """
    Returns {"analyses": [...], "applied": [sql, ...]}.
    apply=False (default): report only. apply=True: actually execute any
    suggested CREATE INDEX for queries that were BOTH a full scan AND
    slower than slow_threshold_ms -- fast-but-technically-unindexed
    queries on a small table aren't worth an index's write-side cost.
    """
    queries = sample_queries or DEFAULT_SAMPLE_QUERIES
    conn = sqlite3.connect(db_path)
    try:
        analyses = [analyze_query(conn, q, p) for q, p in queries]
        applied = []
        if apply:
            for a in analyses:
                if a["suggested_index_sql"] and a["full_table_scan"] and a["avg_time_ms"] >= slow_threshold_ms:
                    conn.execute(a["suggested_index_sql"])
                    applied.append(a["suggested_index_sql"])
            if applied:
                conn.commit()
        return {"analyses": analyses, "applied": applied}
    finally:
        conn.close()


def format_report(result: dict) -> str:
    lines = []
    for a in result["analyses"]:
        flag = "⚠ FULL SCAN" if a["full_table_scan"] else "OK (index search)"
        lines.append(f"[{flag}] {a['avg_time_ms']} ms avg -- {a['query']}")
        lines.append(f"    plan: {a['plan']}")
        if a["suggested_index_sql"]:
            lines.append(f"    suggest: {a['suggested_index_sql']}")
        if a["note"]:
            lines.append(f"    note: {a['note']}")
        lines.append("")
    if result["applied"]:
        lines.append("Applied:")
        lines.extend(f"  {sql}" for sql in result["applied"])
    else:
        lines.append("(apply=False -- nothing was actually created; this is a report.)")
    return "\n".join(lines)


if __name__ == "__main__":
    import os
    import tempfile

    demo_path = os.path.join(tempfile.gettempdir(), "argus_demo_vault.db")
    if os.path.exists(demo_path):
        os.remove(demo_path)

    conn = sqlite3.connect(demo_path)
    conn.execute("""CREATE TABLE long_term_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fact_key TEXT UNIQUE, fact_value TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE conversation_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    conn.executemany("INSERT INTO long_term_memories (fact_key, fact_value) VALUES (?, ?)",
                      [(f"key_{i}", f"value_{i}") for i in range(5000)])
    conn.executemany("INSERT INTO conversation_logs (role, content) VALUES (?, ?)",
                      [("user" if i % 2 == 0 else "assistant", f"message number {i}") for i in range(20000)])
    conn.commit()
    conn.close()

    print("=== BEFORE any indexes ===")
    result = optimize_database(demo_path, apply=False)
    print(format_report(result))

    print("\n=== Applying suggested indexes (apply=True) ===")
    result = optimize_database(demo_path, apply=True, slow_threshold_ms=0.0)
    print(format_report(result))

    print("\n=== AFTER: same queries again ===")
    result = optimize_database(demo_path, apply=False)
    print(format_report(result))

    os.remove(demo_path)
