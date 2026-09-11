"""Tests for scripts/parsers.py against the real captures in tests/fixtures/.

Facts asserted below were established by directly inspecting the fixture HTML/XML/JSON (see the long
comments where a fact turned out to differ from docs/SPEC.md section 6 or from the parser-writing brief).
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts import parsers
from scripts.parsers import ParseError

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_json(name: str) -> Any:
    return json.loads(load(name))


# ===========================================================================
# 6.1 trumpstruth listing and home page
# ===========================================================================


class TestParseListing:
    def test_page1_card_count_and_kind_breakdown(self):
        records = parsers.parse_listing(load("trumpstruth_listing_page1.html"))
        assert len(records) == 100
        kinds = [r["kind"] for r in records]
        assert "reblog" not in kinds  # parse_listing never produces kind "reblog" -- see retruthed tests

        retruthed = [r for r in records if r["retruthed"]]
        assert len(retruthed) == 5
        for r in retruthed:
            # every retruthed card in this fixture is a self-repost target (see module docstring: the card
            # shown *is* the reblogged post's own card, reused verbatim)
            assert r["kind"] == "original"
            assert r["account"] == "realDonaldTrump"
            assert r["retruthed_by"] == "Donald J. Trump"
        assert all(r["retruthed_by"] is None for r in records if not r["retruthed"])

        quotes = [r for r in records if r["kind"] == "quote"]
        assert len(quotes) == 10
        originals = [r for r in records if r["kind"] == "original"]
        assert len(originals) == 100 - len(quotes)

    def test_no_listing_fixture_ever_yields_kind_reblog(self):
        """`parse_listing` reports every card under its own markup-derived kind (original/quote) plus a
        `retruthed` flag -- it must never synthesize a kind "reblog", across any listing-shaped fixture."""
        for fname in (
            "trumpstruth_listing_page1.html",
            "trumpstruth_home.html",
            "trumpstruth_listing_2022_tail.html",
            "trumpstruth_listing_2026-09-09_cursor.html",
        ):
            records = parsers.parse_listing(load(fname))
            assert records, fname
            assert all(r["kind"] != "reblog" for r in records), fname

    def test_page1_media_totals_raw(self):
        # raw, whole-page fact about the fixture (matches the task brief's "45 image and 44 video
        # attachments overall" reading it as a fixture-content count, not a per-record one -- see
        # test_page1_media_totals_own_scope_excludes_nested_quote_media below for why those two differ)
        html = load("trumpstruth_listing_page1.html")
        assert len(re.findall("status-attachment--image", html)) == 45
        assert len(re.findall("status-attachment--video", html)) == 44

    def test_page1_media_totals_own_scope_excludes_nested_quote_media(self):
        """SPEC CLARIFICATION: docs/SPEC.md 6.1 scopes `media` to "the card's own" attachments, mirroring
        how `content_html` is scoped (a card's own content, not the nested quoted/reblogged post's). Applying
        that consistently means a quote card's *nested* inner post's own attachments are not counted in the
        outer record's `media` list. This fixture has exactly 10 quote cards, each with exactly one video
        attachment on its nested/quoted inner post (see e.g. trumpstruth_id 41678 in
        test_quote_card_41678_has_nested_quote_info), which fully accounts for the gap between the raw
        page-wide video count (44, asserted above) and the per-record sum below (34 = 44 - 10).
        """
        records = parsers.parse_listing(load("trumpstruth_listing_page1.html"))
        assert len([r for r in records if r["kind"] == "quote"]) == 10
        images = sum(1 for r in records for m in r["media"] if m["type"] == "image")
        videos = sum(1 for r in records for m in r["media"] if m["type"] == "video")
        assert images == 45
        assert videos == 34

    def test_card_41687_original_video(self):
        records = parsers.parse_listing(load("trumpstruth_listing_page1.html"))
        card = next(r for r in records if r["trumpstruth_id"] == 41687)
        assert card["ts_id"] == "117249775492910498"
        assert card["created_at_utc"] == "2026-09-11T01:19:51Z"
        assert card["kind"] == "original"
        assert card["account"] == "realDonaldTrump"
        assert card["content_html"] == ""
        assert len(card["media"]) == 1
        assert card["media"][0]["type"] == "video"
        assert card["trumpstruth_url"] == "https://www.trumpstruth.org/statuses/41687"

    def test_card_41686(self):
        records = parsers.parse_listing(load("trumpstruth_listing_page1.html"))
        card = next(r for r in records if r["trumpstruth_id"] == 41686)
        assert card["ts_id"] == "117247527370149354"
        assert card["created_at_utc"] == "2026-09-10T15:48:08Z"
        assert card["kind"] == "original"

    def test_quote_card_41678_has_nested_quote_info(self):
        records = parsers.parse_listing(load("trumpstruth_listing_page1.html"))
        card = next(r for r in records if r["trumpstruth_id"] == 41678)
        assert card["kind"] == "quote"
        assert card["quote_id"] == "117246836238536386"
        assert card["quote_of_acct"] == "realDonaldTrump"
        # the outer (quoting) post's own media -- one linodeobjects-mirrored image, not the nested
        # quoted post's video
        assert len(card["media"]) == 1
        assert card["media"][0]["type"] == "image"
        assert card["media"][0]["mirror_url"] is not None
        assert "linodeobjects.com" in card["media"][0]["mirror_url"]

    def test_retruthed_cards_are_the_targets_own_card(self):
        """Layout, established by direct inspection: a `status__reblog-indicator` ("<Name> ReTruthed") is a
        *sibling* div placed immediately before a card, at the same nesting depth as the cards themselves --
        it is not nested inside the card it describes. The card that follows one is not a distinct repost
        card at all: it is the *reblogged target's own* card markup, reused verbatim (same trumpstruth id,
        same ts_id, same header time you'd get by fetching that target directly). Concretely, in this
        fixture, the card immediately following each of the five ReTruthed markers is trumpstruth id 41640 --
        the target post ("The Failing New York Magazine...", ts_id 117238282851088051, posted
        2026-09-09T00:37:08Z). This is cross-checked against trumpstruth_status_41646_removed_reblog.html,
        whose own details table confirms 117238282851088051 / 2026-09-09T00:37:08Z is *that removed repost's
        target* (reblog_of_id / reblog_of_created_at) -- not any repost's own identity. The five distinct
        repost events (of this same target) have their own ts_ids/trumpstruth_ids only recoverable from
        their own status pages (41641/41644/41646/41649 among them) -- never from the listing, which is why
        parse_listing does not set reblog_of_id/reblog_of_acct on these cards at all.
        """
        records = parsers.parse_listing(load("trumpstruth_listing_page1.html"))
        assert len(records) == 100
        retruthed = [r for r in records if r["retruthed"]]
        assert len(retruthed) == 5
        for r in retruthed:
            assert r["trumpstruth_id"] == 41640
            assert r["ts_id"] == "117238282851088051"
            assert r["kind"] == "original"
            assert r["created_at_utc"] == "2026-09-09T00:37:08Z"
            assert r["retruthed_by"] == "Donald J. Trump"
            assert r["content_html"].startswith("<p>The Failing New York Magazine")
            assert "reblog_of_id" not in r
            assert "reblog_of_acct" not in r

    def test_home_page_10_cards(self):
        records = parsers.parse_listing(load("trumpstruth_home.html"))
        assert len(records) == 10
        assert [r["trumpstruth_id"] for r in records] == [
            41687, 41686, 41685, 41677, 41678, 41679, 41680, 41681, 41682, 41683,
        ]

    def test_2022_tail_single_card(self):
        records = parsers.parse_listing(load("trumpstruth_listing_2022_tail.html"))
        assert len(records) == 1
        card = records[0]
        assert card["trumpstruth_id"] == 1824
        assert card["ts_id"] == "107797156496908384"
        assert card["created_at_utc"] == "2022-02-14T15:54:32Z"
        assert card["kind"] == "original"

    def test_2026_09_09_cursor_25_cards(self):
        records = parsers.parse_listing(load("trumpstruth_listing_2026-09-09_cursor.html"))
        assert len(records) == 25

    def test_2026_09_09_cursor_retruthed_cards_contradict_original_brief(self):
        """An earlier version of the task brief for this fixture claimed "reblog cards 41652, 41650, 41648,
        41645". Direct inspection shows this was wrong: none of those four trumpstruth ids has a
        `status__reblog-indicator` or "ReTruthed" text anywhere near them -- they are plain original cards
        with `retruthed: False`. All five `status__reblog-indicator` markers in this file precede
        data-status-url="...41640" (the same reused target card described in
        test_retruthed_cards_are_the_targets_own_card above): id 41640 appears 6 times total in this fixture
        -- once in its own unmarked chronological slot, plus 5 more times immediately after a ReTruthed
        marker, one per distinct repost event of that same target (see tests/fixtures/README.md).
        """
        html = load("trumpstruth_listing_2026-09-09_cursor.html")
        records = parsers.parse_listing(html)
        by_id = {}
        for r in records:
            by_id.setdefault(r["trumpstruth_id"], []).append(r)

        for tid in (41652, 41650, 41648, 41645):
            assert tid in by_id, tid
            assert by_id[tid][0]["kind"] == "original"
            assert by_id[tid][0]["retruthed"] is False
            assert by_id[tid][0]["retruthed_by"] is None

        retruthed_records = [r for r in records if r["retruthed"]]
        assert len(retruthed_records) == 5
        assert all(r["trumpstruth_id"] == 41640 for r in retruthed_records)
        assert all(r["kind"] == "original" for r in retruthed_records)
        assert all(r["retruthed_by"] == "Donald J. Trump" for r in retruthed_records)
        assert len(by_id[41640]) == 6
        assert sum(1 for r in by_id[41640] if not r["retruthed"]) == 1

    def test_parse_listing_parse_error_on_missing_container(self):
        with pytest.raises(ParseError):
            parsers.parse_listing("<html></html>")

    def test_parse_listing_empty_container_returns_empty_list(self):
        html = '<html><body><div class="statuses"></div></body></html>'
        assert parsers.parse_listing(html) == []


class TestNextCursorAndMakeCursor:
    def test_home_page_next_cursor(self):
        cursor = parsers.parse_next_cursor(load("trumpstruth_home.html"))
        assert cursor == "eyJzdGF0dXNfY3JlYXRlZF9hdCI6IjIwMjYtMDktMTAgMTI6NTE6MDkiLCJfcG9pbnRzVG9OZXh0SXRlbXMiOnRydWV9"
        decoded = json.loads(base64.b64decode(cursor))
        assert decoded == {"status_created_at": "2026-09-10 12:51:09", "_pointsToNextItems": True}

    def test_listing_page1_next_cursor(self):
        cursor = parsers.parse_next_cursor(load("trumpstruth_listing_page1.html"))
        decoded = json.loads(base64.b64decode(cursor))
        assert decoded["status_created_at"] == "2026-09-07 00:59:09"

    def test_no_next_cursor_when_absent(self):
        assert parsers.parse_next_cursor("<html></html>") is None

    def test_make_cursor_matches_spec_example(self):
        cursor = parsers.make_cursor("2026-03-01 00:00:00")
        expected = base64.b64encode(
            b'{"status_created_at":"2026-03-01 00:00:00","_pointsToNextItems":true}'
        ).decode("ascii")
        assert cursor == expected

    def test_make_cursor_round_trips_like_the_real_site(self):
        # the real cursor captured on trumpstruth_home.html decodes to exactly the compact-JSON shape
        # make_cursor produces, key order included
        real_cursor = "eyJzdGF0dXNfY3JlYXRlZF9hdCI6IjIwMjYtMDktMTAgMTI6NTE6MDkiLCJfcG9pbnRzVG9OZXh0SXRlbXMiOnRydWV9"
        assert parsers.make_cursor("2026-09-10 12:51:09") == real_cursor


# ===========================================================================
# 6.2 trumpstruth status page
# ===========================================================================


class TestParseStatusPage:
    def test_41686_original_video(self):
        rec = parsers.parse_status_page(load("trumpstruth_status_41686_original_video.html"))
        assert rec["ts_id"] == "117247527370149354"
        assert rec["kind"] == "original"
        assert rec["created_at_utc"] == "2026-09-10T15:48:08Z"
        assert rec["trumpstruth_captured_at"] == "2026-09-11T14:30:45Z"
        assert rec["removed"] is False
        assert rec["trumpstruth_removed_at"] is None
        assert rec["account"] == "realDonaldTrump"
        assert rec["trumpstruth_id"] == 41686
        assert len(rec["media"]) == 1
        media = rec["media"][0]
        assert media["type"] == "video"
        assert media["mirror_url"] is not None
        assert "linodeobjects.com" in media["mirror_url"]

    def test_41646_removed_reblog(self):
        rec = parsers.parse_status_page(load("trumpstruth_status_41646_removed_reblog.html"))
        assert rec["ts_id"] == "117238345561593751"
        assert rec["created_at_utc"] == "2026-09-09T00:53:04Z"
        assert rec["kind"] == "reblog"
        assert rec["reblog_of_id"] == "117238282851088051"
        assert rec["reblog_of_acct"] == "realDonaldTrump"
        assert rec["reblog_of_created_at"] == "2026-09-09T00:37:08Z"
        assert rec["removed"] is True
        # the precise Capture Date <time> tag (02:20:59) falls in the same minute as the minute-precision
        # "confirmed removed ... 10:20 PM EDT" text (02:20:00), so the precise value wins -- see the
        # synthetic-shift test below for the case where they disagree
        assert rec["trumpstruth_removed_at"] == "2026-09-09T02:20:59Z"
        assert rec["account"] == "realDonaldTrump"
        assert rec["content_html"].startswith("<p>The Failing New York Magazine")

    def test_41646_removed_at_falls_back_to_text_when_capture_date_drifts_to_a_different_minute(self):
        """docs/SPEC.md 6.2 correction: `trumpstruth_removed_at` is the minute-precision value parsed from
        the "Removed from platform" text, *unless* the Capture Date row's precise `<time datetime>` falls
        within that same minute, in which case the precise value is used instead (see
        test_41646_removed_reblog above for that normal case). This synthesizes the other branch by shifting
        trumpstruth_status_41646_removed_reblog.html's real Capture Date tag from 02:20:59 to 02:22:59 --
        still "10:20 pm EDT" in the surrounding display text, but a different `datetime` attribute, as if a
        later recapture had merely re-confirmed an already-known removal. Capture Date and the removal text
        no longer agree to the minute, so trumpstruth_removed_at falls back to the coarser, minute-precision
        text value (seconds always :00) rather than the now-stale-looking precise tag.
        """
        html = load("trumpstruth_status_41646_removed_reblog.html")
        assert html.count("2026-09-09T02:20:59+00:00") == 1
        shifted_html = html.replace("2026-09-09T02:20:59+00:00", "2026-09-09T02:22:59+00:00")

        rec = parsers.parse_status_page(shifted_html)
        assert rec["removed"] is True
        assert rec["trumpstruth_captured_at"] == "2026-09-09T02:22:59Z"
        assert rec["trumpstruth_removed_at"] == "2026-09-09T02:20:00Z"

    @pytest.mark.parametrize(
        "fname,ts_id",
        [
            ("trumpstruth_status_41641_removed_reblog.html", "117238301772357460"),
            ("trumpstruth_status_41644_removed_reblog.html", "117238326295991805"),
            ("trumpstruth_status_41649_removed_reblog.html", "117238414290995787"),
        ],
    )
    def test_other_removed_reblogs_follow_same_pattern(self, fname, ts_id):
        rec = parsers.parse_status_page(load(fname))
        assert rec["ts_id"] == ts_id
        assert rec["kind"] == "reblog"
        assert rec["removed"] is True
        assert rec["reblog_of_id"] == "117238282851088051"
        assert rec["reblog_of_acct"] == "realDonaldTrump"
        assert rec["trumpstruth_removed_at"] is not None
        assert rec["account"] == "realDonaldTrump"

    def test_41514_reblog_of_other_account(self):
        rec = parsers.parse_status_page(load("trumpstruth_status_41514_reblog_other.html"))
        assert rec["ts_id"] == "117213738409833358"
        assert rec["kind"] == "reblog"
        assert rec["account"] == "realDonaldTrump"
        assert rec["reblog_of_acct"] == "MichaelCohen212"
        assert rec["reblog_of_id"] == "117190624268499306"
        assert rec["created_at_utc"] == "2026-09-04T16:35:09Z"
        assert rec["reblog_of_created_at"] == "2026-08-31T14:36:55Z"
        assert rec["removed"] is False

    def test_41515_michael_cohens_own_post(self):
        rec = parsers.parse_status_page(load("trumpstruth_status_41515_reblog_other.html"))
        assert rec["ts_id"] == "117190624268499306"
        assert rec["account"] == "MichaelCohen212"
        assert rec["kind"] == "original"

    def test_41678_quote(self):
        rec = parsers.parse_status_page(load("trumpstruth_status_41678_quote.html"))
        assert rec["kind"] == "quote"
        assert rec["quote_id"] == "117246836238536386"
        assert rec["quote_of_acct"] == "realDonaldTrump"
        assert len(rec["media"]) == 1
        assert rec["media"][0]["type"] == "image"
        assert "linodeobjects.com" in rec["media"][0]["mirror_url"]

    def test_41655_is_the_original_target_of_a_later_retruth(self):
        """trumpstruth_status_41655_original_retruthed_target.html (renamed from ..._reblog_self.html) is an
        ordinary original post that its own author later ReTruths elsewhere -- that repost relationship only
        shows up on listing pages, as a `retruthed: True` card pointing back at this same ts_id/trumpstruth_id
        (see TestParseListing.test_retruthed_cards_are_the_targets_own_card). This page itself has no reblog
        markup at all: no "ReTruthed" text, no `status__reblog-indicator` div, no nested `<div
        class="status">` -- it is byte-for-byte the same shape as an "original" status page (compare
        trumpstruth_status_41686_original_video.html), just with an image instead of a video. So, correctly,
        it parses as kind "original".
        """
        rec = parsers.parse_status_page(load("trumpstruth_status_41655_original_retruthed_target.html"))
        assert rec["ts_id"] == "117238706250982520"
        assert rec["created_at_utc"] == "2026-09-09T02:24:48Z"
        assert rec["kind"] == "original"
        assert rec["account"] == "realDonaldTrump"
        assert rec["reblog_of_id"] is None

    def test_parse_error_on_missing_og_url(self):
        with pytest.raises(ParseError):
            parsers.parse_status_page("<html></html>")


# ===========================================================================
# 6.3 trumpstruth search results
# ===========================================================================


class TestParseSearchResults:
    def test_removed_2026_totals(self):
        data = parsers.parse_search_results(load("trumpstruth_search_removed_2026.html"))
        assert data["total"] == 88
        assert len(data["results"]) == 88
        assert all(r["removed"] for r in data["results"])

    def test_removed_2026_url_style_rt_snippet(self):
        """SPEC MISMATCH (docs/SPEC.md 6.3): most removed-reblog snippets in this file are glued
        `RT @handleRest...` text with no id in them at all (same ambiguous format CNN uses) -- only a
        minority use the `RT: https://truthsocial.com/users/<acct>/statuses/<id>` form the spec describes.
        The first result to use that URL form has reblog_of_id 116391828823240211, matching the task brief's
        claim exactly (the brief's "first result" evidently meant first-of-that-format, not first-in-page:
        the page's very first result, trumpstruth id 41649, uses the glued `RT @realDonaldTrump...` form and
        has no recoverable reblog_of_id).
        """
        data = parsers.parse_search_results(load("trumpstruth_search_removed_2026.html"))
        first = data["results"][0]
        assert first["trumpstruth_id"] == 41649
        assert first["snippet_text"].startswith("RT @realDonaldTrump")
        assert first["reblog_of_acct"] == "realDonaldTrump"
        assert first["reblog_of_id"] is None  # no id in this snippet format

        url_style = next(r for r in data["results"] if r["reblog_of_id"] == "116391828823240211")
        assert url_style["reblog_of_acct"] == "realDonaldTrump"

    def test_removed_2026_next_cursor_absent_on_single_page(self):
        data = parsers.parse_search_results(load("trumpstruth_search_removed_2026.html"))
        assert data["next_cursor"] is None

    def test_removed_2026_09_07_to_11(self):
        data = parsers.parse_search_results(load("trumpstruth_search_removed_2026-09-07_to_11.html"))
        assert data["total"] == 4
        ids = [r["trumpstruth_id"] for r in data["results"]]
        assert ids == [41649, 41646, 41644, 41641]
        assert all(r["removed"] for r in data["results"])
        assert data["next_cursor"] is None
        # no fixture result carries a <time datetime> -- created_at_utc is unavailable from search rows
        assert all(r["created_at_utc"] is None for r in data["results"])

    def test_query_trump_10_results_five_digit_comma_total(self):
        data = parsers.parse_search_results(load("trumpstruth_search_query_trump.html"))
        assert len(data["results"]) == 10
        assert data["total"] == 16020
        assert all(not r["removed"] for r in data["results"])
        # this fixture's snippets use a different container (`snippet-content`, with <em> highlights and
        # separate card-title/card-url blocks) that spec 6.3's `snippet-clean-content` selector never
        # matches, so snippet_text comes back empty here -- collectors only rely on it via the
        # removed-search flow, where snippet-clean-content is always present (see tests above).
        assert all(r["snippet_text"] == "" for r in data["results"])

    def test_query_trump_next_cursor_uses_page_param_not_cursor(self):
        """SPEC MISMATCH (docs/SPEC.md 6.3 / 6.1 conflation): a general `query=` search's Next Page link has
        no `cursor=` parameter at all -- it paginates with `page=2` instead. We fall back to that so
        next_cursor is still populated, just not in the base64-cursor shape used by the listing/removed-
        search endpoints.
        """
        data = parsers.parse_search_results(load("trumpstruth_search_query_trump.html"))
        assert data["next_cursor"] == "2"

    def test_parse_error_on_missing_container(self):
        with pytest.raises(ParseError):
            parsers.parse_search_results("<html></html>")


# ===========================================================================
# 6.4 trumpstruth feed and stats
# ===========================================================================


class TestParseFeed:
    def test_feed_100_items(self):
        items = parsers.parse_feed(load("trumpstruth_feed.xml"))
        assert len(items) == 100
        first = items[0]
        assert first["ts_id"] == "117249775492910498"
        assert first["trumpstruth_id"] == 41687
        assert first["trumpstruth_url"] == "https://www.trumpstruth.org/statuses/41687"
        assert first["created_at_utc"] == "2026-09-11T01:19:51Z"

    def test_feed_dated_10_items(self):
        items = parsers.parse_feed(load("trumpstruth_feed_dated_2025-12-01.xml"))
        assert len(items) == 10

    def test_parse_error_on_missing_channel(self):
        with pytest.raises(ParseError):
            parsers.parse_feed("<html></html>")

    def test_parse_error_on_invalid_xml(self):
        with pytest.raises(ParseError):
            parsers.parse_feed("<rss><channel><item>")


class TestParseStats:
    def test_stats_totals_and_coverage(self):
        stats = parsers.parse_stats(load("trumpstruth_stats.html"))
        assert stats["total"] == 37105
        assert stats["original"] == 29410
        assert stats["quote"] == 1997
        assert stats["reblog"] == 5698
        assert stats["coverage_start"] == "2022-02-14"
        assert stats["coverage_end"] == "2026-09-10"

    def test_parse_error_on_missing_container(self):
        with pytest.raises(ParseError):
            parsers.parse_stats("<html></html>")


# ===========================================================================
# 6.5 API objects
# ===========================================================================


class TestApiStatusToPartial:
    @pytest.fixture(scope="class")
    def statuses(self):
        return load_json("api_statuses_2026-09-04_to_09-11.json")

    def test_180_statuses_kind_breakdown(self, statuses):
        assert len(statuses) == 180
        partials = [parsers.api_status_to_partial(s) for s in statuses]
        kinds = [p["kind"] for p in partials]
        assert kinds.count("original") == 163
        assert kinds.count("quote") == 13
        assert kinds.count("reblog") == 4
        assert kinds.count("reply") == 0

    def test_first_object_video_status(self, statuses):
        partial = parsers.api_status_to_partial(statuses[0])
        assert partial["ts_id"] == "117249775492910498"
        assert partial["created_at_utc"] == "2026-09-11T01:19:51Z"
        assert partial["content_html"] == "<p></p>"
        assert len(partial["media"]) == 1
        media = partial["media"][0]
        assert media["type"] == "video"
        assert media["width"] == 1280
        assert media["height"] == 720
        assert media["duration"] == 30.03
        assert partial["_engagement"]["replies"] is not None
        assert partial["_engagement"]["reblogs"] is not None
        assert partial["_engagement"]["favourites"] is not None
        assert partial["_engagement"]["upvotes"] is not None

    @pytest.mark.parametrize(
        "status_id,reblog_of_id,reblog_of_acct",
        [
            ("117238467019560891", "117238282851088051", "realDonaldTrump"),
            ("117213740097315077", "117213723499789673", "realDonaldTrump"),
            ("117213738409833358", "117190624268499306", "MichaelCohen212"),
            ("117210071109792571", "117209653242980598", "realDonaldTrump"),
        ],
    )
    def test_known_reblogs(self, statuses, status_id, reblog_of_id, reblog_of_acct):
        obj = next(s for s in statuses if s["id"] == status_id)
        partial = parsers.api_status_to_partial(obj)
        assert partial["kind"] == "reblog"
        assert partial["reblog_of_id"] == reblog_of_id
        assert partial["reblog_of_acct"] == reblog_of_acct

    def test_michael_cohen_reblog_of_created_at(self, statuses):
        obj = next(s for s in statuses if s["id"] == "117213738409833358")
        partial = parsers.api_status_to_partial(obj)
        assert partial["reblog_of_created_at"] == "2026-08-31T14:36:55Z"

    def test_quote_status_content_starts_with_quote_inline_span(self, statuses):
        obj = next(s for s in statuses if s["id"] == "117246837016957469")
        partial = parsers.api_status_to_partial(obj)
        assert partial["kind"] == "quote"
        assert partial["quote_id"] == "117246836238536386"
        assert partial["content_html"].startswith('<p><span class="quote-inline">')
        # html_to_text (reused from scripts.common) drops the whole quote-inline span
        from scripts.common import html_to_text

        assert html_to_text(partial["content_html"]) == ""

    def test_card_domain_strips_www(self, statuses):
        obj = next(
            s for s in statuses if s.get("card") and "cbsnews" in (s["card"].get("provider_name") or "")
        )
        partial = parsers.api_status_to_partial(obj)
        assert partial["card_domain"] == "cbsnews.com"
        assert partial["card_url"] == obj["card"]["url"]
        assert partial["card_title"] == obj["card"]["title"]

    def test_raw_api_strips_account_recursively(self, statuses):
        obj = next(s for s in statuses if s["id"] == "117238467019560891")  # a reblog
        assert "account" in obj
        assert "account" in obj["reblog"]
        partial = parsers.api_status_to_partial(obj)
        raw = partial["raw_api"]
        assert "account" not in raw
        assert "account" not in raw["reblog"]

        def _walk(node):
            if isinstance(node, dict):
                assert "account" not in node
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for v in node:
                    _walk(v)

        _walk(raw)
        # the original object handed in must not have been mutated
        assert "account" in obj
        assert "account" in obj["reblog"]

    def test_raw_api_strips_account_inside_quote(self, statuses):
        obj = next(s for s in statuses if s["id"] == "117246837016957469")
        assert "account" in obj["quote"]
        partial = parsers.api_status_to_partial(obj)
        assert "account" not in partial["raw_api"]["quote"]

    def test_account_from_first_status(self, statuses):
        account = parsers.api_account_from_status(statuses[0])
        assert account["statuses_count"] == 36549

    def test_reply_kind_synthetic(self):
        # 0 replies occur in the fixture; exercise the branch directly per docs/SPEC.md 6.5
        obj = {
            "id": "999999999999999999",
            "created_at": "2026-09-01T00:00:00.000Z",
            "content": "<p>a reply</p>",
            "in_reply_to_id": "111111111111111111",
            "reblog": None,
            "quote": None,
            "quote_id": None,
            "media_attachments": [],
        }
        partial = parsers.api_status_to_partial(obj)
        assert partial["kind"] == "reply"
        assert partial["in_reply_to_id"] == "111111111111111111"

    def test_parse_error_on_missing_id(self):
        with pytest.raises(ParseError):
            parsers.api_status_to_partial({"created_at": "2026-09-01T00:00:00Z"})


class TestApiStatus404:
    def test_is_valid_json_with_error_key(self):
        body = load_json("api_status_404.json")
        assert body["error"] == "record not found"


# ===========================================================================
# 6.6 CNN rows
# ===========================================================================


class TestCnnRowToPartial:
    @pytest.fixture(scope="class")
    def rows(self):
        return load_json("cnn_archive_sample.json")

    def test_420_rows(self, rows):
        assert len(rows) == 420

    def test_first_row_original_video(self, rows):
        partial = parsers.cnn_row_to_partial(rows[0])
        assert partial["ts_id"] == "117249775492910498"
        assert partial["kind"] == "original"
        assert partial["created_at_utc"] == "2026-09-11T01:19:51Z"
        assert len(partial["media"]) == 1
        assert partial["media"][0]["type"] == "video"
        assert partial["_engagement"]["upvotes"] is None
        assert partial["_engagement"]["downvotes"] is None
        assert partial["_engagement"]["replies"] is not None

    def test_known_reblog_row(self, rows):
        row = next(r for r in rows if r["id"] == "117238345561593751")
        partial = parsers.cnn_row_to_partial(row)
        assert partial["kind"] == "reblog"
        assert partial["reblog_of_acct"] == "realDonaldTrump"
        assert partial["content_text"].startswith("The Failing New York Magazine")

    def test_michael_cohen_row(self, rows):
        row = next(r for r in rows if r["content"].startswith('RT @MichaelCohen212"'))
        partial = parsers.cnn_row_to_partial(row)
        assert partial["kind"] == "reblog"
        assert partial["reblog_of_acct"] == "MichaelCohen212"
        assert partial["content_text"].startswith('"The Weaponized State"')

    def test_media_type_by_extension(self, rows):
        seen_types = set()
        for row in rows:
            for url in row.get("media") or []:
                seen_types.add(parsers.cnn_row_to_partial(row)["media"][0]["type"] if row["media"] else None)
        # sanity: extensions actually present in the fixture map to image/video/unknown as expected
        mp4_row = next(r for r in rows if any(u.endswith(".mp4") for u in r.get("media") or []))
        jpg_row = next(
            r for r in rows if any(u.lower().endswith((".jpg", ".jpeg")) for u in r.get("media") or [])
        )
        assert parsers.cnn_row_to_partial(mp4_row)["media"][0]["type"] == "video"
        assert any(m["type"] == "image" for m in parsers.cnn_row_to_partial(jpg_row)["media"])

    def test_qt_extension_is_video(self, rows):
        """The fixture contains media URLs ending in `.qt` (QuickTime) -- classified as "video" alongside
        mp4/m3u8/mov, per the corrected extension list."""
        qt_row = next(r for r in rows if any(u.lower().endswith(".qt") for u in r.get("media") or []))
        partial = parsers.cnn_row_to_partial(qt_row)
        qt_media = next(m for m in partial["media"] if m["url"].lower().endswith(".qt"))
        assert qt_media["type"] == "video"

    def test_rt_handle_boundary_ambiguity_documented_and_realdonaldtrump_exact(self, rows):
        # realDonaldTrump is special-cased exactly, so its remainder never swallows extra text
        row = next(r for r in rows if r["content"].startswith("RT @realDonaldTrumpI"))
        partial = parsers.cnn_row_to_partial(row)
        assert partial["reblog_of_acct"] == "realDonaldTrump"
        assert partial["content_text"].startswith("I")

    def test_all_keys_present_schema(self, rows):
        assert set(rows[0].keys()) == {
            "id", "created_at", "content", "url", "media", "replies_count", "reblogs_count", "favourites_count",
        }

    def test_parse_error_on_missing_id(self):
        with pytest.raises(ParseError):
            parsers.cnn_row_to_partial({"created_at": "2026-09-01T00:00:00Z", "content": ""})


# ===========================================================================
# cross-source consistency
# ===========================================================================


def test_trumpstruth_and_api_agree_on_michael_cohen_reblog():
    status_page = parsers.parse_status_page(load("trumpstruth_status_41514_reblog_other.html"))
    api_obj = next(
        s for s in load_json("api_statuses_2026-09-04_to_09-11.json") if s["id"] == "117213738409833358"
    )
    api_partial = parsers.api_status_to_partial(api_obj)
    assert status_page["ts_id"] == api_partial["ts_id"]
    assert status_page["reblog_of_id"] == api_partial["reblog_of_id"]
    assert status_page["reblog_of_acct"] == api_partial["reblog_of_acct"]


def test_trumpstruth_and_cnn_agree_on_removed_reblog():
    status_page = parsers.parse_status_page(load("trumpstruth_status_41646_removed_reblog.html"))
    cnn_row = next(r for r in load_json("cnn_archive_sample.json") if r["id"] == "117238345561593751")
    cnn_partial = parsers.cnn_row_to_partial(cnn_row)
    assert status_page["ts_id"] == cnn_partial["ts_id"]
    assert status_page["reblog_of_acct"] == cnn_partial["reblog_of_acct"]


def test_search_results_page_past_the_last_page_is_empty_not_drift():
    data = parsers.parse_search_results(load("trumpstruth_search_removed_page2_empty.html"))
    assert data["results"] == []
    assert data["total"] == 4
    assert data["next_cursor"] is None


def test_search_results_drift_guard_still_raises_on_unknown_markup():
    with pytest.raises(ParseError):
        parsers.parse_search_results("<html><body><p>nothing here</p></body></html>")
