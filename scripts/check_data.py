"""Integrity checks over ``data/`` (docs/SPEC.md section 9).

``run_checks(data_root, ...) -> dict(ok, hard, soft, stats)`` is a pure function of the files on disk (plus
a few optional externally-sourced numbers to compare against). ``hard`` entries are data-corruption bugs:
if any exist, ``ok`` is False and the CLI exits 2. ``soft`` entries are notable-but-not-corrupt anomalies
worth a human glance; they never affect ``ok``.

Only the standard library is used. Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from scripts import store
from scripts.common import ISO_Z_RE, TS_ID_RE, UTC, parse_iso_utc
from scripts.merge import RECORD_FIELDS

log = logging.getLogger(__name__)

VALID_SOURCES = {"api", "trumpstruth", "cnn"}
VALID_KINDS = {"original", "quote", "reblog", "reply"}
VALID_STATUSES = {"present", "deleted"}
MEDIA_ITEM_KEYS = {"type", "url", "preview_url", "mirror_url", "width", "height", "duration"}
_CREATED_AT_ET_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
_WORD_START_RE = re.compile(r"^\w")

_NULLABLE_TIMESTAMP_FIELDS = (
    "last_verified_live_at", "deleted_lower", "deleted_upper", "trumpstruth_captured_at",
    "trumpstruth_removed_at", "edited_at",
)
_REQUIRED_TIMESTAMP_FIELDS = ("created_at_utc", "first_seen_at", "updated_at")
_SAMPLE_LIMIT = 10


# ---------------------------------------------------------------------------
# Loading (file-provenance-preserving -- store.load_posts() alone loses which
# file/order a record came from, which several hard checks need)
# ---------------------------------------------------------------------------


def _load_post_files(data_root: Path) -> List[Tuple[str, List[Dict[str, Any]]]]:
    posts_dir = data_root / "posts"
    if not posts_dir.exists():
        return []
    out = []
    for path in sorted(posts_dir.glob("*.jsonl")):
        records = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                records.append(json.loads(line))
        out.append((path.stem, records))
    return out


def _resolve_now(now: Optional[Union[str, datetime]]) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=UTC)
    return parse_iso_utc(now)


# ---------------------------------------------------------------------------
# Per-record schema/type validation (hard)
# ---------------------------------------------------------------------------


def _validate_record_schema(r: Dict[str, Any]) -> List[str]:
    ts_id = r.get("ts_id")
    problems = []
    missing = [f for f in RECORD_FIELDS if f not in r]
    if missing:
        problems.append("missing_fields:%s:%s" % (ts_id, ",".join(missing)))
        return problems  # further checks assume presence

    if not isinstance(ts_id, str) or not TS_ID_RE.match(ts_id):
        problems.append("bad_ts_id:%r" % (ts_id,))

    for field in _REQUIRED_TIMESTAMP_FIELDS:
        v = r.get(field)
        if not isinstance(v, str) or not ISO_Z_RE.match(v):
            problems.append("bad_timestamp:%s:%s=%r" % (ts_id, field, v))
    for field in _NULLABLE_TIMESTAMP_FIELDS:
        v = r.get(field)
        if v is not None and (not isinstance(v, str) or not ISO_Z_RE.match(v)):
            problems.append("bad_timestamp:%s:%s=%r" % (ts_id, field, v))
    et = r.get("created_at_et")
    if not isinstance(et, str) or not _CREATED_AT_ET_RE.match(et):
        problems.append("bad_timestamp:%s:created_at_et=%r" % (ts_id, et))

    if r.get("kind") not in VALID_KINDS:
        problems.append("bad_kind:%s:%r" % (ts_id, r.get("kind")))
    if r.get("status") not in VALID_STATUSES:
        problems.append("bad_status:%s:%r" % (ts_id, r.get("status")))
    if not isinstance(r.get("et_hour"), int) or not (0 <= r["et_hour"] <= 23):
        problems.append("bad_et_hour:%s:%r" % (ts_id, r.get("et_hour")))
    if not isinstance(r.get("et_dow"), int) or not (0 <= r["et_dow"] <= 6):
        problems.append("bad_et_dow:%s:%r" % (ts_id, r.get("et_dow")))
    if not isinstance(r.get("pinned"), bool):
        problems.append("bad_pinned:%s:%r" % (ts_id, r.get("pinned")))

    media = r.get("media")
    if not isinstance(media, list):
        problems.append("bad_media:%s:not_a_list" % ts_id)
    else:
        for i, item in enumerate(media):
            if not isinstance(item, dict) or set(item.keys()) != MEDIA_ITEM_KEYS:
                problems.append("bad_media_item:%s:%d" % (ts_id, i))

    field_sources = r.get("field_sources")
    if not isinstance(field_sources, dict):
        problems.append("bad_field_sources:%s:not_a_dict" % ts_id)
    else:
        for k, v in field_sources.items():
            if k not in RECORD_FIELDS:
                problems.append("bad_field_sources_key:%s:%r" % (ts_id, k))
            if v not in VALID_SOURCES:
                problems.append("bad_field_sources_value:%s:%s=%r" % (ts_id, k, v))

    return problems


# ---------------------------------------------------------------------------
# run_checks
# ---------------------------------------------------------------------------


def run_checks(
    data_root: Any,
    *,
    run_id: Optional[str] = None,
    api_statuses_count: Optional[int] = None,
    trumpstruth_totals: Optional[Union[Dict[str, Any], int]] = None,
    now: Optional[Union[str, datetime]] = None,
) -> Dict[str, Any]:
    data_root = Path(data_root)
    hard: List[str] = []
    soft: List[str] = []
    now_dt = _resolve_now(now)

    files = _load_post_files(data_root)
    all_records: List[Dict[str, Any]] = []
    index: Dict[str, Dict[str, Any]] = {}
    id_occurrences: Dict[str, List[str]] = defaultdict(list)

    for month, records in files:
        ids_in_file = []
        for r in records:
            ts_id = r.get("ts_id")
            all_records.append(r)
            index[ts_id] = r
            id_occurrences[ts_id].append(month)
            ids_in_file.append(r.get("ts_id"))
            if r.get("created_at_utc"):
                try:
                    actual_month = store.month_of(r["created_at_utc"])
                except (ValueError, KeyError):
                    actual_month = None
                if actual_month is not None and actual_month != month:
                    hard.append("wrong_month_file:%s:file=%s,expected=%s" % (ts_id, month, actual_month))
        if ids_in_file:
            try:
                numeric = [int(x) for x in ids_in_file]
                if numeric != sorted(numeric):
                    hard.append("unsorted_file:%s" % month)
            except (TypeError, ValueError):
                hard.append("unsorted_file:%s:non_numeric_ts_id" % month)

    dup_ids = sorted(tid for tid, months in id_occurrences.items() if len(months) > 1)
    for tid in dup_ids:
        hard.append("duplicate_id:%s:%s" % (tid, ",".join(id_occurrences[tid])))

    for r in all_records:
        hard.extend(_validate_record_schema(r))
        ts_id = r.get("ts_id")
        deleted_upper = r.get("deleted_upper")
        created_at_utc = r.get("created_at_utc")
        if deleted_upper and created_at_utc and isinstance(created_at_utc, str) and isinstance(deleted_upper, str):
            if created_at_utc > deleted_upper:
                hard.append("created_after_deleted_upper:%s:created=%s,deleted_upper=%s" % (ts_id, created_at_utc, deleted_upper))
        deleted_lower = r.get("deleted_lower")
        if deleted_lower and deleted_upper and isinstance(deleted_lower, str) and isinstance(deleted_upper, str):
            if deleted_lower > deleted_upper:
                soft.append("inverted_deletion_bounds:%s:lower=%s,upper=%s" % (ts_id, deleted_lower, deleted_upper))

    # --- deletions.jsonl ---
    deletions = store.load_deletions(data_root)
    seen_deletion_keys = set()
    for d in deletions:
        key = (d.get("ts_id"), d.get("source"))
        if d.get("ts_id") not in index:
            hard.append("deletion_unknown_post:%s:%s" % (d.get("ts_id"), d.get("source")))
        if key in seen_deletion_keys:
            hard.append("duplicate_deletion_event:%s:%s" % key)
        seen_deletion_keys.add(key)

    # --- engagement/*.csv ---
    engagement = store.load_engagement(data_root)
    if any(row.get("ts_id") not in index for row in engagement):
        for row in engagement:
            if row.get("ts_id") not in index:
                hard.append("engagement_unknown_post:%s:%s" % (row.get("ts_id"), row.get("observed_at")))
    by_post: Dict[str, List[str]] = defaultdict(list)
    for row in engagement:
        by_post[row.get("ts_id")].append(row.get("observed_at"))
    for ts_id, times in by_post.items():
        ordered = sorted(t for t in times if t)
        for a, b in zip(ordered, ordered[1:]):
            try:
                delta = parse_iso_utc(b) - parse_iso_utc(a)
            except ValueError:
                continue
            if delta < timedelta(minutes=60):
                hard.append("engagement_too_close:%s:%s,%s" % (ts_id, a, b))

    # --- runs: run_id must exist when given ---
    runs = store.load_runs(data_root)
    if run_id is not None and not any(row.get("run_id") == run_id for row in runs):
        hard.append("missing_run_row:%s" % run_id)

    # --- soft: present count vs api_statuses_count ---
    present_count = sum(1 for r in all_records if r.get("status") == "present")
    deleted_count = sum(1 for r in all_records if r.get("status") == "deleted")
    stats: Dict[str, Any] = {}
    if api_statuses_count is not None:
        diff = abs(present_count - api_statuses_count)
        stats["present_vs_api_statuses_count"] = {
            "present": present_count, "api_statuses_count": api_statuses_count, "diff": diff,
        }
        if diff > 50:
            soft.append(
                "present_count_drift:present=%d,api_statuses_count=%d,diff=%d" % (present_count, api_statuses_count, diff)
            )

    if trumpstruth_totals is not None:
        total_expected = trumpstruth_totals.get("total") if isinstance(trumpstruth_totals, dict) else trumpstruth_totals
        if total_expected is not None:
            local_total = present_count + deleted_count
            diff = abs(local_total - total_expected)
            stats["local_total_vs_trumpstruth_total"] = {
                "local_total": local_total, "trumpstruth_total": total_expected, "diff": diff,
            }
            if diff > 50:
                soft.append(
                    "trumpstruth_total_drift:local_total=%d,trumpstruth_total=%d,diff=%d" % (local_total, total_expected, diff)
                )

    # --- soft: single-source posts older than 24h ---
    single_source_old = sorted(
        r["ts_id"] for r in all_records
        if isinstance(r.get("seen_sources"), list) and len(r["seen_sources"]) == 1
        and isinstance(r.get("created_at_utc"), str)
        and _age(now_dt, r["created_at_utc"]) > timedelta(hours=24)
    )
    stats["single_source_old_posts"] = {"count": len(single_source_old), "sample_ids": single_source_old[:_SAMPLE_LIMIT]}
    if single_source_old:
        soft.append(
            "single_source_old_posts:%d (e.g. %s)" % (len(single_source_old), ", ".join(single_source_old[:_SAMPLE_LIMIT]))
        )

    # --- soft: newest post older than 12h ---
    newest_created_at = max((r["created_at_utc"] for r in all_records if r.get("created_at_utc")), default=None)
    stats["newest_created_at_utc"] = newest_created_at
    if newest_created_at and _age(now_dt, newest_created_at) > timedelta(hours=12):
        soft.append("stale_newest_post:%s" % newest_created_at)

    # --- soft: spike days (count > 3x trailing 28-day median) ---
    spike_days = _spike_days(all_records)
    stats["spike_days"] = spike_days
    if spike_days:
        soft.append("spike_days:%s" % ", ".join("%s(%d)" % (d["et_date"], d["count"]) for d in spike_days))

    # --- soft: cnn_ambiguous_handles ---
    ambiguous_ids = sorted(
        r["ts_id"] for r in all_records
        if r.get("kind") == "reblog"
        and isinstance(r.get("field_sources"), dict)
        and r["field_sources"].get("reblog_of_acct") == "cnn"
        and isinstance(r.get("content_text"), str)
        and _WORD_START_RE.match(r["content_text"])
    )
    stats["cnn_ambiguous_handles"] = {"count": len(ambiguous_ids), "sample_ids": ambiguous_ids[:_SAMPLE_LIMIT]}
    if ambiguous_ids:
        soft.append(
            "cnn_ambiguous_handles:%d (e.g. %s)" % (len(ambiguous_ids), ", ".join(ambiguous_ids[:_SAMPLE_LIMIT]))
        )

    # --- stats: general counts ---
    stats["by_status"] = dict(Counter(r.get("status") for r in all_records))
    stats["by_kind"] = dict(Counter(r.get("kind") for r in all_records))
    stats["by_source_combination"] = dict(
        Counter(",".join(sorted(r.get("seen_sources") or [])) for r in all_records)
    )
    stats["deletions"] = len(deletions)
    stats["engagement_rows"] = len(engagement)
    stats["months_present"] = sorted({month for month, _ in files})
    stats["posts"] = len(all_records)

    return {"ok": len(hard) == 0, "hard": hard, "soft": soft, "stats": stats}


def _age(now_dt: datetime, iso: str) -> timedelta:
    try:
        return now_dt - parse_iso_utc(iso)
    except ValueError:
        return timedelta(0)


def _spike_days(records: Sequence[Dict[str, Any]], trailing_days: int = 28, factor: float = 3.0) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = defaultdict(int)
    for r in records:
        et_date = r.get("et_date")
        if isinstance(et_date, str):
            counts[et_date] += 1
    if not counts:
        return []
    dates = sorted(counts)
    first = datetime.strptime(dates[0], "%Y-%m-%d").date()
    last = datetime.strptime(dates[-1], "%Y-%m-%d").date()
    spikes = []
    d = first
    one_day = timedelta(days=1)
    while d <= last:
        key = d.isoformat()
        count = counts.get(key, 0)
        if count > 0:
            trailing = [counts.get((d - timedelta(days=n)).isoformat(), 0) for n in range(1, trailing_days + 1)]
            median = statistics.median(trailing) if trailing else 0
            if median > 0 and count > factor * median:
                spikes.append({"et_date": key, "count": count, "trailing_median": median})
        d += one_day
    return spikes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.check_data")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("output/checks.json"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run_checks(args.data_root)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    with args.output.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.write("\n")

    if result["hard"]:
        for msg in result["hard"]:
            log.error("HARD: %s", msg)
        return 2
    for msg in result["soft"]:
        log.warning("soft: %s", msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
