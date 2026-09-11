"""Reconciliation: merge a source partial into an existing post record.

Pure functions only -- no network, no clock, no I/O. See docs/SPEC.md section 7 for the
rules this module implements (section 2 defines the record, section 1 the source precedence).
Python 3.9 compatible.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from scripts.common import et_fields, html_to_text, normalize_iso, parse_iso_utc

# ---------------------------------------------------------------------------
# Record shape and precedence tables
# ---------------------------------------------------------------------------

# Ordered exactly as docs/SPEC.md section 2.
RECORD_FIELDS: List[str] = [
    "ts_id",
    "created_at_utc",
    "created_at_et",
    "et_date",
    "et_hour",
    "et_dow",
    "kind",
    "content_html",
    "content_text",
    "lang",
    "in_reply_to_id",
    "quote_id",
    "quote_of_acct",
    "reblog_of_id",
    "reblog_of_acct",
    "reblog_of_created_at",
    "media",
    "card_url",
    "card_domain",
    "card_title",
    "mentions",
    "tags",
    "edited_at",
    "pinned",
    "first_seen_at",
    "first_seen_source",
    "seen_sources",
    "status",
    "last_verified_live_at",
    "deleted_lower",
    "deleted_upper",
    "deleted_source",
    "trumpstruth_id",
    "trumpstruth_captured_at",
    "trumpstruth_removed_at",
    "field_sources",
    "raw_api",
    "updated_at",
    "updated_run_id",
]

# Source precedence for the generic scalar/content/media rule (section 7 rule 3).
SOURCE_RANK: Dict[str, int] = {"api": 3, "trumpstruth": 2, "cnn": 1}

# Source precedence just for created_at_utc (section 1: api > cnn > trumpstruth).
CREATED_AT_RANK: Dict[str, int] = {"api": 3, "cnn": 2, "trumpstruth": 1}

# Fields merged generically under rule 3 (content_html/content_text/media/created_at_utc
# each get their own handling below and are excluded from this list).
SCALAR_FIELDS: List[str] = [
    "kind",
    "lang",
    "in_reply_to_id",
    "quote_id",
    "quote_of_acct",
    "reblog_of_id",
    "reblog_of_acct",
    "reblog_of_created_at",
    "card_url",
    "card_domain",
    "card_title",
    "mentions",
    "tags",
    "edited_at",
    "pinned",
]

_MEDIA_FILL_KEYS: Tuple[str, ...] = ("mirror_url", "preview_url", "width", "height", "duration")

# Fields with str ("") defaults in a fresh record; everything else not special-cased below
# defaults to None (str/null, int/null, object/null fields).
_STR_DEFAULT_FIELDS: FrozenSet[str] = frozenset(
    {
        "created_at_utc",
        "created_at_et",
        "et_date",
        "kind",
        "content_html",
        "content_text",
        "first_seen_at",
        "first_seen_source",
        "updated_at",
        "updated_run_id",
    }
)
_LIST_DEFAULT_FIELDS: FrozenSet[str] = frozenset({"media", "mentions", "tags", "seen_sources"})

_IGNORED_FOR_DIFF: FrozenSet[str] = frozenset({"updated_at", "updated_run_id"})


def new_record(ts_id: str) -> Dict[str, Any]:
    """A fresh §2 record for ``ts_id`` with every field present at its empty default."""
    record: Dict[str, Any] = {}
    for f in RECORD_FIELDS:
        if f == "ts_id":
            record[f] = ts_id
        elif f == "field_sources":
            record[f] = {}
        elif f in _LIST_DEFAULT_FIELDS:
            record[f] = []
        elif f in _STR_DEFAULT_FIELDS:
            record[f] = ""
        elif f == "pinned":
            record[f] = False
        elif f == "status":
            record[f] = "present"
        else:
            record[f] = None
    return record


@dataclass
class MergeResult:
    record: Dict[str, Any]
    changed: bool
    is_new: bool
    deletion_event: Optional[Dict[str, Any]]
    anomalies: List[str]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _fmt_value(value: Any) -> str:
    return str(value)[:60]


def _disagreement(field: str, ts_id: str, old_source: str, old_value: Any, new_source: str, new_value: Any) -> str:
    return "{}_disagreement:{}:{}={},{}={}".format(
        field, ts_id, old_source, _fmt_value(old_value), new_source, _fmt_value(new_value)
    )


def _max_null_safe(*values: Optional[str]) -> Optional[str]:
    present = [v for v in values if v]
    return max(present) if present else None


def _min_null_safe(*values: Optional[str]) -> Optional[str]:
    present = [v for v in values if v]
    return min(present) if present else None


def _copy_if_mutable(value: Any) -> Any:
    return deepcopy(value) if isinstance(value, (list, dict)) else value


def _merge_scalar(
    record: Dict[str, Any],
    field: str,
    new_val: Any,
    source: str,
    ts_id: str,
    anomalies: List[str],
) -> None:
    """Generic rule-3 precedence for one field, using SOURCE_RANK.

    An empty incoming value means "unknown", not "cleared": it never overwrites a
    non-empty existing value (regardless of rank or same-source), and is not an anomaly.
    """
    if _is_empty(new_val):
        return
    existing_val = record.get(field)
    existing_source = record["field_sources"].get(field, "cnn")
    if _is_empty(existing_val) or source == existing_source or SOURCE_RANK[source] > SOURCE_RANK[existing_source]:
        record[field] = _copy_if_mutable(new_val)
        record["field_sources"][field] = source
    else:
        if new_val != existing_val:
            anomalies.append(_disagreement(field, ts_id, existing_source, existing_val, source, new_val))


# ---------------------------------------------------------------------------
# Field-specific rules
# ---------------------------------------------------------------------------


def _merge_created_at(
    record: Dict[str, Any], partial: Dict[str, Any], source: str, ts_id: str, anomalies: List[str]
) -> None:
    """Rule 4: created_at_utc precedence via CREATED_AT_RANK with a 2s tolerance."""
    if not partial.get("created_at_utc"):
        return
    new_val = normalize_iso(partial["created_at_utc"])
    existing_val = record.get("created_at_utc")
    existing_source = record["field_sources"].get("created_at_utc", "cnn")
    higher_or_same = (
        _is_empty(existing_val) or source == existing_source or CREATED_AT_RANK[source] > CREATED_AT_RANK[existing_source]
    )
    if higher_or_same:
        record["field_sources"]["created_at_utc"] = source
        if new_val != existing_val:
            record["created_at_utc"] = new_val
            record.update(et_fields(new_val))
    else:
        if not _is_empty(new_val) and new_val != existing_val:
            diff = abs((parse_iso_utc(new_val) - parse_iso_utc(existing_val)).total_seconds())
            if diff > 2:
                anomalies.append(_disagreement("created_at_utc", ts_id, existing_source, existing_val, source, new_val))


def _merge_content(
    record: Dict[str, Any], partial: Dict[str, Any], source: str, ts_id: str, anomalies: List[str]
) -> None:
    """Rule 5: content_html precedence (cascading to content_text) plus the cnn text fill.

    An empty incoming content_html means "unknown", not "cleared": it never overwrites a
    non-empty existing value, is not an anomaly, and never triggers a content_text recompute.
    """
    if "content_html" in partial:
        new_html = partial["content_html"] or ""
        if not _is_empty(new_html):
            existing_html = record.get("content_html", "")
            existing_source = record["field_sources"].get("content_html", "cnn")
            higher_or_same = (
                _is_empty(existing_html) or source == existing_source or SOURCE_RANK[source] > SOURCE_RANK[existing_source]
            )
            if higher_or_same:
                record["field_sources"]["content_html"] = source
                if new_html != existing_html:
                    record["content_html"] = new_html
                    record["content_text"] = html_to_text(new_html)
                    record["field_sources"]["content_text"] = source
            else:
                if new_html != existing_html:
                    anomalies.append(_disagreement("content_html", ts_id, existing_source, existing_html, source, new_html))

    # cnn (or any source) supplying content_text directly, with no html of its own: only
    # fills the field while the record's own content_html is still empty.
    if "content_text" in partial and not partial.get("content_html") and not record.get("content_html"):
        _merge_scalar(record, "content_text", partial["content_text"], source, ts_id, anomalies)


def _merge_media(
    record: Dict[str, Any], new_media: List[Dict[str, Any]], source: str, ts_id: str, anomalies: List[str]
) -> None:
    """Rule 6: list precedence like a scalar, plus same-length null-position enrichment.

    An empty incoming list means "unknown", not "cleared": it never overwrites a non-empty
    existing list, and is not an anomaly.
    """
    if _is_empty(new_media):
        return
    existing_media = record.get("media", [])
    existing_source = record["field_sources"].get("media", "cnn")
    overwrite = (
        _is_empty(existing_media) or source == existing_source or SOURCE_RANK[source] > SOURCE_RANK[existing_source]
    )
    if overwrite:
        kept = deepcopy(new_media)
        other = existing_media
        record["field_sources"]["media"] = source
    else:
        if new_media != existing_media:
            anomalies.append(_disagreement("media", ts_id, existing_source, existing_media, source, new_media))
        kept = deepcopy(existing_media)
        other = new_media

    if len(kept) == len(other) and kept:
        for i, item in enumerate(kept):
            other_item = other[i] if isinstance(other[i], dict) else {}
            if not isinstance(item, dict):
                continue
            for key in _MEDIA_FILL_KEYS:
                if item.get(key) is None and other_item.get(key) is not None:
                    item[key] = other_item[key]

    record["media"] = kept


def _apply_deletion_signal(
    record: Dict[str, Any],
    partial: Dict[str, Any],
    source: str,
    observed_at: str,
    ts_id: str,
    anomalies: List[str],
) -> None:
    """Rules 7-8: status -> deleted, and the deletion bound bookkeeping."""
    lower_candidates = [
        record.get("last_verified_live_at"),
        partial.get("last_verified_live_at"),
        # trumpstruth Capture Date is only their last processing time (removed pages get re-processed too),
        # so it is never evidence of the post being alive; creation time is the safe floor from that source.
        record.get("created_at_utc") or partial.get("created_at_utc"),
    ]
    lower_candidates = [normalize_iso(v) for v in lower_candidates if v]
    incoming_lower = max(lower_candidates) if lower_candidates else None

    if partial.get("removed"):
        incoming_upper = normalize_iso(partial["trumpstruth_removed_at"]) if partial.get("trumpstruth_removed_at") else None
        deleted_source_value = "trumpstruth"
    else:  # api_404
        incoming_upper = observed_at
        deleted_source_value = "api404"

    merged_lower = _max_null_safe(record.get("deleted_lower"), incoming_lower)
    merged_upper = _min_null_safe(record.get("deleted_upper"), incoming_upper)
    record["deleted_lower"] = merged_lower
    record["deleted_upper"] = merged_upper
    if merged_lower is not None and merged_upper is not None and merged_lower > merged_upper:
        anomalies.append("inverted_bounds:{}".format(ts_id))
    if record.get("deleted_source") is None:
        record["deleted_source"] = deleted_source_value
    record["status"] = "deleted"


def _apply_live_sighting(record: Dict[str, Any], observed_at: str, prev_status: str, ts_id: str, anomalies: List[str]) -> None:
    """Rule 9 (last_verified_live_at) and rule 7's resurrection (api only)."""
    record["last_verified_live_at"] = _max_null_safe(record.get("last_verified_live_at"), observed_at)
    if prev_status == "deleted":
        record["status"] = "present"
        anomalies.append("resurrected:{}".format(ts_id))


def _apply_trumpstruth_meta(record: Dict[str, Any], partial: Dict[str, Any]) -> None:
    """Rule 10: trumpstruth_id/captured_at latest-wins; trumpstruth_removed_at set once."""
    if partial.get("trumpstruth_id") is not None:
        record["trumpstruth_id"] = partial["trumpstruth_id"]
    if partial.get("trumpstruth_captured_at"):
        record["trumpstruth_captured_at"] = normalize_iso(partial["trumpstruth_captured_at"])
    if partial.get("trumpstruth_removed_at") and record.get("trumpstruth_removed_at") is None:
        record["trumpstruth_removed_at"] = normalize_iso(partial["trumpstruth_removed_at"])


def _record_differs(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    for key in RECORD_FIELDS:
        if key in _IGNORED_FOR_DIFF:
            continue
        if a.get(key) != b.get(key):
            return True
    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def merge_partial(
    existing: Optional[Dict[str, Any]],
    partial: Dict[str, Any],
    *,
    source: str,
    observed_at: str,
    run_id: str,
    logged_deletions: FrozenSet[Tuple[str, str]] = frozenset(),
) -> MergeResult:
    """Merge one source partial into ``existing`` (or create a new record).

    ``existing`` is never mutated. ``partial`` keys are §2 field names plus the optional
    ``_source``/``_engagement`` (ignored here), ``removed`` (trumpstruth deletion signal),
    and ``api_404`` (api deletion signal).
    """
    observed_at = normalize_iso(observed_at)
    is_new = existing is None
    ts_id = existing["ts_id"] if existing is not None else partial["ts_id"]
    record = new_record(ts_id) if is_new else deepcopy(existing)
    anomalies: List[str] = []
    prev_status = record.get("status", "present")

    if is_new:
        record["first_seen_at"] = observed_at
        record["first_seen_source"] = source

    record["seen_sources"] = sorted(set(record.get("seen_sources", [])) | {source})

    _merge_created_at(record, partial, source, ts_id, anomalies)

    for field in SCALAR_FIELDS:
        if field in partial:
            _merge_scalar(record, field, partial[field], source, ts_id, anomalies)

    _merge_content(record, partial, source, ts_id, anomalies)

    if "media" in partial:
        _merge_media(record, partial["media"], source, ts_id, anomalies)

    deletion_signal = bool(partial.get("removed")) or bool(partial.get("api_404"))
    if deletion_signal:
        _apply_deletion_signal(record, partial, source, observed_at, ts_id, anomalies)
    elif source == "api":
        _apply_live_sighting(record, observed_at, prev_status, ts_id, anomalies)

    if source == "trumpstruth":
        _apply_trumpstruth_meta(record, partial)

    if source == "api" and "raw_api" in partial:
        record["raw_api"] = deepcopy(partial["raw_api"])

    deletion_event: Optional[Dict[str, Any]] = None
    if deletion_signal and (ts_id, source) not in logged_deletions:
        deletion_event = {
            "ts_id": ts_id,
            "detected_at": observed_at,
            "deleted_lower": record.get("deleted_lower"),
            "deleted_upper": record.get("deleted_upper"),
            "source": source,
            "trumpstruth_removed_at": record.get("trumpstruth_removed_at"),
            "run_id": run_id,
        }

    changed = is_new or _record_differs(record, existing)
    if changed:
        record["updated_at"] = observed_at
        record["updated_run_id"] = run_id
        return MergeResult(record=record, changed=True, is_new=is_new, deletion_event=deletion_event, anomalies=anomalies)
    return MergeResult(record=existing, changed=False, is_new=is_new, deletion_event=deletion_event, anomalies=anomalies)
