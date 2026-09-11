"""Tests for scripts/store.py (docs/SPEC.md section 3). Standard library only, no network."""
import json

from scripts.store import (
    append_deletion,
    append_engagement,
    append_run,
    filter_engagement,
    latest_engagement_times,
    load_deletions,
    load_engagement,
    load_posts,
    load_posts_index,
    load_runs,
    load_state,
    month_of,
    save_posts,
    save_state,
)

ENGAGEMENT_HEADER = "observed_at,ts_id,source,replies,reblogs,favourites,upvotes,downvotes"


def make_post(ts_id, created_at_utc, **extra):
    record = {"ts_id": ts_id, "created_at_utc": created_at_utc, "kind": "original", "content_html": ""}
    record.update(extra)
    return record


def make_engagement_row(ts_id, observed_at, source="api", **extra):
    row = {
        "observed_at": observed_at,
        "ts_id": ts_id,
        "source": source,
        "replies": None,
        "reblogs": None,
        "favourites": None,
        "upvotes": None,
        "downvotes": None,
    }
    row.update(extra)
    return row


# ---------------------------------------------------------------------------
# month_of
# ---------------------------------------------------------------------------


def test_month_of():
    assert month_of("2026-09-09T00:53:04Z") == "2026-09"
    assert month_of("2026-01-01T00:00:00Z") == "2026-01"
    assert month_of("2025-12-31T23:59:59Z") == "2025-12"


# ---------------------------------------------------------------------------
# posts: partitioning, sorting, format
# ---------------------------------------------------------------------------


def test_save_posts_partitions_by_month_and_sorts_by_ts_id(tmp_path):
    records = [
        make_post("100000000000000003", "2026-09-05T00:00:00Z"),
        make_post("100000000000000001", "2026-09-01T00:00:00Z"),
        make_post("100000000000000002", "2026-09-03T00:00:00Z"),
        make_post("200000000000000001", "2026-08-15T00:00:00Z"),
    ]
    save_posts(tmp_path, records)

    posts_dir = tmp_path / "posts"
    assert sorted(p.name for p in posts_dir.glob("*.jsonl")) == ["2026-08.jsonl", "2026-09.jsonl"]

    sep_lines = (posts_dir / "2026-09.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["ts_id"] for line in sep_lines] == [
        "100000000000000001",
        "100000000000000002",
        "100000000000000003",
    ]
    aug_lines = (posts_dir / "2026-08.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(aug_lines[0])["ts_id"] == "200000000000000001"


def test_save_posts_line_format_compact_sorted_unicode(tmp_path):
    records = [make_post("100000000000000001", "2026-09-01T00:00:00Z", content_text="café — done")]
    save_posts(tmp_path, records)
    raw = (tmp_path / "posts" / "2026-09.jsonl").read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    assert text.count("\n") == 1  # exactly one record, trailing newline, no blank lines
    line = text.rstrip("\n")
    assert "café" in line and "—" in line  # ensure_ascii=False
    assert "\\u" not in line
    assert ": " not in line and ", " not in line  # separators=(",", ":")
    obj = json.loads(line)
    assert list(obj.keys()) == sorted(obj.keys())  # sort_keys=True


def test_save_posts_round_trip_byte_identical(tmp_path):
    records = [
        make_post("100000000000000001", "2026-09-01T00:00:00Z", mentions=["a", "b"], tags=[]),
        make_post("100000000000000002", "2026-09-05T12:30:00Z", media=[{"type": "image", "url": None}]),
        make_post("200000000000000001", "2026-08-20T08:00:00Z", field_sources={"kind": "api"}),
    ]
    save_posts(tmp_path, records)
    posts_dir = tmp_path / "posts"
    before = {p.name: p.read_bytes() for p in posts_dir.glob("*.jsonl")}

    loaded = load_posts(tmp_path)
    save_posts(tmp_path, loaded)
    after = {p.name: p.read_bytes() for p in posts_dir.glob("*.jsonl")}
    assert before == after

    # Scramble list order and reverse dict key order: output must be unaffected, since
    # ordering is fully re-derived (sort_keys for JSON, int(ts_id) for record order).
    scrambled = [
        {k: v for k, v in reversed(list(r.items()))} for r in reversed(load_posts(tmp_path))
    ]
    save_posts(tmp_path, scrambled)
    after2 = {p.name: p.read_bytes() for p in posts_dir.glob("*.jsonl")}
    assert before == after2


def test_save_posts_removes_month_files_that_become_empty(tmp_path):
    records = [
        make_post("100000000000000001", "2026-09-01T00:00:00Z"),
        make_post("200000000000000001", "2026-08-20T00:00:00Z"),
    ]
    save_posts(tmp_path, records)
    posts_dir = tmp_path / "posts"
    assert (posts_dir / "2026-08.jsonl").exists()
    assert (posts_dir / "2026-09.jsonl").exists()

    remaining = [r for r in load_posts(tmp_path) if r["ts_id"] != "200000000000000001"]
    save_posts(tmp_path, remaining)
    assert not (posts_dir / "2026-08.jsonl").exists()
    assert (posts_dir / "2026-09.jsonl").exists()


def test_save_posts_empty_list_removes_all_files(tmp_path):
    save_posts(tmp_path, [make_post("100000000000000001", "2026-09-01T00:00:00Z")])
    assert (tmp_path / "posts" / "2026-09.jsonl").exists()
    save_posts(tmp_path, [])
    assert list((tmp_path / "posts").glob("*.jsonl")) == []


def test_save_posts_moving_a_record_to_a_new_month_removes_old_file(tmp_path):
    save_posts(tmp_path, [make_post("100000000000000001", "2026-09-01T00:00:00Z")])
    posts_dir = tmp_path / "posts"
    assert (posts_dir / "2026-09.jsonl").exists()

    moved = load_posts(tmp_path)
    moved[0]["created_at_utc"] = "2026-10-01T00:00:00Z"
    save_posts(tmp_path, moved)

    assert not (posts_dir / "2026-09.jsonl").exists()
    assert (posts_dir / "2026-10.jsonl").exists()


def test_load_posts_empty_when_no_directory(tmp_path):
    assert load_posts(tmp_path) == []
    assert load_posts_index(tmp_path) == {}


def test_load_posts_index(tmp_path):
    save_posts(tmp_path, [make_post("100000000000000001", "2026-09-01T00:00:00Z", kind="reply")])
    index = load_posts_index(tmp_path)
    assert set(index.keys()) == {"100000000000000001"}
    assert index["100000000000000001"]["kind"] == "reply"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    save_posts(tmp_path, [make_post("100000000000000001", "2026-09-01T00:00:00Z")])
    save_state(tmp_path, {"version": 1, "sources": {}})
    save_posts(tmp_path, [make_post("100000000000000002", "2026-09-02T00:00:00Z")])
    assert list(tmp_path.rglob("*.tmp")) == []


# ---------------------------------------------------------------------------
# deletions.jsonl (append-only)
# ---------------------------------------------------------------------------


def test_append_and_load_deletions(tmp_path):
    event1 = {
        "ts_id": "100000000000000001",
        "detected_at": "2026-09-10T00:00:00Z",
        "deleted_lower": "2026-09-09T00:00:00Z",
        "deleted_upper": "2026-09-10T00:00:00Z",
        "source": "trumpstruth",
        "trumpstruth_removed_at": "2026-09-10T00:00:00Z",
        "run_id": "20260910T000000Z-0001",
    }
    event2 = dict(event1, ts_id="100000000000000002", source="api404", trumpstruth_removed_at=None)
    append_deletion(tmp_path, event1)
    append_deletion(tmp_path, event2)
    assert load_deletions(tmp_path) == [event1, event2]


def test_deletions_never_lose_rows_across_many_appends(tmp_path):
    events = [{"ts_id": str(i).zfill(18), "detected_at": "2026-09-10T00:00:00Z", "source": "trumpstruth"}
              for i in range(1, 21)]
    for event in events:
        append_deletion(tmp_path, event)
    loaded = load_deletions(tmp_path)
    assert len(loaded) == 20
    assert [e["ts_id"] for e in loaded] == [e["ts_id"] for e in events]


def test_append_deletion_uses_lf_line_endings(tmp_path):
    append_deletion(tmp_path, {"ts_id": "1", "detected_at": "2026-09-10T00:00:00Z", "source": "api404"})
    raw = (tmp_path / "deletions.jsonl").read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")


# ---------------------------------------------------------------------------
# engagement/YYYY-MM.csv (append-only)
# ---------------------------------------------------------------------------


def test_append_engagement_creates_header_once_and_blanks_none(tmp_path):
    row = make_engagement_row("100000000000000001", "2026-09-01T00:00:00Z", replies=5, reblogs=10, favourites=20)
    append_engagement(tmp_path, [row])
    path = tmp_path / "engagement" / "2026-09.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ENGAGEMENT_HEADER
    assert lines[1] == "2026-09-01T00:00:00Z,100000000000000001,api,5,10,20,,"

    append_engagement(tmp_path, [row])
    lines2 = path.read_text(encoding="utf-8").splitlines()
    assert lines2.count(ENGAGEMENT_HEADER) == 1
    assert len(lines2) == 3


def test_append_engagement_partitions_by_month(tmp_path):
    rows = [
        make_engagement_row("1", "2026-08-31T23:59:59Z", replies=1, reblogs=1, favourites=1),
        make_engagement_row("2", "2026-09-01T00:00:00Z", replies=2, reblogs=2, favourites=2),
    ]
    append_engagement(tmp_path, rows)
    eng_dir = tmp_path / "engagement"
    assert sorted(p.name for p in eng_dir.glob("*.csv")) == ["2026-08.csv", "2026-09.csv"]


def test_load_engagement_round_trip_with_blanks_as_none(tmp_path):
    rows = [make_engagement_row("100000000000000001", "2026-09-01T00:00:00Z", source="cnn", upvotes=3, downvotes=1)]
    append_engagement(tmp_path, rows)
    assert load_engagement(tmp_path) == rows


def test_engagement_never_loses_rows_across_many_appends(tmp_path):
    for i in range(15):
        append_engagement(
            tmp_path, [make_engagement_row("100000000000000001", "2026-09-01T00:%02d:00Z" % i, replies=i)]
        )
    loaded = load_engagement(tmp_path)
    assert len(loaded) == 15
    assert [r["replies"] for r in loaded] == list(range(15))


def test_append_engagement_uses_lf_line_endings(tmp_path):
    append_engagement(tmp_path, [make_engagement_row("1", "2026-09-01T00:00:00Z", replies=1)])
    raw = (tmp_path / "engagement" / "2026-09.csv").read_bytes()
    assert b"\r" not in raw


def test_latest_engagement_times(tmp_path):
    append_engagement(tmp_path, [
        make_engagement_row("A", "2026-09-01T00:00:00Z", replies=1),
        make_engagement_row("A", "2026-09-03T00:00:00Z", source="cnn", replies=2),
        make_engagement_row("B", "2026-09-02T00:00:00Z", replies=3),
    ])
    assert latest_engagement_times(tmp_path) == {"A": "2026-09-03T00:00:00Z", "B": "2026-09-02T00:00:00Z"}


# ---------------------------------------------------------------------------
# filter_engagement throttle (docs/SPEC.md section 3)
# ---------------------------------------------------------------------------


def test_filter_engagement_first_row_always_accepted(tmp_path):
    row = make_engagement_row("A", "2026-09-11T00:00:00Z", replies=1)
    assert filter_engagement(tmp_path, [row], {"A": "2026-09-10T00:00:00Z"}) == [row]


def test_filter_engagement_within_batch_throttle(tmp_path):
    post_created_at = {"A": "2026-09-10T00:00:00Z"}
    row1 = make_engagement_row("A", "2026-09-11T00:00:00Z", replies=1)
    too_soon = make_engagement_row("A", "2026-09-11T00:30:00Z", replies=2)
    ok_later = make_engagement_row("A", "2026-09-11T01:00:00Z", replies=3)
    result = filter_engagement(tmp_path, [row1, too_soon, ok_later], post_created_at)
    assert result == [row1, ok_later]


def test_filter_engagement_exactly_60_minutes_is_allowed(tmp_path):
    post_created_at = {"A": "2026-09-10T00:00:00Z"}
    row1 = make_engagement_row("A", "2026-09-11T00:00:00Z", replies=1)
    exactly_60 = make_engagement_row("A", "2026-09-11T01:00:00Z", replies=2)
    result = filter_engagement(tmp_path, [row1, exactly_60], post_created_at)
    assert result == [row1, exactly_60]


def test_filter_engagement_throttles_against_existing_rows_on_disk(tmp_path):
    post_created_at = {"A": "2026-09-10T00:00:00Z"}
    append_engagement(tmp_path, [make_engagement_row("A", "2026-09-11T00:00:00Z", replies=1)])

    too_soon = [make_engagement_row("A", "2026-09-11T00:45:00Z", source="cnn", replies=2)]
    assert filter_engagement(tmp_path, too_soon, post_created_at) == []

    later_enough = [make_engagement_row("A", "2026-09-11T01:15:00Z", source="cnn", replies=3)]
    assert filter_engagement(tmp_path, later_enough, post_created_at) == later_enough


def test_filter_engagement_old_post_gets_exactly_one_baseline_row(tmp_path):
    post_created_at = {"OLD": "2026-08-01T00:00:00Z"}  # 41 days before observation
    first = make_engagement_row("OLD", "2026-09-11T00:00:00Z", source="cnn", replies=1)
    much_later = make_engagement_row("OLD", "2027-09-11T00:00:00Z", source="cnn", replies=2)

    # Even a full year later (>> 60 minutes), the second row is skipped because one already
    # exists earlier in the same batch.
    result = filter_engagement(tmp_path, [first, much_later], post_created_at)
    assert result == [first]

    # And once that baseline row is actually on disk, a fresh call also yields nothing.
    append_engagement(tmp_path, [first])
    assert filter_engagement(tmp_path, [much_later], post_created_at) == []


def test_filter_engagement_old_post_threshold_boundary(tmp_path):
    # A is exactly 14 days old at observation time; B is one second younger.
    post_created_at = {"A": "2026-08-28T00:00:00Z", "B": "2026-08-28T00:00:01Z"}
    append_engagement(tmp_path, [
        make_engagement_row("A", "2026-09-01T00:00:00Z", replies=0),
        make_engagement_row("B", "2026-09-01T00:00:00Z", replies=0),
    ])
    at_14d = make_engagement_row("A", "2026-09-11T00:00:00Z", source="cnn", replies=1)
    under_14d = make_engagement_row("B", "2026-09-11T00:00:00Z", source="cnn", replies=1)

    result = filter_engagement(tmp_path, [at_14d, under_14d], post_created_at)
    # A: >=14 days old -> old-post rule -> already has a row (from Sep 1) -> skipped.
    # B: <14 days old -> normal 60-min rule -> existing row from Sep 1 is far enough back -> kept.
    assert result == [under_14d]


def test_filter_engagement_unknown_post_created_at_uses_normal_throttle(tmp_path):
    row1 = make_engagement_row("UNKNOWN", "2026-09-11T00:00:00Z", replies=1)
    too_soon = make_engagement_row("UNKNOWN", "2026-09-11T00:10:00Z", replies=2)
    assert filter_engagement(tmp_path, [row1, too_soon], {}) == [row1]


# ---------------------------------------------------------------------------
# runs/YYYY-MM.jsonl (append-only)
# ---------------------------------------------------------------------------


def make_run_row(run_id, started_at, **extra):
    row = {
        "run_id": run_id, "source": "trumpstruth", "started_at": started_at,
        "finished_at": started_at, "ok": True, "requests": 1, "new_posts": 0,
        "updated_posts": 0, "deletions_found": 0, "errors": 0, "notes": None,
    }
    row.update(extra)
    return row


def test_append_and_load_runs_partitioned_by_month(tmp_path):
    row1 = make_run_row("20260901T000000Z-0001", "2026-09-01T00:00:00Z")
    row2 = make_run_row("20260815T000000Z-0002", "2026-08-15T00:00:00Z")
    append_run(tmp_path, row1)
    append_run(tmp_path, row2)

    runs_dir = tmp_path / "runs"
    assert sorted(p.name for p in runs_dir.glob("*.jsonl")) == ["2026-08.jsonl", "2026-09.jsonl"]

    loaded = load_runs(tmp_path)
    assert len(loaded) == 2
    assert {r["run_id"] for r in loaded} == {row1["run_id"], row2["run_id"]}


def test_runs_never_lose_rows_across_many_appends(tmp_path):
    for i in range(10):
        append_run(tmp_path, make_run_row("run-%d" % i, "2026-09-01T00:%02d:00Z" % i, requests=i))
    loaded = load_runs(tmp_path)
    assert len(loaded) == 10
    assert [r["run_id"] for r in loaded] == ["run-%d" % i for i in range(10)]


# ---------------------------------------------------------------------------
# state.json
# ---------------------------------------------------------------------------


def test_load_state_defaults_when_missing(tmp_path):
    assert load_state(tmp_path) == {"version": 1, "sources": {}}


def test_save_state_round_trip_byte_identical(tmp_path):
    state = {
        "version": 1,
        "sources": {
            "trumpstruth": {
                "last_run_at": "2026-09-11T00:00:00Z", "last_ok_at": "2026-09-11T00:00:00Z",
                "processed_removed_ids": [1, 2, 3],
                "backfill": {"phase": "listing", "listing_cursor": None, "removed_cursor": None},
            },
            "cnn": {"last_run_at": None, "last_ok_at": None, "etag": None, "last_modified": None},
            "api": {
                "last_run_at": None, "last_ok_at": None, "reachable": True,
                "last_probe_status": 200, "last_probe_at": "2026-09-11T00:00:00Z", "statuses_count": 42,
            },
        },
    }
    save_state(tmp_path, state)
    path = tmp_path / "state.json"
    before = path.read_bytes()
    assert before.endswith(b"\n")
    assert b"\r" not in before

    loaded = load_state(tmp_path)
    assert loaded == state

    save_state(tmp_path, loaded)
    assert path.read_bytes() == before


def test_save_state_format_indent_and_sort_keys(tmp_path):
    save_state(tmp_path, {"version": 1, "sources": {"b": 1, "a": 2}})
    text = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert text.startswith("{\n")
    assert text.endswith("}\n")
    assert text.index('"a"') < text.index('"b"')
    assert "  " in text  # indent=2
