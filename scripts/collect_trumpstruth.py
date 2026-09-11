"""Collector for trumpstruth.org (docs/SPEC.md section 8, trumpstruth bullet).

``run(ctx, backfill=False, removed_days=14) -> dict`` implements, in order:

(a) fetch listing page 1 (``per_page=100``); every card authored by ``realDonaldTrump`` is merged as a
    partial (a ``retruthed`` card is already the target's own card -- see scripts/parsers.py -- so it is
    merged exactly like any other card); the page must yield at least ``MIN_YIELD_PAGE1`` cards or the run
    aborts (a possible markup-drift signal, same severity as a ``ParseError``).
(b) sequential resolution: every trumpstruth id from ``state.max_trumpstruth_id + 1`` through the listing's
    largest id, plus a probe past it until the first non-200, is fetched individually so that reposts (whose
    own id/ts_id/time never appear on listing pages) are captured. ``max_trumpstruth_id`` is persisted after
    every id fetched so a crash resumes without repeating work already durably recorded.
(c) the "removed" search over the last ``removed_days`` days finds posts trumpstruth has confirmed deleted;
    each new result's status page is fetched and merged with the deletion signal.
(d) when ``backfill=True``, steps (a)-(c) above are replaced entirely by a slow, resumable crawl: the full
    listing history (oldest-first via cursor-following) and the full "removed" history back to 2022-01-01.
    Sequential id resolution is deliberately not part of backfill (see docs/SPEC.md 8 and TODO.md item 2).

Only the standard library is used. Python 3.9 compatible.
"""
from __future__ import annotations

from datetime import timedelta
from typing import List, Any, Dict, Optional, Set, Tuple

from scripts import parsers, store
from scripts.common import EASTERN, HANDLE, Context
from scripts.merge import RECORD_FIELDS, merge_partial
from scripts.parsers import ParseError

LISTING_URL = "https://www.trumpstruth.org/?sort=desc&per_page=100&removed=include"
STATUS_URL_FMT = "https://www.trumpstruth.org/statuses/%d"
SEARCH_URL_FMT = (
    "https://www.trumpstruth.org/search?query=&removed=only&sort=date_desc&per_page=100"
    "&start_date=%s&end_date=%s"
)
# The backfill crawls the same 100-per-page listing as the poll; the site default is only 10 per page.
BACKFILL_START_DATE = "2022-01-01"

MIN_YIELD_PAGE1 = 50
MAX_IDS_PER_RUN = 200
MAX_REMOVED_PAGES = 50
BACKFILL_CHECKPOINT_PAGES = 20

_ALLOWED_EXTRA_PARTIAL_KEYS = frozenset({"removed", "api_404"})
_RECORD_FIELD_SET = frozenset(RECORD_FIELDS)


def to_partial(d: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only docs/SPEC.md section-2 field names plus ``removed``/``api_404``.

    Drops parser-only bookkeeping keys (``retruthed``, ``retruthed_by``, ``account``, ``trumpstruth_url``,
    ``_source``, ``_engagement``, and anything else not part of the stored record) before the dict is
    handed to :func:`scripts.merge.merge_partial`.
    """
    return {k: v for k, v in d.items() if k in _RECORD_FIELD_SET or k in _ALLOWED_EXTRA_PARTIAL_KEYS}


def _new_run_counts() -> Dict[str, int]:
    return {"new_posts": 0, "updated_posts": 0, "deletions_found": 0, "errors": 0}


def _build_row(ctx: Context, started_at: str, *, requests: int, counts: Dict[str, int], notes: str) -> Dict[str, Any]:
    return {
        "run_id": ctx.run_id,
        "source": "trumpstruth",
        "started_at": started_at,
        "finished_at": ctx.now_iso(),
        "ok": True,
        "requests": requests,
        "new_posts": counts["new_posts"],
        "updated_posts": counts["updated_posts"],
        "deletions_found": counts["deletions_found"],
        "errors": counts["errors"],
        "notes": notes,
    }


class _Merger:
    """Small stateful helper shared by every phase below: merges one partial, tracks index/counts/deletions."""

    def __init__(self, ctx: Context, index: Dict[str, Dict[str, Any]], counts: Dict[str, int]):
        self.ctx = ctx
        self.index = index
        self.counts = counts
        self.logged_deletions: Set[Tuple[str, str]] = {
            (d["ts_id"], d["source"]) for d in store.load_deletions(ctx.data_root)
        }
        self.pending_events: List[Dict[str, Any]] = []  # deletion events not yet written (see checkpoint)
        self.unsaved = 0  # merged changes not yet persisted

    def merge(self, partial: Dict[str, Any], source: str = "trumpstruth") -> Any:
        ts_id = partial["ts_id"]
        result = merge_partial(
            self.index.get(ts_id),
            partial,
            source=source,
            observed_at=self.ctx.now_iso(),
            run_id=self.ctx.run_id,
            logged_deletions=frozenset(self.logged_deletions),
        )
        if result.changed:
            self.index[ts_id] = result.record
            self.unsaved += 1
            if result.is_new:
                self.counts["new_posts"] += 1
            else:
                self.counts["updated_posts"] += 1
        if result.deletion_event is not None:
            self.pending_events.append(result.deletion_event)
            self.logged_deletions.add((ts_id, source))
            self.counts["deletions_found"] += 1
        return result

    def checkpoint(self, min_changes: int = 0) -> None:
        """Persist posts first, then the deletion events that reference them, so a crash can never leave
        deletion events (or state) pointing at records that were never written."""
        if self.unsaved < min_changes and not self.pending_events:
            return
        if self.unsaved or self.pending_events:
            store.save_posts(self.ctx.data_root, list(self.index.values()))
            for event in self.pending_events:
                store.append_deletion(self.ctx.data_root, event)
            self.pending_events = []
            self.unsaved = 0


def _save_progress(merger: _Merger, state: Dict[str, Any], min_changes: int = 0) -> None:
    """Checkpoint merged records (if enough have accumulated) and only then persist state that refers to them."""
    merger.checkpoint(min_changes)
    store.save_state(merger.ctx.data_root, state)


def _default_source_state() -> Dict[str, Any]:
    return {
        "last_run_at": None,
        "last_ok_at": None,
        "processed_removed_ids": [],
        "max_trumpstruth_id": None,
        "other_account_ids": [],
        "backfill": {"phase": None, "listing_cursor": None, "removed_cursor": None, "removed_page": None},
    }


def _source_state(ctx: Context) -> Dict[str, Any]:
    state = ctx.state
    state.setdefault("version", 1)
    sources = state.setdefault("sources", {})
    src = sources.setdefault("trumpstruth", _default_source_state())
    src.setdefault("processed_removed_ids", [])
    src.setdefault("max_trumpstruth_id", None)
    src.setdefault("other_account_ids", [])
    src.setdefault("backfill", {"phase": None, "listing_cursor": None, "removed_cursor": None, "removed_page": None})
    return src


# ---------------------------------------------------------------------------
# (a) + (b): listing page 1 and sequential id resolution
# ---------------------------------------------------------------------------


def _process_card(merger: _Merger, card: Dict[str, Any]) -> bool:
    """Merge one listing/status-page partial if authored by realDonaldTrump. Returns True if merged."""
    if card.get("account") != HANDLE:
        return False
    merger.merge(to_partial(card))
    return True


def _fetch_status_page(ctx: Context, trumpstruth_id: int) -> Tuple[int, Optional[Dict[str, Any]]]:
    """GET one trumpstruth status page. Returns (http_status, partial_or_None)."""
    resp = ctx.http.get(STATUS_URL_FMT % trumpstruth_id)
    if resp.status == 404:
        return 404, None
    if resp.status != 200:
        return resp.status, None
    return 200, parsers.parse_status_page(resp.text)


def _run_listing_and_resolution(ctx: Context, state: Dict[str, Any], src: Dict[str, Any], merger: _Merger) -> int:
    """Steps (a) and (b). Returns the number of cards/ids skipped for being another account's."""
    resp = ctx.http.get(LISTING_URL)
    cards = parsers.parse_listing(resp.text)
    if len(cards) < MIN_YIELD_PAGE1:
        raise ParseError(
            "trumpstruth listing page 1 yielded only %d cards (min_yield=%d)" % (len(cards), MIN_YIELD_PAGE1)
        )

    other_account_skipped = 0
    listing_max = 0
    for card in cards:
        tid = card.get("trumpstruth_id")
        if tid is not None and tid > listing_max:
            listing_max = tid
        try:
            if not _process_card(merger, card):
                other_account_skipped += 1
        except ParseError:
            raise
        except Exception:
            ctx.logger.exception("trumpstruth: failed merging listing card %r", tid)
            merger.counts["errors"] += 1

    if src["max_trumpstruth_id"] is None:
        # First-ever run: only resolve the newest id (plus the probe), not the whole history.
        src["max_trumpstruth_id"] = listing_max - 1
    start_id = src["max_trumpstruth_id"] + 1

    fetched = 0
    max_seen_200: Optional[int] = None

    tid = start_id
    while tid <= listing_max and fetched < MAX_IDS_PER_RUN:
        status, partial = _fetch_status_page_safe(ctx, tid, merger)
        fetched += 1
        if status == 200:
            max_seen_200 = tid
            if partial is not None and partial.get("account") != HANDLE:
                other = src["other_account_ids"]
                if tid not in other:
                    other.append(tid)
                    other.sort()
                other_account_skipped += 1
        _save_progress(merger, state, min_changes=10)
        tid += 1

    if fetched < MAX_IDS_PER_RUN:
        probe_id = listing_max + 1
        while fetched < MAX_IDS_PER_RUN:
            status, partial = _fetch_status_page_safe(ctx, probe_id, merger)
            fetched += 1
            _save_progress(merger, state, min_changes=10)
            if status != 200:
                break
            max_seen_200 = probe_id
            if partial is not None and partial.get("account") != HANDLE:
                other = src["other_account_ids"]
                if probe_id not in other:
                    other.append(probe_id)
                    other.sort()
                other_account_skipped += 1
            probe_id += 1

    src["max_trumpstruth_id"] = max_seen_200 if max_seen_200 is not None else listing_max
    _save_progress(merger, state)
    return other_account_skipped


def _fetch_status_page_safe(ctx: Context, tid: int, merger: _Merger) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Fetch + merge one sequential-resolution id. 404/other non-200 -> gap, logged and skipped."""
    try:
        status, partial = _fetch_status_page(ctx, tid)
    except ParseError:
        raise
    except Exception:
        ctx.logger.exception("trumpstruth: failed fetching/parsing status %d", tid)
        merger.counts["errors"] += 1
        return 0, None
    if status != 200:
        return status, None
    try:
        if partial.get("account") == HANDLE:
            merger.merge(to_partial(partial))
    except ParseError:
        raise
    except Exception:
        ctx.logger.exception("trumpstruth: failed merging status %d", tid)
        merger.counts["errors"] += 1
    return status, partial


# ---------------------------------------------------------------------------
# (c) removed search (also reused, with different dates, by backfill step (d))
# ---------------------------------------------------------------------------


def _search_url(start_date: str, end_date: str, cursor: Optional[str], page_num: int) -> str:
    base = SEARCH_URL_FMT % (start_date, end_date)
    if cursor:
        return base + "&cursor=" + cursor
    if page_num > 1:
        return base + "&page=%d" % page_num
    return base


def _process_removed_result(ctx: Context, merger: _Merger, trumpstruth_id: int) -> None:
    status, partial = _fetch_status_page(ctx, trumpstruth_id)
    if status != 200:
        merger.counts["errors"] += 1
        return
    if partial.get("account") == HANDLE:
        merger.merge(to_partial(partial))


def _removed_search(
    ctx: Context, src: Dict[str, Any], merger: _Merger, start_date: str, end_date: str, max_pages: int = MAX_REMOVED_PAGES
) -> None:
    processed = set(src["processed_removed_ids"])
    cursor: Optional[str] = None
    page_num = 1
    seen = 0
    for _ in range(max_pages):
        url = _search_url(start_date, end_date, cursor, page_num)
        resp = ctx.http.get(url)
        data = parsers.parse_search_results(resp.text)
        results = data["results"]
        if not results:
            break
        for r in results:
            tid = r["trumpstruth_id"]
            if tid in processed:
                continue
            try:
                _process_removed_result(ctx, merger, tid)
            except ParseError:
                raise
            except Exception:
                ctx.logger.exception("trumpstruth: failed processing removed id %d", tid)
                merger.counts["errors"] += 1
                continue
            processed.add(tid)
            src["processed_removed_ids"] = sorted(processed)  # recorded per id so a crash mid-page is safe
        seen += len(results)
        src["processed_removed_ids"] = sorted(processed)
        _save_progress(merger, ctx.state)
        total = data.get("total")
        if total is not None and seen >= total:
            break  # every result already seen; a further page would come back empty
        next_cursor = data.get("next_cursor")
        if next_cursor:
            cursor = next_cursor
        else:
            cursor = None
            page_num += 1


def _run_removed_search(ctx: Context, src: Dict[str, Any], merger: _Merger, removed_days: int) -> None:
    today = ctx.clock.now().astimezone(EASTERN).date()
    start_date = (today - timedelta(days=removed_days)).isoformat()
    end_date = today.isoformat()
    _removed_search(ctx, src, merger, start_date, end_date)


# ---------------------------------------------------------------------------
# (d) backfill
# ---------------------------------------------------------------------------


def _backfill_listing(ctx: Context, state: Dict[str, Any], src: Dict[str, Any], bf: Dict[str, Any], merger: _Merger) -> None:
    cursor = bf.get("listing_cursor")
    page_count = 0
    while True:
        url = LISTING_URL if not cursor else (LISTING_URL + "&cursor=" + cursor)
        resp = ctx.http.get(url)
        cards = parsers.parse_listing(resp.text)
        if not cards:
            break
        for card in cards:
            try:
                _process_card(merger, card)
            except ParseError:
                raise
            except Exception:
                ctx.logger.exception("trumpstruth backfill: failed merging card %r", card.get("trumpstruth_id"))
                merger.counts["errors"] += 1
        page_count += 1
        next_cursor = parsers.parse_next_cursor(resp.text)
        cursor = next_cursor
        if page_count % BACKFILL_CHECKPOINT_PAGES == 0 or not next_cursor:
            # The cursor is persisted only together with the records crawled up to it, so a crash re-crawls at
            # most BACKFILL_CHECKPOINT_PAGES pages instead of skipping posts that were never written.
            merger.checkpoint()
            bf["listing_cursor"] = cursor
            store.save_state(ctx.data_root, state)
        if not next_cursor:
            break
    bf["phase"] = "removed"
    bf["listing_cursor"] = None
    store.save_state(ctx.data_root, state)


def _backfill_removed(ctx: Context, state: Dict[str, Any], src: Dict[str, Any], bf: Dict[str, Any], merger: _Merger) -> None:
    today = ctx.clock.now().astimezone(EASTERN).date().isoformat()
    processed = set(src["processed_removed_ids"])
    cursor = bf.get("removed_cursor")
    page_num = bf.get("removed_page") or 1
    seen = 0
    for _ in range(MAX_REMOVED_PAGES):
        url = _search_url(BACKFILL_START_DATE, today, cursor, page_num)
        resp = ctx.http.get(url)
        data = parsers.parse_search_results(resp.text)
        results = data["results"]
        if not results:
            bf["phase"] = "done"
            bf["removed_cursor"] = None
            _save_progress(merger, state)
            return
        for r in results:
            tid = r["trumpstruth_id"]
            if tid in processed:
                continue
            try:
                _process_removed_result(ctx, merger, tid)
            except ParseError:
                raise
            except Exception:
                ctx.logger.exception("trumpstruth backfill: failed removed id %d", tid)
                merger.counts["errors"] += 1
                continue
            processed.add(tid)
            src["processed_removed_ids"] = sorted(processed)  # recorded per id so a crash mid-page is safe
        seen += len(results)
        src["processed_removed_ids"] = sorted(processed)
        total = data.get("total")
        next_cursor = data.get("next_cursor")
        if next_cursor:
            cursor = next_cursor
        else:
            cursor = None
            page_num += 1
        bf["removed_cursor"] = cursor
        bf["removed_page"] = page_num
        if total is not None and seen >= total:
            bf["phase"] = "done"
            bf["removed_cursor"] = None
            _save_progress(merger, state)
            return
        _save_progress(merger, state)
    # MAX_REMOVED_PAGES reached without emptying: phase stays "removed" so the next run resumes here.


def _run_backfill(ctx: Context, state: Dict[str, Any], src: Dict[str, Any], merger: _Merger) -> None:
    bf = src["backfill"]
    if not bf.get("phase"):
        bf["phase"] = "listing"
        bf["listing_cursor"] = None
        bf["removed_cursor"] = None
        bf["removed_page"] = None

    if bf["phase"] == "listing":
        _backfill_listing(ctx, state, src, bf, merger)

    if bf["phase"] == "removed":
        _backfill_removed(ctx, state, src, bf, merger)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(ctx: Context, backfill: bool = False, removed_days: int = 14) -> Dict[str, Any]:
    started_at = ctx.now_iso()
    start_requests = ctx.http.request_count
    state = ctx.state
    src = _source_state(ctx)
    src["last_run_at"] = started_at

    index = store.load_posts_index(ctx.data_root)
    counts = _new_run_counts()
    merger = _Merger(ctx, index, counts)

    try:
        if backfill:
            _run_backfill(ctx, state, src, merger)
            notes = "backfill phase=%s" % src["backfill"]["phase"]
        else:
            other_skipped = _run_listing_and_resolution(ctx, state, src, merger)
            _run_removed_search(ctx, src, merger, removed_days)
            notes = "other_account_skipped=%d max_trumpstruth_id=%s" % (other_skipped, src["max_trumpstruth_id"])
    finally:
        # Whatever happened, persist what was merged (records before the events that reference them) so the
        # data files, deletion log and state never disagree.
        merger.checkpoint()
        store.save_state(ctx.data_root, state)
    src["last_ok_at"] = ctx.now_iso()
    store.save_state(ctx.data_root, state)

    requests = ctx.http.request_count - start_requests
    row = _build_row(ctx, started_at, requests=requests, counts=counts, notes=notes)
    store.append_run(ctx.data_root, row)
    return row
