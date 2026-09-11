"""Read/write layer for the ``data/`` directory (docs/SPEC.md section 3).

Every function takes an explicit ``root`` (the data directory, e.g. ``<repo>/data``) so tests can
point at a ``tmp_path`` instead. Standard library only. Python 3.9 compatible.
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List

from scripts.common import parse_iso_utc

_ENGAGEMENT_FIELDS = ["observed_at", "ts_id", "source", "replies", "reblogs", "favourites", "upvotes", "downvotes"]
_ENGAGEMENT_NUMERIC_FIELDS = ("replies", "reblogs", "favourites", "upvotes", "downvotes")
_THROTTLE_INTERVAL = timedelta(minutes=60)
_OLD_POST_THRESHOLD = timedelta(days=14)


def month_of(iso: str) -> str:
    """Return the ``YYYY-MM`` partition key for a canonical UTC timestamp."""
    return parse_iso_utc(iso).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically via a temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _append_jsonl_line(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write(line + "\n")


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# posts/YYYY-MM.jsonl
# ---------------------------------------------------------------------------


def load_posts(root: Path) -> List[Dict[str, Any]]:
    posts_dir = Path(root) / "posts"
    records: List[Dict[str, Any]] = []
    if not posts_dir.exists():
        return records
    for path in sorted(posts_dir.glob("*.jsonl")):
        records.extend(_load_jsonl(path))
    records.sort(key=lambda r: int(r["ts_id"]))
    return records


def load_posts_index(root: Path) -> Dict[str, Dict[str, Any]]:
    return {record["ts_id"]: record for record in load_posts(root)}


def save_posts(root: Path, records: List[Dict[str, Any]]) -> None:
    """Rewrite posts/*.jsonl from ``records``, partitioned by month of created_at_utc.

    Deterministic: sorted by int(ts_id) within each month, compact sorted-key JSON, one
    record per line, trailing newline, atomic replace. Month files left with no records
    are removed.
    """
    posts_dir = Path(root) / "posts"
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        month = month_of(record["created_at_utc"])
        groups.setdefault(month, []).append(record)
    for month_records in groups.values():
        month_records.sort(key=lambda r: int(r["ts_id"]))

    existing_months = set()
    if posts_dir.exists():
        existing_months = {p.stem for p in posts_dir.glob("*.jsonl")}

    for stale_month in existing_months - set(groups.keys()):
        (posts_dir / (stale_month + ".jsonl")).unlink()

    for month, month_records in groups.items():
        lines = (
            json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for r in month_records
        )
        text = "".join(line + "\n" for line in lines)
        _atomic_write_text(posts_dir / (month + ".jsonl"), text)


# ---------------------------------------------------------------------------
# deletions.jsonl (append-only)
# ---------------------------------------------------------------------------


def append_deletion(root: Path, event: Dict[str, Any]) -> None:
    _append_jsonl_line(Path(root) / "deletions.jsonl", event)


def load_deletions(root: Path) -> List[Dict[str, Any]]:
    return _load_jsonl(Path(root) / "deletions.jsonl")


# ---------------------------------------------------------------------------
# engagement/YYYY-MM.csv (append-only)
# ---------------------------------------------------------------------------


def _blank(value: Any) -> Any:
    return "" if value is None else value


def append_engagement(root: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    eng_dir = Path(root) / "engagement"
    eng_dir.mkdir(parents=True, exist_ok=True)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(month_of(row["observed_at"]), []).append(row)

    for month, month_rows in groups.items():
        path = eng_dir / (month + ".csv")
        is_new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            if is_new:
                writer.writerow(_ENGAGEMENT_FIELDS)
            for row in month_rows:
                writer.writerow([_blank(row.get(name)) for name in _ENGAGEMENT_FIELDS])


def load_engagement(root: Path) -> List[Dict[str, Any]]:
    eng_dir = Path(root) / "engagement"
    rows: List[Dict[str, Any]] = []
    if not eng_dir.exists():
        return rows
    for path in sorted(eng_dir.glob("*.csv")):
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                row: Dict[str, Any] = {
                    "observed_at": raw["observed_at"],
                    "ts_id": raw["ts_id"],
                    "source": raw["source"],
                }
                for name in _ENGAGEMENT_NUMERIC_FIELDS:
                    value = raw.get(name)
                    row[name] = int(value) if value not in (None, "") else None
                rows.append(row)
    return rows


def latest_engagement_times(root: Path) -> Dict[str, str]:
    """Latest ``observed_at`` (any source) per ts_id, as canonical UTC ISO strings."""
    latest: Dict[str, str] = {}
    for row in load_engagement(root):
        ts_id = row["ts_id"]
        observed_at = row["observed_at"]
        if ts_id not in latest or observed_at > latest[ts_id]:
            latest[ts_id] = observed_at
    return latest


def filter_engagement(
    root: Path, rows: List[Dict[str, Any]], post_created_at: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Apply the engagement throttle (docs/SPEC.md section 3) to a candidate batch.

    Skips a row when the post's latest existing row (on disk, or an earlier row already
    accepted from this same batch) is less than 60 minutes older than ``observed_at``.
    A post that is more than 14 days old at observation time only ever gets a row if it
    has none yet (on disk or earlier in this batch) -- this gives a backfill exactly one
    baseline row per historical post, regardless of the 60-minute gap.
    """
    existing_latest = latest_engagement_times(root)
    existing_dt = {ts_id: parse_iso_utc(observed_at) for ts_id, observed_at in existing_latest.items()}
    batch_latest: Dict[str, Any] = {}
    accepted: List[Dict[str, Any]] = []

    for row in rows:
        ts_id = row["ts_id"]
        observed_dt = parse_iso_utc(row["observed_at"])

        last_seen = batch_latest.get(ts_id)
        if last_seen is None:
            last_seen = existing_dt.get(ts_id)

        created_at = post_created_at.get(ts_id)
        is_old = created_at is not None and (observed_dt - parse_iso_utc(created_at)) >= _OLD_POST_THRESHOLD

        if is_old:
            skip = last_seen is not None
        else:
            skip = last_seen is not None and (observed_dt - last_seen) < _THROTTLE_INTERVAL

        if not skip:
            accepted.append(row)
            batch_latest[ts_id] = observed_dt

    return accepted


# ---------------------------------------------------------------------------
# runs/YYYY-MM.jsonl (append-only)
# ---------------------------------------------------------------------------


def append_run(root: Path, row: Dict[str, Any]) -> None:
    month = month_of(row["started_at"])
    _append_jsonl_line(Path(root) / "runs" / (month + ".jsonl"), row)


def load_runs(root: Path) -> List[Dict[str, Any]]:
    runs_dir = Path(root) / "runs"
    rows: List[Dict[str, Any]] = []
    if not runs_dir.exists():
        return rows
    for path in sorted(runs_dir.glob("*.jsonl")):
        rows.extend(_load_jsonl(path))
    return rows


# ---------------------------------------------------------------------------
# state.json
# ---------------------------------------------------------------------------


def load_state(root: Path) -> Dict[str, Any]:
    path = Path(root) / "state.json"
    if not path.exists():
        return {"version": 1, "sources": {}}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(root: Path, state: Dict[str, Any]) -> None:
    text = json.dumps(state, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(Path(root) / "state.json", text)
