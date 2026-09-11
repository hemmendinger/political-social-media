"""Tests for scripts/weekly.py (docs/SPEC.md section 11): render_markdown's shape and the CLI's
file output. Uses the synthetic dataset/db fixtures from tests/conftest.py for the CLI tests.
"""
from __future__ import annotations

from scripts import weekly

HEADINGS = [
    "## Headline",
    "## Posts by day",
    "## Hour histogram (ET)",
    "## Overnight share",
    "## Bursts",
    "## Deletions",
    "## Top reblogged accounts",
    "## Link domains",
    "## Media mix",
    "## Engagement stats",
    "## Longest silence",
    "## Edits",
    "## Caveats",
]


def _empty_report(days):
    return {
        "posts_by_day": [
            {"et_date": d, "original": 0, "quote": 0, "reblog": 0, "reply": 0, "total": 0, "deleted": 0}
            for d in days
        ],
        "hour_histogram": [0] * 24,
        "overnight_share": {"overnight": 0, "total": 0, "share": None},
        "bursts": [],
        "deletions": [],
        "top_reblogged_accounts": [],
        "link_domains": [],
        "media_mix": {"no_media": 0, "image_only": 0, "video_only": 0, "mixed": 0, "media_items_by_type": {}},
        "engagement_stats": {},
        "longest_silence": None,
        "edits": {"count": 0, "rows": []},
    }


def _minimal_baseline():
    return {
        "window": _empty_report(["2026-09-07", "2026-09-08"]),
        "trailing": _empty_report(["2026-07-13", "2026-07-14"]),
        "meta": {
            "start": "2026-09-07", "end": "2026-09-08",
            "trailing_start": "2026-07-13", "trailing_end": "2026-07-14",
        },
    }


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def test_render_markdown_contains_all_section_headings():
    md = weekly.render_markdown(_minimal_baseline())
    for heading in HEADINGS:
        assert heading in md, "missing heading %r" % heading


def test_render_markdown_contains_caveats_paragraph():
    md = weekly.render_markdown(_minimal_baseline())
    assert "Deletion is an interval, not a point" in md
    assert "presumed live" in md
    assert "Engagement counts are snapshots" in md


def test_render_markdown_handles_empty_window_gracefully():
    md = weekly.render_markdown(_minimal_baseline())
    assert "None." in md  # bursts/deletions/etc. with nothing to show
    assert "Fewer than two posts in this window." in md


def test_render_markdown_headline_shows_totals():
    md = weekly.render_markdown(_minimal_baseline())
    assert "2026-09-07" in md and "2026-09-08" in md


# ---------------------------------------------------------------------------
# CLI: writes md + csv files
# ---------------------------------------------------------------------------


def test_cli_start_end_writes_md_and_csv_files(db_path, tmp_path):
    out_dir = tmp_path / "reports"
    rc = weekly.main(["--start", "2026-07-01", "--end", "2026-07-06", "--db", str(db_path), "--out", str(out_dir)])
    assert rc == 0

    label = "2026-07-01_2026-07-06"
    md_path = out_dir / (label + ".md")
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    for heading in HEADINGS:
        assert heading in text

    for table in (
        "posts_by_day", "hour_histogram", "bursts", "deletions",
        "top_reblogged_accounts", "link_domains", "media_mix", "engagement_stats",
    ):
        csv_path = out_dir / ("%s__%s.csv" % (label, table))
        assert csv_path.exists(), "missing %s" % csv_path
        assert csv_path.read_text(encoding="utf-8").splitlines()  # at least a header row


def test_cli_week_flag_writes_expected_label(db_path, tmp_path):
    out_dir = tmp_path / "reports"
    rc = weekly.main(["--week", "2026-W37", "--db", str(db_path), "--out", str(out_dir)])
    assert rc == 0
    assert (out_dir / "2026-W37.md").exists()
    assert (out_dir / "2026-W37__posts_by_day.csv").exists()


def test_cli_requires_week_or_start_end(db_path, tmp_path):
    import pytest

    with pytest.raises(SystemExit):
        weekly.main(["--db", str(db_path), "--out", str(tmp_path / "reports")])
