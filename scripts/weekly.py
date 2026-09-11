"""Weekly baseline report: renders ``baseline()`` into markdown + CSV (docs/SPEC.md section 11).

CLI: ``python -m scripts.weekly (--week 2026-W37 | --start YYYY-MM-DD --end YYYY-MM-DD)
[--db PATH] [--out DIR]``. ``render_markdown`` is exposed separately so tests (and callers who
already have a baseline dict) don't need a database.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from scripts.metrics import baseline, iso_week_bounds

CAVEATS = (
    "**Caveats.** Deletion is an interval, not a point: `deleted_lower` is the last moment a post was "
    "confirmed live and `deleted_upper` is the first moment it was confirmed gone, so lifetime and "
    "deletion-window minutes are bounds around the true deletion time, not exact figures. Posts seen only "
    "in archives from before polling began are presumed live and are not individually re-verified; a post "
    "flips from deleted back to present only if the API returns it again. Engagement counts are snapshots "
    "taken at observation time (at most one per post per hour, and only one baseline row for posts already "
    "over two weeks old when first observed), never final totals."
)

_DAY_COLUMNS = ["et_date", "original", "quote", "reblog", "reply", "total", "deleted"]


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------


def _num(x: Any) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return "%.1f" % x
    return str(x)


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else "%.1f%%" % (x * 100.0)


def _total_posts(report: Dict[str, Any]) -> int:
    return sum(day["total"] for day in report["posts_by_day"])


def _bar_chart(hist: Sequence[int], width: int = 30) -> str:
    peak = max(hist) if hist else 0
    lines = []
    for hour in range(24):
        n = hist[hour]
        bar_len = 0 if peak == 0 else round((n / peak) * width)
        lines.append("%02d:00  %s %d" % (hour, "#" * bar_len, n))
    return "\n".join(lines)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_num(v) for v in row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def render_markdown(baseline_dict: Dict[str, Any]) -> str:
    meta = baseline_dict["meta"]
    window = baseline_dict["window"]
    trailing = baseline_dict["trailing"]

    trailing_days = max(1, len(trailing["posts_by_day"]))
    trailing_weeks = trailing_days / 7.0
    trailing_total = _total_posts(trailing)
    trailing_weekly_avg = trailing_total / trailing_weeks if trailing_weeks else 0.0
    window_total = _total_posts(window)

    parts: List[str] = []
    parts.append("# Weekly report: %s to %s" % (meta["start"], meta["end"]))
    parts.append("")

    parts.append("## Headline")
    parts.append(
        "- Posts this window (%s to %s): **%d**" % (meta["start"], meta["end"], window_total)
    )
    parts.append(
        "- Trailing weekly average (%s to %s, %.1f weeks): **%.1f**"
        % (meta["trailing_start"], meta["trailing_end"], trailing_weeks, trailing_weekly_avg)
    )
    parts.append("")

    parts.append("## Posts by day")
    parts.append(_table(_DAY_COLUMNS, [[d[c] for c in _DAY_COLUMNS] for d in window["posts_by_day"]]))
    parts.append("")

    parts.append("## Hour histogram (ET)")
    parts.append("```")
    parts.append(_bar_chart(window["hour_histogram"]))
    parts.append("```")
    parts.append("")

    ov = window["overnight_share"]
    parts.append("## Overnight share")
    parts.append(
        "- Overnight (00:00-05:59 ET): %d of %d posts (%s)" % (ov["overnight"], ov["total"], _pct(ov["share"]))
    )
    parts.append("")

    parts.append("## Bursts")
    if window["bursts"]:
        rows = [[b["start_et"], b["end_et"], b["count"], json.dumps(b["kinds"], sort_keys=True)] for b in window["bursts"]]
        parts.append(_table(["start_et", "end_et", "count", "kinds"], rows))
    else:
        parts.append("None.")
    parts.append("")

    parts.append("## Deletions")
    if window["deletions"]:
        rows = [
            [d["ts_id"], d["created_at_et"], d["kind"], d["lifetime_min"], d["deletion_window_min"],
             d["deleted_source"], d["snippet"]]
            for d in window["deletions"]
        ]
        parts.append(_table(
            ["ts_id", "created_at_et", "kind", "lifetime_min", "deletion_window_min", "deleted_source", "snippet"],
            rows,
        ))
    else:
        parts.append("None.")
    parts.append("")

    parts.append("## Top reblogged accounts")
    if window["top_reblogged_accounts"]:
        rows = [[a["account"], a["count"]] for a in window["top_reblogged_accounts"]]
        parts.append(_table(["account", "count"], rows))
    else:
        parts.append("None.")
    parts.append("")

    parts.append("## Link domains")
    if window["link_domains"]:
        rows = [[d["domain"], d["count"]] for d in window["link_domains"]]
        parts.append(_table(["domain", "count"], rows))
    else:
        parts.append("None.")
    parts.append("")

    mm = window["media_mix"]
    parts.append("## Media mix")
    parts.append(_table(
        ["no_media", "image_only", "video_only", "mixed"],
        [[mm["no_media"], mm["image_only"], mm["video_only"], mm["mixed"]]],
    ))
    if mm["media_items_by_type"]:
        parts.append("")
        parts.append(_table(
            ["media_type", "count"],
            [[t, c] for t, c in sorted(mm["media_items_by_type"].items())],
        ))
    parts.append("")

    parts.append("## Engagement stats")
    es = window["engagement_stats"]
    if es:
        rows = []
        for kind in sorted(es):
            s = es[kind]
            rows.append([
                kind, s["n"],
                s["favourites"]["median"], s["favourites"]["p90"],
                s["reblogs"]["median"], s["reblogs"]["p90"],
                s["replies"]["median"], s["replies"]["p90"],
            ])
        parts.append(_table(
            ["kind", "n", "favourites_median", "favourites_p90", "reblogs_median", "reblogs_p90",
             "replies_median", "replies_p90"],
            rows,
        ))
    else:
        parts.append("None.")
    parts.append("")

    parts.append("## Longest silence")
    ls = window["longest_silence"]
    if ls:
        parts.append("- %.1f minutes, from %s to %s" % (ls["gap_min"], ls["from_et"], ls["to_et"]))
    else:
        parts.append("Fewer than two posts in this window.")
    parts.append("")

    ed = window["edits"]
    parts.append("## Edits")
    parts.append("- %d edited post(s) in this window." % ed["count"])
    if ed["rows"]:
        rows = [[r["ts_id"], r["created_at_et"], r["kind"], r["edited_at"]] for r in ed["rows"]]
        parts.append(_table(["ts_id", "created_at_et", "kind", "edited_at"], rows))
    parts.append("")

    parts.append("## Caveats")
    parts.append(CAVEATS)
    parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def _csv_table(name: str, report: Dict[str, Any]) -> Tuple[List[str], List[List[Any]]]:
    if name == "posts_by_day":
        return _DAY_COLUMNS, [[d[c] for c in _DAY_COLUMNS] for d in report["posts_by_day"]]
    if name == "hour_histogram":
        return ["et_hour", "count"], [[h, c] for h, c in enumerate(report["hour_histogram"])]
    if name == "bursts":
        return (
            ["start_et", "end_et", "count", "kinds"],
            [[b["start_et"], b["end_et"], b["count"], json.dumps(b["kinds"], sort_keys=True)] for b in report["bursts"]],
        )
    if name == "deletions":
        cols = ["ts_id", "created_at_et", "kind", "lifetime_min", "deletion_window_min", "deleted_source", "snippet"]
        return cols, [[d[c] for c in cols] for d in report["deletions"]]
    if name == "top_reblogged_accounts":
        return ["account", "count"], [[a["account"], a["count"]] for a in report["top_reblogged_accounts"]]
    if name == "link_domains":
        return ["domain", "count"], [[d["domain"], d["count"]] for d in report["link_domains"]]
    if name == "media_mix":
        mm = report["media_mix"]
        rows = [
            ["no_media", mm["no_media"]], ["image_only", mm["image_only"]],
            ["video_only", mm["video_only"]], ["mixed", mm["mixed"]],
        ]
        rows.extend(["media_type:%s" % t, c] for t, c in sorted(mm["media_items_by_type"].items()))
        return ["metric", "value"], rows
    if name == "engagement_stats":
        cols = ["kind", "n", "favourites_median", "favourites_p90", "reblogs_median", "reblogs_p90",
                "replies_median", "replies_p90"]
        rows = []
        for kind in sorted(report["engagement_stats"]):
            s = report["engagement_stats"][kind]
            rows.append([
                kind, s["n"], s["favourites"]["median"], s["favourites"]["p90"],
                s["reblogs"]["median"], s["reblogs"]["p90"], s["replies"]["median"], s["replies"]["p90"],
            ])
        return cols, rows
    raise ValueError("unknown table %r" % name)


_CSV_TABLES = (
    "posts_by_day", "hour_histogram", "bursts", "deletions",
    "top_reblogged_accounts", "link_domains", "media_mix", "engagement_stats",
)


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _label_and_bounds(args: argparse.Namespace) -> Tuple[str, str, str]:
    if args.week:
        start, end = iso_week_bounds(args.week)
        return args.week, start, end
    return "%s_%s" % (args.start, args.end), args.start, args.end


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.weekly")
    parser.add_argument("--week", help="ISO week, e.g. 2026-W37")
    parser.add_argument("--start", help="ET start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", help="ET end date YYYY-MM-DD (inclusive)")
    parser.add_argument("--db", type=Path, default=Path("data/truths.sqlite"))
    parser.add_argument("--out", type=Path, default=Path("output/reports"))
    args = parser.parse_args(argv)

    if args.week and (args.start or args.end):
        parser.error("pass either --week or --start/--end, not both")
    if not args.week and not (args.start and args.end):
        parser.error("pass either --week or both --start and --end")

    label, start, end = _label_and_bounds(args)

    conn = sqlite3.connect(str(args.db))
    try:
        result = baseline(conn, start, end)
    finally:
        conn.close()

    args.out.mkdir(parents=True, exist_ok=True)
    md_path = args.out / (label + ".md")
    md_path.write_text(render_markdown(result), encoding="utf-8")

    window = result["window"]
    for name in _CSV_TABLES:
        columns, rows = _csv_table(name, window)
        _write_csv(args.out / ("%s__%s.csv" % (label, name)), columns, rows)

    print("wrote %s" % md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
