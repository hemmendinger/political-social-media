"""Tests for scripts/collect_api.py (docs/SPEC.md section 8, api bullet)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import collect_api as capi
from scripts import store
from scripts.common import Context, FakeClock, FakeTransport, Http, Response, TransportError
from scripts.merge import merge_partial

FIXTURES = Path(__file__).parent / "fixtures"
UTC = timezone.utc
STATUSES_URL = capi.STATUSES_URL


def make_ctx(tmp_path, transport, state=None, run_id="run-0001", clock=None, max_attempts=4):
    clock = clock or FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))
    http = Http(transport, clock, max_attempts=max_attempts)
    return Context(http=http, clock=clock, data_root=tmp_path, state=state or {"version": 1, "sources": {}}, run_id=run_id)


def load_statuses() -> List[Dict[str, Any]]:
    return json.loads((FIXTURES / "api_statuses_2026-09-04_to_09-11.json").read_text(encoding="utf-8"))


def json_response(obj: Any, status: int = 200) -> Response:
    return Response(status, {}, json.dumps(obj).encode("utf-8"))


def seed_present_post(tmp_path, ts_id, created_at_utc, last_verified_live_at):
    r1 = merge_partial(
        None, {"ts_id": ts_id, "created_at_utc": created_at_utc, "kind": "original", "content_html": "<p>seed</p>"},
        source="api", observed_at=last_verified_live_at, run_id="seed",
    )
    store.save_posts(tmp_path, [r1.record])


class AlwaysFailTransport:
    """Always raises TransportError -- exercises Http's TransportError retry/reraise path."""

    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=30.0):
        self.calls.append((url, dict(headers or {})))
        raise TransportError("connection reset")


# ---------------------------------------------------------------------------
# probe / reachability
# ---------------------------------------------------------------------------


def test_probe_403_marks_unreachable_and_touches_no_posts(tmp_path):
    transport = FakeTransport({STATUSES_URL: Response(403, {}, b"blocked")})
    ctx = make_ctx(tmp_path, transport)  # no fallback_transport configured -> 403 is returned, not raised

    row = capi.run(ctx)
    assert row["ok"] is True
    assert row["notes"] == "unreachable: 403"

    saved = store.load_state(tmp_path)
    assert saved["sources"]["api"]["reachable"] is False
    assert saved["sources"]["api"]["last_probe_status"] == 403
    assert store.load_posts(tmp_path) == []


def test_probe_429_exhausts_retries_marks_unreachable(tmp_path):
    responses = [Response(429, {}, b"") for _ in range(2)]
    transport = FakeTransport({STATUSES_URL: responses})
    ctx = make_ctx(tmp_path, transport, max_attempts=2)

    row = capi.run(ctx)
    assert row["ok"] is True
    assert row["notes"] == "unreachable: 429"
    saved = store.load_state(tmp_path)
    assert saved["sources"]["api"]["reachable"] is False
    assert saved["sources"]["api"]["last_probe_status"] == 429
    assert store.load_posts(tmp_path) == []


def test_probe_transport_error_marks_unreachable(tmp_path):
    transport = AlwaysFailTransport()
    ctx = make_ctx(tmp_path, transport, max_attempts=2)

    row = capi.run(ctx)
    assert row["ok"] is True
    assert row["notes"] == "unreachable: transport_error"
    saved = store.load_state(tmp_path)
    assert saved["sources"]["api"]["reachable"] is False
    assert saved["sources"]["api"]["last_probe_status"] is None
    assert store.load_posts(tmp_path) == []


# ---------------------------------------------------------------------------
# success path: pagination, merging, statuses_count, engagement
# ---------------------------------------------------------------------------


def test_success_pagination_all_180_statuses_merged(tmp_path):
    statuses = load_statuses()
    ids = [s["id"] for s in statuses]
    routes = {STATUSES_URL: json_response(statuses[0:20])}
    for i in range(20, 180, 20):
        max_id = ids[i - 1]
        routes[STATUSES_URL + "&max_id=" + max_id] = json_response(statuses[i : i + 20])
    transport = FakeTransport(routes)
    ctx = make_ctx(tmp_path, transport)

    row = capi.run(ctx, max_pages=9)
    assert row["ok"] is True
    assert row["new_posts"] == 180

    index = store.load_posts_index(tmp_path)
    assert len(index) == 180
    assert set(index.keys()) == set(ids)

    saved = store.load_state(tmp_path)
    assert saved["sources"]["api"]["statuses_count"] == 36549
    assert saved["sources"]["api"]["reachable"] is True

    engagement = store.load_engagement(tmp_path)
    assert len(engagement) == 180
    assert all(row["source"] == "api" for row in engagement)


def test_pagination_stops_when_a_page_has_only_known_ids(tmp_path):
    statuses = load_statuses()
    first_20 = statuses[0:20]
    ids = [s["id"] for s in first_20]

    # Seed the index with exactly those 20 ids already present, via a real run of the merge layer.
    seeded = []
    for obj in first_20:
        from scripts.parsers import api_status_to_partial

        partial = api_status_to_partial(obj)
        seeded.append(merge_partial(None, partial, source="api", observed_at="2026-09-01T00:00:00Z", run_id="seed").record)
    store.save_posts(tmp_path, seeded)

    # No route beyond page 0 is provided: if the collector tried to fetch a second page, the test would
    # fail with FakeTransport's "no route matches" error instead of a plain assertion failure.
    transport = FakeTransport({STATUSES_URL: json_response(first_20)})
    ctx = make_ctx(tmp_path, transport)

    row = capi.run(ctx, max_pages=9)
    assert row["ok"] is True
    assert row["new_posts"] == 0
    assert row["updated_posts"] == 20  # the all-known page is merged (fresh live sighting), then pagination stops
    assert len(transport.calls) == 1
    assert len(store.load_posts_index(tmp_path)) == 20


# ---------------------------------------------------------------------------
# deletion candidates
# ---------------------------------------------------------------------------


def test_deletion_candidate_verified_404_marks_deleted(tmp_path):
    statuses = load_statuses()
    page0 = statuses[0:20]  # spans 2026-09-10T12:01:27Z .. 2026-09-11T01:19:51Z
    missing_ts_id = "199999999999999999"
    seed_present_post(tmp_path, missing_ts_id, "2026-09-10T12:30:00Z", "2026-09-10T13:00:00Z")

    routes = {
        STATUSES_URL: json_response(page0),
        capi.STATUS_URL_FMT % missing_ts_id: Response(404, {}, (FIXTURES / "api_status_404.json").read_bytes()),
    }
    transport = FakeTransport(routes)
    ctx = make_ctx(tmp_path, transport)

    row = capi.run(ctx, max_pages=1, max_verify=3)
    assert row["ok"] is True
    assert row["deletions_found"] == 1

    index = store.load_posts_index(tmp_path)
    rec = index[missing_ts_id]
    assert rec["status"] == "deleted"
    assert rec["deleted_source"] == "api404"
    assert rec["deleted_lower"] == "2026-09-10T13:00:00Z"
    assert rec["deleted_upper"] is not None

    deletions = store.load_deletions(tmp_path)
    assert len(deletions) == 1
    assert deletions[0]["ts_id"] == missing_ts_id
    assert deletions[0]["source"] == "api"


def test_deletion_candidate_verified_200_stays_present(tmp_path):
    statuses = load_statuses()
    page0 = statuses[0:20]
    missing_ts_id = "199999999999999999"
    seed_present_post(tmp_path, missing_ts_id, "2026-09-10T12:30:00Z", "2026-09-10T13:00:00Z")

    live_obj = dict(statuses[0])
    live_obj["id"] = missing_ts_id
    live_obj["created_at"] = "2026-09-10T12:30:00.000Z"

    routes = {
        STATUSES_URL: json_response(page0),
        capi.STATUS_URL_FMT % missing_ts_id: json_response(live_obj),
    }
    transport = FakeTransport(routes)
    ctx = make_ctx(tmp_path, transport)

    row = capi.run(ctx, max_pages=1, max_verify=3)
    assert row["ok"] is True
    assert row["deletions_found"] == 0

    index = store.load_posts_index(tmp_path)
    rec = index[missing_ts_id]
    assert rec["status"] == "present"
    assert rec["last_verified_live_at"] > "2026-09-10T13:00:00Z"
    assert store.load_deletions(tmp_path) == []


def test_page_with_only_known_ids_is_still_merged_before_stopping(tmp_path):
    statuses = load_statuses()
    page1 = statuses[:20]
    records = []
    for obj in page1:
        r = merge_partial(
            None, {"ts_id": obj["id"], "created_at_utc": obj["created_at"], "kind": "original", "content_text": "x"},
            source="cnn", observed_at="2026-09-11T10:00:00Z", run_id="seed",
        )
        records.append(r.record)
    store.save_posts(tmp_path, records)
    transport = FakeTransport({STATUSES_URL: json_response(page1)})
    ctx = make_ctx(tmp_path, transport)

    row = capi.run(ctx)

    assert row["ok"] is True
    assert row["requests"] == 1  # the all-known page ends pagination ...
    assert row["updated_posts"] == 20  # ... but is merged first
    index = store.load_posts_index(tmp_path)
    for obj in page1:
        rec = index[obj["id"]]
        assert rec["last_verified_live_at"] == "2026-09-11T12:00:00Z"
        assert "api" in rec["seen_sources"]
    assert len(store.load_engagement(tmp_path)) == 20


def test_recently_unreachable_api_is_skipped_without_requests(tmp_path):
    state = {"version": 1, "sources": {"api": {"reachable": False, "last_probe_at": "2026-09-11T10:00:00Z"}}}
    transport = FakeTransport({})  # any request would fail the test with "no route"
    ctx = make_ctx(tmp_path, transport, state=state)
    row = capi.run(ctx)
    assert row["ok"] is True
    assert row["requests"] == 0
    assert row["notes"].startswith("skipped: unreachable")


def test_unreachable_api_is_reprobed_after_six_hours(tmp_path):
    state = {"version": 1, "sources": {"api": {"reachable": False, "last_probe_at": "2026-09-11T02:00:00Z"}}}
    transport = FakeTransport({STATUSES_URL: Response(403, {}, b"blocked")})
    ctx = make_ctx(tmp_path, transport, state=state)
    row = capi.run(ctx)
    assert row["notes"] == "unreachable: 403"
    assert store.load_state(tmp_path)["sources"]["api"]["last_probe_at"] == "2026-09-11T12:00:00Z"
