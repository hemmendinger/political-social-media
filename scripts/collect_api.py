"""Collector for the Truth Social API (docs/SPEC.md section 8, api bullet).

``run(ctx, max_pages=5, max_verify=3) -> dict``: the first page request doubles as the reachability probe.
On 403/429/a transport-level failure the source is marked unreachable and the run still returns ``ok=True``
(this is an expected, recoverable condition -- GitHub-hosted runners are geo-blocked as often as not -- not
a collector failure). Otherwise pages are walked with ``max_id`` until a page contains only already-known
ids or ``max_pages`` is reached; every object is merged (source ``api``) with engagement rows recorded
through the throttle. Posts that look like they should still be live (``status=present``,
``last_verified_live_at`` set, ``created_at_utc`` inside the fetched window) but were absent from every
fetched page are re-verified individually, up to ``max_verify`` of them, to catch deletions between polls.

Only the standard library is used. Python 3.9 compatible.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from scripts import parsers, store
from scripts.common import parse_iso_utc, Context, HttpError, TransportError
from scripts.merge import merge_partial
from scripts.parsers import ParseError

ACCOUNT_ID = "107780257626128497"
REPROBE_MINUTES = 6 * 60  # re-check a blocked network every 6 h
STATUSES_URL = "https://truthsocial.com/api/v1/accounts/%s/statuses?limit=20&exclude_replies=false" % ACCOUNT_ID
STATUS_URL_FMT = "https://truthsocial.com/api/v1/statuses/%s"


def _new_run_counts() -> Dict[str, int]:
    return {"new_posts": 0, "updated_posts": 0, "deletions_found": 0, "errors": 0}


def _build_row(ctx: Context, started_at: str, *, requests: int, counts: Dict[str, int], notes: str) -> Dict[str, Any]:
    return {
        "run_id": ctx.run_id,
        "source": "api",
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
    src = sources.setdefault(
        "api",
        {"last_run_at": None, "last_ok_at": None, "reachable": None, "last_probe_status": None,
         "last_probe_at": None, "statuses_count": None},
    )
    return src


def _strip_private(partial: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the parser's own private keys (``_source``, ``_engagement``, ...) before merging."""
    return {k: v for k, v in partial.items() if not k.startswith("_")}


def _engagement_row(observed_at: str, partial: Dict[str, Any]) -> Dict[str, Any]:
    eng = partial.get("_engagement") or {}
    return {
        "observed_at": observed_at,
        "ts_id": partial["ts_id"],
        "source": "api",
        "replies": eng.get("replies"),
        "reblogs": eng.get("reblogs"),
        "favourites": eng.get("favourites"),
        "upvotes": eng.get("upvotes"),
        "downvotes": eng.get("downvotes"),
    }


def run(ctx: Context, max_pages: int = 5, max_verify: int = 3) -> Dict[str, Any]:
    started_at = ctx.now_iso()
    start_requests = ctx.http.request_count
    src = _source_state(ctx)
    src["last_run_at"] = started_at

    # Once the API is known to be blocked from this network (GitHub runners get a Cloudflare 403), re-probe only
    # every REPROBE_MINUTES instead of burning the retry budget and ~1 minute of pacing on every run.
    last_probe = src.get("last_probe_at")
    if src.get("reachable") is False and last_probe:
        age_min = (ctx.clock.now() - parse_iso_utc(last_probe)).total_seconds() / 60.0
        if age_min < REPROBE_MINUTES:
            row = _build_row(
                ctx, started_at, requests=0, counts=_new_run_counts(),
                notes="skipped: unreachable at last probe %s" % last_probe,
            )
            store.append_run(ctx.data_root, row)
            store.save_state(ctx.data_root, ctx.state)
            return row

    probe_resp = None
    probe_status: Optional[int] = None
    try:
        probe_resp = ctx.http.get(STATUSES_URL)
        probe_status = probe_resp.status
    except HttpError as exc:
        probe_status = exc.status
    except TransportError:
        probe_status = None

    if probe_resp is None or probe_status != 200:
        src["reachable"] = False
        src["last_probe_status"] = probe_status
        src["last_probe_at"] = ctx.now_iso()
        store.save_state(ctx.data_root, ctx.state)
        label = probe_status if probe_status is not None else "transport_error"
        row = _build_row(
            ctx, started_at, requests=ctx.http.request_count - start_requests, counts=_new_run_counts(),
            notes="unreachable: %s" % label,
        )
        store.append_run(ctx.data_root, row)
        return row

    src["reachable"] = True
    src["last_probe_status"] = 200
    src["last_probe_at"] = ctx.now_iso()

    index = store.load_posts_index(ctx.data_root)
    logged_deletions = {(d["ts_id"], d["source"]) for d in store.load_deletions(ctx.data_root)}
    counts = _new_run_counts()
    engagement_rows: List[Dict[str, Any]] = []
    fetched_ids = set()
    fetched_created_ats: List[str] = []
    statuses_count: Optional[int] = None

    def merge_one(partial: Dict[str, Any], observed_at: str) -> Any:
        ts_id = partial["ts_id"]
        result = merge_partial(
            index.get(ts_id), partial, source="api", observed_at=observed_at, run_id=ctx.run_id,
            logged_deletions=frozenset(logged_deletions),
        )
        if result.changed:
            index[ts_id] = result.record
            counts["new_posts" if result.is_new else "updated_posts"] += 1
        if result.deletion_event is not None:
            store.append_deletion(ctx.data_root, result.deletion_event)
            logged_deletions.add((ts_id, "api"))
            counts["deletions_found"] += 1
        return result

    resp = probe_resp
    max_id: Optional[str] = None
    for page in range(max_pages):
        if resp is None:
            resp = ctx.http.get(STATUSES_URL + "&max_id=" + str(max_id))
        batch = resp.json()
        if page == 0 and batch:
            statuses_count = parsers.api_account_from_status(batch[0]).get("statuses_count")
        if not batch:
            resp = None
            break
        ids = [s["id"] for s in batch]
        # A page holding only known ids ends pagination, but it is still merged: it carries the live sightings
        # and engagement counts that deletion detection and analysis depend on.
        all_known = all(i in index for i in ids)

        observed_at = ctx.now_iso()
        for obj in batch:
            try:
                partial = parsers.api_status_to_partial(obj)
            except ParseError:
                raise
            except Exception:
                ctx.logger.exception("api: failed parsing status %r", obj.get("id"))
                counts["errors"] += 1
                continue
            try:
                merge_one(_strip_private(partial), observed_at)
                engagement_rows.append(_engagement_row(observed_at, partial))
            except Exception:
                ctx.logger.exception("api: failed merging status %r", obj.get("id"))
                counts["errors"] += 1
                continue
            fetched_ids.add(partial["ts_id"])
            if partial.get("created_at_utc"):
                fetched_created_ats.append(partial["created_at_utc"])

        max_id = ids[-1]
        resp = None
        if all_known:
            break

    if statuses_count is not None:
        src["statuses_count"] = statuses_count

    if fetched_created_ats:
        oldest = min(fetched_created_ats)
        newest = max(fetched_created_ats)
        candidates = sorted(
            ts_id
            for ts_id, rec in index.items()
            if rec.get("status") == "present"
            and rec.get("last_verified_live_at")
            and rec.get("created_at_utc")
            and oldest <= rec["created_at_utc"] <= newest
            and ts_id not in fetched_ids
        )
        for ts_id in candidates[:max_verify]:
            try:
                vresp = ctx.http.get(STATUS_URL_FMT % ts_id)
            except (HttpError, TransportError):
                ctx.logger.exception("api: failed verifying status %s", ts_id)
                counts["errors"] += 1
                continue
            observed_at = ctx.now_iso()
            if vresp.status == 404:
                merge_one({"ts_id": ts_id, "api_404": True}, observed_at)
            elif vresp.status == 200:
                try:
                    obj = vresp.json()
                    partial = parsers.api_status_to_partial(obj)
                    merge_one(_strip_private(partial), observed_at)
                except ParseError:
                    raise
                except Exception:
                    ctx.logger.exception("api: failed verify-parsing status %s", ts_id)
                    counts["errors"] += 1
            else:
                counts["errors"] += 1

    post_created_at = {ts_id: rec["created_at_utc"] for ts_id, rec in index.items()}
    filtered = store.filter_engagement(ctx.data_root, engagement_rows, post_created_at)
    store.append_engagement(ctx.data_root, filtered)
    store.save_posts(ctx.data_root, list(index.values()))

    src["last_ok_at"] = ctx.now_iso()
    store.save_state(ctx.data_root, ctx.state)

    row = _build_row(
        ctx, started_at, requests=ctx.http.request_count - start_requests, counts=counts,
        notes="statuses_count=%s" % statuses_count,
    )
    store.append_run(ctx.data_root, row)
    return row
