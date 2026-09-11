"""Pure parsers for trumpstruth.org, the Truth Social API, and CNN's archive (docs/SPEC.md section 6).

Every function is pure (no network, no clock) and returns plain dicts: a "partial record" is a subset of
the docs/SPEC.md section 2 post fields plus ``_source`` and, where known, ``_engagement``. ``ParseError`` is
raised only when the container markup a function depends on is entirely absent (a drift guard for when the
site's template changes); a container that legitimately holds nothing yields an empty list/None fields
instead. Only the standard library is used (``re`` and ``xml.etree.ElementTree``; no third-party HTML libs).

This module was written against real captures in tests/fixtures/ (see its README) and several places where
docs/SPEC.md section 6 turned out not to match what the site actually sends are called out inline below with
"SPEC MISMATCH" comments (also summarized in the implementation report). Highlights:

* The reblog marker's actual CSS class is ``status__reblog-indicator`` (holding the text "<Name> ReTruthed"),
  never ``status__reblog-info`` as section 6.2 says.
* On listing/home/cursor pages, a card preceded by a ``status__reblog-indicator`` is the *reblogged post's
  own* card markup reused verbatim (same trumpstruth id, same ts_id, same header time as if you'd fetched the
  target directly) -- not a distinct card for the repost. The repost's own distinct trumpstruth id / ts_id /
  repost time is never exposed on listing pages -- only on that repost's own status page (reachable via the
  removed-search results, not via the listing). So ``parse_listing`` reports such a card under its own
  ordinary kind (``original``, or ``quote`` if it happens to have a nested status -- never ``reblog``), plus
  ``retruthed: True`` and ``retruthed_by`` (the name in the indicator). The same target can carry several
  ``retruthed: True`` occurrences on one page (one per repost event); callers that want a deduplicated list
  of distinct posts need to dedupe on ``trumpstruth_id``/``ts_id`` themselves.
* trumpstruth search result rows never carry a ``<time datetime>`` in any captured fixture (only plain text
  like "September 8, 2026, 9:10 PM"); per section 6.3's own wording ("when present") we leave
  ``created_at_utc`` as None there rather than reparsing the text.
* Removed-search snippets use *two different* "RT" formats in the same file: the literal
  ``RT: https://truthsocial.com/users/<acct>/statuses/<id>`` form section 6.3 documents, and the CNN-style
  glued ``RT @handleRemainder...`` form with no id at all. Both are handled.
"""
from __future__ import annotations

import base64
import copy
import json
import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from scripts.common import HANDLE, html_to_text, normalize_iso, parse_et_text

TRUMPSTRUTH_BASE = "https://www.trumpstruth.org"


class ParseError(Exception):
    """Raised when the markup a parser depends on is entirely absent (drift guard)."""


# ---------------------------------------------------------------------------
# Generic, nesting-aware "<div class="status">" scanning, shared by the listing
# and status-page parsers (docs/SPEC.md 6.1, 6.2).
# ---------------------------------------------------------------------------

_DIV_TAG_RE = re.compile(r"<div\b[^>]*>|</div\s*>", re.I)
_STATUS_DIV_OPEN_RE = re.compile(
    r'<div\s+class="status"(?:\s+data-status-url="https://www\.trumpstruth\.org/statuses/(\d+)")?\s*>', re.I
)


def _find_matching_close(html: str, open_end: int) -> Tuple[int, int]:
    """Given the index right after some tag's opening ``<div ...>``, return (inner_end, block_end):
    the index where the matching ``</div>`` starts, and the index right after it. Depth-counts nested
    ``<div>`` tags so a nested status div doesn't terminate the match early."""
    depth = 1
    for m in _DIV_TAG_RE.finditer(html, open_end):
        if m.group(0)[1] == "/":
            depth -= 1
            if depth == 0:
                return m.start(), m.end()
        else:
            depth += 1
    raise ParseError("unbalanced <div> while scanning a status block")


def _iter_status_divs(html: str, start: int = 0, end: Optional[int] = None) -> List[Dict[str, Any]]:
    """Top-level ``<div class="status">`` blocks in ``html[start:end]``. A block nested inside another
    (the quoted/reblogged inner post) is *not* returned as its own entry, because the scan jumps to each
    block's matching close before searching again -- exactly the "nested status is part of the card body,
    not a separate card" rule in docs/SPEC.md 6.1."""
    if end is None:
        end = len(html)
    pos = start
    blocks = []
    while True:
        m = _STATUS_DIV_OPEN_RE.search(html, pos, end)
        if not m:
            break
        inner_start = m.end()
        inner_end, block_end = _find_matching_close(html, inner_start)
        blocks.append(
            {
                "trumpstruth_id": int(m.group(1)) if m.group(1) else None,
                "inner_html": html[inner_start:inner_end],
                "start": m.start(),
                "end": block_end,
            }
        )
        pos = block_end
    return blocks


_HEADER_HANDLE_RE = re.compile(r'class="status-info__meta-item">@([A-Za-z0-9_]+)</a>')
_HEADER_TIME_RE = re.compile(r'<time datetime="([^"]+)"')
_EXTERNAL_LINK_TAG_RE = re.compile(r'<a\s[^>]*class="status__external-link"[^>]*>', re.I)
_EXTERNAL_HREF_RE = re.compile(r'href="https://truthsocial\.com/@([A-Za-z0-9_]+)/(\d+)"')
_CONTENT_RE = re.compile(r'<div class="status__content">(.*?)</div>', re.S)

# One combined, order-preserving scan for both attachment kinds (docs/SPEC.md 6.1):
#   image: <a href=mirror_url><img src=...></a> -- src counts as `url` only when it points at
#          truthsocial.com, else it's just a `preview_url` (the trumpstruth-page-only linodeobjects
#          copy is not a truthsocial original).
#   video: <video src=url poster=mirror_url> -- the poster is the only trumpstruth (linodeobjects) copy
#          available at this markup; the linodeobjects *video* mirror only appears in the separate
#          "File Attachments" details section, which we deliberately do not scrape.
_ATTACHMENT_RE = re.compile(
    r'<div class="status-attachment status-attachment--image">\s*'
    r'<a href="([^"]*)"[^>]*>\s*<img src="([^"]*)"'
    r"|"
    r'<div class="status-attachment status-attachment--video">\s*'
    r'<video src="([^"]*)"[^>]*?\bposter="([^"]*)"',
    re.I | re.S,
)


def _extract_media(scope: str) -> List[Dict[str, Any]]:
    media = []
    for m in _ATTACHMENT_RE.finditer(scope):
        if m.group(1) is not None or m.group(2) is not None:
            mirror_url, img_src = m.group(1) or None, m.group(2) or None
            if img_src and "truthsocial.com" in img_src:
                url, preview_url = img_src, None
            else:
                url, preview_url = None, img_src
            media.append(
                {
                    "type": "image",
                    "url": url,
                    "preview_url": preview_url,
                    "mirror_url": mirror_url,
                    "width": None,
                    "height": None,
                    "duration": None,
                }
            )
        else:
            video_src, poster = m.group(3) or None, m.group(4) or None
            media.append(
                {
                    "type": "video",
                    "url": video_src,
                    "preview_url": None,
                    "mirror_url": poster,
                    "width": None,
                    "height": None,
                    "duration": None,
                }
            )
    return media


def _external_link(scope: str) -> Optional[Tuple[str, str]]:
    """Return (handle, ts_id) from a `status__external-link` anchor, or None."""
    tag_m = _EXTERNAL_LINK_TAG_RE.search(scope)
    if not tag_m:
        return None
    href_m = _EXTERNAL_HREF_RE.search(tag_m.group(0))
    if not href_m:
        return None
    return href_m.group(1), href_m.group(2)


def _parse_single_status(inner_html: str) -> Dict[str, Any]:
    """Parse one card/status div's own inner HTML: its own handle/ts_id/time/content/media, plus (when a
    quoted or reblogged inner post is nested inside it) the same for that nested post under "nested"."""
    nested_blocks = _iter_status_divs(inner_html)
    own_scope = inner_html[: nested_blocks[0]["start"]] if nested_blocks else inner_html

    handle_m = _HEADER_HANDLE_RE.search(own_scope)
    time_m = _HEADER_TIME_RE.search(own_scope)
    link = _external_link(own_scope)
    content_m = _CONTENT_RE.search(own_scope)

    result: Dict[str, Any] = {
        "handle": handle_m.group(1) if handle_m else None,
        "ts_id": link[1] if link else None,
        "created_at_utc": normalize_iso(time_m.group(1)) if time_m else None,
        "content_html": content_m.group(1).strip() if content_m else "",
        "media": _extract_media(own_scope),
        "nested": None,
    }
    if nested_blocks:
        nb_scope = nested_blocks[0]["inner_html"]
        n_handle_m = _HEADER_HANDLE_RE.search(nb_scope)
        n_time_m = _HEADER_TIME_RE.search(nb_scope)
        n_link = _external_link(nb_scope)
        result["nested"] = {
            "handle": n_handle_m.group(1) if n_handle_m else None,
            "ts_id": n_link[1] if n_link else None,
            "created_at_utc": normalize_iso(n_time_m.group(1)) if n_time_m else None,
        }
    return result


# ---------------------------------------------------------------------------
# 6.1 trumpstruth listing and home page
# ---------------------------------------------------------------------------

_STATUSES_CONTAINER_RE = re.compile(r'<div class="statuses"\s*>')
_REBLOG_MARK_RE = re.compile(r'<div\s+class="status__reblog-indicator">(.*?)</div>', re.I | re.S)
_REBLOG_NAME_RE = re.compile(r"<strong>(.*?)</strong>", re.S)
_NEXT_PAGE_RE = re.compile(r'<a href="([^"]+)"[^>]*>\s*Next Page', re.S)
_CURSOR_PARAM_RE = re.compile(r"[?&]cursor=([^&]+)")
_PAGE_PARAM_RE = re.compile(r"[?&]page=(\d+)")


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """Parse a trumpstruth listing/home/cursor page into partial records (docs/SPEC.md 6.1).

    A card preceded by a ``status__reblog-indicator`` ("<Name> ReTruthed") is *not* a distinct repost card:
    it is the reblogged target's own card, reused verbatim (see the module docstring). So such a card is
    reported under its own ordinary kind straight from its markup -- ``original``, or ``quote`` if it happens
    to have a nested status -- never ``reblog``, and ``ts_id``/``trumpstruth_id``/``created_at_utc`` are the
    *target's* own identifiers, not a repost's. Two extra keys carry the repost signal instead: ``retruthed``
    (True when a ``status__reblog-indicator`` immediately precedes the card) and ``retruthed_by`` (the name
    inside the indicator, e.g. "Donald J. Trump"; None when not retruthed). We deliberately do *not* set
    ``reblog_of_id``/``reblog_of_acct`` here -- those describe a repost's *own* record, and this page never
    exposes a repost's own ts_id/trumpstruth_id/time at all (only that repost's own status page does, e.g.
    reached via the removed-search results). The same target can appear several times on one page, once per
    repost event, each with ``retruthed: True`` -- every occurrence is returned; deduping by
    ``trumpstruth_id``/``ts_id`` is left to the caller.
    """
    container_m = _STATUSES_CONTAINER_RE.search(html)
    if not container_m:
        raise ParseError('no <div class="statuses"> container found')
    container_end, _ = _find_matching_close(html, container_m.end())
    container_start = container_m.end()

    reblog_marks = []
    for m in _REBLOG_MARK_RE.finditer(html, container_start, container_end):
        name_m = _REBLOG_NAME_RE.search(m.group(1))
        name = html_to_text(name_m.group(1)).strip() if name_m else None
        reblog_marks.append((m.start(), name))
    blocks = _iter_status_divs(html, container_start, container_end)

    records = []
    prev_end = container_start
    for blk in blocks:
        retruthed = False
        retruthed_by = None
        for pos, name in reblog_marks:
            if prev_end <= pos < blk["start"]:
                retruthed = True
                retruthed_by = name
                break

        parsed = _parse_single_status(blk["inner_html"])
        kind = "quote" if parsed["nested"] else "original"

        record: Dict[str, Any] = {
            "_source": "trumpstruth",
            "trumpstruth_id": blk["trumpstruth_id"],
            "trumpstruth_url": "%s/statuses/%d" % (TRUMPSTRUTH_BASE, blk["trumpstruth_id"])
            if blk["trumpstruth_id"] is not None
            else None,
            "ts_id": parsed["ts_id"],
            "created_at_utc": parsed["created_at_utc"],
            "kind": kind,
            "account": parsed["handle"],
            "retruthed": retruthed,
            "retruthed_by": retruthed_by,
            "content_html": parsed["content_html"],
            "media": parsed["media"],
            "quote_id": None,
            "quote_of_acct": None,
        }
        if kind == "quote" and parsed["nested"]:
            record["quote_id"] = parsed["nested"]["ts_id"]
            record["quote_of_acct"] = parsed["nested"]["handle"]
        records.append(record)
        prev_end = blk["end"]
    return records


def parse_next_cursor(html: str) -> Optional[str]:
    """Return the ``cursor=`` value of the "Next Page" link, or None (inactive/absent Next Page)."""
    m = _NEXT_PAGE_RE.search(html)
    if not m:
        return None
    href = unescape(m.group(1))
    cm = _CURSOR_PARAM_RE.search(href)
    return cm.group(1) if cm else None


def make_cursor(naive_ts: str) -> str:
    """Build a trumpstruth pagination cursor from a naive ``YYYY-MM-DD HH:MM:SS`` string (docs/SPEC.md 6.1).
    The site interprets it in its own zone; callers pass UTC plus 5 hours to be safe."""
    payload = json.dumps({"status_created_at": naive_ts, "_pointsToNextItems": True}, separators=(",", ":"))
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# 6.2 trumpstruth status page
# ---------------------------------------------------------------------------

_OG_URL_RE = re.compile(r'<meta property="og:url" content="https://www\.trumpstruth\.org/statuses/(\d+)"')
_DETAILS_ROW_RE = re.compile(
    r'<td class="status-details-table__key">\s*([^<]*?)\s*</td>\s*'
    r'<td class="status-details-table__value">\s*(.*?)\s*</td>',
    re.S,
)


def parse_status_page(html: str) -> Dict[str, Any]:
    """Parse a trumpstruth ``/statuses/<id>`` page into a partial record (docs/SPEC.md 6.2).

    See the module docstring: the reblog marker class is actually ``status__reblog-indicator`` (not
    ``status__reblog-info``). trumpstruth_status_41655_original_retruthed_target.html has none of that
    markup at all -- it is the *target* of a self-repost (see the ``retruthed``/``retruthed_by`` fields on
    ``parse_listing``, which is where that repost relationship actually shows up), and on its own status page
    it is, correctly, just an ordinary original post.

    ``trumpstruth_captured_at`` (from the "Capture Date" row) is trumpstruth's last processing time for this
    page and nothing more: live posts get re-crawled, and removed pages get re-processed too (observed
    2026-09-11: pages removed in April carried September capture dates). It is therefore never evidence that
    the post was alive at that time and must not feed a deletion bound. ``trumpstruth_removed_at`` below is
    upgraded to the capture timestamp only when both fall within the same minute (the capture that discovered
    the removal), otherwise the minute-precision removal text stands.
    """
    og_m = _OG_URL_RE.search(html)
    if not og_m:
        raise ParseError("no og:url meta tag found; not a trumpstruth status page")
    trumpstruth_id = int(og_m.group(1))

    top_blocks = _iter_status_divs(html)
    if not top_blocks:
        raise ParseError("no status div found on status page")
    main = _parse_single_status(top_blocks[0]["inner_html"])

    # SPEC MISMATCH (docs/SPEC.md 6.2): the class is `status__reblog-indicator`, holding the text
    # "<Name> ReTruthed" -- `status__reblog-info` never appears in any captured fixture.
    is_reblog = bool(re.search(r'class="status__reblog-indicator"', html))

    details: Dict[str, str] = {}
    for m in _DETAILS_ROW_RE.finditer(html):
        key = html_to_text(m.group(1)).strip()
        details[key] = m.group(2)

    removed = "Removed from platform" in details

    # ts_id / created_at_utc: prefer the details table (always present, and the *only* accurate source
    # for a reblog page, where the status div itself shows the *reblogged* post's own ts_id/time).
    ts_id = main["ts_id"]
    tsid_m = re.search(r"<code>(\d+)</code>", details.get("TRUTH Social status ID", ""))
    if tsid_m:
        ts_id = tsid_m.group(1)

    created_at_utc = main["created_at_utc"]
    opd = details.get("Original Post Date")
    if opd:
        time_m = _HEADER_TIME_RE.search(opd)
        created_at_utc = normalize_iso(time_m.group(1)) if time_m else parse_et_text(html_to_text(opd))

    captured_at = None
    cap = details.get("Capture Date")
    if cap:
        time_m = _HEADER_TIME_RE.search(cap)
        captured_at = normalize_iso(time_m.group(1)) if time_m else parse_et_text(html_to_text(cap))

    removed_at = None
    if removed:
        # SPEC MISMATCH (docs/SPEC.md 6.2): in every removed fixture, the "Removed from platform" cell
        # itself carries no <time> tag at all -- only minute-precision plain text like "Yes -- confirmed
        # removed Sep 8, 2026, 10:20 PM EDT" (no seconds), so that's the floor of our precision. The Capture
        # Date row's own <time> tag (see the docstring: that recapture is what discovered the removal) is
        # often the *same* instant with second precision -- when it falls in the same minute as the text, we
        # use that more precise value; otherwise (e.g. a later recapture that merely re-confirmed removal)
        # the two can genuinely disagree, and the text -- what trumpstruth itself says removal was confirmed
        # at -- wins.
        removed_cell = details.get("Removed from platform", "")
        removed_at = parse_et_text(html_to_text(removed_cell))
        if captured_at and captured_at[:16] == removed_at[:16]:
            removed_at = captured_at

    kind = "reblog" if is_reblog else ("quote" if main["nested"] else "original")

    record: Dict[str, Any] = {
        "_source": "trumpstruth",
        "trumpstruth_id": trumpstruth_id,
        "trumpstruth_url": "%s/statuses/%d" % (TRUMPSTRUTH_BASE, trumpstruth_id),
        "ts_id": ts_id,
        "created_at_utc": created_at_utc,
        "kind": kind,
        "removed": removed,
        "trumpstruth_captured_at": captured_at,
        "trumpstruth_removed_at": removed_at,
        "content_html": main["content_html"],
        "media": main["media"],
        "quote_id": None,
        "quote_of_acct": None,
        "reblog_of_id": None,
        "reblog_of_acct": None,
        "reblog_of_created_at": None,
    }
    if kind == "reblog":
        record["account"] = HANDLE
        record["reblog_of_id"] = main["ts_id"]
        record["reblog_of_acct"] = main["handle"]
        record["reblog_of_created_at"] = main["created_at_utc"]
    elif kind == "quote":
        record["account"] = main["handle"]
        if main["nested"]:
            record["quote_id"] = main["nested"]["ts_id"]
            record["quote_of_acct"] = main["nested"]["handle"]
    else:
        record["account"] = main["handle"]
    return record


# ---------------------------------------------------------------------------
# 6.3 trumpstruth search results
# ---------------------------------------------------------------------------

_SEARCH_RESULTS_CONTAINER_RE = re.compile(r'<div class="search-page__results">')
_SEARCH_ITEM_OPEN_RE = re.compile(
    r'<div class="search-result"\s+data-status-url="https://www\.trumpstruth\.org/statuses/(\d+)"', re.I
)
_SEARCH_TOTAL_RE = re.compile(r"([\d,]+)\s+results")
_SNIPPET_RE = re.compile(r'class="snippet-clean-content">(.*?)</div>', re.S)
_SNIPPET_RT_URL_RE = re.compile(r"^RT:\s*https://truthsocial\.com/users/([A-Za-z0-9_]+)/statuses/(\d+)")
_SNIPPET_RT_AT_RE = re.compile(r"^RT @([A-Za-z0-9_]{1,30})")


def _match_rt_at_handle(text: str) -> Optional[str]:
    """Match a glued ``RT @handleRest...`` prefix (same ambiguity as docs/SPEC.md 6.6's cnn rule): our own
    account is special-cased exactly since we know its exact spelling, else fall back to the generic,
    boundary-ambiguous regex."""
    trump_prefix = "RT @" + HANDLE
    if text.startswith(trump_prefix):
        return HANDLE
    m = _SNIPPET_RT_AT_RE.match(text)
    return m.group(1) if m else None


def parse_search_results(html: str) -> Dict[str, Any]:
    """Parse a trumpstruth ``/search`` results page (docs/SPEC.md 6.3).

    Two "RT" snippet formats coexist in the removed-search fixtures: ``RT: https://truthsocial.com/users/
    <acct>/statuses/<id>...`` (spec's documented form, yields reblog_of_id) and a glued ``RT @handleRest...``
    form with no id in it at all (yields reblog_of_acct only). General ``query=`` searches (as opposed to
    ``removed=only``) use a different snippet container entirely (``snippet-content``, with
    ``<em>`` highlight markup and separate card-title/card-url blocks) and never populate
    ``snippet-clean-content``, so ``snippet_text`` comes back empty for those -- collectors only rely on this
    field for the removed-search flow (docs/SPEC.md section 8), where it is always populated.
    """
    container_m = _SEARCH_RESULTS_CONTAINER_RE.search(html)
    if not container_m:
        # A page past the last result renders the search heading ("4 results ... (Page 2)") with no results
        # container at all (verified live 2026-09-11). That is an empty page, not markup drift.
        if "search-page__heading-meta" in html:
            total_m = _SEARCH_TOTAL_RE.search(html)
            total = int(total_m.group(1).replace(",", "")) if total_m else None
            return {"total": total, "results": [], "next_cursor": None}
        raise ParseError('no <div class="search-page__results"> container found')
    container_end, _ = _find_matching_close(html, container_m.end())

    total = None
    total_m = _SEARCH_TOTAL_RE.search(html)
    if total_m:
        total = int(total_m.group(1).replace(",", ""))

    results = []
    pos = container_m.end()
    while True:
        m = _SEARCH_ITEM_OPEN_RE.search(html, pos, container_end)
        if not m:
            break
        item_inner_end, item_block_end = _find_matching_close(html, m.end())
        item_html = html[m.end() : item_inner_end]

        handle_m = _HEADER_HANDLE_RE.search(item_html)
        time_m = _HEADER_TIME_RE.search(item_html)
        snippet_m = _SNIPPET_RE.search(item_html)
        snippet_text = html_to_text(snippet_m.group(1)) if snippet_m else ""

        rec: Dict[str, Any] = {
            "trumpstruth_id": int(m.group(1)),
            "trumpstruth_url": "%s/statuses/%s" % (TRUMPSTRUTH_BASE, m.group(1)),
            "account": handle_m.group(1) if handle_m else None,
            "removed": "status__deleted-badge" in item_html,
            "snippet_text": snippet_text,
            "created_at_utc": normalize_iso(time_m.group(1)) if time_m else None,
            "reblog_of_id": None,
            "reblog_of_acct": None,
        }
        url_m = _SNIPPET_RT_URL_RE.match(snippet_text)
        if url_m:
            rec["reblog_of_acct"] = url_m.group(1)
            rec["reblog_of_id"] = url_m.group(2)
        else:
            rec["reblog_of_acct"] = _match_rt_at_handle(snippet_text)
        results.append(rec)
        pos = item_block_end

    next_cursor = None
    next_m = _NEXT_PAGE_RE.search(html)
    if next_m:
        href = unescape(next_m.group(1))
        cm = _CURSOR_PARAM_RE.search(href)
        if cm:
            next_cursor = cm.group(1)
        else:
            pm = _PAGE_PARAM_RE.search(href)
            if pm:
                next_cursor = pm.group(1)

    return {"total": total, "results": results, "next_cursor": next_cursor}


# ---------------------------------------------------------------------------
# 6.4 trumpstruth feed and stats
# ---------------------------------------------------------------------------

_TRUTH_NS = "https://truthsocial.com/ns"
_FEED_STATUSES_URL_RE = re.compile(r"/statuses/(\d+)")


def parse_feed(xml_text: str) -> List[Dict[str, Any]]:
    """Parse the trumpstruth RSS feed (docs/SPEC.md 6.4)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ParseError("invalid feed XML: %s" % exc) from exc
    channel = root.find("channel")
    if channel is None:
        raise ParseError("no <channel> element found in feed XML")

    items = []
    for item in channel.findall("item"):
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        trumpstruth_url = link or guid or None
        id_m = _FEED_STATUSES_URL_RE.search(trumpstruth_url or "")
        trumpstruth_id = int(id_m.group(1)) if id_m else None

        ts_id_el = item.find("{%s}originalId" % _TRUTH_NS)
        ts_id = ts_id_el.text.strip() if ts_id_el is not None and ts_id_el.text else None

        pub_date = item.findtext("pubDate")
        created_at_utc = normalize_iso(pub_date) if pub_date else None

        items.append(
            {
                "_source": "trumpstruth",
                "ts_id": ts_id,
                "trumpstruth_id": trumpstruth_id,
                "trumpstruth_url": trumpstruth_url,
                "created_at_utc": created_at_utc,
                "title": item.findtext("title") or "",
                "description_html": item.findtext("description") or "",
            }
        )
    return items


_STATS_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_STATS_DATE_RE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")
_STATS_SUMMARY_RE = re.compile(r'class="[^"]*\bstats-page__summary\b[^"]*"')
_STATS_TOTAL_RE = re.compile(r'stats-page__summary-value--total">([\d,]+)</span>')
_STATS_COVERAGE_RE = re.compile(
    r"Total archive coverage:</strong>\s*(.*?)\s*[–-]\s*(.*?)\s*</p>", re.S
)


def _stats_long_date(text: str) -> str:
    m = _STATS_DATE_RE.search(text)
    if not m:
        raise ParseError("unrecognized date text in stats page: %r" % text)
    month = _STATS_MONTHS.get(m.group(1).lower())
    if month is None:
        raise ParseError("unknown month name in stats page: %r" % text)
    return "%04d-%02d-%02d" % (int(m.group(3)), month, int(m.group(2)))


def _stats_card_value(html: str, kind: str) -> int:
    m = re.search(
        r'stats-page__summary-card--%s">\s*<span class="stats-page__summary-value">([\d,]+)</span>' % kind,
        html,
        re.S,
    )
    if not m:
        raise ParseError("stats summary card not found: %s" % kind)
    return int(m.group(1).replace(",", ""))


def parse_stats(html: str) -> Dict[str, Any]:
    """Parse the trumpstruth ``/stats`` page (docs/SPEC.md 6.4)."""
    if not _STATS_SUMMARY_RE.search(html):
        raise ParseError('no <section class="stats-page__summary"> container found')

    total_m = _STATS_TOTAL_RE.search(html)
    if not total_m:
        raise ParseError("total posts value not found on stats page")

    coverage_m = _STATS_COVERAGE_RE.search(html)
    if not coverage_m:
        raise ParseError("coverage text not found on stats page")

    return {
        "total": int(total_m.group(1).replace(",", "")),
        "original": _stats_card_value(html, "original"),
        "quote": _stats_card_value(html, "quote"),
        "reblog": _stats_card_value(html, "reblog"),
        "coverage_start": _stats_long_date(html_to_text(coverage_m.group(1))),
        "coverage_end": _stats_long_date(html_to_text(coverage_m.group(2))),
    }


# ---------------------------------------------------------------------------
# 6.5 API objects
# ---------------------------------------------------------------------------


def _strip_accounts(obj: Any) -> Any:
    """Deep copy with every dict key literally named "account" removed, at any depth."""
    if isinstance(obj, dict):
        return {k: _strip_accounts(v) for k, v in obj.items() if k != "account"}
    if isinstance(obj, list):
        return [_strip_accounts(v) for v in obj]
    return obj


def _api_media(attachments: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    media = []
    for a in attachments or []:
        meta = ((a.get("meta") or {}).get("original")) or {}
        media.append(
            {
                "type": a.get("type"),
                "url": a.get("url"),
                "preview_url": a.get("preview_url"),
                "mirror_url": None,
                "width": meta.get("width"),
                "height": meta.get("height"),
                "duration": meta.get("duration"),
            }
        )
    return media


def _api_card(card: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not card:
        return {"card_url": None, "card_domain": None, "card_title": None}
    url = card.get("url")
    domain = None
    if url:
        host = urlparse(url).hostname
        if host:
            domain = host[4:] if host.startswith("www.") else host
    return {"card_url": url, "card_domain": domain, "card_title": card.get("title")}


def api_status_to_partial(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Parse one Truth Social API status object into a partial record (docs/SPEC.md 6.5, source ``api``)."""
    if not obj.get("id"):
        raise ParseError("status object has no id")

    reblog = obj.get("reblog")
    quote = obj.get("quote")
    quote_id = obj.get("quote_id")
    in_reply_to_id = obj.get("in_reply_to_id")

    if reblog:
        kind = "reblog"
    elif in_reply_to_id:
        kind = "reply"
    elif quote_id or quote:
        kind = "quote"
    else:
        kind = "original"

    # For a reblog, the *content* fields describe the reblogged post, not the wrapper (docs/SPEC.md 6.5).
    source_obj = reblog if reblog else obj

    record: Dict[str, Any] = {
        "_source": "api",
        "ts_id": obj.get("id"),
        "created_at_utc": normalize_iso(obj["created_at"]) if obj.get("created_at") else None,
        "kind": kind,
        "content_html": source_obj.get("content", ""),
        "lang": source_obj.get("language"),
        "in_reply_to_id": in_reply_to_id,
        "edited_at": normalize_iso(obj["edited_at"]) if obj.get("edited_at") else None,
        "pinned": bool(obj.get("pinned", False)),
        "media": _api_media(source_obj.get("media_attachments")),
        "mentions": [m.get("acct") for m in (source_obj.get("mentions") or []) if m.get("acct")],
        "tags": [t.get("name") for t in (source_obj.get("tags") or []) if t.get("name")],
        "quote_id": None,
        "quote_of_acct": None,
        "reblog_of_id": None,
        "reblog_of_acct": None,
        "reblog_of_created_at": None,
    }
    record.update(_api_card(source_obj.get("card")))

    if kind == "reblog":
        record["reblog_of_id"] = reblog.get("id")
        record["reblog_of_acct"] = (reblog.get("account") or {}).get("acct")
        record["reblog_of_created_at"] = normalize_iso(reblog["created_at"]) if reblog.get("created_at") else None
    elif kind == "quote":
        if quote:
            record["quote_id"] = quote.get("id") or quote_id
            record["quote_of_acct"] = (quote.get("account") or {}).get("acct")
        else:
            record["quote_id"] = quote_id

    record["raw_api"] = _strip_accounts(copy.deepcopy(obj))
    record["_engagement"] = {
        "replies": obj.get("replies_count"),
        "reblogs": obj.get("reblogs_count"),
        "favourites": obj.get("favourites_count"),
        "upvotes": obj.get("upvotes_count"),
        "downvotes": obj.get("downvotes_count"),
    }
    return record


def api_account_from_status(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Extract account-level stats carried on a status object's embedded ``account`` (docs/SPEC.md 6.5)."""
    account = obj.get("account") or {}
    return {
        "statuses_count": account.get("statuses_count"),
        "followers_count": account.get("followers_count"),
        "last_status_at": account.get("last_status_at"),
    }


# ---------------------------------------------------------------------------
# 6.6 CNN rows
# ---------------------------------------------------------------------------

_CNN_RT_GENERIC_RE = re.compile(r"^RT @([A-Za-z0-9_]{1,30})(.*)$", re.S)
_CNN_VIDEO_EXTS = {"mp4", "m3u8", "mov", "qt"}
_CNN_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}
_CNN_EXT_RE = re.compile(r"\.([A-Za-z0-9]+)(?:\?.*)?$")


def _cnn_media_type(url: str) -> str:
    m = _CNN_EXT_RE.search(url)
    ext = m.group(1).lower() if m else ""
    if ext in _CNN_VIDEO_EXTS:
        return "video"
    if ext in _CNN_IMAGE_EXTS:
        return "image"
    return "unknown"


def cnn_row_to_partial(row: Dict[str, Any]) -> Dict[str, Any]:
    """Parse one row of CNN's ``truth_archive.json`` into a partial record (docs/SPEC.md 6.6, source ``cnn``).

    CNN glues the "RT @handle" prefix directly onto the reblogged content with no separator, e.g.
    ``"RT @realDonaldTrumpThe Failing New York..."``. The handle/content boundary is genuinely ambiguous for
    any handle followed immediately by a word character (a generic ``^RT @(\\w+)`` match would happily eat
    into the content, e.g. capturing "realDonaldTrumpThe" as the handle) -- we only resolve this exactly for
    our own account (``HANDLE``, checked first, since we always know its exact spelling); for any other
    account we fall back to the same greedy regex and accept the ambiguity. This is deliberate: the merge
    layer (docs/SPEC.md section 7) never lets a lower-precedence ``cnn`` value override a handle already
    known from a better source (``api`` or ``trumpstruth``), so an occasionally-too-long cnn handle is
    self-correcting once a better source has seen the same post.
    """
    if not row.get("id"):
        raise ParseError("cnn row has no id")

    content = row.get("content") or ""
    kind = "original"
    reblog_of_acct = None
    content_text = content

    trump_prefix = "RT @" + HANDLE
    if content.startswith(trump_prefix):
        kind = "reblog"
        reblog_of_acct = HANDLE
        content_text = content[len(trump_prefix) :]
    else:
        m = _CNN_RT_GENERIC_RE.match(content)
        if m:
            kind = "reblog"
            reblog_of_acct = m.group(1)
            content_text = m.group(2)

    media = [
        {
            "type": _cnn_media_type(url),
            "url": url,
            "preview_url": None,
            "mirror_url": None,
            "width": None,
            "height": None,
            "duration": None,
        }
        for url in row.get("media") or []
    ]

    return {
        "_source": "cnn",
        "ts_id": row.get("id"),
        "created_at_utc": normalize_iso(row["created_at"]) if row.get("created_at") else None,
        "kind": kind,
        "content_text": content_text,
        "reblog_of_acct": reblog_of_acct,
        "media": media,
        "_engagement": {
            "replies": row.get("replies_count"),
            "reblogs": row.get("reblogs_count"),
            "favourites": row.get("favourites_count"),
            "upvotes": None,
            "downvotes": None,
        },
    }
