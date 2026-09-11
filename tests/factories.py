"""Test factories for post/engagement/deletion/run records (docs/SPEC.md section 2, 3)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from scripts.common import et_fields
from scripts.store import append_deletion, append_engagement, append_run, save_posts


def make_post(ts_id: str, created_at_utc: str, **overrides: Any) -> Dict[str, Any]:
    """A complete section-2 post record with sensible defaults, overridable per field."""
    record: Dict[str, Any] = {
        "ts_id": ts_id,
        "created_at_utc": created_at_utc,
        "kind": "original",
        "content_html": "",
        "content_text": "",
        "lang": "en",
        "in_reply_to_id": None,
        "quote_id": None,
        "quote_of_acct": None,
        "reblog_of_id": None,
        "reblog_of_acct": None,
        "reblog_of_created_at": None,
        "media": [],
        "card_url": None,
        "card_domain": None,
        "card_title": None,
        "mentions": [],
        "tags": [],
        "edited_at": None,
        "pinned": False,
        "first_seen_at": created_at_utc,
        "first_seen_source": "api",
        "seen_sources": ["api"],
        "status": "present",
        "last_verified_live_at": None,
        "deleted_lower": None,
        "deleted_upper": None,
        "deleted_source": None,
        "trumpstruth_id": None,
        "trumpstruth_captured_at": None,
        "trumpstruth_removed_at": None,
        "field_sources": {},
        "raw_api": None,
        "updated_at": created_at_utc,
        "updated_run_id": "test",
    }
    record.update(et_fields(created_at_utc))
    record.update(overrides)
    return record


def make_media_item(type_: str, **overrides: Any) -> Dict[str, Any]:
    """A complete media item (all seven §2 keys), for building a post's ``media`` list."""
    item: Dict[str, Any] = {
        "type": type_,
        "url": None,
        "preview_url": None,
        "mirror_url": None,
        "width": None,
        "height": None,
        "duration": None,
    }
    item.update(overrides)
    return item


def make_run_row(run_id: str, started_at: str, **overrides: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "run_id": run_id,
        "source": "trumpstruth",
        "started_at": started_at,
        "finished_at": started_at,
        "ok": True,
        "requests": 1,
        "new_posts": 0,
        "updated_posts": 0,
        "deletions_found": 0,
        "errors": 0,
        "notes": None,
    }
    row.update(overrides)
    return row


def write_dataset(
    tmp_path: Path,
    posts: Iterable[Dict[str, Any]],
    engagement_rows: Sequence[Dict[str, Any]] = (),
    deletions: Iterable[Dict[str, Any]] = (),
    runs: Iterable[Dict[str, Any]] = (),
) -> Path:
    """Save a synthetic dataset through ``scripts.store`` under ``tmp_path``. Returns the data root."""
    save_posts(tmp_path, list(posts))
    if engagement_rows:
        append_engagement(tmp_path, list(engagement_rows))
    for event in deletions:
        append_deletion(tmp_path, event)
    for row in runs:
        append_run(tmp_path, row)
    return tmp_path
