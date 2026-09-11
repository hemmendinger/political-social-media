"""Tests for scripts/query.py (docs/SPEC.md section 11): run_query, the three output formats,
and that every starter query under queries/ executes cleanly against the synthetic db.
"""
from __future__ import annotations

from pathlib import Path

from scripts import query

QUERIES_DIR = Path(__file__).resolve().parent.parent / "queries"


# ---------------------------------------------------------------------------
# run_query
# ---------------------------------------------------------------------------


def test_run_query_returns_columns_and_rows(conn):
    columns, rows = query.run_query(conn, "SELECT ts_id, kind FROM posts ORDER BY ts_id LIMIT 3")
    assert columns == ["ts_id", "kind"]
    assert len(rows) == 3
    assert all(isinstance(r, tuple) and len(r) == 2 for r in rows)


def test_run_query_with_params(conn):
    columns, rows = query.run_query(conn, "SELECT COUNT(*) AS n FROM posts WHERE kind = ?", ("reblog",))
    assert columns == ["n"]
    assert rows == [(4,)]  # C1, C2, C3 (elonmusk) + C4 (someguy)


def test_run_query_empty_result(conn):
    columns, rows = query.run_query(conn, "SELECT ts_id FROM posts WHERE kind = 'nonexistent-kind'")
    assert columns == ["ts_id"]
    assert rows == []


# ---------------------------------------------------------------------------
# Output formats (pure functions, fixed input)
# ---------------------------------------------------------------------------


def test_format_table_pads_columns():
    text = query.format_table(["a", "bb"], [(1, "x"), (22, "yy")])
    lines = text.splitlines()
    assert lines[0] == "a   bb"
    assert lines[1] == "--  --"
    assert lines[2] == "1   x "
    assert lines[3] == "22  yy"


def test_format_table_empty_columns():
    assert query.format_table([], []) == ""


def test_format_markdown_renders_pipe_table():
    text = query.format_markdown(["a", "b"], [(1, "x"), (2, None)])
    lines = text.splitlines()
    assert lines[0] == "| a | b |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 1 | x |"
    assert lines[3] == "| 2 |  |"  # None renders blank


def test_format_csv_writes_stream():
    import io

    buf = io.StringIO()
    query.format_csv(["a", "b"], [(1, "x"), (2, None)], stream=buf)
    assert buf.getvalue() == "a,b\n1,x\n2,\n"


def test_format_csv_returns_text_without_stream():
    text = query.format_csv(["a", "b"], [(1, "x")])
    assert "a,b" in text
    assert "1,x" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_sql_table_format(db_path, capsys):
    rc = query.main(["--sql", "SELECT 1 AS one, 2 AS two", "--db", str(db_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "one" in out and "two" in out
    assert "1" in out and "2" in out


def test_cli_sql_csv_format(db_path, capsys):
    rc = query.main(["--sql", "SELECT 1 AS one", "--db", str(db_path), "--format", "csv"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "one"


def test_cli_sql_markdown_format(db_path, capsys):
    rc = query.main(["--sql", "SELECT 1 AS one", "--db", str(db_path), "--format", "markdown"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "| one |" in out


def test_cli_file_option(db_path, capsys, tmp_path):
    sql_file = tmp_path / "q.sql"
    sql_file.write_text("SELECT COUNT(*) AS n FROM posts;\n", encoding="utf-8")
    rc = query.main(["--file", str(sql_file), "--db", str(db_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "30" in out


def test_cli_limit_caps_rows(db_path, capsys):
    rc = query.main(["--sql", "SELECT ts_id FROM posts ORDER BY ts_id", "--db", str(db_path),
                      "--format", "csv", "--limit", "5"])
    assert rc == 0
    out = capsys.readouterr().out
    # header + 5 data rows, no more
    assert len([line for line in out.splitlines() if line.strip()]) == 6


# ---------------------------------------------------------------------------
# every queries/*.sql file runs cleanly against the synthetic db
# ---------------------------------------------------------------------------


def test_every_starter_query_executes(conn):
    sql_files = sorted(QUERIES_DIR.glob("*.sql"))
    assert len(sql_files) == 11
    for path in sql_files:
        sql = path.read_text(encoding="utf-8")
        columns, rows = query.run_query(conn, sql)
        assert isinstance(columns, list)
        assert isinstance(rows, list)
