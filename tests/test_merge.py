"""Truth-table tests for scripts/merge.py (docs/SPEC.md section 7)."""
from __future__ import annotations

import copy

from scripts.common import et_fields, html_to_text
from scripts.merge import (
    CREATED_AT_RANK,
    RECORD_FIELDS,
    SOURCE_RANK,
    merge_partial,
    new_record,
)

TID = "117238345561593751"
TID2 = "117238345561593999"
TID3 = "117238345562000001"


def _base(source="api", ts_id=TID, observed_at="2026-09-01T00:00:00Z", **fields):
    """A freshly created, minimal 'present' record to build later scenarios on."""
    partial = {"ts_id": ts_id, "created_at_utc": "2026-09-01T00:00:00Z", "kind": "original"}
    partial.update(fields)
    return merge_partial(None, partial, source=source, observed_at=observed_at, run_id="r0").record


# ---------------------------------------------------------------------------
# new_record / new-record-via-merge defaults
# ---------------------------------------------------------------------------


def test_new_record_defaults():
    r = new_record(TID)
    assert set(r.keys()) == set(RECORD_FIELDS)
    assert r["ts_id"] == TID
    assert r["pinned"] is False
    assert r["media"] == []
    assert r["mentions"] == []
    assert r["tags"] == []
    assert r["seen_sources"] == []
    assert r["field_sources"] == {}
    assert r["status"] == "present"
    assert r["raw_api"] is None
    assert r["lang"] is None
    assert r["trumpstruth_id"] is None


def test_new_record_from_api_source():
    partial = {
        "ts_id": TID,
        "created_at_utc": "2026-09-09T00:53:04Z",
        "kind": "original",
        "content_html": "<p>Hello world</p>",
        "lang": "en",
        "media": [],
        "raw_api": {"id": TID},
    }
    result = merge_partial(None, partial, source="api", observed_at="2026-09-09T00:53:10Z", run_id="r1")
    r = result.record
    assert result.is_new is True
    assert result.changed is True
    assert set(r.keys()) == set(RECORD_FIELDS)
    assert r["first_seen_at"] == "2026-09-09T00:53:10Z"
    assert r["first_seen_source"] == "api"
    assert r["seen_sources"] == ["api"]
    assert r["status"] == "present"
    assert r["last_verified_live_at"] == "2026-09-09T00:53:10Z"  # live sighting
    assert r["content_text"] == "Hello world"
    assert r["raw_api"] == {"id": TID}
    # untouched fields keep new_record()'s defaults
    assert r["trumpstruth_id"] is None
    assert r["trumpstruth_captured_at"] is None
    assert r["deleted_lower"] is None
    assert r["updated_at"] == "2026-09-09T00:53:10Z"
    assert r["updated_run_id"] == "r1"


def test_new_record_from_trumpstruth_source():
    partial = {
        "ts_id": TID2,
        "created_at_utc": "2026-09-09T00:53:04Z",
        "kind": "original",
        "content_html": "<p>Hi</p>",
        "trumpstruth_id": 41686,
        "trumpstruth_captured_at": "2026-09-09T01:00:00Z",
    }
    result = merge_partial(None, partial, source="trumpstruth", observed_at="2026-09-09T01:00:05Z", run_id="r1")
    r = result.record
    assert set(r.keys()) == set(RECORD_FIELDS)
    assert r["first_seen_source"] == "trumpstruth"
    assert r["seen_sources"] == ["trumpstruth"]
    assert r["last_verified_live_at"] is None  # not an api sighting
    assert r["trumpstruth_id"] == 41686
    assert r["trumpstruth_captured_at"] == "2026-09-09T01:00:00Z"
    assert r["raw_api"] is None


def test_new_record_from_cnn_source():
    partial = {
        "ts_id": TID3,
        "created_at_utc": "2026-09-09T00:53:04Z",
        "kind": "original",
        "content_text": "Hello from cnn",
    }
    result = merge_partial(None, partial, source="cnn", observed_at="2026-09-09T02:00:00Z", run_id="r1")
    r = result.record
    assert set(r.keys()) == set(RECORD_FIELDS)
    assert r["first_seen_source"] == "cnn"
    assert r["content_html"] == ""
    assert r["content_text"] == "Hello from cnn"  # filled since content_html empty
    assert r["field_sources"]["content_text"] == "cnn"
    assert r["last_verified_live_at"] is None
    assert r["trumpstruth_id"] is None
    assert r["raw_api"] is None


# ---------------------------------------------------------------------------
# seen_sources / first_seen
# ---------------------------------------------------------------------------


def test_seen_sources_union_sorted():
    r = _base(source="cnn")
    r = merge_partial(r, {"ts_id": TID, "kind": "original"}, source="api", observed_at="2026-09-01T01:00:00Z", run_id="r1").record
    r = merge_partial(r, {"ts_id": TID, "kind": "original"}, source="trumpstruth", observed_at="2026-09-01T02:00:00Z", run_id="r2").record
    assert r["seen_sources"] == ["api", "cnn", "trumpstruth"]


def test_first_seen_immutability():
    r0 = _base(source="cnn", observed_at="2026-09-01T00:00:00Z")
    assert r0["first_seen_at"] == "2026-09-01T00:00:00Z"
    assert r0["first_seen_source"] == "cnn"
    r1 = merge_partial(r0, {"ts_id": TID, "kind": "quote"}, source="api", observed_at="2026-09-05T00:00:00Z", run_id="r1").record
    assert r1["first_seen_at"] == "2026-09-01T00:00:00Z"
    assert r1["first_seen_source"] == "cnn"


# ---------------------------------------------------------------------------
# Scalar precedence (rule 3): kind as the representative field
# ---------------------------------------------------------------------------


def test_kind_precedence_higher_source_overwrites():
    r0 = _base(source="trumpstruth", kind="reply")
    assert r0["kind"] == "reply"
    assert r0["field_sources"]["kind"] == "trumpstruth"
    r1 = merge_partial(r0, {"ts_id": TID, "kind": "quote"}, source="api", observed_at="2026-09-01T01:00:00Z", run_id="r1")
    assert r1.record["kind"] == "quote"
    assert r1.record["field_sources"]["kind"] == "api"
    assert r1.anomalies == []


def test_cnn_cannot_overwrite_api_and_anomaly_format_matches_spec_example():
    r0 = _base(source="api", kind="original")
    result = merge_partial(r0, {"ts_id": TID, "kind": "reblog"}, source="cnn", observed_at="2026-09-01T01:00:00Z", run_id="r1")
    assert result.record["kind"] == "original"  # dropped
    assert result.record["field_sources"]["kind"] == "api"
    assert result.anomalies == ["kind_disagreement:{}:api=original,cnn=reblog".format(TID)]


def test_same_source_latest_wins():
    r0 = _base(source="trumpstruth", kind="reply")
    result = merge_partial(r0, {"ts_id": TID, "kind": "quote"}, source="trumpstruth", observed_at="2026-09-01T01:00:00Z", run_id="r1")
    assert result.record["kind"] == "quote"
    assert result.anomalies == []


def test_pinned_bool_disagreement_anomaly():
    r0 = _base(source="api", pinned=True)
    result = merge_partial(r0, {"ts_id": TID, "pinned": False}, source="cnn", observed_at="2026-09-01T01:00:00Z", run_id="r1")
    assert result.record["pinned"] is True
    assert result.anomalies == ["pinned_disagreement:{}:api=True,cnn=False".format(TID)]


def test_mentions_list_precedence_and_empty_never_clears():
    r0 = _base(source="cnn", mentions=["alice"])
    assert r0["mentions"] == ["alice"]
    r1 = merge_partial(r0, {"ts_id": TID, "mentions": ["bob", "carol"]}, source="trumpstruth", observed_at="2026-09-01T01:00:00Z", run_id="r1").record
    assert r1["mentions"] == ["bob", "carol"]
    # an empty incoming value means "unknown", not "cleared": even a higher-ranked source
    # (api > trumpstruth) must not use it to blank out a known, non-empty value, and it is
    # not an anomaly.
    result = merge_partial(r1, {"ts_id": TID, "mentions": []}, source="api", observed_at="2026-09-01T02:00:00Z", run_id="r2")
    assert result.record["mentions"] == ["bob", "carol"]
    assert result.record["field_sources"]["mentions"] == "trumpstruth"  # untouched
    assert result.anomalies == []
    # the only real change from this merge is "api" joining seen_sources
    assert result.changed is True
    assert result.record["seen_sources"] == ["api", "cnn", "trumpstruth"]


# ---------------------------------------------------------------------------
# created_at_utc precedence (rule 4) + et_fields recomputation
# ---------------------------------------------------------------------------


def test_created_at_within_tolerance_is_silently_ignored_when_lower_precedence():
    r0 = _base(source="cnn", **{"created_at_utc": "2026-09-09T00:53:04Z"})
    result = merge_partial(
        r0, {"ts_id": TID, "created_at_utc": "2026-09-09T00:53:05Z"}, source="trumpstruth",
        observed_at="2026-09-01T01:00:00Z", run_id="r1",
    )
    assert result.record["created_at_utc"] == "2026-09-09T00:53:04Z"  # unchanged
    assert result.anomalies == []


def test_created_at_beyond_tolerance_is_anomaly_and_keeps_higher_precedence():
    r0 = _base(source="api", **{"created_at_utc": "2026-09-09T00:53:04Z"})
    result = merge_partial(
        r0, {"ts_id": TID, "created_at_utc": "2026-09-09T00:53:10Z"}, source="cnn",
        observed_at="2026-09-01T01:00:00Z", run_id="r1",
    )
    assert result.record["created_at_utc"] == "2026-09-09T00:53:04Z"
    assert result.anomalies == [
        "created_at_utc_disagreement:{}:api=2026-09-09T00:53:04Z,cnn=2026-09-09T00:53:10Z".format(TID)
    ]


def test_created_at_rank_lets_cnn_beat_trumpstruth():
    r0 = _base(source="trumpstruth", **{"created_at_utc": "2026-09-09T00:53:04Z"})
    assert CREATED_AT_RANK["cnn"] > CREATED_AT_RANK["trumpstruth"]
    result = merge_partial(
        r0, {"ts_id": TID, "created_at_utc": "2026-09-09T00:53:20Z"}, source="cnn",
        observed_at="2026-09-01T01:00:00Z", run_id="r1",
    )
    assert result.record["created_at_utc"] == "2026-09-09T00:53:20Z"
    assert result.record["field_sources"]["created_at_utc"] == "cnn"


def test_created_at_et_fields_recomputation():
    r0 = _base(source="cnn")
    result = merge_partial(
        r0, {"ts_id": TID, "created_at_utc": "2026-09-09T00:53:04Z"}, source="api",
        observed_at="2026-09-09T01:00:00Z", run_id="r1",
    )
    r = result.record
    expected = et_fields("2026-09-09T00:53:04Z")
    assert r["created_at_et"] == expected["created_at_et"] == "2026-09-08T20:53:04-04:00"
    assert r["et_date"] == expected["et_date"] == "2026-09-08"
    assert r["et_hour"] == expected["et_hour"] == 20
    assert r["et_dow"] == expected["et_dow"] == 1  # Tuesday


# ---------------------------------------------------------------------------
# content_html / content_text (rule 5)
# ---------------------------------------------------------------------------


def test_content_html_change_recomputes_content_text():
    r0 = _base(source="api", **{"content_html": "<p>Hello<br>World</p>"})
    assert r0["content_text"] == html_to_text("<p>Hello<br>World</p>")
    result = merge_partial(
        r0, {"ts_id": TID, "content_html": "<p>Updated</p>"}, source="api",
        observed_at="2026-09-01T01:00:00Z", run_id="r1",
    )
    assert result.record["content_text"] == html_to_text("<p>Updated</p>")
    assert result.record["content_text"] == "Updated"


def test_cnn_content_text_fills_only_when_html_empty():
    # html still empty -> fill applies
    r0 = _base(source="cnn")
    assert r0["content_html"] == ""
    r1 = merge_partial(r0, {"ts_id": TID, "content_text": "cnn text"}, source="cnn", observed_at="2026-09-01T01:00:00Z", run_id="r1").record
    assert r1["content_text"] == "cnn text"
    assert r1["field_sources"]["content_text"] == "cnn"

    # html already populated by api -> cnn text must not override the derived text
    r2 = _base(source="api", **{"content_html": "<p>Real</p>"})
    assert r2["content_text"] == "Real"
    r3 = merge_partial(r2, {"ts_id": TID, "content_text": "cnn fallback"}, source="cnn", observed_at="2026-09-01T01:00:00Z", run_id="r1").record
    assert r3["content_text"] == "Real"
    assert r3["field_sources"]["content_text"] == "api"


def test_content_html_empty_never_overwrites_non_empty_even_at_higher_or_same_rank():
    # cross-source: api outranks trumpstruth, but an empty content_html must not wipe real content
    r0 = _base(source="trumpstruth", **{"content_html": "<p>real</p>"})
    assert r0["content_text"] == "real"
    result = merge_partial(r0, {"ts_id": TID, "content_html": ""}, source="api", observed_at="2026-09-01T01:00:00Z", run_id="r1")
    assert result.record["content_html"] == "<p>real</p>"
    assert result.record["content_text"] == "real"
    assert result.record["field_sources"]["content_html"] == "trumpstruth"
    assert result.anomalies == []
    # the only real change from this merge is "api" joining seen_sources
    assert result.changed is True
    assert result.record["seen_sources"] == ["api", "trumpstruth"]

    # same-source: a later, incomplete api observation must not wipe an earlier api value either
    r1 = _base(source="api", **{"content_html": "<p>real</p>"})
    result2 = merge_partial(r1, {"ts_id": TID, "content_html": ""}, source="api", observed_at="2026-09-01T01:00:00Z", run_id="r2")
    assert result2.record["content_html"] == "<p>real</p>"
    assert result2.record["content_text"] == "real"
    assert result2.anomalies == []


def test_cnn_content_text_survives_later_empty_content_html():
    r0 = _base(source="cnn")
    r1 = merge_partial(r0, {"ts_id": TID, "content_text": "cnn text"}, source="cnn", observed_at="2026-09-01T01:00:00Z", run_id="r1").record
    assert r1["content_text"] == "cnn text"
    assert r1["field_sources"]["content_text"] == "cnn"
    # a later trumpstruth (or api) partial arriving with an empty content_html must not
    # recompute (and blank) content_text from that rejected empty value.
    result = merge_partial(r1, {"ts_id": TID, "content_html": ""}, source="trumpstruth", observed_at="2026-09-01T02:00:00Z", run_id="r2")
    assert result.record["content_text"] == "cnn text"
    assert result.record["content_html"] == ""
    assert result.anomalies == []


# ---------------------------------------------------------------------------
# media (rule 6)
# ---------------------------------------------------------------------------


def test_media_same_length_enrichment_on_precedence_win():
    existing_media = [{
        "type": "image", "url": None, "preview_url": "http://prev1",
        "mirror_url": "http://mirror1", "width": None, "height": None, "duration": None,
    }]
    r0 = _base(source="trumpstruth", media=existing_media)
    new_media = [{
        "type": "image", "url": "http://real1", "preview_url": None,
        "mirror_url": None, "width": 800, "height": 600, "duration": None,
    }]
    result = merge_partial(r0, {"ts_id": TID, "media": new_media}, source="api", observed_at="2026-09-01T01:00:00Z", run_id="r1")
    kept = result.record["media"]
    assert kept == [{
        "type": "image", "url": "http://real1", "preview_url": "http://prev1",
        "mirror_url": "http://mirror1", "width": 800, "height": 600, "duration": None,
    }]
    assert result.record["field_sources"]["media"] == "api"


def test_media_disagreement_anomaly_still_enriches_kept_list():
    existing_media = [{
        "type": "video", "url": "http://real2", "preview_url": None,
        "mirror_url": None, "width": None, "height": None, "duration": 30,
    }]
    r0 = _base(source="api", media=existing_media)
    incoming_media = [{
        "type": "video", "url": "http://different", "preview_url": "http://prev2",
        "mirror_url": "http://mirror2", "width": 640, "height": 480, "duration": None,
    }]
    result = merge_partial(r0, {"ts_id": TID, "media": incoming_media}, source="cnn", observed_at="2026-09-01T01:00:00Z", run_id="r1")
    assert len(result.anomalies) == 1
    assert result.anomalies[0].startswith("media_disagreement:{}:".format(TID))
    # existing list is kept (api outranks cnn) but enriched from the lower-precedence list
    assert result.record["media"] == [{
        "type": "video", "url": "http://real2", "preview_url": "http://prev2",
        "mirror_url": "http://mirror2", "width": 640, "height": 480, "duration": 30,
    }]
    assert result.record["field_sources"]["media"] == "api"  # provenance unchanged


def test_media_empty_list_never_overwrites_non_empty():
    existing_media = [{
        "type": "image", "url": "http://real", "preview_url": None,
        "mirror_url": None, "width": None, "height": None, "duration": None,
    }]
    r0 = _base(source="trumpstruth", media=existing_media)
    # api outranks trumpstruth, but an empty media list means "unknown", not "no media"
    result = merge_partial(r0, {"ts_id": TID, "media": []}, source="api", observed_at="2026-09-01T01:00:00Z", run_id="r1")
    assert result.record["media"] == existing_media
    assert result.record["field_sources"]["media"] == "trumpstruth"
    assert result.anomalies == []
    # the only real change from this merge is "api" joining seen_sources
    assert result.changed is True
    assert result.record["seen_sources"] == ["api", "trumpstruth"]


# ---------------------------------------------------------------------------
# status transitions and deletion signals (rules 7-8)
# ---------------------------------------------------------------------------


def test_status_present_to_deleted_via_trumpstruth_removed():
    r0 = _base(source="trumpstruth")
    result = merge_partial(
        r0, {
            "ts_id": TID, "removed": True,
            "trumpstruth_captured_at": "2026-09-02T00:00:00Z",
            "trumpstruth_removed_at": "2026-09-03T00:00:00Z",
        },
        source="trumpstruth", observed_at="2026-09-02T00:05:00Z", run_id="r1",
    )
    assert result.record["status"] == "deleted"
    assert result.record["deleted_source"] == "trumpstruth"
    assert result.deletion_event is not None
    assert result.deletion_event["source"] == "trumpstruth"


def test_status_present_to_deleted_via_api_404():
    r0 = _base(source="api")
    result = merge_partial(r0, {"ts_id": TID, "api_404": True}, source="api", observed_at="2026-09-02T00:00:00Z", run_id="r1")
    assert result.record["status"] == "deleted"
    assert result.record["deleted_source"] == "api404"
    assert result.record["deleted_upper"] == "2026-09-02T00:00:00Z"
    assert result.deletion_event["source"] == "api"


def test_resurrection_via_api_live_sighting():
    r0 = _base(source="api")
    deleted = merge_partial(r0, {"ts_id": TID, "api_404": True}, source="api", observed_at="2026-09-02T00:00:00Z", run_id="r1").record
    assert deleted["status"] == "deleted"
    result = merge_partial(
        deleted, {"ts_id": TID, "kind": "original"}, source="api",
        observed_at="2026-09-03T00:00:00Z", run_id="r2",
    )
    assert result.record["status"] == "present"
    assert "resurrected:{}".format(TID) in result.anomalies
    # clears nothing else
    assert result.record["deleted_lower"] == deleted["deleted_lower"]
    assert result.record["deleted_upper"] == deleted["deleted_upper"]
    assert result.record["deleted_source"] == "api404"


def test_cnn_partial_does_not_resurrect():
    r0 = _base(source="api")
    deleted = merge_partial(r0, {"ts_id": TID, "api_404": True}, source="api", observed_at="2026-09-02T00:00:00Z", run_id="r1").record
    result = merge_partial(deleted, {"ts_id": TID, "kind": "original"}, source="cnn", observed_at="2026-09-03T00:00:00Z", run_id="r2")
    assert result.record["status"] == "deleted"
    assert "resurrected:{}".format(TID) not in result.anomalies


# ---------------------------------------------------------------------------
# Deletion bounds (rule 8)
# ---------------------------------------------------------------------------


def test_bounds_max_min_merge_is_order_independent():
    existing0 = _base(source="api", observed_at="2026-09-01T00:00:00Z")
    assert existing0["last_verified_live_at"] == "2026-09-01T00:00:00Z"

    trumpstruth_partial = {
        "ts_id": TID, "removed": True,
        "trumpstruth_captured_at": "2026-09-02T00:00:00Z",
        "trumpstruth_removed_at": "2026-09-03T00:00:00Z",
    }
    api404_partial = {"ts_id": TID, "api_404": True}

    # order A: trumpstruth then api404
    r1 = merge_partial(existing0, trumpstruth_partial, source="trumpstruth", observed_at="2026-09-02T00:05:00Z", run_id="a1").record
    r2 = merge_partial(r1, api404_partial, source="api", observed_at="2026-09-02T12:00:00Z", run_id="a2").record

    # order B: api404 then trumpstruth, from the same starting point
    s1 = merge_partial(existing0, api404_partial, source="api", observed_at="2026-09-02T12:00:00Z", run_id="b1").record
    s2 = merge_partial(s1, trumpstruth_partial, source="trumpstruth", observed_at="2026-09-02T00:05:00Z", run_id="b2").record

    assert (r2["deleted_lower"], r2["deleted_upper"]) == (s2["deleted_lower"], s2["deleted_upper"])
    assert r2["deleted_lower"] == "2026-09-02T00:00:00Z"
    assert r2["deleted_upper"] == "2026-09-02T12:00:00Z"
    # deleted_source is legitimately order-dependent (first signal wins)
    assert r2["deleted_source"] == "trumpstruth"
    assert s2["deleted_source"] == "api404"


def test_bounds_null_safe_with_no_prior_signals():
    r0 = _base(source="trumpstruth")
    result = merge_partial(r0, {"ts_id": TID, "removed": True}, source="trumpstruth", observed_at="2026-09-02T00:00:00Z", run_id="r1")
    assert result.record["deleted_lower"] is None
    assert result.record["deleted_upper"] is None
    assert "inverted_bounds:{}".format(TID) not in result.anomalies


def test_inverted_bounds_anomaly():
    r0 = _base(source="api", observed_at="2026-09-01T00:00:00Z")
    step1 = merge_partial(r0, {"ts_id": TID, "api_404": True}, source="api", observed_at="2026-09-01T00:00:00Z", run_id="r1").record
    assert step1["deleted_upper"] == "2026-09-01T00:00:00Z"
    result = merge_partial(
        step1, {"ts_id": TID, "removed": True, "trumpstruth_captured_at": "2026-09-05T00:00:00Z"},
        source="trumpstruth", observed_at="2026-09-05T00:05:00Z", run_id="r2",
    )
    assert result.record["deleted_lower"] == "2026-09-05T00:00:00Z"
    assert result.record["deleted_upper"] == "2026-09-01T00:00:00Z"
    assert "inverted_bounds:{}".format(TID) in result.anomalies


def test_deleted_source_set_once():
    r0 = _base(source="trumpstruth")
    deleted = merge_partial(r0, {"ts_id": TID, "removed": True}, source="trumpstruth", observed_at="2026-09-02T00:00:00Z", run_id="r1").record
    assert deleted["deleted_source"] == "trumpstruth"
    result = merge_partial(deleted, {"ts_id": TID, "api_404": True}, source="api", observed_at="2026-09-03T00:00:00Z", run_id="r2")
    assert result.record["deleted_source"] == "trumpstruth"  # unchanged


def test_deletion_event_emitted_once_and_suppressed_by_logged_deletions():
    r0 = _base(source="api", observed_at="2026-09-01T00:00:00Z")
    partial = {
        "ts_id": TID, "removed": True,
        "trumpstruth_captured_at": "2026-09-02T00:00:00Z",
        "trumpstruth_removed_at": "2026-09-03T00:00:00Z",
    }
    r1 = merge_partial(r0, partial, source="trumpstruth", observed_at="2026-09-02T00:05:00Z", run_id="r1")
    assert r1.deletion_event == {
        "ts_id": TID,
        "detected_at": "2026-09-02T00:05:00Z",
        "deleted_lower": r1.record["deleted_lower"],
        "deleted_upper": r1.record["deleted_upper"],
        "source": "trumpstruth",
        "trumpstruth_removed_at": r1.record["trumpstruth_removed_at"],
        "run_id": "r1",
    }

    # re-merging the identical partial before the caller has logged it: record settles
    # (changed=False) but the event must still be offered so the caller can retry logging it
    r2 = merge_partial(r1.record, partial, source="trumpstruth", observed_at="2026-09-02T00:05:00Z", run_id="r2")
    assert r2.changed is False
    assert r2.deletion_event is not None

    # once logged, suppressed
    r3 = merge_partial(
        r1.record, partial, source="trumpstruth", observed_at="2026-09-02T00:05:00Z", run_id="r3",
        logged_deletions=frozenset({(TID, "trumpstruth")}),
    )
    assert r3.deletion_event is None


# ---------------------------------------------------------------------------
# last_verified_live_at (rule 9), trumpstruth_* (rule 10), raw_api (rule 11)
# ---------------------------------------------------------------------------


def test_last_verified_live_at_keeps_maximum():
    r0 = _base(source="api", observed_at="2026-09-05T00:00:00Z")
    assert r0["last_verified_live_at"] == "2026-09-05T00:00:00Z"
    # an earlier (out-of-order) observation must not roll it back
    r1 = merge_partial(r0, {"ts_id": TID, "kind": "original"}, source="api", observed_at="2026-09-01T00:00:00Z", run_id="r1").record
    assert r1["last_verified_live_at"] == "2026-09-05T00:00:00Z"
    r2 = merge_partial(r1, {"ts_id": TID, "kind": "original"}, source="api", observed_at="2026-09-10T00:00:00Z", run_id="r2").record
    assert r2["last_verified_live_at"] == "2026-09-10T00:00:00Z"


def test_trumpstruth_removed_at_immutable_once_set():
    r0 = _base(source="trumpstruth")
    r1 = merge_partial(
        r0, {"ts_id": TID, "removed": True, "trumpstruth_removed_at": "2026-09-03T00:00:00Z"},
        source="trumpstruth", observed_at="2026-09-03T00:05:00Z", run_id="r1",
    ).record
    assert r1["trumpstruth_removed_at"] == "2026-09-03T00:00:00Z"
    r2 = merge_partial(
        r1, {"ts_id": TID, "removed": True, "trumpstruth_removed_at": "2026-09-04T00:00:00Z"},
        source="trumpstruth", observed_at="2026-09-04T00:05:00Z", run_id="r2",
    ).record
    assert r2["trumpstruth_removed_at"] == "2026-09-03T00:00:00Z"  # unchanged


def test_raw_api_replacement_and_non_api_leaves_it_untouched():
    r0 = _base(source="api", **{"raw_api": {"id": TID, "content": "old"}})
    assert r0["raw_api"] == {"id": TID, "content": "old"}
    r1 = merge_partial(r0, {"ts_id": TID, "raw_api": {"id": TID, "content": "new"}}, source="api", observed_at="2026-09-01T01:00:00Z", run_id="r1").record
    assert r1["raw_api"] == {"id": TID, "content": "new"}
    r2 = merge_partial(r1, {"ts_id": TID, "kind": "original"}, source="trumpstruth", observed_at="2026-09-01T02:00:00Z", run_id="r2").record
    assert r2["raw_api"] == {"id": TID, "content": "new"}  # untouched by non-api source


# ---------------------------------------------------------------------------
# changed / idempotency / no mutation (rule 12)
# ---------------------------------------------------------------------------


def test_idempotency_merging_same_partial_twice():
    partial = {
        "ts_id": TID,
        "created_at_utc": "2026-09-01T00:00:00Z",
        "kind": "original",
        "content_html": "<p>Hi</p>",
        "media": [{"type": "image", "url": "http://x", "preview_url": None, "mirror_url": None, "width": None, "height": None, "duration": None}],
    }
    r1 = merge_partial(None, partial, source="api", observed_at="2026-09-01T00:00:00Z", run_id="r1")
    assert r1.changed is True
    r2 = merge_partial(r1.record, partial, source="api", observed_at="2026-09-01T00:00:00Z", run_id="r2")
    assert r2.changed is False
    assert r2.record == r1.record
    assert r2.record is r1.record  # unchanged: the same object is returned


def test_no_mutation_of_existing_input():
    r0 = _base(
        source="trumpstruth",
        media=[{"type": "image", "url": None, "preview_url": "http://p", "mirror_url": None, "width": None, "height": None, "duration": None}],
    )
    snapshot = copy.deepcopy(r0)
    result = merge_partial(
        r0, {"ts_id": TID, "kind": "quote", "media": [{"type": "image", "url": "http://real", "preview_url": None, "mirror_url": None, "width": None, "height": None, "duration": None}]},
        source="api", observed_at="2026-09-01T01:00:00Z", run_id="r1",
    )
    assert r0 == snapshot  # the input dict (incl. nested media/field_sources) is untouched
    assert result.record != r0  # a real (different) change did happen
