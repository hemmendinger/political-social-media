"""Collector for CNN's Truth Social archive (docs/SPEC.md section 8, cnn bullet).

``run(ctx, force=False) -> dict``: skips unless ``force`` or at least two hours have passed since
``last_ok_at``; conditionally GETs the archive JSON with ``If-None-Match`` when an etag is stored (a 304
means nothing changed); otherwise merges every row (source ``cnn``), records engagement rows through the
throttle in scripts/store.py, and stores the response's etag/last-modified for next time.

Only the standard library is used. Python 3.9 compatible.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from scripts import parsers, store
from scripts.common import Context, parse_iso_utc
from scripts.merge import merge_partial
from scripts.parsers import ParseError

ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
SKIP_INTERVAL = timedelta(hours=2)


def _new_run_counts() -> Dict[str, int]:
    return {"new_posts": 0, "updated_posts": 0, "deletions_found": 0, "errors": 0}


def _build_row(ctx: Context, started_at: str, *, requests: int, counts: Dict[str, int], notes: Any) -> Dict[str, Any]:
    return {
        "run_id": ctx.run_id,
        "source": "cnn",
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


def _source_state(ctx: Context) -> Dict[str, Any]:
    state = ctx.state
    state.setdefault("version", 1)
    sources = state.setdefault("sources", {})
    src = sources.setdefault("cnn", {"last_run_at": None, "last_ok_at": None, "etag": None, "last_modified": None})
    src.setdefault("etag", None)
    src.setdefault("last_modified", None)
    return src


def run(ctx: Context, force: bool = False) -> Dict[str, Any]:
    started_at = ctx.now_iso()
    start_requests = ctx.http.request_count
    src = _source_state(ctx)

    last_ok_at = src.get("last_ok_at")
    if not force and last_ok_at:
        elapsed = ctx.clock.now() - parse_iso_utc(last_ok_at)
        if elapsed < SKIP_INTERVAL:
            minutes = int(elapsed.total_seconds() // 60)
            row = _build_row(
                ctx, started_at, requests=0, counts=_new_run_counts(), notes="skipped: ran %d min ago" % minutes
            )
            store.append_run(ctx.data_root, row)
            return row

    src["last_run_at"] = started_at

    headers = {}
    if src.get("etag"):
        headers["If-None-Match"] = src["etag"]
    resp = ctx.http.get(ARCHIVE_URL, headers=headers)

    if resp.status == 304:
        src["last_ok_at"] = ctx.now_iso()
        store.save_state(ctx.data_root, ctx.state)
        row = _build_row(
            ctx, started_at, requests=ctx.http.request_count - start_requests, counts=_new_run_counts(),
            notes="not modified",
        )
        store.append_run(ctx.data_root, row)
        return row

    if resp.status != 200:
        raise RuntimeError("cnn archive fetch failed: HTTP %s" % resp.status)

    rows: List[Dict[str, Any]] = resp.json()
    index = store.load_posts_index(ctx.data_root)
    logged_deletions = {(d["ts_id"], d["source"]) for d in store.load_deletions(ctx.data_root)}
    counts = _new_run_counts()
    engagement_rows: List[Dict[str, Any]] = []
    observed_at = ctx.now_iso()

    for row in rows:
        try:
            partial = parsers.cnn_row_to_partial(row)
        except ParseError:
            raise
        except Exception:
            ctx.logger.exception("cnn: failed parsing row %r", row.get("id"))
            counts["errors"] += 1
            continue
        try:
            ts_id = partial["ts_id"]
            result = merge_partial(
                index.get(ts_id), partial, source="cnn", observed_at=observed_at, run_id=ctx.run_id,
                logged_deletions=frozenset(logged_deletions),
            )
            if result.changed:
                index[ts_id] = result.record
                counts["new_posts" if result.is_new else "updated_posts"] += 1
            if result.deletion_event is not None:
                store.append_deletion(ctx.data_root, result.deletion_event)
                logged_deletions.add((ts_id, "cnn"))
                counts["deletions_found"] += 1
            eng = partial.get("_engagement") or {}
            engagement_rows.append(
                {
                    "observed_at": observed_at,
                    "ts_id": ts_id,
                    "source": "cnn",
                    "replies": eng.get("replies"),
                    "reblogs": eng.get("reblogs"),
                    "favourites": eng.get("favourites"),
                    "upvotes": eng.get("upvotes"),
                    "downvotes": eng.get("downvotes"),
                }
            )
        except Exception:
            ctx.logger.exception("cnn: failed merging row %r", row.get("id"))
            counts["errors"] += 1

    post_created_at = {ts_id: rec["created_at_utc"] for ts_id, rec in index.items()}
    filtered = store.filter_engagement(ctx.data_root, engagement_rows, post_created_at)
    store.append_engagement(ctx.data_root, filtered)
    store.save_posts(ctx.data_root, list(index.values()))

    src["etag"] = resp.headers.get("etag")
    src["last_modified"] = resp.headers.get("last-modified")
    src["last_ok_at"] = ctx.now_iso()
    store.save_state(ctx.data_root, ctx.state)

    row = _build_row(
        ctx, started_at, requests=ctx.http.request_count - start_requests, counts=counts,
        notes="imported=%d" % len(rows),
    )
    store.append_run(ctx.data_root, row)
    return row
