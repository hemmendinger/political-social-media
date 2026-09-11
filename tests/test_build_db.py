"""Tests for scripts/build_db.py (docs/SPEC.md section 10) against the synthetic dataset in
tests/conftest.py. Standard library only, no network.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts import build_db
from tests.conftest import D1_CONTENT, IDS

V_POSTS_ET_COLUMNS = [
    "ts_id", "created_at_utc", "created_at_et", "et_date", "et_hour", "et_dow", "kind", "status",
    "is_deleted", "content_text", "content_len", "media_count", "media_types", "card_domain",
    "card_url", "reblog_of_acct", "reblog_of_id", "quote_of_acct", "quote_id", "mentions", "tags",
    "edited_at", "deleted_lower", "deleted_upper", "deleted_source", "lifetime_min",
    "deletion_window_min", "first_seen_source", "seen_sources",
]
V_ENGAGEMENT_LATEST_COLUMNS = [
    "ts_id", "observed_at", "source", "replies", "reblogs", "favourites", "upvotes", "downvotes",
]


def _columns(conn, relation):
    cur = conn.execute("SELECT * FROM %s LIMIT 0" % relation)
    return [d[0] for d in cur.description]


# ---------------------------------------------------------------------------
# Table counts
# ---------------------------------------------------------------------------


def test_table_counts(conn):
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 30
    assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 4  # C9:1 + C10:1 + C11:2
    assert conn.execute("SELECT COUNT(*) FROM engagement").fetchone()[0] == 8
    assert conn.execute("SELECT COUNT(*) FROM deletions").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2


def test_build_returns_matching_stats(db_path, dataset):
    stats = build_db.build(dataset, db_path)
    assert stats["posts"] == 30
    assert stats["media"] == 4
    assert stats["engagement"] == 8
    assert stats["deletions"] == 2
    assert stats["runs"] == 2
    assert isinstance(stats["seconds"], float)
    assert stats["seconds"] >= 0


# ---------------------------------------------------------------------------
# View column lists
# ---------------------------------------------------------------------------


def test_v_posts_et_columns(conn):
    assert _columns(conn, "v_posts_et") == V_POSTS_ET_COLUMNS


def test_v_deletions_columns_match_v_posts_et(conn):
    assert _columns(conn, "v_deletions") == V_POSTS_ET_COLUMNS


def test_v_engagement_latest_columns(conn):
    assert _columns(conn, "v_engagement_latest") == V_ENGAGEMENT_LATEST_COLUMNS


def test_v_deletions_contains_only_deleted_posts(conn):
    rows = conn.execute("SELECT ts_id FROM v_deletions ORDER BY ts_id").fetchall()
    assert sorted(r[0] for r in rows) == sorted([IDS["D1"], IDS["D2"]])


# ---------------------------------------------------------------------------
# lifetime_min / deletion_window_min (hand-computed)
# ---------------------------------------------------------------------------


def test_lifetime_and_window_minutes_d1(conn):
    # created 2026-08-01T12:00:00Z, deleted_upper 14:30:00Z -> 150 min lifetime.
    # deleted_lower 13:00:00Z .. deleted_upper 14:30:00Z -> 90 min window.
    row = conn.execute(
        "SELECT lifetime_min, deletion_window_min FROM v_posts_et WHERE ts_id = ?", (IDS["D1"],)
    ).fetchone()
    assert row[0] == pytest.approx(150.0, abs=1e-6)
    assert row[1] == pytest.approx(90.0, abs=1e-6)


def test_lifetime_and_window_minutes_d2(conn):
    # created 2026-08-02T09:00:00Z, deleted_upper 09:05:00Z -> 5 min lifetime.
    # deleted_lower == deleted_upper == 09:05:00Z -> 0 min window.
    row = conn.execute(
        "SELECT lifetime_min, deletion_window_min FROM v_posts_et WHERE ts_id = ?", (IDS["D2"],)
    ).fetchone()
    assert row[0] == pytest.approx(5.0, abs=1e-6)
    assert row[1] == pytest.approx(0.0, abs=1e-6)


def test_lifetime_min_null_for_present_posts(conn):
    row = conn.execute(
        "SELECT lifetime_min, deletion_window_min FROM v_posts_et WHERE ts_id = ?", (IDS["A1"],)
    ).fetchone()
    assert row[0] is None
    assert row[1] is None


def test_is_deleted_flag(conn):
    assert conn.execute("SELECT is_deleted FROM v_posts_et WHERE ts_id = ?", (IDS["D1"],)).fetchone()[0] == 1
    assert conn.execute("SELECT is_deleted FROM v_posts_et WHERE ts_id = ?", (IDS["A1"],)).fetchone()[0] == 0


# ---------------------------------------------------------------------------
# media_types / content_len / media_count
# ---------------------------------------------------------------------------


def test_media_types_and_count_image_only(conn):
    row = conn.execute("SELECT media_count, media_types FROM posts WHERE ts_id = ?", (IDS["C9"],)).fetchone()
    assert row == (1, "image")


def test_media_types_and_count_video_only(conn):
    row = conn.execute("SELECT media_count, media_types FROM posts WHERE ts_id = ?", (IDS["C10"],)).fetchone()
    assert row == (1, "video")


def test_media_types_and_count_mixed(conn):
    row = conn.execute("SELECT media_count, media_types FROM posts WHERE ts_id = ?", (IDS["C11"],)).fetchone()
    assert row == (2, "image,video")


def test_media_count_zero_when_no_media(conn):
    row = conn.execute("SELECT media_count, media_types FROM posts WHERE ts_id = ?", (IDS["A1"],)).fetchone()
    assert row == (0, "")


def test_content_len(conn):
    row = conn.execute("SELECT content_len FROM posts WHERE ts_id = ?", (IDS["D1"],)).fetchone()
    assert row[0] == len(D1_CONTENT)


# ---------------------------------------------------------------------------
# Booleans / JSON columns stored as spec'd
# ---------------------------------------------------------------------------


def test_pinned_stored_as_integer(conn):
    row = conn.execute("SELECT pinned FROM posts WHERE ts_id = ?", (IDS["A1"],)).fetchone()
    assert row[0] == 0


def test_media_json_column_round_trips(conn):
    import json

    row = conn.execute("SELECT media FROM posts WHERE ts_id = ?", (IDS["C9"],)).fetchone()
    media = json.loads(row[0])
    assert media == [
        {
            "type": "image", "url": "https://truthsocial.com/media/1.jpg",
            "preview_url": "https://truthsocial.com/media/1_small.jpg", "mirror_url": None,
            "width": 800, "height": 600, "duration": None,
        }
    ]


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


def test_expected_indexes_exist(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    names = {r[0] for r in rows}
    assert "ix_posts_created_at_utc" in names
    assert "ix_posts_et_date" in names
    assert "ix_posts_kind" in names
    assert "ix_posts_status" in names
    assert "ix_engagement_ts_id_observed_at" in names


# ---------------------------------------------------------------------------
# Idempotent rebuild / atomic replace hygiene
# ---------------------------------------------------------------------------


def test_rebuild_is_idempotent(tmp_path, dataset):
    db = tmp_path / "data" / "truths.sqlite"
    stats1 = build_db.build(dataset, db)
    stats2 = build_db.build(dataset, db)
    for key in ("posts", "media", "engagement", "deletions", "runs"):
        assert stats1[key] == stats2[key]

    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 30
        assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 4
    finally:
        conn.close()


def test_rebuild_leaves_no_journal_or_temp_files(tmp_path, dataset):
    db = tmp_path / "data" / "truths.sqlite"
    build_db.build(dataset, db)
    build_db.build(dataset, db)

    leftovers = [
        p for p in db.parent.iterdir()
        if p.name != db.name and (p.suffix == ".tmp" or "-journal" in p.name or "-wal" in p.name or "-shm" in p.name)
    ]
    assert leftovers == []


def test_rebuild_removes_stale_journal_next_to_target(tmp_path, dataset):
    db = tmp_path / "data" / "truths.sqlite"
    build_db.build(dataset, db)
    stale_journal = db.parent / (db.name + "-journal")
    stale_journal.write_text("stale", encoding="utf-8")
    assert stale_journal.exists()

    build_db.build(dataset, db)
    assert not stale_journal.exists()
