"""Hand-computed expectations for scripts/metrics.py (docs/SPEC.md section 11), against the
synthetic dataset in tests/conftest.py. Each test uses a tight start/end window around just the
group of posts relevant to that metric -- see tests/conftest.py for the full layout.
"""
from __future__ import annotations

import pytest

from scripts.metrics import (
    baseline,
    bursts,
    deletions,
    edits,
    engagement_stats,
    hour_histogram,
    iso_week_bounds,
    link_domains,
    longest_silence,
    media_mix,
    overnight_share,
    posts_by_day,
    top_reblogged_accounts,
)
from tests.conftest import D1_CONTENT, IDS

ZERO_DAY = {"original": 0, "quote": 0, "reblog": 0, "reply": 0, "total": 0, "deleted": 0}


# ---------------------------------------------------------------------------
# posts_by_day
# ---------------------------------------------------------------------------


def test_posts_by_day_includes_zero_days(conn):
    rows = posts_by_day(conn, "2026-03-07", "2026-03-10")
    by_date = {r["et_date"]: r for r in rows}
    assert list(by_date.keys()) == ["2026-03-07", "2026-03-08", "2026-03-09", "2026-03-10"]

    assert by_date["2026-03-07"] == dict(et_date="2026-03-07", **ZERO_DAY)
    assert by_date["2026-03-10"] == dict(et_date="2026-03-10", **ZERO_DAY)

    d08 = by_date["2026-03-08"]
    assert (d08["original"], d08["total"], d08["deleted"]) == (3, 3, 0)  # A1, A2, A3

    d09 = by_date["2026-03-09"]
    assert (d09["original"], d09["total"], d09["deleted"]) == (1, 1, 0)  # A4


# ---------------------------------------------------------------------------
# hour_histogram across the DST change
# ---------------------------------------------------------------------------


def test_hour_histogram_spring_forward_gap(conn):
    # A1 06:30Z -> 01:30 EST (hour 1); A2 07:30Z -> 03:30 EDT (hour 3, hour 2 is skipped by the
    # spring-forward jump); A3 15:00Z -> 11:00 EDT (hour 11).
    hist = hour_histogram(conn, "2026-03-08", "2026-03-08")
    assert len(hist) == 24
    expected = [0] * 24
    expected[1] = 1
    expected[3] = 1
    expected[11] = 1
    assert hist == expected


def test_hour_histogram_fall_back_repeated_hour(conn):
    # G1 05:30Z -> 01:30 EDT and G2 06:30Z -> 01:30 EST: two different UTC instants land on the
    # same ET clock hour because of the fall-back repeat, so hour 1 counts both.
    hist = hour_histogram(conn, "2026-11-01", "2026-11-01")
    expected = [0] * 24
    expected[1] = 2
    assert hist == expected


# ---------------------------------------------------------------------------
# overnight_share
# ---------------------------------------------------------------------------


def test_overnight_share(conn):
    result = overnight_share(conn, "2026-03-08", "2026-03-08")
    assert result == {"overnight": 2, "total": 3, "share": pytest.approx(2 / 3)}


def test_overnight_share_none_when_no_posts(conn):
    result = overnight_share(conn, "2026-01-01", "2026-01-01")
    assert result == {"overnight": 0, "total": 0, "share": None}


# ---------------------------------------------------------------------------
# bursts: 6 posts within 8 minutes vs 4 posts spread out
# ---------------------------------------------------------------------------


def test_bursts_detects_the_cluster_and_ignores_the_spread(conn):
    result = bursts(conn, "2026-06-15", "2026-06-16")
    assert len(result) == 1
    burst = result[0]
    assert burst["count"] == 6
    assert burst["kinds"] == {"original": 6}
    assert burst["start_et"] == "2026-06-15T10:00:00-04:00"
    assert burst["end_et"] == "2026-06-15T10:08:00-04:00"


def test_bursts_respects_min_posts(conn):
    # With min_posts raised past the cluster size, nothing qualifies.
    assert bursts(conn, "2026-06-15", "2026-06-16", min_posts=7) == []


# ---------------------------------------------------------------------------
# deletions
# ---------------------------------------------------------------------------


def test_deletions_lifetimes_and_snippet(conn):
    rows = deletions(conn, "2026-08-01", "2026-08-02")
    by_id = {r["ts_id"]: r for r in rows}
    assert set(by_id) == {IDS["D1"], IDS["D2"]}

    d1 = by_id[IDS["D1"]]
    assert d1["lifetime_min"] == pytest.approx(150.0)
    assert d1["deletion_window_min"] == pytest.approx(90.0)
    assert d1["deleted_source"] == "trumpstruth"
    assert d1["snippet"] == D1_CONTENT[:120]
    assert len(d1["snippet"]) == 120

    d2 = by_id[IDS["D2"]]
    assert d2["lifetime_min"] == pytest.approx(5.0)
    assert d2["deletion_window_min"] == pytest.approx(0.0)
    assert d2["deleted_source"] == "api404"
    assert d2["snippet"] == "Deleted quickly"


# ---------------------------------------------------------------------------
# top_reblogged_accounts / link_domains / media_mix
# ---------------------------------------------------------------------------


def test_top_reblogged_accounts(conn):
    result = top_reblogged_accounts(conn, "2026-07-01", "2026-07-06")
    assert result == [{"account": "elonmusk", "count": 3}, {"account": "someguy", "count": 1}]


def test_link_domains(conn):
    result = link_domains(conn, "2026-07-01", "2026-07-06")
    assert result == [{"domain": "example.com", "count": 3}, {"domain": "foo.example", "count": 1}]


def test_media_mix(conn):
    result = media_mix(conn, "2026-07-01", "2026-07-06")
    assert result == {
        "no_media": 9, "image_only": 1, "video_only": 1, "mixed": 1,
        "media_items_by_type": {"image": 2, "video": 2},
    }


# ---------------------------------------------------------------------------
# engagement_stats: odd count (original, n=3) vs even count (reblog, n=4)
# ---------------------------------------------------------------------------


def test_engagement_stats_odd_and_even_counts(conn):
    result = engagement_stats(conn, "2026-07-01", "2026-07-06")

    reblog = result["reblog"]  # favourites [5, 15, 25, 35], n=4 (even)
    assert reblog["n"] == 4
    assert reblog["favourites"] == {"median": 15, "p90": 35}
    assert reblog["reblogs"] == {"median": 4, "p90": 8}
    assert reblog["replies"] == {"median": 2, "p90": 4}

    original = result["original"]  # favourites [10, 20, 30], n=3 (odd)
    assert original["n"] == 3
    assert original["favourites"] == {"median": 20, "p90": 30}
    assert original["reblogs"] == {"median": 2, "p90": 3}
    assert original["replies"] == {"median": 2, "p90": 3}


def test_engagement_stats_uses_latest_snapshot_per_post(conn):
    # C1 has two engagement rows (favourites 1, then 5); only the latest may count.
    result = engagement_stats(conn, "2026-07-01", "2026-07-01")
    assert result["reblog"]["n"] == 2  # C1, C2 only (C3/C4 are on 07-02)
    assert result["reblog"]["favourites"]["p90"] == 15  # not 1 -- the stale row must be excluded


# ---------------------------------------------------------------------------
# longest_silence
# ---------------------------------------------------------------------------


def test_longest_silence(conn):
    result = longest_silence(conn, "2026-03-08", "2026-03-09")
    assert result["gap_min"] == pytest.approx(1380.0)  # A3 15:00Z 03-08 -> A4 14:00Z 03-09
    assert result["from_et"] == "2026-03-08T11:00:00-04:00"
    assert result["to_et"] == "2026-03-09T10:00:00-04:00"


def test_longest_silence_none_with_fewer_than_two_posts(conn):
    assert longest_silence(conn, "2026-03-09", "2026-03-09") is None
    assert longest_silence(conn, "2026-01-01", "2026-01-01") is None


# ---------------------------------------------------------------------------
# edits
# ---------------------------------------------------------------------------


def test_edits(conn):
    result = edits(conn, "2026-07-01", "2026-07-06")
    assert result["count"] == 1
    assert result["rows"] == [{
        "ts_id": IDS["C7"], "created_at_et": "2026-07-04T08:00:00-04:00",
        "kind": "original", "edited_at": "2026-07-04T12:30:00Z",
    }]


# ---------------------------------------------------------------------------
# iso_week_bounds
# ---------------------------------------------------------------------------


def test_iso_week_bounds_2026_w37():
    assert iso_week_bounds("2026-W37") == ("2026-09-07", "2026-09-13")


def test_iso_week_bounds_2026_w01_starts_in_prior_year():
    # ISO week 1 of 2026 begins in late December 2025.
    assert iso_week_bounds("2026-W01") == ("2025-12-29", "2026-01-04")


# ---------------------------------------------------------------------------
# baseline meta
# ---------------------------------------------------------------------------


def test_baseline_meta_dates(conn):
    result = baseline(conn, "2026-09-07", "2026-09-13")
    assert result["meta"] == {
        "start": "2026-09-07", "end": "2026-09-13",
        "trailing_start": "2026-07-13", "trailing_end": "2026-09-06",
    }
    # No posts fall inside the window itself...
    assert sum(d["total"] for d in result["window"]["posts_by_day"]) == 0
    # ...but the trailing 8 weeks (2026-07-13 .. 2026-09-06) catch exactly the two deletions.
    assert sum(d["total"] for d in result["trailing"]["posts_by_day"]) == 2
    assert len(result["trailing"]["deletions"]) == 2


def test_baseline_custom_trailing_weeks(conn):
    result = baseline(conn, "2026-09-07", "2026-09-13", trailing_weeks=2)
    assert result["meta"]["trailing_end"] == "2026-09-06"
    assert result["meta"]["trailing_start"] == "2026-08-24"  # 14 days ending 2026-09-06
