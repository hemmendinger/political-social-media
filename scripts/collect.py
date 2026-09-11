"""Orchestrator CLI: ``python -m scripts.collect`` (docs/SPEC.md sections 8 and 12).

Runs the selected collectors (in the fixed order trumpstruth, cnn, api) against one shared
:class:`~scripts.common.Context`, isolating a collector's own failure from the others; runs
``scripts.check_data.run_checks``; then (unless ``--no-export``) rebuilds ``data/truths.sqlite`` and writes
``output/posts.csv`` and ``output/metrics.json``.

``run_all`` and ``write_exports`` are exposed separately from ``main`` so tests can drive them directly
against an in-memory ``Context`` without going through argument parsing, process locking, or real
transports.

Only the standard library is used. Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sqlite3
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from scripts import build_db, check_data, collect_api, collect_archive, collect_trumpstruth, metrics, store
from scripts.common import EASTERN, Context, CurlCffiTransport, Http, SystemClock, UrllibTransport, new_run_id

log = logging.getLogger(__name__)

SOURCE_ORDER = ["trumpstruth", "cnn", "api"]
LOCK_MAX_AGE = timedelta(minutes=30)

POSTS_CSV_COLUMNS = [
    "ts_id", "created_at_utc", "created_at_et", "et_date", "et_hour", "et_dow", "kind", "status",
    "content_text", "media_count", "media_types", "card_domain", "reblog_of_acct", "reblog_of_id",
    "quote_of_acct", "quote_id", "deleted_lower", "deleted_upper", "deleted_source",
    "first_seen_source", "seen_sources", "trumpstruth_id",
]


# ---------------------------------------------------------------------------
# run_all: run the selected collectors + checks against an already-built Context
# ---------------------------------------------------------------------------


def _failure_row(ctx: Context, source: str, started_at: str, exc: Exception) -> Dict[str, Any]:
    return {
        "run_id": ctx.run_id,
        "source": source,
        "started_at": started_at,
        "finished_at": ctx.now_iso(),
        "ok": False,
        "requests": 0,
        "new_posts": 0,
        "updated_posts": 0,
        "deletions_found": 0,
        "errors": 1,
        "notes": ("%s: %s" % (type(exc).__name__, exc))[:500],
    }


def run_all(
    ctx: Context,
    sources: Sequence[str],
    *,
    backfill: bool = False,
    force_cnn: bool = False,
    output_dir: Any = Path("output"),
    no_export: bool = False,
) -> Tuple[int, str]:
    """Run the selected sources, then checks, then (unless ``no_export``) the exports.

    Returns ``(exit_code, summary_line)``. Exit codes per docs/SPEC.md 8/12: 0 clean, 1 if any collector
    raised, 2 if ``check_data`` reported a hard failure (2 wins when both happen).
    """
    output_dir = Path(output_dir)
    selected = [s for s in SOURCE_ORDER if s in sources]

    any_failed = False
    for name in selected:
        started_at = ctx.now_iso()
        try:
            if name == "trumpstruth":
                row = collect_trumpstruth.run(ctx, backfill=backfill)
            elif name == "cnn":
                row = collect_archive.run(ctx, force=force_cnn)
            elif name == "api":
                row = collect_api.run(ctx)
            else:  # pragma: no cover - SOURCE_ORDER is the only source of names
                continue
            log.info("%s: ok=%s notes=%s", name, row.get("ok"), row.get("notes"))
        except Exception as exc:
            log.exception("%s: collector failed", name)
            any_failed = True
            store.append_run(ctx.data_root, _failure_row(ctx, name, started_at, exc))

    api_state = (ctx.state.get("sources", {}) or {}).get("api") or {}
    checks = check_data.run_checks(
        ctx.data_root, run_id=ctx.run_id, api_statuses_count=api_state.get("statuses_count"), now=ctx.clock.now()
    )
    _write_json(output_dir / "checks.json", checks)

    new_posts_total = 0
    deletions_total = 0
    for r in store.load_runs(ctx.data_root):
        if r.get("run_id") == ctx.run_id:
            new_posts_total += r.get("new_posts") or 0
            deletions_total += r.get("deletions_found") or 0

    checks_label = "checks ok" if checks["ok"] else "checks FAILED"
    summary = "collect: +%d posts, +%d deletions, %s" % (new_posts_total, deletions_total, checks_label)

    if not no_export:
        write_exports(ctx, output_dir)

    if not checks["ok"]:
        exit_code = 2
    elif any_failed:
        exit_code = 1
    else:
        exit_code = 0
    return exit_code, summary


# ---------------------------------------------------------------------------
# Exports: sqlite rebuild, posts.csv, metrics.json
# ---------------------------------------------------------------------------


def _post_csv_row(post: Dict[str, Any]) -> Dict[str, Any]:
    media = post.get("media") or []
    return {
        "ts_id": post.get("ts_id"),
        "created_at_utc": post.get("created_at_utc"),
        "created_at_et": post.get("created_at_et"),
        "et_date": post.get("et_date"),
        "et_hour": post.get("et_hour"),
        "et_dow": post.get("et_dow"),
        "kind": post.get("kind"),
        "status": post.get("status"),
        "content_text": post.get("content_text"),
        "media_count": len(media),
        "media_types": ",".join((m.get("type") or "") for m in media),
        "card_domain": post.get("card_domain"),
        "reblog_of_acct": post.get("reblog_of_acct"),
        "reblog_of_id": post.get("reblog_of_id"),
        "quote_of_acct": post.get("quote_of_acct"),
        "quote_id": post.get("quote_id"),
        "deleted_lower": post.get("deleted_lower"),
        "deleted_upper": post.get("deleted_upper"),
        "deleted_source": post.get("deleted_source"),
        "first_seen_source": post.get("first_seen_source"),
        "seen_sources": "|".join(post.get("seen_sources") or []),
        "trumpstruth_id": post.get("trumpstruth_id"),
    }


def write_posts_csv(path: Any, posts: List[Dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(posts, key=lambda p: int(p["ts_id"]))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=POSTS_CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for post in ordered:
            writer.writerow(_post_csv_row(post))


def _write_json(path: Any, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.write("\n")


def write_exports(ctx: Context, output_dir: Any) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    data_root = Path(ctx.data_root)
    db_path = data_root / "truths.sqlite"

    build_db.build(data_root, db_path)

    posts = store.load_posts(data_root)
    write_posts_csv(output_dir / "posts.csv", posts)

    conn = sqlite3.connect(str(db_path))
    try:
        end_date = ctx.clock.now().astimezone(EASTERN).date()
        start_date = end_date - timedelta(days=6)
        baseline = metrics.baseline(conn, start_date.isoformat(), end_date.isoformat())
    finally:
        conn.close()
    _write_json(output_dir / "metrics.json", baseline)


# ---------------------------------------------------------------------------
# Lock file (docs/SPEC.md 8/12): data/.lock, ignored when older than 30 minutes
# ---------------------------------------------------------------------------


def acquire_lock(lock_path: Any) -> bool:
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age <= LOCK_MAX_AGE.total_seconds():
            return False
        try:
            lock_path.unlink()
        except OSError:
            pass
    try:
        with lock_path.open("x", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except FileExistsError:
        return False
    return True


def release_lock(lock_path: Any) -> None:
    try:
        Path(lock_path).unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.collect")
    parser.add_argument("--sources", default="trumpstruth,cnn,api")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--force-cnn", action="store_true")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--summary-file", type=Path, default=None)
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    data_root: Path = args.data_root
    lock_path = data_root / ".lock"
    if not acquire_lock(lock_path):
        print("collect: another run holds the lock (%s); exiting" % lock_path)
        return 1

    try:
        clock = SystemClock()
        http = Http(UrllibTransport(), clock, fallback_transport=CurlCffiTransport())
        state = store.load_state(data_root)
        run_id = new_run_id(clock)
        ctx = Context(http=http, clock=clock, data_root=data_root, state=state, run_id=run_id)

        exit_code, summary = run_all(
            ctx, sources, backfill=args.backfill, force_cnn=args.force_cnn,
            output_dir=args.output_dir, no_export=args.no_export,
        )
        if args.summary_file:
            args.summary_file.parent.mkdir(parents=True, exist_ok=True)
            with args.summary_file.open("w", encoding="utf-8", newline="\n") as f:
                f.write(summary + "\n")
        print(summary)
        return exit_code
    finally:
        release_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
