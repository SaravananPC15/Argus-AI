"""
sql_to_nosql.py — Protocol Relational-to-NoSQL Transpiler.

Parses standard `CREATE TABLE` DDL (one or several statements -- it
follows FOREIGN KEY relationships between them) and maps it to a
MongoDB/BSON-style document schema plus a concrete example document.

SCOPE, ON PURPOSE: this is a hand-rolled parser for CREATE TABLE
statements specifically (column defs, inline REFERENCES, and separate
PRIMARY KEY/FOREIGN KEY constraint clauses) -- not a general SQL
parser, and it doesn't try to be one. That's why there's no new
dependency added to requirements.txt for this: a general SQL grammar
is a much bigger scope than "map a schema to a document shape," and a
focused hand-rolled parser covers that actual job without pulling in
a full SQL toolchain for it.

THE GENUINELY IMPORTANT PART ISN'T THE PARSING, IT'S THE EMBED-VS-
REFERENCE DECISION: turning a foreign key into a NoSQL document
structure isn't mechanical -- you either embed the related rows as a
sub-document/array (denormalized, fast to read, but the child can't
easily be queried/updated on its own and can make the parent document
grow without bound) or keep a reference field and do a second lookup
(normalized, closer to the relational original, avoids unbounded
growth). This defaults every relationship to reference-based -- the
safer default for a migration -- and separately flags which
relationships LOOK like good embedding candidates (a child table
referenced by exactly one parent, "one-to-few" in practice) rather
than silently picking one strategy for you.
"""

import re


_TYPE_MAP = {
    "INT": "int32", "INTEGER": "int32", "SMALLINT": "int32", "TINYINT": "int32",
    "BIGINT": "int64", "SERIAL": "int64", "AUTOINCREMENT": "int64",
    "VARCHAR": "string", "CHAR": "string", "TEXT": "string", "NVARCHAR": "string",
    "FLOAT": "double", "REAL": "double", "DOUBLE": "double",
    "DECIMAL": "decimal128", "NUMERIC": "decimal128",
    "BOOLEAN": "bool", "BOOL": "bool",
    "DATE": "date", "DATETIME": "date", "TIMESTAMP": "date",
    "BLOB": "binData", "JSON": "object", "JSONB": "object",
}


def _split_top_level_commas(s: str):
    """Splits on commas, but only at paren-depth 0 -- so `DECIMAL(10,2)`
    or `FOREIGN KEY (a, b) REFERENCES x(y, z)` don't get sliced apart."""
    parts, depth, current = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _map_type(sql_type: str) -> str:
    base = re.match(r"[A-Za-z]+", sql_type)
    key = base.group(0).upper() if base else sql_type.upper()
    return _TYPE_MAP.get(key, "string")


def _example_value(nosql_type: str):
    return {
        "int32": 0, "int64": 0, "double": 0.0, "decimal128": "0.00",
        "bool": False, "date": "2026-07-23T00:00:00Z",
        "binData": "<binary>", "object": {},
    }.get(nosql_type, "example")


def parse_create_tables(sql: str) -> dict:
    """
    Returns {table_name: {"columns": [...], "primary_key": [...],
    "foreign_keys": [{"column","ref_table","ref_column"}]}} for every
    CREATE TABLE statement found in `sql`.
    """
    tables = {}
    for match in re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?(\w+)[\"'`]?\s*\((.*?)\)\s*;",
        sql, re.IGNORECASE | re.DOTALL,
    ):
        table_name, body = match.group(1), match.group(2)
        columns, primary_key, foreign_keys = [], [], []

        for segment in _split_top_level_commas(body):
            seg_upper = segment.upper().strip()

            fk_match = re.match(
                r"FOREIGN\s+KEY\s*\(\s*(\w+)\s*\)\s*REFERENCES\s+[\"'`]?(\w+)[\"'`]?\s*\(\s*(\w+)\s*\)",
                segment, re.IGNORECASE)
            if fk_match:
                foreign_keys.append({"column": fk_match.group(1),
                                      "ref_table": fk_match.group(2),
                                      "ref_column": fk_match.group(3)})
                continue

            pk_match = re.match(r"PRIMARY\s+KEY\s*\(([^)]+)\)", segment, re.IGNORECASE)
            if pk_match:
                primary_key.extend(c.strip() for c in pk_match.group(1).split(","))
                continue

            if seg_upper.startswith(("UNIQUE", "CHECK", "CONSTRAINT")):
                continue  # table-level constraints not relevant to the document shape

            col_match = re.match(r"[\"'`]?(\w+)[\"'`]?\s+([A-Za-z]+(?:\([^)]*\))?)", segment)
            if not col_match:
                continue
            col_name, col_type = col_match.group(1), col_match.group(2)

            is_pk = bool(re.search(r"PRIMARY\s+KEY", segment, re.IGNORECASE))
            is_unique = bool(re.search(r"\bUNIQUE\b", segment, re.IGNORECASE))
            not_null = bool(re.search(r"NOT\s+NULL", segment, re.IGNORECASE)) or is_pk
            inline_ref = re.search(
                r"REFERENCES\s+[\"'`]?(\w+)[\"'`]?\s*\(\s*(\w+)\s*\)", segment, re.IGNORECASE)

            if is_pk:
                primary_key.append(col_name)
            if inline_ref:
                foreign_keys.append({"column": col_name, "ref_table": inline_ref.group(1),
                                      "ref_column": inline_ref.group(2)})

            columns.append({"name": col_name, "sql_type": col_type,
                             "nosql_type": _map_type(col_type),
                             "not_null": not_null, "unique": is_unique})

        tables[table_name] = {"columns": columns, "primary_key": primary_key,
                               "foreign_keys": foreign_keys}
    return tables


def _referenced_by_count(tables: dict, table_name: str) -> int:
    """How many OTHER tables have a foreign key pointing at table_name --
    used for the embedding-candidate heuristic below."""
    count = 0
    for name, t in tables.items():
        if name == table_name:
            continue
        if any(fk["ref_table"] == table_name for fk in t["foreign_keys"]):
            count += 1
    return count


def to_document_schema(tables: dict) -> dict:
    """
    Returns {table_name: {"document_schema": {...}, "example": {...},
    "embedding_candidate": bool, "embedding_note": str or None}}.
    Every foreign key becomes a plain reference field by default
    (e.g. customer_id stays customer_id, just noted as a reference
    rather than an enforced constraint -- NoSQL doesn't enforce FKs).
    """
    result = {}
    for table_name, table in tables.items():
        fk_columns = {fk["column"]: fk for fk in table["foreign_keys"]}
        properties, example = {}, {}
        for col in table["columns"]:
            properties[col["name"]] = {
                "bsonType": col["nosql_type"],
                "required": col["not_null"],
            }
            if col["name"] in fk_columns:
                fk = fk_columns[col["name"]]
                properties[col["name"]]["reference"] = f"{fk['ref_table']}.{fk['ref_column']}"
            example[col["name"]] = _example_value(col["nosql_type"])

        referenced_by = _referenced_by_count(tables, table_name)
        # A table that's the "one" side of exactly one relationship (only
        # ever referenced by rows of a single other table) is the classic
        # one-to-few embedding candidate -- e.g. order_items inside orders.
        is_candidate = referenced_by == 0 and len(table["foreign_keys"]) == 1
        embedding_note = None
        if is_candidate:
            parent = table["foreign_keys"][0]["ref_table"]
            embedding_note = (f"'{table_name}' only ever relates to '{parent}' -- a common "
                               f"NoSQL alternative here is embedding '{table_name}' rows as "
                               f"an array field on the '{parent}' document instead of a "
                               f"separate collection, IF '{table_name}' rows are small in "
                               f"number per '{parent}' and always read together with it. "
                               f"Keep it as a reference (the default below) if '{table_name}' "
                               f"rows are numerous, queried on their own, or updated "
                               f"independently -- embedding trades those for read speed.")

        result[table_name] = {
            "document_schema": {"bsonType": "object", "properties": properties,
                                 "required": [c["name"] for c in table["columns"] if c["not_null"]]},
            "example": example,
            "embedding_candidate": is_candidate,
            "embedding_note": embedding_note,
        }
    return result


def format_report(schema: dict) -> str:
    import json
    lines = []
    for table_name, info in schema.items():
        lines.append(f"=== {table_name} -> collection '{table_name}' ===")
        lines.append(json.dumps(info["example"], indent=2))
        if info["embedding_note"]:
            lines.append(f"\nNOTE: {info['embedding_note']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sample_sql = """
    CREATE TABLE customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(120) NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL,
        created_at TIMESTAMP
    );

    CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        total DECIMAL(10,2) NOT NULL,
        placed_at TIMESTAMP
    );

    CREATE TABLE order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_name VARCHAR(200) NOT NULL,
        quantity INT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id)
    );
    """
    tables = parse_create_tables(sample_sql)
    for name, t in tables.items():
        print(f"{name}: columns={[c['name'] for c in t['columns']]} "
              f"pk={t['primary_key']} fks={t['foreign_keys']}")
    print()
    schema = to_document_schema(tables)
    print(format_report(schema))
