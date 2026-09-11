"""Tests for scripts/collect_archive.py (docs/SPEC.md section 8, cnn bullet)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import collect_archive as ca
from scripts import store
from scripts.common import Context, FakeClock, FakeTransport, Http, Response

FIXTURES = Path(__file__).parent / "fixtures"
UTC = timezone.utc
ARCHIVE_URL = ca.ARCHIVE_URL


def make_ctx(tmp_path, transport, state=None, run_id="run-0001", clock=None):
    clock = clock or FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))
    http = Http(transport, clock)
    return Context(http=http, clock=clock, data_root=tmp_path, state=state or {"version": 1, "sources": {}}, run_id=run_id)


def sample_bytes() -> bytes:
    return (FIXTURES / "cnn_archive_sample.json").read_bytes()


def test_skip_within_two_hours_of_last_ok(tmp_path):
    clock = FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))
    last_ok = (clock.now() - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {"version": 1, "sources": {"cnn": {"last_ok_at": last_ok, "etag": None, "last_modified": None}}}
    transport = FakeTransport({})  # no routes: any request would fail the test
    ctx = make_ctx(tmp_path, transport, state=state, clock=clock)

    row = ca.run(ctx)
    assert row["ok"] is True
    assert row["requests"] == 0
    assert row["notes"] == "skipped: ran 30 min ago"
    assert transport.calls == []


def test_force_bypasses_skip_window(tmp_path):
    clock = FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))
    last_ok = (clock.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {"version": 1, "sources": {"cnn": {"last_ok_at": last_ok, "etag": None, "last_modified": None}}}
    transport = FakeTransport({ARCHIVE_URL: Response(200, {}, b"[]")})
    ctx = make_ctx(tmp_path, transport, state=state, clock=clock)

    row = ca.run(ctx, force=True)
    assert row["ok"] is True
    assert len(transport.calls) == 1


def test_304_not_modified(tmp_path):
    state = {"version": 1, "sources": {"cnn": {"etag": 'W/"abc123"', "last_modified": None}}}
    transport = FakeTransport({ARCHIVE_URL: Response(304, {}, b"")})
    ctx = make_ctx(tmp_path, transport, state=state)

    row = ca.run(ctx)
    assert row["ok"] is True
    assert row["notes"] == "not modified"
    url, headers = transport.calls[0]
    assert headers["If-None-Match"] == 'W/"abc123"'

    saved = store.load_state(tmp_path)
    assert saved["sources"]["cnn"]["last_ok_at"] is not None
    assert store.load_posts(tmp_path) == []


def test_import_cnn_sample_420_posts_and_engagement_once(tmp_path):
    clock = FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))
    headers = {"ETag": 'W/"v1"', "Last-Modified": "Fri, 11 Sep 2026 01:19:51 GMT"}
    transport = FakeTransport({ARCHIVE_URL: [Response(200, headers, sample_bytes()), Response(200, headers, sample_bytes())]})
    ctx = make_ctx(tmp_path, transport, clock=clock)

    row = ca.run(ctx)
    assert row["ok"] is True
    assert row["new_posts"] == 420

    index = store.load_posts_index(tmp_path)
    assert len(index) == 420
    assert index["117238345561593751"]["kind"] == "reblog"
    assert index["117238345561593751"]["reblog_of_acct"] == "realDonaldTrump"

    saved = store.load_state(tmp_path)
    assert saved["sources"]["cnn"]["etag"] == 'W/"v1"'
    assert saved["sources"]["cnn"]["last_modified"] == "Fri, 11 Sep 2026 01:19:51 GMT"

    engagement_first = store.load_engagement(tmp_path)
    assert len(engagement_first) == 420

    # second run, forced, well within the hour -> filter_engagement throttles everything out
    row2 = ca.run(ctx, force=True)
    assert row2["ok"] is True
    engagement_second = store.load_engagement(tmp_path)
    assert len(engagement_second) == 420  # unchanged: no duplicate rows
