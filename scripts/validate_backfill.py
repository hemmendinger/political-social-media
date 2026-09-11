"""One-time cross-source validation after the history backfill (plan: "Backfill validation").

Compares the CNN archive JSON (as downloaded) with the merged records in data/ and prints a report:
id overlap, kind agreement, created_at agreement, content agreement on a random sample, and the posts known to only
one source. Paste the summary into MISTAKES.md.

Usage: python -m scripts.validate_backfill --cnn data/raw/truth_archive.json [--data-root data] [--sample 300] [--seed 1]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Dict, List

from scripts.common import parse_iso_utc
from scripts.parsers import cnn_row_to_partial
from scripts.store import load_posts_index

_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm(text: str, n: int = 60) -> str:
    return _NORM_RE.sub("", (text or "").lower())[:n]


def validate(cnn_rows: List[dict], index: Dict[str, dict], sample: int = 300, seed: int = 1) -> dict:
    cnn_by_id = {str(r["id"]): r for r in cnn_rows}
    ids_cnn = set(cnn_by_id)
    ids_records = set(index)
    both = ids_cnn & ids_records
    only_cnn = ids_cnn - ids_records
    tt_only = {k for k, r in index.items() if "trumpstruth" in r["seen_sources"] and "cnn" not in r["seen_sources"]}

    kind_pairs: Counter = Counter()
    created_disagree = []
    for ts_id in both:
        rec = index[ts_id]
        guess = cnn_row_to_partial(cnn_by_id[ts_id])
        kind_pairs[(guess["kind"], rec["kind"])] += 1
        try:
            delta = abs(parse_iso_utc(guess["created_at_utc"]) - parse_iso_utc(rec["created_at_utc"]))
        except ValueError:
            delta = timedelta(days=999)
        if delta > timedelta(seconds=2):
            created_disagree.append((ts_id, guess["created_at_utc"], rec["created_at_utc"]))

    rng = random.Random(seed)
    candidates = sorted(i for i in both if (cnn_by_id[i].get("content") or "").strip())
    picked = rng.sample(candidates, min(sample, len(candidates)))
    content_agree, content_mismatch = 0, []
    for ts_id in picked:
        guess = cnn_row_to_partial(cnn_by_id[ts_id])
        rec = index[ts_id]
        a, b = _norm(guess.get("content_text", "")), _norm(rec.get("content_text", ""))
        if a and b and (a == b or a.startswith(b) or b.startswith(a)):
            content_agree += 1
        else:
            content_mismatch.append((ts_id, (guess.get("content_text") or "")[:70], (rec.get("content_text") or "")[:70]))

    source_combos = Counter("+".join(r["seen_sources"]) for r in index.values())
    return {
        "counts": {
            "cnn_rows": len(ids_cnn),
            "records": len(ids_records),
            "in_both": len(both),
            "only_cnn": len(only_cnn),
            "trumpstruth_not_cnn": len(tt_only),
            "by_source_combination": dict(source_combos),
            "by_status": dict(Counter(r["status"] for r in index.values())),
            "by_kind": dict(Counter(r["kind"] for r in index.values())),
        },
        "kind_agreement": {"%s->%s" % k: v for k, v in sorted(kind_pairs.items())},
        "created_at_disagreements": {"count": len(created_disagree), "sample": created_disagree[:10]},
        "content_sample": {
            "sampled": len(picked),
            "agree": content_agree,
            "mismatch_sample": content_mismatch[:15],
        },
        "only_cnn_sample": sorted(only_cnn)[:20],
        "trumpstruth_not_cnn_sample": sorted(tt_only)[:20],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cnn", required=True, help="path to the downloaded truth_archive.json")
    ap.add_argument("--data-root", default="data")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json", help="also write the full report to this path")
    args = ap.parse_args(argv)
    cnn_rows = json.load(open(args.cnn, encoding="utf-8"))
    index = load_posts_index(Path(args.data_root))
    report = validate(cnn_rows, index, sample=args.sample, seed=args.seed)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    c = report["counts"]
    print("CNN rows %d | records %d | in both %d | only CNN %d | trumpstruth-not-CNN %d"
          % (c["cnn_rows"], c["records"], c["in_both"], c["only_cnn"], c["trumpstruth_not_cnn"]))
    print("by source combination:", c["by_source_combination"])
    print("by status:", c["by_status"], "| by kind:", c["by_kind"])
    print("kind agreement (cnn guess -> record):", report["kind_agreement"])
    print("created_at disagreements > 2 s:", report["created_at_disagreements"]["count"])
    cs = report["content_sample"]
    print("content sample: %d/%d agree" % (cs["agree"], cs["sampled"]))
    for row in cs["mismatch_sample"][:5]:
        print("   mismatch", row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
