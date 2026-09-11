"""Tests for the time helpers and html_to_text in scripts/common.py (docs/SPEC.md section 4, 6.7)."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.common import (
    et_fields,
    html_to_text,
    parse_et_text,
    parse_iso_utc,
    to_utc_iso,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# parse_iso_utc
# ---------------------------------------------------------------------------


def test_parse_iso_utc_with_fractional_seconds_and_z():
    dt = parse_iso_utc("2026-09-09T00:53:04.960Z")
    assert dt == datetime(2026, 9, 9, 0, 53, 4, 960000, tzinfo=UTC)
    assert dt.tzinfo is not None


def test_parse_iso_utc_with_z():
    dt = parse_iso_utc("2026-09-09T00:53:04Z")
    assert dt == datetime(2026, 9, 9, 0, 53, 4, tzinfo=UTC)


def test_parse_iso_utc_with_explicit_offset():
    dt = parse_iso_utc("2026-09-09T00:53:04+00:00")
    assert dt == datetime(2026, 9, 9, 0, 53, 4, tzinfo=UTC)


def test_parse_iso_utc_with_non_zero_offset_converts_to_utc():
    dt = parse_iso_utc("2026-09-08T20:53:04-04:00")
    assert dt == datetime(2026, 9, 9, 0, 53, 4, tzinfo=UTC)


def test_parse_iso_utc_space_separator_assumed_utc():
    dt = parse_iso_utc("2026-09-09 00:53:04")
    assert dt == datetime(2026, 9, 9, 0, 53, 4, tzinfo=UTC)


def test_parse_iso_utc_rfc_2822():
    dt = parse_iso_utc("Fri, 11 Sep 2026 01:19:51 +0000")
    assert dt == datetime(2026, 9, 11, 1, 19, 51, tzinfo=UTC)


def test_parse_iso_utc_rfc_2822_with_offset_converts_to_utc():
    dt = parse_iso_utc("Fri, 11 Sep 2026 01:19:51 -0400")
    assert dt == datetime(2026, 9, 11, 5, 19, 51, tzinfo=UTC)


def test_parse_iso_utc_none_raises():
    with pytest.raises(ValueError):
        parse_iso_utc(None)


def test_parse_iso_utc_garbage_raises():
    with pytest.raises(ValueError):
        parse_iso_utc("not a timestamp")


# ---------------------------------------------------------------------------
# to_utc_iso
# ---------------------------------------------------------------------------


def test_to_utc_iso_drops_sub_seconds():
    dt = datetime(2026, 9, 9, 0, 53, 4, 960000, tzinfo=UTC)
    assert to_utc_iso(dt) == "2026-09-09T00:53:04Z"


def test_to_utc_iso_converts_non_utc_to_utc():
    dt = datetime(2026, 9, 8, 20, 53, 4, tzinfo=timezone(timedelta(hours=-4)))
    assert to_utc_iso(dt) == "2026-09-09T00:53:04Z"


def test_to_utc_iso_naive_raises():
    with pytest.raises(ValueError):
        to_utc_iso(datetime(2026, 9, 9, 0, 53, 4))


# ---------------------------------------------------------------------------
# parse_et_text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Tuesday, September 8, 2026, 09:10 pm EDT", "2026-09-09T01:10:00Z"),
        ("Sep 8, 2026, 10:20 PM EDT", "2026-09-09T02:20:00Z"),
        ("September 10, 2026, 11:48 AM", "2026-09-10T15:48:00Z"),
        ("January 15, 2026, 9:05 AM", "2026-01-15T14:05:00Z"),
    ],
)
def test_parse_et_text_cases(text, expected):
    assert parse_et_text(text) == expected


def test_parse_et_text_wrong_zone_abbreviation_raises():
    # Sep 8 2026 9:10pm ET is EDT (daylight), so labeling it EST is inconsistent.
    with pytest.raises(ValueError):
        parse_et_text("September 8, 2026, 9:10 PM EST")


# --- DST spring-forward boundary (2026-03-08 02:00 local clocks jump to 03:00 EDT) ---


def test_parse_et_text_dst_spring_forward_edt_side():
    assert parse_et_text("March 8, 2026, 3:00 AM EDT") == "2026-03-08T07:00:00Z"


def test_parse_et_text_dst_spring_forward_est_side():
    assert parse_et_text("March 8, 2026, 1:59 AM EST") == "2026-03-08T06:59:00Z"


# --- DST fall-back ambiguous hour (2026-11-01 01:00-02:00 local occurs twice) ---


def test_parse_et_text_dst_fall_back_edt_side():
    assert parse_et_text("November 1, 2026, 1:30 AM EDT") == "2026-11-01T05:30:00Z"


def test_parse_et_text_dst_fall_back_est_side():
    assert parse_et_text("November 1, 2026, 1:30 AM EST") == "2026-11-01T06:30:00Z"


# ---------------------------------------------------------------------------
# et_fields
# ---------------------------------------------------------------------------


def test_et_fields_basic():
    fields = et_fields("2026-09-09T00:53:04Z")
    assert fields["created_at_et"] == "2026-09-08T20:53:04-04:00"
    assert fields["et_date"] == "2026-09-08"
    assert fields["et_hour"] == 20
    assert fields["et_dow"] == 1  # Tuesday


def test_et_fields_january_standard_time_offset():
    fields = et_fields("2026-01-15T14:05:00Z")
    assert fields["created_at_et"] == "2026-01-15T09:05:00-05:00"
    assert fields["et_date"] == "2026-01-15"
    assert fields["et_hour"] == 9
    assert fields["et_dow"] == 3  # Thursday


# ---------------------------------------------------------------------------
# html_to_text (docs/SPEC.md 6.7)
# ---------------------------------------------------------------------------


def test_html_to_text_empty_or_none():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_html_to_text_removes_quote_inline_blocks_entirely():
    # The whole quote-inline span -- including its own nested tags -- disappears, leaving
    # the two surrounding block boundaries (</p> then <p>) as a single newline.
    html = '<p>Main text</p><span class="quote-inline">quoted stuff <b>bold</b></span><p>after</p>'
    assert html_to_text(html) == "Main text\nafter"


def test_html_to_text_br_and_p_become_newlines():
    html = "<p>line one<br>line two</p><p>paragraph two</p>"
    assert html_to_text(html) == "line one\nline two\nparagraph two"


def test_html_to_text_div_close_becomes_newline():
    html = "<div>first</div><div>second</div>"
    assert html_to_text(html) == "first\nsecond"


def test_html_to_text_unescapes_entities():
    html = "<p>Tom &amp; Jerry &mdash; 100&#37; &quot;great&quot;</p>"
    assert html_to_text(html) == 'Tom & Jerry — 100% "great"'


def test_html_to_text_collapses_whitespace_and_blank_lines():
    html = "<p>a   b\t\tc</p><br><br><br><p>d</p>"
    result = html_to_text(html)
    assert "a b c" in result
    # 3+ consecutive newlines collapse to 2, and the ends are stripped.
    assert "\n\n\n" not in result
    assert result == result.strip()


def test_html_to_text_strips_remaining_tags():
    html = '<p>Hello <a href="https://example.com">world</a> <b>bold</b></p>'
    assert html_to_text(html) == "Hello world bold"
