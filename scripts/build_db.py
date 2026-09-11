"""Rebuild ``data/truths.sqlite`` from ``data/`` (docs/SPEC.md section 10).

Pure ETL: every post/engagement/deletion/run field is already computed by the merge layer
(``created_at_et``, ``et_date`` etc. live on the stored record). This module just loads the
JSONL/CSV files via ``scripts.store`` and pours them into SQLite tables and analysis views.
Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from scripts.store import load_deletions, load_engagement, load_posts, load_runs

log = logging.getLogger(__name__)

# Section 2 fields, in spec order. Values are stored verbatim except JSON_FIELDS (encoded as
# compact JSON text) and BOOL_FIELDS (encoded as 0/1).
POST_FIELDS: List[str] = [
    "ts_id", "created_at_utc", "created_at_et", "et_date", "et_hour", "et_dow", "kind",
    "content_html", "content_text", "lang", "in_reply_to_id", "quote_id", "quote_of_acct",
    "reblog_of_id", "reblog_of_acct", "reblog_of_created_at", "media", "card_url", "card_domain",
    "card_title", "mentions", "tags", "edited_at", "pinned", "first_seen_at", "first_seen_source",
    "seen_sources", "status", "last_verified_live_at", "deleted_lower", "deleted_upper",
    "deleted_source", "trumpstruth_id", "trumpstruth_captured_at", "trumpstruth_removed_at",
    "field_sources", "raw_api", "updated_at", "updated_run_id",
]
JSON_FIELDS = {"media", "mentions", "tags", "seen_sources", "field_sources", "raw_api"}
BOOL_FIELDS = {"pinned"}
EXTRA_POST_FIELDS = ["media_count", "media_types", "content_len"]

MEDIA_ITEM_FIELDS = ["type", "url", "preview_url", "mirror_url", "width", "height", "duration"]
MEDIA_COLUMNS = ["ts_id", "idx"] + MEDIA_ITEM_FIELDS

ENGAGEMENT_FIELDS = ["observed_at", "ts_id", "source", "replies", "reblogs", "favourites", "upvotes", "downvotes"]

DELETION_FIELDS = ["ts_id", "detected_at", "deleted_lower", "deleted_upper", "source", "trumpstruth_removed_at", "run_id"]

RUN_FIELDS = [
    "run_id", "source", "started_at", "finished_at", "ok", "requests", "new_posts",
    "updated_posts", "deletions_found", "errors", "notes",
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _posts_column_defs() -> List[str]:
    defs = []
    for field in POST_FIELDS:
        if field == "ts_id":
            defs.append("ts_id TEXT PRIMARY KEY")
        elif field == "et_hour" or field == "et_dow":
            defs.append("%s INTEGER" % field)
        elif field == "pinned":
            defs.append("pinned INTEGER")
        else:
            defs.append("%s TEXT" % field)
    defs.append("media_count INTEGER")
    defs.append("media_types TEXT")
    defs.append("content_len INTEGER")
    return defs


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE posts (%s)" % ", ".join(_posts_column_defs()))
    conn.execute(
        "CREATE TABLE media ("
        "ts_id TEXT, idx INTEGER, type TEXT, url TEXT, preview_url TEXT, mirror_url TEXT, "
        "width INTEGER, height INTEGER, duration REAL, PRIMARY KEY (ts_id, idx))"
    )
    conn.execute(
        "CREATE TABLE engagement ("
        "observed_at TEXT, ts_id TEXT, source TEXT, replies INTEGER, reblogs INTEGER, "
        "favourites INTEGER, upvotes INTEGER, downvotes INTEGER)"
    )
    conn.execute(
        "CREATE TABLE deletions ("
        "ts_id TEXT, detected_at TEXT, deleted_lower TEXT, deleted_upper TEXT, source TEXT, "
        "trumpstruth_removed_at TEXT, run_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE runs ("
        "run_id TEXT, source TEXT, started_at TEXT, finished_at TEXT, ok INTEGER, requests INTEGER, "
        "new_posts INTEGER, updated_posts INTEGER, deletions_found INTEGER, errors INTEGER, notes TEXT)"
    )


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX ix_posts_created_at_utc ON posts(created_at_utc)")
    conn.execute("CREATE INDEX ix_posts_et_date ON posts(et_date)")
    conn.execute("CREATE INDEX ix_posts_kind ON posts(kind)")
    conn.execute("CREATE INDEX ix_posts_status ON posts(status)")
    conn.execute("CREATE INDEX ix_engagement_ts_id_observed_at ON engagement(ts_id, observed_at)")


def _create_views(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIEW v_posts_et AS
        SELECT
            ts_id,
            created_at_utc,
            created_at_et,
            et_date,
            et_hour,
            et_dow,
            kind,
            status,
            CASE WHEN status = 'deleted' THEN 1 ELSE 0 END AS is_deleted,
            content_text,
            content_len,
            media_count,
            media_types,
            card_domain,
            card_url,
            reblog_of_acct,
            reblog_of_id,
            quote_of_acct,
            quote_id,
            mentions,
            tags,
            edited_at,
            deleted_lower,
            deleted_upper,
            deleted_source,
            CASE
                WHEN status = 'deleted' AND deleted_upper IS NOT NULL
                THEN (julianday(deleted_upper) - julianday(created_at_utc)) * 1440.0
                ELSE NULL
            END AS lifetime_min,
            CASE
                WHEN deleted_lower IS NOT NULL AND deleted_upper IS NOT NULL
                THEN (julianday(deleted_upper) - julianday(deleted_lower)) * 1440.0
                ELSE NULL
            END AS deletion_window_min,
            first_seen_source,
            seen_sources
        FROM posts
        """
    )
    conn.execute("CREATE VIEW v_deletions AS SELECT * FROM v_posts_et WHERE is_deleted = 1")
    conn.execute(
        """
        CREATE VIEW v_engagement_latest AS
        SELECT ts_id, observed_at, source, replies, reblogs, favourites, upvotes, downvotes
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY ts_id ORDER BY observed_at DESC, rowid DESC
            ) AS rn
            FROM engagement
        )
        WHERE rn = 1
        """
    )


# ---------------------------------------------------------------------------
# Row shaping
# ---------------------------------------------------------------------------


def _json_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _post_row(post: Dict[str, Any]) -> Tuple[Any, ...]:
    values: List[Any] = []
    for field in POST_FIELDS:
        value = post.get(field)
        if field in JSON_FIELDS:
            value = _json_or_none(value)
        elif field in BOOL_FIELDS:
            value = 1 if value else 0
        values.append(value)
    media = post.get("media") or []
    media_types = ",".join((item.get("type") or "") for item in media)
    content_text = post.get("content_text") or ""
    values.append(len(media))
    values.append(media_types)
    values.append(len(content_text))
    return tuple(values)


def _media_rows(post: Dict[str, Any]) -> List[Tuple[Any, ...]]:
    ts_id = post["ts_id"]
    rows = []
    for idx, item in enumerate(post.get("media") or []):
        rows.append((
            ts_id, idx, item.get("type"), item.get("url"), item.get("preview_url"),
            item.get("mirror_url"), item.get("width"), item.get("height"), item.get("duration"),
        ))
    return rows


def _row(fields: Sequence[str], obj: Dict[str, Any]) -> Tuple[Any, ...]:
    values = []
    for field in fields:
        value = obj.get(field)
        if field == "ok":
            value = 1 if value else 0
        values.append(value)
    return tuple(values)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _remove_stale_journal(db_file: Path) -> None:
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(str(db_file) + suffix)
        if sidecar.exists():
            sidecar.unlink()


def build(data_root: Path, db_path: Path) -> Dict[str, Any]:
    """Rebuild ``db_path`` from ``data_root`` from scratch. Returns a stats dict.

    Builds into a temp file next to ``db_path`` and atomically replaces it, so a crash mid-build
    never leaves a half-written database at ``db_path``.
    """
    t0 = time.monotonic()
    data_root = Path(data_root)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_stale_journal(db_path)

    posts = load_posts(data_root)
    engagement = load_engagement(data_root)
    deletions = load_deletions(data_root)
    runs = load_runs(data_root)

    fd, tmp_name = tempfile.mkstemp(prefix=db_path.name + ".", suffix=".tmp", dir=str(db_path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    tmp_path.unlink()  # sqlite3.connect creates the file fresh; mkstemp only reserves the name

    try:
        conn = sqlite3.connect(str(tmp_path))
        try:
            conn.execute("PRAGMA journal_mode = MEMORY")
            conn.execute("PRAGMA synchronous = OFF")
            with conn:
                _create_schema(conn)
                conn.executemany(
                    "INSERT INTO posts VALUES (%s)" % ",".join(["?"] * (len(POST_FIELDS) + len(EXTRA_POST_FIELDS))),
                    (_post_row(p) for p in posts),
                )
                media_rows: List[Tuple[Any, ...]] = []
                for p in posts:
                    media_rows.extend(_media_rows(p))
                if media_rows:
                    conn.executemany(
                        "INSERT INTO media VALUES (%s)" % ",".join(["?"] * len(MEDIA_COLUMNS)), media_rows
                    )
                if engagement:
                    conn.executemany(
                        "INSERT INTO engagement VALUES (%s)" % ",".join(["?"] * len(ENGAGEMENT_FIELDS)),
                        (_row(ENGAGEMENT_FIELDS, r) for r in engagement),
                    )
                if deletions:
                    conn.executemany(
                        "INSERT INTO deletions VALUES (%s)" % ",".join(["?"] * len(DELETION_FIELDS)),
                        (_row(DELETION_FIELDS, r) for r in deletions),
                    )
                if runs:
                    conn.executemany(
                        "INSERT INTO runs VALUES (%s)" % ",".join(["?"] * len(RUN_FIELDS)),
                        (_row(RUN_FIELDS, r) for r in runs),
                    )
                _create_views(conn)
                _create_indexes(conn)
        finally:
            conn.close()
        _remove_stale_journal(tmp_path)
        os.replace(str(tmp_path), str(db_path))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
        _remove_stale_journal(tmp_path)

    _remove_stale_journal(db_path)

    media_count = sum(len(p.get("media") or []) for p in posts)
    return {
        "posts": len(posts),
        "media": media_count,
        "engagement": len(engagement),
        "deletions": len(deletions),
        "runs": len(runs),
        "seconds": round(time.monotonic() - t0, 3),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.build_db")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--db", type=Path, default=Path("data/truths.sqlite"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stats = build(args.data_root, args.db)
    print(
        "posts=%d media=%d engagement=%d deletions=%d runs=%d seconds=%.3f"
        % (stats["posts"], stats["media"], stats["engagement"], stats["deletions"], stats["runs"], stats["seconds"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
