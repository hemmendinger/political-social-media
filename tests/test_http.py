"""Tests for the HTTP layer in scripts/common.py (docs/SPEC.md section 5).

No network access: everything runs through FakeTransport + FakeClock.
"""
from datetime import datetime, timezone

import pytest

from scripts.common import (
    FakeClock,
    FakeTransport,
    Http,
    HttpError,
    Response,
    TransportError,
)

UTC = timezone.utc


class FlakyTransport:
    """A Transport that raises TransportError the first ``fail_times`` calls, then answers.

    Not part of the spec'd FakeTransport contract (which only ever returns Response objects) --
    this is a minimal local test double for exercising the TransportError retry path without
    touching the network.
    """

    def __init__(self, fail_times, then_response):
        self.calls = []
        self._fail_times = fail_times
        self._response = then_response
        self._count = 0

    def get(self, url, headers=None, timeout=30.0):
        self.calls.append((url, dict(headers or {})))
        self._count += 1
        if self._count <= self._fail_times:
            raise TransportError("simulated connection reset")
        return self._response


def make_clock():
    return FakeClock(datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC))


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------


def test_pacing_sleeps_between_two_trumpstruth_requests():
    clock = make_clock()
    transport = FakeTransport(
        {
            "https://trumpstruth.org/a": Response(200, {}, b"a"),
            "https://trumpstruth.org/b": Response(200, {}, b"b"),
        }
    )
    http = Http(transport, clock)
    http.get("https://trumpstruth.org/a")
    http.get("https://trumpstruth.org/b")
    assert clock.sleeps == [1.5]


def test_pacing_none_for_ix_cnn_io():
    clock = make_clock()
    transport = FakeTransport(
        {
            "https://ix.cnn.io/a": Response(200, {}, b"a"),
            "https://ix.cnn.io/b": Response(200, {}, b"b"),
        }
    )
    http = Http(transport, clock)
    http.get("https://ix.cnn.io/a")
    http.get("https://ix.cnn.io/b")
    assert clock.sleeps == []


def test_pacing_no_sleep_when_enough_time_already_elapsed():
    clock = make_clock()
    transport = FakeTransport(
        {
            "https://trumpstruth.org/a": Response(200, {}, b"a"),
            "https://trumpstruth.org/b": Response(200, {}, b"b"),
        }
    )
    http = Http(transport, clock)
    http.get("https://trumpstruth.org/a")
    clock.advance(10)  # well past the 1.5s min_interval
    http.get("https://trumpstruth.org/b")
    assert clock.sleeps == []


# ---------------------------------------------------------------------------
# 429 handling
# ---------------------------------------------------------------------------


def test_429_with_retry_after_sleeps_that_many_seconds_then_succeeds():
    clock = make_clock()
    transport = FakeTransport(
        {
            "https://trumpstruth.org/x": [
                Response(429, {"Retry-After": "7"}, b""),
                Response(200, {}, b"ok"),
            ]
        }
    )
    http = Http(transport, clock)
    resp = http.get("https://trumpstruth.org/x")
    assert resp.status == 200
    assert resp.text == "ok"
    assert clock.sleeps == [7]
    assert http.request_count == 2


def test_429_without_retry_after_sleeps_default_30():
    clock = make_clock()
    transport = FakeTransport(
        {
            "https://trumpstruth.org/x": [
                Response(429, {}, b""),
                Response(200, {}, b"ok"),
            ]
        }
    )
    http = Http(transport, clock)
    resp = http.get("https://trumpstruth.org/x")
    assert resp.status == 200
    assert clock.sleeps == [30]


def test_429_retry_after_capped_to_120():
    clock = make_clock()
    transport = FakeTransport(
        {
            "https://trumpstruth.org/x": [
                Response(429, {"Retry-After": "500"}, b""),
                Response(200, {}, b"ok"),
            ]
        }
    )
    http = Http(transport, clock)
    http.get("https://trumpstruth.org/x")
    assert clock.sleeps == [120]


# ---------------------------------------------------------------------------
# 5xx handling
# ---------------------------------------------------------------------------


def test_5xx_retried_then_http_error_after_max_attempts():
    clock = make_clock()
    responses = [Response(503, {}, b"unavailable") for _ in range(4)]
    transport = FakeTransport({"https://trumpstruth.org/x": responses})
    http = Http(transport, clock, max_attempts=4)
    with pytest.raises(HttpError) as excinfo:
        http.get("https://trumpstruth.org/x")
    assert excinfo.value.status == 503
    assert excinfo.value.url == "https://trumpstruth.org/x"
    assert clock.sleeps == [5, 10, 15]  # 5 * attempt, no sleep before the final raise
    assert http.request_count == 4


def test_5xx_recovers_before_exhausting_attempts():
    clock = make_clock()
    transport = FakeTransport(
        {
            "https://trumpstruth.org/x": [
                Response(500, {}, b""),
                Response(200, {}, b"ok"),
            ]
        }
    )
    http = Http(transport, clock, max_attempts=4)
    resp = http.get("https://trumpstruth.org/x")
    assert resp.status == 200
    assert clock.sleeps == [5]


# ---------------------------------------------------------------------------
# 403 fallback (truthsocial.com only)
# ---------------------------------------------------------------------------


def test_403_on_truthsocial_switches_to_fallback_and_sticks():
    clock = make_clock()
    primary = FakeTransport(
        {
            "https://truthsocial.com/api/1": Response(403, {}, b"blocked"),
            "https://truthsocial.com/api/2": Response(403, {}, b"blocked"),
        }
    )
    fallback = FakeTransport(
        {
            "https://truthsocial.com/api/1": Response(200, {}, b"one"),
            "https://truthsocial.com/api/2": Response(200, {}, b"two"),
        }
    )
    http = Http(primary, clock, fallback_transport=fallback)

    resp1 = http.get("https://truthsocial.com/api/1")
    assert resp1.status == 200
    assert resp1.text == "one"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1

    # Second call to the same host should go straight to the fallback transport.
    resp2 = http.get("https://truthsocial.com/api/2")
    assert resp2.status == 200
    assert resp2.text == "two"
    assert len(primary.calls) == 1  # primary untouched this time
    assert len(fallback.calls) == 2


def test_403_on_truthsocial_without_fallback_is_returned_not_raised():
    clock = make_clock()
    transport = FakeTransport({"https://truthsocial.com/api/1": Response(403, {}, b"blocked")})
    http = Http(transport, clock)  # no fallback_transport configured
    resp = http.get("https://truthsocial.com/api/1")
    assert resp.status == 403
    assert http.request_count == 1


def test_403_on_other_host_is_returned_not_raised_even_with_fallback():
    clock = make_clock()
    primary = FakeTransport({"https://ix.cnn.io/data": Response(403, {}, b"blocked")})
    fallback = FakeTransport({"https://ix.cnn.io/data": Response(200, {}, b"should not be used")})
    http = Http(primary, clock, fallback_transport=fallback)
    resp = http.get("https://ix.cnn.io/data")
    assert resp.status == 403
    assert len(fallback.calls) == 0


# ---------------------------------------------------------------------------
# Other 4xx
# ---------------------------------------------------------------------------


def test_404_is_returned_not_raised():
    clock = make_clock()
    transport = FakeTransport({"https://trumpstruth.org/missing": Response(404, {}, b"not found")})
    http = Http(transport, clock)
    resp = http.get("https://trumpstruth.org/missing")
    assert resp.status == 404
    assert resp.text == "not found"


def test_other_4xx_is_returned_not_raised():
    clock = make_clock()
    transport = FakeTransport({"https://trumpstruth.org/x": Response(410, {}, b"gone")})
    http = Http(transport, clock)
    resp = http.get("https://trumpstruth.org/x")
    assert resp.status == 410


# ---------------------------------------------------------------------------
# TransportError
# ---------------------------------------------------------------------------


def test_transport_error_counts_as_an_attempt_then_succeeds():
    clock = make_clock()
    transport = FlakyTransport(fail_times=1, then_response=Response(200, {}, b"ok"))
    http = Http(transport, clock, max_attempts=4)
    resp = http.get("https://trumpstruth.org/x")
    assert resp.status == 200
    assert http.request_count == 2
    assert len(transport.calls) == 2


def test_transport_error_exhausts_attempts_and_reraises():
    clock = make_clock()
    transport = FlakyTransport(fail_times=99, then_response=Response(200, {}, b"ok"))
    http = Http(transport, clock, max_attempts=3)
    with pytest.raises(TransportError):
        http.get("https://trumpstruth.org/x")
    assert http.request_count == 3
    assert len(transport.calls) == 3


# ---------------------------------------------------------------------------
# request_count
# ---------------------------------------------------------------------------


def test_request_count_increments_across_calls():
    clock = make_clock()
    transport = FakeTransport(
        {
            "https://ix.cnn.io/a": Response(200, {}, b"a"),
            "https://ix.cnn.io/b": Response(200, {}, b"b"),
        }
    )
    http = Http(transport, clock)
    assert http.request_count == 0
    http.get("https://ix.cnn.io/a")
    assert http.request_count == 1
    http.get("https://ix.cnn.io/b")
    assert http.request_count == 2


# ---------------------------------------------------------------------------
# Default headers
# ---------------------------------------------------------------------------


def test_default_headers_present_for_generic_host():
    clock = make_clock()
    transport = FakeTransport({"https://ix.cnn.io/data": Response(200, {}, b"{}")})
    http = Http(transport, clock)
    http.get("https://ix.cnn.io/data")
    url, headers = transport.calls[0]
    assert headers["User-Agent"].startswith("Mozilla/5.0")
    assert "Chrome" in headers["User-Agent"]
    assert headers["Accept-Language"] == "en-US,en;q=0.9"
    assert "Accept" not in headers
    assert "Referer" not in headers


def test_default_headers_include_accept_and_referer_for_truthsocial():
    clock = make_clock()
    transport = FakeTransport({"https://truthsocial.com/api/x": Response(200, {}, b"{}")})
    http = Http(transport, clock)
    http.get("https://truthsocial.com/api/x")
    url, headers = transport.calls[0]
    assert headers["Accept"] == "application/json, text/plain, */*"
    assert headers["Referer"] == "https://truthsocial.com/@realDonaldTrump"


def test_caller_headers_override_and_extend_defaults():
    clock = make_clock()
    transport = FakeTransport({"https://ix.cnn.io/data": Response(200, {}, b"{}")})
    http = Http(transport, clock)
    http.get("https://ix.cnn.io/data", headers={"If-None-Match": 'W/"abc"', "Accept-Language": "fr"})
    url, headers = transport.calls[0]
    assert headers["If-None-Match"] == 'W/"abc"'
    assert headers["Accept-Language"] == "fr"


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


def test_response_lower_cases_header_keys():
    resp = Response(200, {"Content-Type": "application/json", "X-Foo": "Bar"}, b"{}")
    assert resp.headers == {"content-type": "application/json", "x-foo": "Bar"}


def test_response_text_decodes_utf8_with_replace_errors():
    resp = Response(200, {}, b"\xff\xfehello")
    text = resp.text  # must not raise, even on invalid utf-8
    assert "hello" in text


def test_response_json():
    resp = Response(200, {"Content-Type": "application/json"}, b'{"a": 1, "b": [1, 2, 3]}')
    assert resp.json() == {"a": 1, "b": [1, 2, 3]}


# ---------------------------------------------------------------------------
# FakeTransport itself
# ---------------------------------------------------------------------------


def test_fake_transport_callable_matcher():
    resp = Response(200, {}, b"matched")
    transport = FakeTransport({lambda url: "special" in url: resp})
    out = transport.get("https://example.com/special/path")
    assert out is resp


def test_fake_transport_raises_clear_error_when_list_exhausted():
    transport = FakeTransport({"https://example.com/x": [Response(200, {}, b"only one")]})
    transport.get("https://example.com/x")
    with pytest.raises(Exception):
        transport.get("https://example.com/x")


def test_fake_transport_single_response_reused_indefinitely():
    resp = Response(200, {}, b"static")
    transport = FakeTransport({"https://example.com/x": resp})
    assert transport.get("https://example.com/x") is resp
    assert transport.get("https://example.com/x") is resp
    assert transport.get("https://example.com/x") is resp
