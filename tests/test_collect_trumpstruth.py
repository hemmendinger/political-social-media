"""Tests for scripts/collect_trumpstruth.py (docs/SPEC.md section 8, trumpstruth bullet).

Network is always a FakeTransport; time is always a FakeClock pinned to 2026-09-11T12:00:00Z (America/New_York
is on EDT then, so "today" in ET is also 2026-09-11) so the removed-search date window lines up with the
real captured fixtures.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import collect_trumpstruth as ct
from scripts import store
from scripts.common import Context, FakeClock, FakeTransport, Http, Response
from scripts.parsers import ParseError

FIXTURES = Path(__file__).parent / "fixtures"
UTC = timezone.utc

LISTING_URL = "https://www.trumpstruth.org/?sort=desc&per_page=100&removed=include"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_response(name: str, status: int = 200) -> Response:
    return Response(status, {}, fixture_text(name).encode("utf-8"))


def status_url(trumpstruth_id: int) -> str:
    return "https://www.trumpstruth.org/statuses/%d" % trumpstruth_id


def make_ctx(tmp_path, transport, state=None, run_id="run-0001", clock=None):
    clock = clock or FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))
    http = Http(transport, clock)
    return Context(http=http, clock=clock, data_root=tmp_path, state=state or {"version": 1, "sources": {}}, run_id=run_id)


def _synthetic_card(tid: int, handle: str = "realDonaldTrump") -> str:
    ts_id = "1%017d" % tid
    dt = "2026-01-01T00:00:00+00:00"
    return (
        '<div class="status" data-status-url="https://www.trumpstruth.org/statuses/%d">'
        '<a class="status-info__meta-item">@%s</a>'
        '<time datetime="%s"></time>'
        '<a href="https://truthsocial.com/@%s/%s" class="status__external-link">link</a>'
        '<div class="status__content"><p>Post %d</p></div>'
        "</div>"
    ) % (tid, handle, dt, handle, ts_id, tid)


def _synthetic_listing_html(ids, next_link=None) -> str:
    cards = "".join(_synthetic_card(tid) for tid in ids)
    extra = ('<a href="%s">Next Page</a>' % next_link) if next_link else ""
    return '<html><body><div class="statuses">%s</div>%s</body></html>' % (cards, extra)


# ---------------------------------------------------------------------------
# (a) listing page 1 + (b) sequential resolution + (c) removed search
# ---------------------------------------------------------------------------


def test_listing_resolution_and_removed_search_full_run(tmp_path):
    routes = {
        LISTING_URL: fixture_response("trumpstruth_listing_page1.html"),
        status_url(41686): fixture_response("trumpstruth_status_41686_original_video.html"),
        status_url(41687): Response(404, {}, b"not found"),
        status_url(41688): Response(404, {}, b"not found"),
        status_url(41649): fixture_response("trumpstruth_status_41649_removed_reblog.html"),
        status_url(41646): fixture_response("trumpstruth_status_41646_removed_reblog.html"),
        status_url(41644): fixture_response("trumpstruth_status_41644_removed_reblog.html"),
        status_url(41641): fixture_response("trumpstruth_status_41641_removed_reblog.html"),
        (lambda url: "start_date=2026-09-07" in url and "end_date=2026-09-11" in url): fixture_response(
            "trumpstruth_search_removed_2026-09-07_to_11.html"
        ),
    }
    transport = FakeTransport(routes)
    state = {"version": 1, "sources": {"trumpstruth": {"max_trumpstruth_id": 41685}}}
    clock = FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))
    ctx = make_ctx(tmp_path, transport, state=state, run_id="run-0001", clock=clock)

    row = ct.run(ctx, removed_days=4)

    assert row["ok"] is True
    assert row["source"] == "trumpstruth"

    saved_state = store.load_state(tmp_path)
    src = saved_state["sources"]["trumpstruth"]
    assert src["max_trumpstruth_id"] == 41686

    index = store.load_posts_index(tmp_path)
    card = index["117247527370149354"]
    assert card["kind"] == "original"
    assert card["content_html"] != ""
    assert len(card["media"]) == 1
    assert card["media"][0]["type"] == "video"

    # (c): the four removed results, processed in the order the search fixture lists them
    # (41649, 41646, 41644, 41641 -- descending, sort=date_desc), each fetched, merged as removed, and
    # logged as a deletion event exactly once.
    removed_ts_ids = {
        41641: "117238301772357460",
        41644: "117238326295991805",
        41646: "117238345561593751",
        41649: "117238414290995787",
    }
    for tsid in removed_ts_ids.values():
        rec = index[tsid]
        assert rec["status"] == "deleted"
        assert rec["deleted_source"] == "trumpstruth"
        assert rec["kind"] == "reblog"
        assert rec["reblog_of_id"] == "117238282851088051"

    deletions = store.load_deletions(tmp_path)
    assert len(deletions) == 4
    assert [d["ts_id"] for d in deletions] == [
        removed_ts_ids[41649], removed_ts_ids[41646], removed_ts_ids[41644], removed_ts_ids[41641],
    ]
    assert [d["deleted_upper"] for d in deletions] == [
        "2026-09-09T02:31:01Z", "2026-09-09T02:20:59Z", "2026-09-09T02:20:23Z", "2026-09-09T02:02:39Z",
    ]
    assert all(d["source"] == "trumpstruth" for d in deletions)

    assert set(saved_state["sources"]["trumpstruth"]["processed_removed_ids"]) == {41641, 41644, 41646, 41649}

    # --- second, identical run: byte-identical posts/deletions, no re-fetch of processed removed ids ---
    posts_before = {p.name: p.read_bytes() for p in (tmp_path / "posts").glob("*.jsonl")}
    deletions_before = (tmp_path / "deletions.jsonl").read_bytes()
    calls_before = len(transport.calls)

    state2 = store.load_state(tmp_path)
    ctx2 = make_ctx(tmp_path, transport, state=state2, run_id="run-0002", clock=clock)
    row2 = ct.run(ctx2, removed_days=4)
    assert row2["ok"] is True

    posts_after = {p.name: p.read_bytes() for p in (tmp_path / "posts").glob("*.jsonl")}
    deletions_after = (tmp_path / "deletions.jsonl").read_bytes()
    assert posts_after == posts_before
    assert deletions_after == deletions_before

    # no new fetches of the four already-processed removed status pages
    urls_called_in_run2 = [u for u, _h in transport.calls[calls_before:]]
    for tid in (41641, 41644, 41646, 41649):
        assert status_url(tid) not in urls_called_in_run2


def test_min_yield_failure_raises(tmp_path):
    small_page = _synthetic_listing_html(range(1, 11))  # only 10 cards, below min_yield=50
    transport = FakeTransport({LISTING_URL: Response(200, {}, small_page.encode("utf-8"))})
    ctx = make_ctx(tmp_path, transport)
    with pytest.raises(ParseError):
        ct.run(ctx)


def test_other_account_id_skipped_and_recorded_in_other_account_ids(tmp_path):
    # 50 synthetic cards (ids 41466..41515) satisfy min_yield; the listing max is 41515, and state
    # already claims everything up to 41514, so sequential resolution fetches exactly id 41515 --
    # the real fixture for which is MichaelCohen212's own post, not realDonaldTrump's.
    ids = list(range(41466, 41516))
    assert ids[-1] == 41515
    page_html = _synthetic_listing_html(ids)
    empty_search_results = '<html><body><div class="search-page__results"></div></body></html>'
    routes = {
        LISTING_URL: Response(200, {}, page_html.encode("utf-8")),
        status_url(41515): fixture_response("trumpstruth_status_41515_reblog_other.html"),
        status_url(41516): Response(404, {}, b"not found"),  # probe stops immediately
        (lambda url: "search?query=" in url): Response(200, {}, empty_search_results.encode("utf-8")),
    }
    transport = FakeTransport(routes)
    state = {"version": 1, "sources": {"trumpstruth": {"max_trumpstruth_id": 41514}}}
    ctx = make_ctx(tmp_path, transport, state=state)

    row = ct.run(ctx)
    assert row["ok"] is True

    index = store.load_posts_index(tmp_path)
    assert "117190624268499306" not in index  # Michael Cohen's own post was never merged

    saved_state = store.load_state(tmp_path)
    assert 41515 in saved_state["sources"]["trumpstruth"]["other_account_ids"]
    assert saved_state["sources"]["trumpstruth"]["max_trumpstruth_id"] == 41515


# ---------------------------------------------------------------------------
# (d) backfill
# ---------------------------------------------------------------------------


def test_backfill_follows_home_cursor_to_2022_tail_then_finishes_removed_phase(tmp_path):
    home_cursor = "eyJzdGF0dXNfY3JlYXRlZF9hdCI6IjIwMjYtMDktMTAgMTI6NTE6MDkiLCJfcG9pbnRzVG9OZXh0SXRlbXMiOnRydWV9"
    empty_search_results = '<html><body><div class="search-page__results"></div></body></html>'
    routes = {
        LISTING_URL: fixture_response("trumpstruth_home.html"),
        (lambda url: ("cursor=" + home_cursor) in url): fixture_response("trumpstruth_listing_2022_tail.html"),
        (lambda url: "start_date=2022-01-01" in url): Response(200, {}, empty_search_results.encode("utf-8")),
    }
    transport = FakeTransport(routes)
    ctx = make_ctx(tmp_path, transport)

    row = ct.run(ctx, backfill=True)
    assert row["ok"] is True

    index = store.load_posts_index(tmp_path)
    assert len(index) == 11  # 10 cards on the home page + 1 on the 2022 tail page

    saved_state = store.load_state(tmp_path)
    bf = saved_state["sources"]["trumpstruth"]["backfill"]
    assert bf["phase"] == "done"
    assert bf["listing_cursor"] is None


def test_backfill_listing_stops_on_a_page_with_zero_cards(tmp_path):
    page1 = _synthetic_listing_html([1, 2, 3], next_link="https://www.trumpstruth.org/?cursor=XYZ")
    page2 = '<html><body><div class="statuses"></div></body></html>'  # 0 cards -> stop
    routes = {
        LISTING_URL: Response(200, {}, page1.encode("utf-8")),
        (lambda url: "cursor=XYZ" in url): Response(200, {}, page2.encode("utf-8")),
    }
    transport = FakeTransport(routes)
    ctx = make_ctx(tmp_path, transport)

    # Stop the run right after the listing phase completes, before it cascades into the removed-search
    # phase (which would need its own route) -- easiest way is to just not provide a removed-search route
    # and assert the listing-side outcome directly via state, calling only the listing half.
    src = ct._source_state(ctx)
    from scripts.merge import merge_partial  # local import: only needed for the tiny _Merger stand-in below

    counts = ct._new_run_counts()
    merger = ct._Merger(ctx, store.load_posts_index(tmp_path), counts)
    src["backfill"]["phase"] = "listing"
    ct._backfill_listing(ctx, ctx.state, src, src["backfill"], merger)

    store.save_posts(tmp_path, list(merger.index.values()))
    assert len(merger.index) == 3
    assert src["backfill"]["phase"] == "removed"
    for u, _h in transport.calls:
        assert "cursor=" not in u or u.endswith("cursor=XYZ")


def _week_search_routes():
    return {
        (lambda url: "removed=only" in url and "&page=" not in url): fixture_response(
            "trumpstruth_search_removed_2026-08-28_to_09-11.html"
        ),
        (lambda url: "removed=only" in url and "&page=2" in url): fixture_response(
            "trumpstruth_search_removed_page2_empty.html"
        ),
        status_url(41649): fixture_response("trumpstruth_status_41649_removed_reblog.html"),
        status_url(41646): fixture_response("trumpstruth_status_41646_removed_reblog.html"),
        status_url(41644): fixture_response("trumpstruth_status_41644_removed_reblog.html"),
    }


def test_removed_search_stops_when_total_is_reached_without_requesting_page_2(tmp_path):
    routes = _week_search_routes()
    routes[status_url(41641)] = fixture_response("trumpstruth_status_41641_removed_reblog.html")
    transport = FakeTransport(routes)
    ctx = make_ctx(tmp_path, transport)
    src = ct._source_state(ctx)
    merger = ct._Merger(ctx, {}, ct._new_run_counts())

    ct._removed_search(ctx, src, merger, "2026-08-28", "2026-09-11")

    assert not any("&page=2" in url for url, _ in transport.calls)
    assert src["processed_removed_ids"] == [41641, 41644, 41646, 41649]
    assert len(store.load_deletions(tmp_path)) == 4
    assert all(r["status"] == "deleted" for r in store.load_posts(tmp_path))


def test_crash_mid_removed_search_leaves_records_events_and_state_consistent(tmp_path):
    routes = _week_search_routes()
    routes[LISTING_URL] = fixture_response("trumpstruth_listing_page1.html")
    routes[status_url(41688)] = Response(404, {}, b"")
    routes[status_url(41641)] = Response(200, {}, b"<html><body>drift</body></html>")  # ParseError on the 4th
    transport = FakeTransport(routes)
    state = {"version": 1, "sources": {"trumpstruth": {"max_trumpstruth_id": 41687}}}
    ctx = make_ctx(tmp_path, transport, state=state)

    with pytest.raises(ParseError):
        ct.run(ctx)

    index = store.load_posts_index(tmp_path)
    deleted = sorted(i for i, r in index.items() if r["status"] == "deleted")
    assert deleted == ["117238326295991805", "117238345561593751", "117238414290995787"]
    events = store.load_deletions(tmp_path)
    assert sorted(e["ts_id"] for e in events) == deleted
    saved = store.load_state(tmp_path)["sources"]["trumpstruth"]
    assert saved["processed_removed_ids"] == [41644, 41646, 41649]
    assert saved.get("last_ok_at") is None
    assert len(index) >= 95  # the listing cards were persisted too
