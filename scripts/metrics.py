"""Analysis metrics over ``data/truths.sqlite`` (docs/SPEC.md section 11).

Every top-level metric function takes an open ``sqlite3.Connection`` plus inclusive ET date
strings ``start``/``end`` (``YYYY-MM-DD``) and returns JSON-serializable lists/dicts. Callers
build the connection (e.g. ``sqlite3.connect(str(db_path))``); nothing here opens a connection
or hits the filesystem. All date arithmetic uses Python's ``datetime``/``date`` -- the only
SQLite-side date math is the UTC ``julianday`` interval arithmetic baked into ``v_posts_et`` by
``build_db.py``, which involves no local-time conversion.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from scripts.common import parse_iso_utc

__all__ = [
    "posts_by_day", "hour_histogram", "overnight_share", "bursts", "deletions",
    "top_reblogged_accounts", "link_domains", "media_mix", "engagement_stats",
    "longest_silence", "edits", "baseline", "iso_week_bounds",
]

_DAY_KINDS = ("original", "quote", "reblog", "reply")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _date_range(start: str, end: str) -> List[str]:
    d0 = _parse_date(start)
    d1 = _parse_date(end)
    days = []
    d = d0
    while d <= d1:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def _percentile(sorted_values: Sequence[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile: rank = ceil(pct/100 * n), 1-indexed into the sorted values."""
    n = len(sorted_values)
    if n == 0:
        return None
    rank = max(1, min(n, math.ceil(pct / 100.0 * n)))
    return sorted_values[rank - 1]


# ---------------------------------------------------------------------------
# posts_by_day / hour_histogram / overnight_share
# ---------------------------------------------------------------------------


def posts_by_day(conn: sqlite3.Connection, start: str, end: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT et_date, kind, is_deleted FROM v_posts_et WHERE et_date BETWEEN ? AND ?",
        (start, end),
    ).fetchall()
    days = _date_range(start, end)
    counts: Dict[str, Dict[str, int]] = {
        d: {"original": 0, "quote": 0, "reblog": 0, "reply": 0, "total": 0, "deleted": 0} for d in days
    }
    for et_date, kind, is_deleted in rows:
        bucket = counts.setdefault(
            et_date, {"original": 0, "quote": 0, "reblog": 0, "reply": 0, "total": 0, "deleted": 0}
        )
        if kind in _DAY_KINDS:
            bucket[kind] += 1
        bucket["total"] += 1
        if is_deleted:
            bucket["deleted"] += 1
    return [dict(et_date=d, **counts[d]) for d in days]


def hour_histogram(conn: sqlite3.Connection, start: str, end: str) -> List[int]:
    rows = conn.execute(
        "SELECT et_hour, COUNT(*) FROM v_posts_et WHERE et_date BETWEEN ? AND ? GROUP BY et_hour",
        (start, end),
    ).fetchall()
    counts = [0] * 24
    for hour, n in rows:
        counts[hour] = n
    return counts


def overnight_share(conn: sqlite3.Connection, start: str, end: str) -> Dict[str, Any]:
    hist = hour_histogram(conn, start, end)
    overnight = sum(hist[0:6])
    total = sum(hist)
    share = (overnight / total) if total else None
    return {"overnight": overnight, "total": total, "share": share}


# ---------------------------------------------------------------------------
# bursts
# ---------------------------------------------------------------------------


def bursts(
    conn: sqlite3.Connection, start: str, end: str, window_min: int = 10, min_posts: int = 5
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT ts_id, created_at_utc, created_at_et, kind FROM v_posts_et "
        "WHERE et_date BETWEEN ? AND ? ORDER BY created_at_utc",
        (start, end),
    ).fetchall()
    n = len(rows)
    if n == 0:
        return []
    times = [parse_iso_utc(r[1]) for r in rows]
    window = timedelta(minutes=window_min)

    candidates: List[Tuple[int, int]] = []
    j = 0
    for i in range(n):
        if j < i:
            j = i
        while j + 1 < n and times[j + 1] - times[i] <= window:
            j += 1
        if j - i + 1 >= min_posts:
            candidates.append((i, j))

    merged: List[Tuple[int, int]] = []
    for i, j in candidates:
        if merged and i <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], j))
        else:
            merged.append((i, j))

    result = []
    for i, j in merged:
        kinds: Dict[str, int] = {}
        for r in rows[i : j + 1]:
            kinds[r[3]] = kinds.get(r[3], 0) + 1
        result.append({
            "start_et": rows[i][2],
            "end_et": rows[j][2],
            "count": j - i + 1,
            "kinds": kinds,
        })
    return result


# ---------------------------------------------------------------------------
# deletions
# ---------------------------------------------------------------------------


def deletions(conn: sqlite3.Connection, start: str, end: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT ts_id, created_at_et, kind, lifetime_min, deletion_window_min, deleted_source, content_text "
        "FROM v_deletions WHERE et_date BETWEEN ? AND ? ORDER BY created_at_utc",
        (start, end),
    ).fetchall()
    result = []
    for ts_id, created_at_et, kind, lifetime_min, deletion_window_min, deleted_source, content_text in rows:
        result.append({
            "ts_id": ts_id,
            "created_at_et": created_at_et,
            "kind": kind,
            "lifetime_min": lifetime_min,
            "deletion_window_min": deletion_window_min,
            "deleted_source": deleted_source,
            "snippet": (content_text or "")[:120],
        })
    return result


# ---------------------------------------------------------------------------
# top_reblogged_accounts / link_domains / media_mix
# ---------------------------------------------------------------------------


def top_reblogged_accounts(conn: sqlite3.Connection, start: str, end: str, n: int = 10) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT reblog_of_acct, COUNT(*) AS c FROM v_posts_et "
        "WHERE et_date BETWEEN ? AND ? AND kind = 'reblog' AND reblog_of_acct IS NOT NULL "
        "GROUP BY reblog_of_acct ORDER BY c DESC, reblog_of_acct ASC LIMIT ?",
        (start, end, n),
    ).fetchall()
    return [{"account": acct, "count": c} for acct, c in rows]


def link_domains(conn: sqlite3.Connection, start: str, end: str, n: int = 10) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT card_domain, COUNT(*) AS c FROM v_posts_et "
        "WHERE et_date BETWEEN ? AND ? AND card_domain IS NOT NULL AND card_domain != '' "
        "GROUP BY card_domain ORDER BY c DESC, card_domain ASC LIMIT ?",
        (start, end, n),
    ).fetchall()
    return [{"domain": d, "count": c} for d, c in rows]


def media_mix(conn: sqlite3.Connection, start: str, end: str) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT media_count, media_types FROM v_posts_et WHERE et_date BETWEEN ? AND ?",
        (start, end),
    ).fetchall()
    no_media = image_only = video_only = mixed = 0
    for media_count, media_types in rows:
        if not media_count:
            no_media += 1
            continue
        types = set(t for t in (media_types or "").split(",") if t)
        if types == {"image"}:
            image_only += 1
        elif types == {"video"}:
            video_only += 1
        else:
            mixed += 1
    type_rows = conn.execute(
        "SELECT m.type, COUNT(*) FROM media m JOIN v_posts_et p ON p.ts_id = m.ts_id "
        "WHERE p.et_date BETWEEN ? AND ? GROUP BY m.type",
        (start, end),
    ).fetchall()
    return {
        "no_media": no_media,
        "image_only": image_only,
        "video_only": video_only,
        "mixed": mixed,
        "media_items_by_type": {t: c for t, c in type_rows},
    }


# ---------------------------------------------------------------------------
# engagement_stats
# ---------------------------------------------------------------------------


def engagement_stats(conn: sqlite3.Connection, start: str, end: str) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT p.kind, e.favourites, e.reblogs, e.replies FROM v_posts_et p "
        "JOIN v_engagement_latest e ON e.ts_id = p.ts_id WHERE p.et_date BETWEEN ? AND ?",
        (start, end),
    ).fetchall()
    by_kind: Dict[str, Dict[str, Any]] = {}
    for kind, favourites, reblogs, replies in rows:
        entry = by_kind.setdefault(kind, {"n": 0, "favourites": [], "reblogs": [], "replies": []})
        entry["n"] += 1
        if favourites is not None:
            entry["favourites"].append(favourites)
        if reblogs is not None:
            entry["reblogs"].append(reblogs)
        if replies is not None:
            entry["replies"].append(replies)

    result: Dict[str, Any] = {}
    for kind, entry in by_kind.items():
        stat: Dict[str, Any] = {"n": entry["n"]}
        for field in ("favourites", "reblogs", "replies"):
            vals = sorted(entry[field])
            stat[field] = {"median": _percentile(vals, 50), "p90": _percentile(vals, 90)}
        result[kind] = stat
    return result


# ---------------------------------------------------------------------------
# longest_silence / edits
# ---------------------------------------------------------------------------


def longest_silence(conn: sqlite3.Connection, start: str, end: str) -> Optional[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT created_at_utc, created_at_et FROM v_posts_et WHERE et_date BETWEEN ? AND ? "
        "ORDER BY created_at_utc",
        (start, end),
    ).fetchall()
    if len(rows) < 2:
        return None
    best_gap = None
    best_from_et = None
    best_to_et = None
    for (utc1, et1), (utc2, et2) in zip(rows, rows[1:]):
        gap = (parse_iso_utc(utc2) - parse_iso_utc(utc1)).total_seconds() / 60.0
        if best_gap is None or gap > best_gap:
            best_gap = gap
            best_from_et = et1
            best_to_et = et2
    return {"gap_min": best_gap, "from_et": best_from_et, "to_et": best_to_et}


def edits(conn: sqlite3.Connection, start: str, end: str) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT ts_id, created_at_et, kind, edited_at FROM v_posts_et "
        "WHERE et_date BETWEEN ? AND ? AND edited_at IS NOT NULL ORDER BY created_at_utc",
        (start, end),
    ).fetchall()
    items = [{"ts_id": r[0], "created_at_et": r[1], "kind": r[2], "edited_at": r[3]} for r in rows]
    return {"count": len(items), "rows": items}


# ---------------------------------------------------------------------------
# baseline / iso_week_bounds
# ---------------------------------------------------------------------------


def _report(conn: sqlite3.Connection, start: str, end: str) -> Dict[str, Any]:
    return {
        "posts_by_day": posts_by_day(conn, start, end),
        "hour_histogram": hour_histogram(conn, start, end),
        "overnight_share": overnight_share(conn, start, end),
        "bursts": bursts(conn, start, end),
        "deletions": deletions(conn, start, end),
        "top_reblogged_accounts": top_reblogged_accounts(conn, start, end),
        "link_domains": link_domains(conn, start, end),
        "media_mix": media_mix(conn, start, end),
        "engagement_stats": engagement_stats(conn, start, end),
        "longest_silence": longest_silence(conn, start, end),
        "edits": edits(conn, start, end),
    }


def baseline(conn: sqlite3.Connection, start: str, end: str, trailing_weeks: int = 8) -> Dict[str, Any]:
    start_date = _parse_date(start)
    trailing_end_date = start_date - timedelta(days=1)
    trailing_start_date = trailing_end_date - timedelta(days=trailing_weeks * 7 - 1)
    trailing_start = trailing_start_date.isoformat()
    trailing_end = trailing_end_date.isoformat()

    return {
        "window": _report(conn, start, end),
        "trailing": _report(conn, trailing_start, trailing_end),
        "meta": {"start": start, "end": end, "trailing_start": trailing_start, "trailing_end": trailing_end},
    }


def iso_week_bounds(week: str) -> Tuple[str, str]:
    """``"2026-W37" -> ("2026-09-07", "2026-09-13")`` (Monday..Sunday, ISO week date rules)."""
    year_str, week_str = week.split("-W")
    year = int(year_str)
    week_no = int(week_str)
    monday = date.fromisocalendar(year, week_no, 1)
    sunday = date.fromisocalendar(year, week_no, 7)
    return (monday.isoformat(), sunday.isoformat())
