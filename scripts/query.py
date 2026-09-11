"""Ad-hoc SQL runner over ``data/truths.sqlite`` (docs/SPEC.md section 11).

``run_query`` is the pure core; ``main`` wires it to argv/stdout. Output formats never touch the
database -- they operate on plain ``(columns, rows)`` tuples so they're trivial to unit test.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple


def run_query(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> Tuple[List[str], List[tuple]]:
    cur = conn.execute(sql, tuple(params))
    columns = [d[0] for d in cur.description] if cur.description else []
    rows = [tuple(row) for row in cur.fetchall()]
    return columns, rows


def format_table(columns: Sequence[str], rows: Sequence[tuple]) -> str:
    if not columns:
        return ""
    str_rows = [["" if v is None else str(v) for v in row] for row in rows]
    widths = [len(c) for c in columns]
    for row in str_rows:
        for i, v in enumerate(row):
            widths[i] = max(widths[i], len(v))

    def fmt_row(vals: Sequence[str]) -> str:
        return "  ".join(v.ljust(widths[i]) for i, v in enumerate(vals))

    lines = [fmt_row(columns), "  ".join("-" * w for w in widths)]
    lines.extend(fmt_row(row) for row in str_rows)
    return "\n".join(lines)


def format_markdown(columns: Sequence[str], rows: Sequence[tuple]) -> str:
    if not columns:
        return ""

    def esc(v: Any) -> str:
        return "" if v is None else str(v).replace("|", "\\|")

    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(esc(v) for v in row) + " |" for row in rows)
    return "\n".join(lines)


def format_csv(columns: Sequence[str], rows: Sequence[tuple], stream=None) -> Optional[str]:
    """Write CSV to ``stream`` (default ``sys.stdout``); returns the text only when no stream is given."""
    import io

    owns_buffer = stream is None
    out = io.StringIO() if owns_buffer else stream
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return out.getvalue() if owns_buffer else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.query")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sql", help="inline SQL to run")
    source.add_argument("--file", type=Path, help="path to a .sql file to run")
    parser.add_argument("--db", type=Path, default=Path("data/truths.sqlite"))
    parser.add_argument("--format", choices=["table", "csv", "markdown"], default="table")
    parser.add_argument("--limit", type=int, default=None, help="cap the number of rows shown")
    args = parser.parse_args(argv)

    sql = args.sql if args.sql is not None else args.file.read_text(encoding="utf-8")

    conn = sqlite3.connect(str(args.db))
    try:
        columns, rows = run_query(conn, sql)
    finally:
        conn.close()

    if args.limit is not None:
        rows = rows[: args.limit]

    if args.format == "csv":
        format_csv(columns, rows, stream=sys.stdout)
    elif args.format == "markdown":
        print(format_markdown(columns, rows))
    else:
        print(format_table(columns, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
