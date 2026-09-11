"""Shared helpers: time handling, clocks, HTML to text, run ids, and the collector context.

HTTP transports and the paced ``Http`` client live further down in this module (see docs/SPEC.md section 5).
Python 3.9 compatible.
"""
from __future__ import annotations

import email.utils
import html as html_lib
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

ACCOUNT_ID = "107780257626128497"
HANDLE = "realDonaldTrump"
UTC = timezone.utc
EASTERN = ZoneInfo("America/New_York")
ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
TS_ID_RE = re.compile(r"^\d{18}$")

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?\s*(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso_utc(value: str) -> datetime:
    """Parse an ISO-8601 or RFC-2822 timestamp into an aware UTC datetime.

    Accepted: ``2026-09-09T00:53:04.960Z``, ``2026-09-09T00:53:04Z``, ``2026-09-09T00:53:04+00:00``,
    ``2026-09-09 00:53:04`` (assumed UTC), ``Fri, 11 Sep 2026 01:19:51 +0000``.
    """
    if value is None:
        raise ValueError("timestamp is None")
    s = value.strip()
    m = _ISO_RE.match(s)
    if m:
        year, month, day, hour, minute, second = (int(x) for x in m.groups()[:6])
        frac = m.group(7)
        micro = int((frac + "000000")[:6]) if frac else 0
        offset = m.group(8)
        if offset in (None, "Z"):
            tz = UTC
        else:
            sign = 1 if offset[0] == "+" else -1
            digits = offset[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
        return datetime(year, month, day, hour, minute, second, micro, tzinfo=tz).astimezone(UTC)
    try:
        dt = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("unrecognized timestamp: %r" % value) from exc
    if dt is None:
        raise ValueError("unrecognized timestamp: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_utc_iso(dt: datetime) -> str:
    """Render an aware datetime as ``YYYY-MM-DDTHH:MM:SSZ`` (sub-seconds dropped)."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_iso(value: str) -> str:
    """Parse any accepted timestamp and re-render it in the canonical UTC form."""
    return to_utc_iso(parse_iso_utc(value))


_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_ET_TEXT_RE = re.compile(
    r"(?:[A-Za-z]+,\s*)?"  # optional weekday
    r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4}),?\s+"  # month day year
    r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?"  # time
    r"(?:\s*(E[SD]T|ET))?"  # optional zone abbreviation
)


def parse_et_text(text: str) -> str:
    """Parse a trumpstruth.org Eastern-time string into canonical UTC ISO.

    Examples: ``Tuesday, September 8, 2026, 09:10 pm EDT``, ``Sep 8, 2026, 10:20 PM EDT``,
    ``September 10, 2026, 11:48 AM``. A zone abbreviation, when present, must match America/New_York for
    that instant; otherwise ``ValueError`` is raised.
    """
    m = _ET_TEXT_RE.search(text or "")
    if not m:
        raise ValueError("unrecognized Eastern time text: %r" % text)
    month_name, day, year, hour, minute, second, ampm, zone = m.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        raise ValueError("unknown month in %r" % text)
    hour_i = int(hour)
    if ampm:
        is_pm = ampm.lower().startswith("p")
        if hour_i == 12:
            hour_i = 12 if is_pm else 0
        elif is_pm:
            hour_i += 12
    fold = 1 if (zone or "").upper() == "EST" else 0
    local = datetime(int(year), month, int(day), hour_i, int(minute), int(second or 0), tzinfo=EASTERN, fold=fold)
    if zone and zone.upper() in ("EST", "EDT") and local.tzname() != zone.upper():
        raise ValueError("zone %s does not match America/New_York for %r" % (zone, text))
    return to_utc_iso(local)


def et_fields(created_at_utc: str) -> Dict[str, Any]:
    """Derive the Eastern-time analysis fields from a canonical UTC timestamp."""
    local = parse_iso_utc(created_at_utc).astimezone(EASTERN)
    return {
        "created_at_et": local.isoformat(timespec="seconds"),
        "et_date": local.date().isoformat(),
        "et_hour": local.hour,
        "et_dow": local.weekday(),
    }


# ---------------------------------------------------------------------------
# Clocks and run ids
# ---------------------------------------------------------------------------


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            import time

            time.sleep(seconds)


class FakeClock:
    """Deterministic clock for tests: ``sleep`` advances ``now`` and records the durations."""

    def __init__(self, start: Optional[datetime] = None):
        self._now = start or datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)
        if self._now.tzinfo is None:
            self._now = self._now.replace(tzinfo=UTC)
        self.sleeps: List[float] = []

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if seconds > 0:
            self._now = self._now + timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


def utc_now_iso(clock: Any) -> str:
    return to_utc_iso(clock.now())


def new_run_id(clock: Any) -> str:
    return clock.now().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(2)


# ---------------------------------------------------------------------------
# HTML to text
# ---------------------------------------------------------------------------

_QUOTE_INLINE_RE = re.compile(r"<span[^>]*\bclass=\"[^\"]*\bquote-inline\b[^\"]*\"[^>]*>.*?</span>", re.S | re.I)
_BREAK_RE = re.compile(r"<br\s*/?>|</p\s*>|</div\s*>|</li\s*>|</h[1-6]\s*>|</blockquote\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(html_str: Optional[str]) -> str:
    """Convert post HTML to plain text (docs/SPEC.md 6.7)."""
    if not html_str:
        return ""
    s = _QUOTE_INLINE_RE.sub("", html_str)
    s = _BREAK_RE.sub("\n", s)
    s = _TAG_RE.sub("", s)
    s = html_lib.unescape(s).replace("\xa0", " ").replace("\r", "")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in s.split("\n")]
    s = "\n".join(lines)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ---------------------------------------------------------------------------
# Collector context
# ---------------------------------------------------------------------------


@dataclass
class Context:
    http: Any
    clock: Any
    data_root: Path
    state: Dict[str, Any]
    run_id: str
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("scripts.collect"))
    raw_dir: Optional[Path] = None  # when set, collectors may save raw responses here

    def now_iso(self) -> str:
        return utc_now_iso(self.clock)


# ---------------------------------------------------------------------------
# HTTP (docs/SPEC.md section 5)
# ---------------------------------------------------------------------------

import json
import urllib.error
import urllib.request
from typing import Protocol
from urllib.parse import urlsplit

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class Response:
    """An HTTP response: status code, lower-cased headers, and raw body bytes."""

    def __init__(self, status: int, headers: Optional[Dict[str, str]] = None, body: bytes = b""):
        self.status = status
        self.headers: Dict[str, str] = {k.lower(): v for k, v in (headers or {}).items()}
        self.body: bytes = body if body is not None else b""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Response(status=%r, headers=%r, body=%d bytes)" % (self.status, self.headers, len(self.body))


class TransportError(Exception):
    """A network-level failure: DNS, connection reset, timeout, etc."""


class HttpError(Exception):
    """Raised by :class:`Http` once retries are exhausted."""

    def __init__(self, status: Optional[int], url: str):
        self.status = status
        self.url = url
        super().__init__("HTTP %s for %s" % (status, url))


class Transport(Protocol):
    """Sends a single GET request. Must never raise for HTTP status codes (4xx/5xx)."""

    def get(self, url: str, headers: Dict[str, str], timeout: float) -> Response:
        ...


class UrllibTransport:
    """Transport built on the standard library's ``urllib``."""

    def get(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30.0) -> Response:
        request = urllib.request.Request(url, headers=headers or {}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return Response(resp.status, dict(resp.headers.items()), resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            headers_out = dict(exc.headers.items()) if exc.headers is not None else {}
            exc.close()
            return Response(exc.code, headers_out, body)
        except urllib.error.URLError as exc:
            raise TransportError(str(exc.reason)) from exc
        except OSError as exc:
            # e.g. socket.timeout and other low-level connection failures not wrapped by urllib
            raise TransportError(str(exc)) from exc


class CurlCffiTransport:
    """Fallback transport built on ``curl_cffi``, impersonating a real browser TLS fingerprint."""

    def get(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30.0) -> Response:
        import curl_cffi

        try:
            resp = curl_cffi.requests.get(url, headers=headers or {}, timeout=timeout, impersonate="chrome")
        except Exception as exc:  # curl_cffi's exception hierarchy varies by version
            raise TransportError(str(exc)) from exc
        return Response(resp.status_code, dict(resp.headers), resp.content)


class FakeTransport:
    """Deterministic transport for tests.

    ``routes`` maps a url string, or a ``callable(url) -> bool``, to either a single
    :class:`Response` (returned every time it matches) or a list of ``Response`` objects
    consumed in order (raises a clear error once exhausted). ``.calls`` records every
    ``(url, headers)`` pair passed to ``get``.
    """

    def __init__(self, routes: Dict[Any, Any]):
        self._routes = list(routes.items())
        self.calls: List[Any] = []

    def get(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30.0) -> Response:
        self.calls.append((url, dict(headers or {})))
        for matcher, value in self._routes:
            if self._matches(matcher, url):
                return self._consume(value, url)
        raise AssertionError("FakeTransport: no route matches %r" % (url,))

    @staticmethod
    def _matches(matcher: Any, url: str) -> bool:
        if callable(matcher):
            return bool(matcher(url))
        return matcher == url

    @staticmethod
    def _consume(value: Any, url: str) -> Response:
        if isinstance(value, list):
            if not value:
                raise AssertionError("FakeTransport: responses for %r are exhausted" % (url,))
            return value.pop(0)
        return value


_DEFAULT_MIN_INTERVAL: Dict[str, float] = {
    "truthsocial.com": 12.0,
    "www.trumpstruth.org": 1.5,
    "trumpstruth.org": 1.5,
    "ix.cnn.io": 0.0,
}


class Http:
    """Paced HTTP client: per-host rate limiting, 429/5xx retry, 403 fallback (docs/SPEC.md section 5)."""

    DEFAULT_MIN_INTERVAL = _DEFAULT_MIN_INTERVAL

    def __init__(
        self,
        transport: Any,
        clock: Any,
        min_interval: Optional[Dict[str, float]] = None,
        max_attempts: int = 4,
        fallback_transport: Any = None,
    ):
        self.transport = transport
        self.clock = clock
        self.min_interval: Dict[str, float] = dict(_DEFAULT_MIN_INTERVAL)
        if min_interval:
            self.min_interval.update(min_interval)
        self.max_attempts = max_attempts
        self.fallback_transport = fallback_transport
        self.request_count = 0
        self._last_request_at: Dict[str, datetime] = {}
        self._fallback_hosts: set = set()

    def get(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30.0) -> Response:
        host = (urlsplit(url).hostname or "").lower()
        merged_headers = self._build_headers(host, headers)
        attempt = 0
        while True:
            attempt += 1
            self._pace(host)
            transport = self._transport_for(host)
            self._last_request_at[host] = self.clock.now()
            self.request_count += 1
            try:
                response = transport.get(url, headers=merged_headers, timeout=timeout)
            except TransportError:
                if attempt >= self.max_attempts:
                    raise
                continue

            status = response.status

            if status == 429:
                if attempt >= self.max_attempts:
                    raise HttpError(status, url)
                self.clock.sleep(self._retry_after_seconds(response))
                continue

            if 500 <= status < 600:
                if attempt >= self.max_attempts:
                    raise HttpError(status, url)
                self.clock.sleep(5 * attempt)
                continue

            if status == 403 and host == "truthsocial.com" and self.fallback_transport is not None:
                self._fallback_hosts.add(host)
                if attempt >= self.max_attempts:
                    raise HttpError(status, url)
                continue

            return response

    def _transport_for(self, host: str) -> Any:
        if host in self._fallback_hosts and self.fallback_transport is not None:
            return self.fallback_transport
        return self.transport

    def _pace(self, host: str) -> None:
        interval = self.min_interval.get(host, 0.0)
        if interval <= 0:
            return
        last = self._last_request_at.get(host)
        if last is None:
            return
        elapsed = (self.clock.now() - last).total_seconds()
        wait = interval - elapsed
        if wait > 0:
            self.clock.sleep(wait)

    @staticmethod
    def _build_headers(host: str, headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        merged = {
            "User-Agent": _CHROME_UA,
            "Accept-Language": "en-US,en;q=0.9",
        }
        if host == "truthsocial.com":
            merged["Accept"] = "application/json, text/plain, */*"
            merged["Referer"] = "https://truthsocial.com/@realDonaldTrump"
        if headers:
            merged.update(headers)
        return merged

    @staticmethod
    def _retry_after_seconds(response: "Response") -> int:
        raw = response.headers.get("retry-after")
        if raw is None:
            return 30
        try:
            seconds = int(str(raw).strip())
        except (TypeError, ValueError):
            return 30
        if seconds < 0:
            return 30
        return min(seconds, 120)
