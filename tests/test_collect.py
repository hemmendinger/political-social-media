"""Tests for scripts/collect.py (docs/SPEC.md sections 8 and 12)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import collect as collect_mod
from scripts import store
from scripts.common import Context, FakeClock, FakeTransport, Http
from scripts.merge import merge_partial

UTC = timezone.utc


def make_ctx(tmp_path, run_id="run-1", clock=None):
    clock = clock or FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))
    http = Http(FakeTransport({}), clock)
    return Context(http=http, clock=clock, data_root=tmp_path, state={"version": 1, "sources": {}}, run_id=run_id)


def _fake_collector(name, calls, *, ok=True, new_posts=0, deletions_found=0, notes=None, save_post=None, raise_exc=None):
    def _run(ctx, **kwargs):
        calls.append(name)
        if raise_exc is not None:
            raise raise_exc
        if save_post is not None:
            store.save_posts(ctx.data_root, [save_post])
        row = {
            "run_id": ctx.run_id, "source": name, "started_at": ctx.now_iso(), "finished_at": ctx.now_iso(),
            "ok": ok, "requests": 1, "new_posts": new_posts, "updated_posts": 0,
            "deletions_found": deletions_found, "errors": 0, "notes": notes,
        }
        store.append_run(ctx.data_root, row)
        return row

    return _run


def make_post(ts_id="100000000000000001", created_at_utc="2026-09-10T00:00:00Z"):
    return merge_partial(
        None,
        {"ts_id": ts_id, "created_at_utc": created_at_utc, "kind": "original", "content_html": "<p>hi</p>",
         "media": [{"type": "image", "url": "http://x", "preview_url": None, "mirror_url": None,
                    "width": None, "height": None, "duration": None}]},
        source="api", observed_at=created_at_utc, run_id="seed",
    ).record


# ---------------------------------------------------------------------------
# run_all: ordering, aggregation, exit codes, source-failure isolation
# ---------------------------------------------------------------------------


def test_run_all_runs_sources_in_fixed_order_and_aggregates_summary(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(collect_mod.collect_trumpstruth, "run", _fake_collector("trumpstruth", calls, new_posts=5, deletions_found=1))
    monkeypatch.setattr(collect_mod.collect_archive, "run", _fake_collector("cnn", calls, new_posts=3))
    monkeypatch.setattr(collect_mod.collect_api, "run", _fake_collector("api", calls, new_posts=2, deletions_found=2))

    ctx = make_ctx(tmp_path)
    exit_code, summary = collect_mod.run_all(ctx, ["api", "trumpstruth", "cnn"], output_dir=tmp_path / "output", no_export=True)

    assert calls == ["trumpstruth", "cnn", "api"]  # fixed order, regardless of the `sources` argument's order
    assert exit_code == 0
    assert summary == "collect: +10 posts, +3 deletions, checks ok"
    assert (tmp_path / "output" / "checks.json").exists()


def test_run_all_source_selection_filters_but_keeps_order(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(collect_mod.collect_trumpstruth, "run", _fake_collector("trumpstruth", calls))
    monkeypatch.setattr(collect_mod.collect_archive, "run", _fake_collector("cnn", calls))
    monkeypatch.setattr(collect_mod.collect_api, "run", _fake_collector("api", calls))

    ctx = make_ctx(tmp_path)
    collect_mod.run_all(ctx, ["api", "trumpstruth"], output_dir=tmp_path / "output", no_export=True)
    assert calls == ["trumpstruth", "api"]


def test_run_all_isolates_one_source_failure_and_continues(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(collect_mod.collect_trumpstruth, "run", _fake_collector("trumpstruth", calls, new_posts=1))
    monkeypatch.setattr(collect_mod.collect_archive, "run", _fake_collector("cnn", calls, raise_exc=RuntimeError("boom")))
    monkeypatch.setattr(collect_mod.collect_api, "run", _fake_collector("api", calls, new_posts=1))

    ctx = make_ctx(tmp_path)
    exit_code, summary = collect_mod.run_all(ctx, ["trumpstruth", "cnn", "api"], output_dir=tmp_path / "output", no_export=True)

    assert calls == ["trumpstruth", "cnn", "api"]  # api still ran despite cnn's exception
    assert exit_code == 1
    assert "checks ok" in summary

    runs = store.load_runs(tmp_path)
    cnn_row = next(r for r in runs if r["source"] == "cnn")
    assert cnn_row["ok"] is False
    assert "boom" in cnn_row["notes"]


def test_run_all_exit_code_2_on_hard_check_failure_even_without_collector_failure(tmp_path, monkeypatch):
    # a corrupt posts file (unparseable timestamp) makes check_data report a hard failure even though
    # every collector itself "succeeds".
    bad = make_post()
    bad["created_at_utc"] = "not-a-timestamp"
    posts_dir = tmp_path / "posts"
    posts_dir.mkdir(parents=True)
    (posts_dir / "2026-09.jsonl").write_text(json.dumps(bad, sort_keys=True) + "\n", encoding="utf-8")

    calls = []
    monkeypatch.setattr(collect_mod.collect_trumpstruth, "run", _fake_collector("trumpstruth", calls))
    monkeypatch.setattr(collect_mod.collect_archive, "run", _fake_collector("cnn", calls))
    monkeypatch.setattr(collect_mod.collect_api, "run", _fake_collector("api", calls))

    ctx = make_ctx(tmp_path)
    exit_code, summary = collect_mod.run_all(ctx, ["trumpstruth", "cnn", "api"], output_dir=tmp_path / "output", no_export=True)
    assert exit_code == 2
    assert summary.endswith("checks FAILED")


# ---------------------------------------------------------------------------
# lock file semantics
# ---------------------------------------------------------------------------


def test_lock_acquire_blocks_second_caller_then_releases(tmp_path):
    lock = tmp_path / "data" / ".lock"
    assert collect_mod.acquire_lock(lock) is True
    assert lock.exists()
    assert collect_mod.acquire_lock(lock) is False
    collect_mod.release_lock(lock)
    assert not lock.exists()
    assert collect_mod.acquire_lock(lock) is True


def test_stale_lock_older_than_30_minutes_is_ignored(tmp_path):
    lock = tmp_path / "data" / ".lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999", encoding="utf-8")
    old = time.time() - 31 * 60
    os.utime(lock, (old, old))
    assert collect_mod.acquire_lock(lock) is True


def test_fresh_lock_under_30_minutes_is_respected(tmp_path):
    lock = tmp_path / "data" / ".lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999", encoding="utf-8")
    recent = time.time() - 10 * 60
    os.utime(lock, (recent, recent))
    assert collect_mod.acquire_lock(lock) is False


# ---------------------------------------------------------------------------
# exports: sqlite rebuild, posts.csv columns, metrics.json
# ---------------------------------------------------------------------------


def test_write_exports_produces_sqlite_posts_csv_and_metrics(tmp_path):
    store.save_posts(tmp_path, [make_post()])
    clock = FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))
    ctx = make_ctx(tmp_path, clock=clock)
    output_dir = tmp_path / "output"

    collect_mod.write_exports(ctx, output_dir)

    assert (tmp_path / "truths.sqlite").exists()

    csv_bytes = (output_dir / "posts.csv").read_bytes()
    assert b"\r" not in csv_bytes
    csv_text = csv_bytes.decode("utf-8")
    header = csv_text.splitlines()[0].split(",")
    assert header == collect_mod.POSTS_CSV_COLUMNS
    assert "100000000000000001" in csv_text
    assert ",1,image," in csv_text  # media_count=1, media_types="image"

    metrics_data = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert "window" in metrics_data
    assert "trailing" in metrics_data
    assert "meta" in metrics_data


def test_run_all_end_to_end_with_exports(tmp_path, monkeypatch):
    calls = []
    post = make_post()
    monkeypatch.setattr(
        collect_mod.collect_trumpstruth, "run",
        _fake_collector("trumpstruth", calls, new_posts=1, save_post=post),
    )
    monkeypatch.setattr(collect_mod.collect_archive, "run", _fake_collector("cnn", calls))
    monkeypatch.setattr(collect_mod.collect_api, "run", _fake_collector("api", calls))

    ctx = make_ctx(tmp_path)
    output_dir = tmp_path / "output"
    exit_code, summary = collect_mod.run_all(ctx, ["trumpstruth", "cnn", "api"], output_dir=output_dir, no_export=False)

    assert exit_code == 0
    assert summary == "collect: +1 posts, +0 deletions, checks ok"
    assert (tmp_path / "truths.sqlite").exists()
    assert (output_dir / "posts.csv").exists()
    assert (output_dir / "metrics.json").exists()
    assert (output_dir / "checks.json").exists()


# ---------------------------------------------------------------------------
# CLI: summary file
# ---------------------------------------------------------------------------


def test_main_writes_summary_file_and_returns_exit_code(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(collect_mod.collect_trumpstruth, "run", _fake_collector("trumpstruth", calls))
    monkeypatch.setattr(collect_mod.collect_archive, "run", _fake_collector("cnn", calls))
    monkeypatch.setattr(collect_mod.collect_api, "run", _fake_collector("api", calls))

    def fake_run_all(ctx, sources, **kwargs):
        return 0, "collect: +0 posts, +0 deletions, checks ok"

    monkeypatch.setattr(collect_mod, "run_all", fake_run_all)

    data_root = tmp_path / "data"
    summary_file = tmp_path / "summary.txt"
    code = collect_mod.main(
        ["--data-root", str(data_root), "--output-dir", str(tmp_path / "output"), "--summary-file", str(summary_file)]
    )
    assert code == 0
    assert summary_file.read_text(encoding="utf-8") == "collect: +0 posts, +0 deletions, checks ok\n"
    assert not (data_root / ".lock").exists()  # released
