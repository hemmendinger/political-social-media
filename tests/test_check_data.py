"""Tests for scripts/check_data.py (docs/SPEC.md section 9)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from scripts import check_data as cd
from scripts import store
from scripts.merge import merge_partial

NOW = "2026-09-11T12:00:00Z"


def make_record(ts_id, created_at_utc, source="api", **extra):
    partial = {"ts_id": ts_id, "created_at_utc": created_at_utc, "kind": "original", "content_html": "<p>hi</p>"}
    partial.update(extra)
    return merge_partial(None, partial, source=source, observed_at=created_at_utc, run_id="seed").record


def _write_line(path: Path, record) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def _valid_dataset(tmp_path):
    """Two present posts plus one properly-bounded deleted post, a well-spaced engagement pair, one run row."""
    r1 = make_record("100000000000000001", "2026-08-15T00:00:00Z")
    r2 = make_record("100000000000000002", "2026-09-01T00:00:00Z")
    base3 = merge_partial(
        None, {"ts_id": "100000000000000003", "created_at_utc": "2026-09-02T00:00:00Z", "kind": "original"},
        source="api", observed_at="2026-09-02T00:00:05Z", run_id="seed",
    ).record
    del3 = merge_partial(
        base3, {"ts_id": "100000000000000003", "api_404": True}, source="api", observed_at="2026-09-03T00:00:00Z",
        run_id="seed2",
    )
    store.save_posts(tmp_path, [r1, r2, del3.record])
    store.append_deletion(tmp_path, del3.deletion_event)
    store.append_engagement(
        tmp_path,
        [
            {"observed_at": "2026-09-01T00:00:00Z", "ts_id": "100000000000000002", "source": "api",
             "replies": 1, "reblogs": 1, "favourites": 1, "upvotes": None, "downvotes": None},
            {"observed_at": "2026-09-01T02:00:00Z", "ts_id": "100000000000000002", "source": "api",
             "replies": 2, "reblogs": 2, "favourites": 2, "upvotes": None, "downvotes": None},
        ],
    )
    store.append_run(
        tmp_path,
        {"run_id": "run-1", "source": "api", "started_at": "2026-09-01T00:00:00Z",
         "finished_at": "2026-09-01T00:01:00Z", "ok": True, "requests": 1, "new_posts": 3, "updated_posts": 0,
         "deletions_found": 1, "errors": 0, "notes": None},
    )
    return ["100000000000000001", "100000000000000002", "100000000000000003"]


# ---------------------------------------------------------------------------
# passing dataset
# ---------------------------------------------------------------------------


def test_passing_dataset_has_no_hard_failures(tmp_path):
    _valid_dataset(tmp_path)
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["hard"] == []
    assert result["ok"] is True
    assert result["stats"]["posts"] == 3
    assert result["stats"]["deletions"] == 1
    assert result["stats"]["engagement_rows"] == 2
    assert result["stats"]["by_status"] == {"present": 2, "deleted": 1}


def test_run_id_check_passes_when_row_exists(tmp_path):
    _valid_dataset(tmp_path)
    result = cd.run_checks(tmp_path, run_id="run-1", now=NOW)
    assert result["ok"] is True


def test_run_id_check_fails_when_row_missing(tmp_path):
    _valid_dataset(tmp_path)
    result = cd.run_checks(tmp_path, run_id="run-does-not-exist", now=NOW)
    assert result["ok"] is False
    assert any(h.startswith("missing_run_row:run-does-not-exist") for h in result["hard"])


# ---------------------------------------------------------------------------
# hard checks: one failing case each
# ---------------------------------------------------------------------------


def test_hard_duplicate_id_across_months(tmp_path):
    ids = _valid_dataset(tmp_path)
    rec = store.load_posts_index(tmp_path)[ids[0]]
    path = tmp_path / "posts" / (store.month_of(rec["created_at_utc"]) + ".jsonl")
    _write_line(path, rec)  # same id appended a second time
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["ok"] is False
    assert any(h.startswith("duplicate_id:%s" % ids[0]) for h in result["hard"])


def test_hard_wrong_month_file(tmp_path):
    _valid_dataset(tmp_path)
    rec = make_record("100000000000000099", "2026-09-05T00:00:00Z")  # belongs in 2026-09.jsonl
    _write_line(tmp_path / "posts" / "2026-08.jsonl", rec)  # placed in the wrong file instead
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["ok"] is False
    assert any(h.startswith("wrong_month_file:100000000000000099") for h in result["hard"])


def test_hard_unsorted_file(tmp_path):
    r1 = make_record("100000000000000005", "2026-09-01T00:00:00Z")
    r2 = make_record("100000000000000002", "2026-09-02T00:00:00Z")
    path = tmp_path / "posts" / "2026-09.jsonl"
    _write_line(path, r1)
    _write_line(path, r2)  # smaller ts_id written after the larger one
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["ok"] is False
    assert any(h.startswith("unsorted_file:2026-09") for h in result["hard"])


def test_hard_bad_timestamp(tmp_path):
    rec = make_record("100000000000000006", "2026-09-01T00:00:00Z")
    rec["created_at_utc"] = "not-a-timestamp"
    _write_line(tmp_path / "posts" / "2026-09.jsonl", rec)
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["ok"] is False
    assert any(h.startswith("bad_timestamp:100000000000000006:created_at_utc") for h in result["hard"])


def test_hard_deletion_references_unknown_post(tmp_path):
    _valid_dataset(tmp_path)
    store.append_deletion(
        tmp_path,
        {"ts_id": "999999999999999999", "detected_at": "2026-09-05T00:00:00Z", "deleted_lower": None,
         "deleted_upper": "2026-09-05T00:00:00Z", "source": "api404", "trumpstruth_removed_at": None,
         "run_id": "run-x"},
    )
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["ok"] is False
    assert any("deletion_unknown_post:999999999999999999" in h for h in result["hard"])


def test_hard_engagement_rows_within_60_minutes(tmp_path):
    ids = _valid_dataset(tmp_path)
    store.append_engagement(
        tmp_path,
        [
            {"observed_at": "2026-09-06T00:00:00Z", "ts_id": ids[0], "source": "api",
             "replies": 1, "reblogs": None, "favourites": None, "upvotes": None, "downvotes": None},
            {"observed_at": "2026-09-06T00:30:00Z", "ts_id": ids[0], "source": "cnn",
             "replies": 2, "reblogs": None, "favourites": None, "upvotes": None, "downvotes": None},
        ],
    )
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["ok"] is False
    assert any(h.startswith("engagement_too_close:%s" % ids[0]) for h in result["hard"])


def test_hard_created_at_after_deleted_upper(tmp_path):
    base = merge_partial(
        None, {"ts_id": "100000000000000007", "created_at_utc": "2026-09-05T00:00:00Z", "kind": "original"},
        source="api", observed_at="2026-09-05T00:00:05Z", run_id="seed",
    ).record
    deleted = merge_partial(
        base, {"ts_id": "100000000000000007", "api_404": True}, source="api", observed_at="2026-09-04T00:00:00Z",
        run_id="seed2",
    ).record
    store.save_posts(tmp_path, [deleted])
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["ok"] is False
    assert any(h.startswith("created_after_deleted_upper:100000000000000007") for h in result["hard"])


# ---------------------------------------------------------------------------
# soft checks
# ---------------------------------------------------------------------------


def test_soft_inverted_deletion_bounds(tmp_path):
    base = merge_partial(
        None, {"ts_id": "100000000000000008", "created_at_utc": "2026-09-01T00:00:00Z", "kind": "original"},
        source="api", observed_at="2026-09-05T00:00:00Z", run_id="seed",
    ).record
    deleted = merge_partial(
        base, {"ts_id": "100000000000000008", "api_404": True}, source="api", observed_at="2026-09-03T00:00:00Z",
        run_id="seed2",
    ).record
    assert deleted["deleted_lower"] > deleted["deleted_upper"]
    store.save_posts(tmp_path, [deleted])
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["ok"] is True  # soft only
    assert any(h.startswith("inverted_deletion_bounds:100000000000000008") for h in result["soft"])


def test_soft_statuses_count_drift_beyond_tolerance(tmp_path):
    _valid_dataset(tmp_path)  # present_count == 2
    result = cd.run_checks(tmp_path, api_statuses_count=200, now=NOW)
    assert result["ok"] is True
    assert result["stats"]["present_vs_api_statuses_count"]["diff"] == 198
    assert any(h.startswith("present_count_drift") for h in result["soft"])


def test_soft_single_source_recent_posts(tmp_path):
    _valid_dataset(tmp_path)
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["stats"]["single_source_recent_posts"]["count"] == 3
    assert any(h.startswith("single_source_recent_posts:") for h in result["soft"])


def test_single_source_posts_older_than_30_days_are_not_flagged(tmp_path):
    store.save_posts(tmp_path, [make_record("100000000000000009", "2026-06-01T00:00:00Z")])
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["stats"]["single_source_recent_posts"]["count"] == 0


def test_soft_stale_newest_post(tmp_path):
    _valid_dataset(tmp_path)  # newest post is 2026-09-02, `now` is 2026-09-11 -> definitely stale
    result = cd.run_checks(tmp_path, now=NOW)
    assert any(h.startswith("stale_newest_post:") for h in result["soft"])


def test_soft_spike_day(tmp_path):
    records = []
    start = date(2026, 7, 1)
    n = 1
    for i in range(28):
        d = start + timedelta(days=i)
        records.append(make_record("1%017d" % n, "%sT12:00:00Z" % d.isoformat()))
        n += 1
    spike_date = start + timedelta(days=28)
    for i in range(25):  # 25 posts: above the 20-post floor and 25x the trailing median of 1
        records.append(make_record("1%017d" % n, "%sT12:%02d:00Z" % (spike_date.isoformat(), i * 2)))
        n += 1
    store.save_posts(tmp_path, records)
    result = cd.run_checks(tmp_path, now="2026-09-11T12:00:00Z")
    assert result["ok"] is True
    spikes = result["stats"]["spike_days"]
    assert any(s["et_date"] == spike_date.isoformat() and s["count"] == 25 for s in spikes)
    assert any(h.startswith("spike_days:") for h in result["soft"])


def test_soft_cnn_ambiguous_handles(tmp_path):
    rec = merge_partial(
        None,
        {"ts_id": "100000000000000009", "created_at_utc": "2026-09-01T00:00:00Z", "kind": "reblog",
         "content_text": "Hello world reposted"},
        source="cnn", observed_at="2026-09-01T00:00:05Z", run_id="seed",
    ).record
    rec["reblog_of_acct"] = "MichaelCohen212"
    rec["field_sources"]["reblog_of_acct"] = "cnn"
    store.save_posts(tmp_path, [rec])
    result = cd.run_checks(tmp_path, now=NOW)
    assert result["ok"] is True
    assert result["stats"]["cnn_ambiguous_handles"] == {"count": 1, "sample_ids": ["100000000000000009"]}
    assert not any(h.startswith("cnn_ambiguous_handles:") for h in result["soft"])  # stats only, not an anomaly


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_checks_json_and_exits_0_when_clean(tmp_path):
    _valid_dataset(tmp_path)
    output = tmp_path / "out" / "checks.json"
    code = cd.main(["--data-root", str(tmp_path), "--output", str(output)])
    assert code == 0
    assert output.exists()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["ok"] is True
    assert output.read_text(encoding="utf-8").startswith("{\n")


def test_cli_exits_2_on_hard_failure(tmp_path):
    rec = make_record("100000000000000006", "2026-09-01T00:00:00Z")
    rec["created_at_utc"] = "not-a-timestamp"
    _write_line(tmp_path / "posts" / "2026-09.jsonl", rec)
    output = tmp_path / "out" / "checks.json"
    code = cd.main(["--data-root", str(tmp_path), "--output", str(output)])
    assert code == 2
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["ok"] is False


def test_spike_day_below_the_absolute_floor_is_not_flagged(tmp_path):
    records = []
    start = date(2026, 7, 1)
    n = 1
    for i in range(28):
        records.append(make_record("1%017d" % n, "%sT12:00:00Z" % (start + timedelta(days=i)).isoformat()))
        n += 1
    spike_date = start + timedelta(days=28)
    for i in range(6):  # 6x the median but only 6 posts
        records.append(make_record("1%017d" % n, "%sT12:%02d:00Z" % (spike_date.isoformat(), i * 5)))
        n += 1
    store.save_posts(tmp_path, records)
    result = cd.run_checks(tmp_path, now="2026-09-11T12:00:00Z")
    assert result["stats"]["spike_days"] == []
