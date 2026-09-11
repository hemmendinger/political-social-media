"""Shared synthetic dataset for the analysis-layer tests (build_db, metrics, weekly, query).

30 posts spanning the 2026-03-08 spring-forward and 2026-11-01 fall-back DST changes, with
reblogs, a quote, media, link cards, two deletions with hand-checkable bounds, a burst of six
posts inside eight minutes, four spread-out posts, and engagement snapshots sized to exercise
both the odd- and even-count branches of the median/p90 calculation. Grouped by label (A/B/C/D/G)
so individual metric tests can pick a tight ``start``/``end`` window around just the posts they
care about instead of reasoning about the whole dataset at once.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts import build_db
from tests.factories import make_media_item, make_post, make_run_row, write_dataset

_BASE_ID = 100000000000000000


def _id(i: int) -> str:
    return str(_BASE_ID + i)


IDS = {
    "A1": _id(1), "A2": _id(2), "A3": _id(3), "A4": _id(4),
    "B_BURST": [_id(i) for i in range(5, 11)],
    "B_SPREAD": [_id(i) for i in range(11, 15)],
    "C1": _id(15), "C2": _id(16), "C3": _id(17), "C4": _id(18), "C5": _id(19),
    "C6": _id(20), "C7": _id(21), "C8": _id(22), "C9": _id(23), "C10": _id(24),
    "C11": _id(25), "C12": _id(26),
    "D1": _id(27), "D2": _id(28),
    "G1": _id(29), "G2": _id(30),
}

# Deliberately > 120 chars so the deletions-report snippet is a genuine truncation.
D1_CONTENT = (
    "This Truth Social post is going to be deleted shortly after it goes live, and this "
    "sentence is deliberately long so it exceeds the snippet truncation length used by the "
    "deletions report."
)

IMAGE_ITEM = make_media_item(
    "image", url="https://truthsocial.com/media/1.jpg",
    preview_url="https://truthsocial.com/media/1_small.jpg", width=800, height=600,
)
VIDEO_ITEM = make_media_item(
    "video", url="https://truthsocial.com/media/2.mp4", width=1280, height=720, duration=30.5,
)


def _build_posts():
    posts = []

    # --- Group A: DST spring-forward, 2026-03-08 (clocks jump 01:59:59 EST -> 03:00:00 EDT) ---
    posts.append(make_post(IDS["A1"], "2026-03-08T06:30:00Z", content_text="DST spring pre-jump post"))
    posts.append(make_post(IDS["A2"], "2026-03-08T07:30:00Z", content_text="DST spring post-jump post"))
    posts.append(make_post(IDS["A3"], "2026-03-08T15:00:00Z", content_text="Sunday afternoon post"))
    posts.append(make_post(IDS["A4"], "2026-03-09T14:00:00Z", content_text="Monday morning post"))

    # --- Group B: a burst of 6 posts inside 8 minutes, then 4 posts spread well apart ---
    burst_times = ["14:00:00", "14:02:00", "14:04:00", "14:05:00", "14:06:00", "14:08:00"]
    for i, t in enumerate(burst_times, start=1):
        posts.append(make_post(IDS["B_BURST"][i - 1], "2026-06-15T%sZ" % t, content_text="Burst post %d" % i))

    spread_times = ["10:00:00", "10:20:00", "10:45:00", "11:10:00"]
    for i, t in enumerate(spread_times, start=1):
        posts.append(make_post(IDS["B_SPREAD"][i - 1], "2026-06-16T%sZ" % t, content_text="Spread post %d" % i))

    # --- Group C: reblogs, a quote, link cards, media mix, a reply, one edit ---
    posts.append(make_post(
        IDS["C1"], "2026-07-01T12:00:00Z", kind="reblog", reblog_of_acct="elonmusk",
        reblog_of_id="900000000000000001", reblog_of_created_at="2026-06-30T10:00:00Z",
        content_text="Reblog of elonmusk 1",
    ))
    posts.append(make_post(
        IDS["C2"], "2026-07-01T13:00:00Z", kind="reblog", reblog_of_acct="elonmusk",
        reblog_of_id="900000000000000002", reblog_of_created_at="2026-06-30T11:00:00Z",
        content_text="Reblog of elonmusk 2",
    ))
    posts.append(make_post(
        IDS["C3"], "2026-07-02T12:00:00Z", kind="reblog", reblog_of_acct="elonmusk",
        reblog_of_id="900000000000000003", reblog_of_created_at="2026-07-01T09:00:00Z",
        content_text="Reblog of elonmusk 3",
    ))
    posts.append(make_post(
        IDS["C4"], "2026-07-02T13:00:00Z", kind="reblog", reblog_of_acct="someguy",
        reblog_of_id="900000000000000004", reblog_of_created_at="2026-07-01T09:30:00Z",
        content_text="Reblog of someguy 1",
    ))
    posts.append(make_post(
        IDS["C5"], "2026-07-03T12:00:00Z", kind="quote", quote_of_acct="newsguy",
        quote_id="900000000000000005", card_url="https://example.com/story-a",
        card_domain="example.com", card_title="Story A", content_text="Quote of newsguy",
    ))
    posts.append(make_post(
        IDS["C6"], "2026-07-03T13:00:00Z", card_url="https://example.com/story-b",
        card_domain="example.com", card_title="Story B", content_text="Original with card b",
    ))
    posts.append(make_post(
        IDS["C7"], "2026-07-04T12:00:00Z", card_url="https://example.com/story-c",
        card_domain="example.com", card_title="Story C", content_text="Original with card c",
        edited_at="2026-07-04T12:30:00Z",
    ))
    posts.append(make_post(
        IDS["C8"], "2026-07-04T13:00:00Z", card_url="https://foo.example/x",
        card_domain="foo.example", card_title="Foo story", content_text="Original with foo card",
    ))
    posts.append(make_post(IDS["C9"], "2026-07-05T12:00:00Z", media=[IMAGE_ITEM], content_text="Image only post"))
    posts.append(make_post(IDS["C10"], "2026-07-05T13:00:00Z", media=[VIDEO_ITEM], content_text="Video only post"))
    posts.append(make_post(
        IDS["C11"], "2026-07-05T14:00:00Z", media=[IMAGE_ITEM, VIDEO_ITEM], content_text="Mixed media post",
    ))
    posts.append(make_post(
        IDS["C12"], "2026-07-06T12:00:00Z", kind="reply", in_reply_to_id="900000000000000012",
        content_text="Reply post",
    ))

    # --- Group D: two deletions with hand-checkable lower/upper bounds ---
    posts.append(make_post(
        IDS["D1"], "2026-08-01T12:00:00Z", status="deleted", deleted_source="trumpstruth",
        deleted_lower="2026-08-01T13:00:00Z", deleted_upper="2026-08-01T14:30:00Z",
        trumpstruth_removed_at="2026-08-01T14:30:00Z", content_text=D1_CONTENT,
    ))
    posts.append(make_post(
        IDS["D2"], "2026-08-02T09:00:00Z", status="deleted", deleted_source="api404",
        deleted_lower="2026-08-02T09:05:00Z", deleted_upper="2026-08-02T09:05:00Z",
        content_text="Deleted quickly",
    ))

    # --- Group G: DST fall-back, 2026-11-01 (the 01:xx-01:59 local hour occurs twice) ---
    posts.append(make_post(IDS["G1"], "2026-11-01T05:30:00Z", content_text="DST fall EDT side"))
    posts.append(make_post(IDS["G2"], "2026-11-01T06:30:00Z", content_text="DST fall EST side"))

    assert len(posts) == 30
    return posts


def _engagement_row(ts_id, observed_at, replies, reblogs, favourites, source="api"):
    return {
        "observed_at": observed_at, "ts_id": ts_id, "source": source,
        "replies": replies, "reblogs": reblogs, "favourites": favourites,
        "upvotes": None, "downvotes": None,
    }


def _build_engagement():
    return [
        # C1 gets two snapshots -- the earlier one must be superseded by the later in
        # v_engagement_latest / engagement_stats.
        _engagement_row(IDS["C1"], "2026-07-01T12:05:00Z", 0, 0, 1),
        _engagement_row(IDS["C1"], "2026-07-01T12:10:00Z", 1, 2, 5),
        _engagement_row(IDS["C2"], "2026-07-01T13:10:00Z", 2, 4, 15),
        _engagement_row(IDS["C3"], "2026-07-02T12:10:00Z", 3, 6, 25),
        _engagement_row(IDS["C4"], "2026-07-02T13:10:00Z", 4, 8, 35),
        _engagement_row(IDS["C6"], "2026-07-03T13:10:00Z", 1, 1, 10),
        _engagement_row(IDS["C7"], "2026-07-04T12:10:00Z", 2, 2, 20),
        _engagement_row(IDS["C8"], "2026-07-04T13:10:00Z", 3, 3, 30),
    ]


def _build_deletion_events():
    return [
        {
            "ts_id": IDS["D1"], "detected_at": "2026-08-01T14:30:00Z",
            "deleted_lower": "2026-08-01T13:00:00Z", "deleted_upper": "2026-08-01T14:30:00Z",
            "source": "trumpstruth", "trumpstruth_removed_at": "2026-08-01T14:30:00Z", "run_id": "test-run-1",
        },
        {
            "ts_id": IDS["D2"], "detected_at": "2026-08-02T09:05:00Z",
            "deleted_lower": "2026-08-02T09:05:00Z", "deleted_upper": "2026-08-02T09:05:00Z",
            "source": "api404", "trumpstruth_removed_at": None, "run_id": "test-run-1",
        },
    ]


def _build_runs():
    return [
        make_run_row("test-run-1", "2026-08-01T14:35:00Z", source="trumpstruth", deletions_found=2),
        make_run_row("test-run-2", "2026-09-11T00:00:00Z", source="api", new_posts=30),
    ]


@pytest.fixture
def dataset(tmp_path):
    """Write the synthetic dataset under ``tmp_path/data`` via scripts.store. Returns the data root."""
    data_root = tmp_path / "data"
    write_dataset(
        data_root, _build_posts(),
        engagement_rows=_build_engagement(),
        deletions=_build_deletion_events(),
        runs=_build_runs(),
    )
    return data_root


@pytest.fixture
def db_path(tmp_path, dataset):
    """Build data/truths.sqlite from ``dataset`` and return its path."""
    path = tmp_path / "data" / "truths.sqlite"
    build_db.build(dataset, path)
    return path


@pytest.fixture
def conn(db_path):
    connection = sqlite3.connect(str(db_path))
    try:
        yield connection
    finally:
        connection.close()
