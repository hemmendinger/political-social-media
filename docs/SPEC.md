# Truth Social pipeline: implementation spec

Read this before touching any module. It is the contract between modules and the test suite.
The approved plan (design rationale, source research) lives outside the repo; this file is the code-level contract.

## 0. Ground rules

- Python **3.9-compatible** syntax everywhere (desktop runs 3.9, cloud runs 3.12): no `match`, no `X | Y` unions at
  runtime, no backslashes inside f-string expressions, use `typing.Optional/List/Dict`. `from __future__ import annotations` is fine.
- `scripts/` is a package (`scripts/__init__.py`). Modules import each other absolutely: `from scripts.common import ...`.
  Entry points run as `python -m scripts.collect`, `python -m scripts.build_db`, etc. Each script exposes `main(argv=None)`.
- Library code logs through `logging.getLogger(__name__)`; only `main()` configures logging and prints.
- Pure functions wherever possible; every network or clock dependency is injected so tests never sleep or hit the network.
- Tests: `pytest` from the repo root (`pytest.ini` sets `pythonpath = .`). Fixtures in `tests/fixtures/` are real captures
  (see its README). Tests marked `@pytest.mark.live` are skipped by default.
- Third-party deps: `tzdata`, `curl_cffi` (lazy import, fallback only), `pandas` (analysis only), `pytest` (dev).
- Timestamps: **all stored times are UTC ISO-8601 with a `Z` suffix**, second precision, e.g. `2026-09-09T00:53:04Z`.
  Sub-second parts are dropped. Eastern-time fields are derived, never the primary value.

## 1. Identifiers and sources

- `ts_id`: Truth Social status id, string of 18 digits (Snowflake-like, increasing with time). Sort numerically.
- Account: `realDonaldTrump`, account id `107780257626128497`.
- Sources: `api` (truthsocial.com API), `trumpstruth` (trumpstruth.org), `cnn` (ix.cnn.io archive).
- Precedence for conflicting field values: `api` > `trumpstruth` > `cnn`, except `created_at_utc`: `api` > `cnn` > `trumpstruth`.

## 2. Post record (one JSON object per post)

| field | type | notes |
|---|---|---|
| ts_id | str | primary key |
| created_at_utc | str | UTC ISO `Z`; for a reblog this is when Trump reposted |
| created_at_et | str | ISO with offset, e.g. `2026-09-08T20:53:04-04:00` |
| et_date | str | `YYYY-MM-DD` in America/New_York |
| et_hour | int | 0..23 |
| et_dow | int | 0=Monday .. 6=Sunday (Python weekday) |
| kind | str | `original` / `quote` / `reblog` / `reply` |
| content_html | str | `""` when unknown or empty; for a reblog, the reblogged post's html |
| content_text | str | derived from content_html (see 6.7); for cnn-only rows, the cnn text |
| lang | str/null | |
| in_reply_to_id | str/null | |
| quote_id | str/null | quoted status id |
| quote_of_acct | str/null | handle without `@` |
| reblog_of_id | str/null | reblogged status id |
| reblog_of_acct | str/null | handle without `@` (`realDonaldTrump` for self-reposts) |
| reblog_of_created_at | str/null | UTC ISO of the reblogged post |
| media | list | items `{type, url, preview_url, mirror_url, width, height, duration}`; type in `image/video/gifv/audio/unknown`; url = original truthsocial URL when known; mirror_url = trumpstruth linodeobjects copy |
| card_url | str/null | link preview target |
| card_domain | str/null | hostname of card_url without a leading `www.` |
| card_title | str/null | |
| mentions | list[str] | handles without `@`, in order, unique |
| tags | list[str] | hashtag names |
| edited_at | str/null | UTC ISO |
| pinned | bool | |
| first_seen_at | str | UTC ISO of our first sighting (set once) |
| first_seen_source | str | set once |
| seen_sources | list[str] | sorted unique |
| status | str | `present` / `deleted` |
| last_verified_live_at | str/null | UTC ISO; api only; max of observations |
| deleted_lower | str/null | last moment known to exist |
| deleted_upper | str/null | first moment confirmed gone |
| deleted_source | str/null | `trumpstruth` / `api404` |
| trumpstruth_id | int/null | |
| trumpstruth_captured_at | str/null | UTC ISO |
| trumpstruth_removed_at | str/null | UTC ISO (their confirmed-removed time) |
| field_sources | dict | field name -> source that last set it (provenance for the precedence rule) |
| raw_api | object/null | latest API object with every `account` key removed (also inside `reblog`/`quote`) |
| updated_at | str | UTC ISO of last change |
| updated_run_id | str | |

Validation (used by `check_data`): every field present (nulls allowed where marked); `ts_id` matches `^\d{18}$`;
timestamps match `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` (except `created_at_et`, which carries an offset); `kind`/`status`
in their enums; `media` items have all seven keys; `field_sources` keys are field names and values are source names.

## 3. Files (the source of truth, all under `data/`)

- `posts/YYYY-MM.jsonl`: partition = month of `created_at_utc`. One line per post, **sorted by int(ts_id) ascending**,
  JSON with `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`, `\n` line endings, trailing newline.
  Rewritten atomically (write a temp file in the same directory, then replace).
- `deletions.jsonl`: append-only event log, one line per detection event:
  `{ts_id, detected_at, deleted_lower, deleted_upper, source, trumpstruth_removed_at, run_id}`. Unique on (ts_id, source).
- `engagement/YYYY-MM.csv`: partition = month of `observed_at`. Header
  `observed_at,ts_id,source,replies,reblogs,favourites,upvotes,downvotes` (blank for unknown). Append-only.
  Throttle: skip when the post's most recent row (any source) is less than 60 minutes older than `observed_at`;
  posts older than 14 days at observation time get a row only if they have none yet (this lets the CNN backfill record one
  baseline row per historical post).
- `runs/YYYY-MM.jsonl`: append-only, one line per (run, source):
  `{run_id, source, started_at, finished_at, ok, requests, new_posts, updated_posts, deletions_found, errors, notes}`.
- `state.json` (indent=2, sort_keys): `{"version": 1, "sources": {"trumpstruth": {...}, "cnn": {...}, "api": {...}}}`;
  each source keeps `last_run_at`, `last_ok_at`, plus source-specific keys:
  trumpstruth `processed_removed_ids` (sorted list of trumpstruth ids already resolved), `max_trumpstruth_id` (highest
  trumpstruth status id fetched by sequential resolution), `other_account_ids` (sorted list of trumpstruth ids skipped because
  another account authored them) and `backfill` (`phase`, `listing_cursor`, `removed_cursor`, `removed_page`); cnn `etag`, `last_modified`; api `reachable`, `last_probe_status`,
  `last_probe_at`, `statuses_count`.
- `raw/` (gitignored): optional per-run raw responses for debugging: `raw/YYYY-MM-DD/<run_id>-<name>`.

`scripts/store.py` owns all reads and writes: `load_posts(root) -> List[dict]`, `load_posts_index(root) -> Dict[str, dict]`,
`save_posts(root, records)`, `append_deletion(root, event)`, `load_deletions(root)`, `append_engagement(root, rows)`,
`latest_engagement_times(root) -> Dict[ts_id, observed_at]`, `append_run(root, row)`, `load_runs(root)`, `load_state(root)`,
`save_state(root, state)`, `month_of(iso) -> "YYYY-MM"`. Loading then saving unchanged data must be byte-identical.
The data root is always a parameter (default `<repo>/data`) so tests can use `tmp_path`.

## 4. Time helpers (`scripts/common.py`)

- `parse_iso_utc(s) -> datetime` (aware, UTC): accepts `2026-09-09T00:53:04.960Z`, `2026-09-09T00:53:04Z`,
  `2026-09-09T00:53:04+00:00`, `2026-09-09 00:53:04` (assume UTC), and RFC-2822 (`Fri, 11 Sep 2026 01:19:51 +0000`).
- `to_utc_iso(dt) -> str` (drops sub-seconds), `utc_now_iso(clock) -> str`.
- `parse_et_text(s) -> str`: trumpstruth strings such as `Tuesday, September 8, 2026, 09:10 pm EDT`,
  `Sep 8, 2026, 10:20 PM EDT`, `September 10, 2026, 11:48 AM`; interpret in America/New_York (a zone abbreviation, if
  present, must agree with the zone's offset for that instant, else raise `ValueError`); return UTC ISO.
- `et_fields(created_at_utc) -> dict(created_at_et, et_date, et_hour, et_dow)` via `zoneinfo.ZoneInfo("America/New_York")`.
- `Clock` protocol: `now() -> datetime` (aware UTC) and `sleep(seconds)`. `SystemClock`; `FakeClock(start)` whose `sleep`
  advances `now` and records the requested durations.
- `new_run_id(clock) -> str` = `YYYYMMDDTHHMMSSZ-` + 4 hex chars.

## 5. HTTP (`scripts/common.py`)

```
class Response: status: int; headers: Dict[str, str] (lower-cased keys); body: bytes; text (utf-8, errors="replace"); json()
class TransportError(Exception)      # network-level failure (DNS, timeout, reset)
class HttpError(Exception): status, url  # raised after retries are exhausted
class Transport(Protocol): def get(self, url, headers, timeout) -> Response   # never raises for HTTP status codes
UrllibTransport                    # stdlib urllib; must not follow the default error path for 4xx/5xx (catch HTTPError, wrap)
CurlCffiTransport                  # lazy `import curl_cffi`; requests.get(..., impersonate="chrome")
FakeTransport(routes)              # url or callable(url) -> Response | list of Responses consumed in order; .calls records (url, headers)
class Http:
    def __init__(self, transport, clock, min_interval=None, max_attempts=4, fallback_transport=None)
    def get(self, url, headers=None, timeout=30.0) -> Response
    request_count: int
```
Default `min_interval` seconds per host: `truthsocial.com` 12.0, `www.trumpstruth.org` and `trumpstruth.org` 1.5, `ix.cnn.io` 0.
Behavior: pace per host with the injected clock (sleep so consecutive requests to a host are at least the interval apart);
429 → sleep `Retry-After` (integer seconds; cap 120; default 30 when absent) then retry; 5xx → sleep `5 * attempt` then retry;
403 from `truthsocial.com` → if a fallback transport exists, retry through it and keep using it for that host;
after `max_attempts` raise `HttpError`. 404 and other 4xx are returned, not raised. `TransportError` counts as an attempt.
Default headers: Chrome UA, `Accept-Language: en-US,en;q=0.9`; for truthsocial.com also
`Accept: application/json, text/plain, */*` and `Referer: https://truthsocial.com/@realDonaldTrump`.

## 6. Parsers (`scripts/parsers.py`) — pure functions; fixtures in `tests/fixtures/`

Every parser returns plain dicts. A "partial record" is a subset of the §2 fields plus `_source` and, where known,
`_engagement = {replies, reblogs, favourites, upvotes, downvotes}`. Raise `ParseError` when the expected container markup is
absent (drift guard); return an empty list when the container exists but holds nothing. Use `html.parser` from the stdlib or
regular expressions; no third-party HTML libraries.

### 6.1 trumpstruth listing and home page
`parse_listing(html) -> List[dict]`. Cards are `<div class="status" data-status-url="https://www.trumpstruth.org/statuses/N">`
directly inside the `class="statuses"` container; a **nested** `<div class="status">` inside a card's body is the quoted or
reblogged inner post, not a separate card. Per card: `trumpstruth_id` (N), `trumpstruth_url`, `ts_id` from the
`status__external-link` href (`https://truthsocial.com/@realDonaldTrump/<ts_id>`), `created_at_utc` from the header
`<time datetime>` (for a reblog card this is the repost time), `kind`: `quote` if it has a nested status, else `original` (never `reblog`, see below); `content_html` = the card's own
`status__content` inner html (for reblogs, the inner post's content); `media` from `status-attachment--image`
(`<a href>` = mirror_url, `<img src>` = url if it points at truthsocial.com, else preview_url) and
`status-attachment--video` (`<video src>` = url, `poster` = mirror_url, type video). Inner post, when present:
`quote_id`/`reblog_of_id` from its own external link, `quote_of_acct`/`reblog_of_acct` from its `@handle`,
`reblog_of_created_at` from its `<time datetime>`. **Reposts on listing pages (verified 2026-09-11):** a repost is rendered as a `status__reblog-indicator` element
(`<strong>Donald J. Trump</strong> ReTruthed`) immediately followed by the *target* post's own card, reused verbatim
(the target's trumpstruth id, ts_id, header time, content). The repost's own ts_id and time never appear on listing pages.
`parse_listing` therefore returns such a card as the target's ordinary partial with `retruthed: True` and `retruthed_by`;
the same target can appear several times on one page. The repost's own record comes only from its own status page
(details table: `TRUTH Social status ID` = the repost's id, `Original Post Date` = the repost time; the header shows the
target's author and time). Every trumpstruth parser also returns `account` (author handle of the main status); trumpstruth
stores reposted authors' originals as their own entries (e.g. 41515 = MichaelCohen212's post), which collectors skip.
`parse_next_cursor(html) -> Optional[str]` returns the `cursor=` value of the Next Page link.
`make_cursor(naive_ts: str) -> str` = base64 of `{"status_created_at":"YYYY-MM-DD HH:MM:SS","_pointsToNextItems":true}`
(compact separators). The site interprets the timestamp in its own zone; callers pass UTC plus 5 hours to be safe.

### 6.2 trumpstruth status page
`parse_status_page(html) -> dict`: `trumpstruth_id` from `og:url`, everything in 6.1 for the main status, plus the details
table (`status-details-table__key` / `status-details-table__value`): `TRUTH Social status ID` → ts_id, `Original Post Date` →
created_at_utc (for a reblog page this is the repost time; the header time is the reblogged post's time → reblog_of_created_at),
`Capture Date` → trumpstruth_captured_at (trumpstruth's last processing time: a later re-check for live posts, the removal
confirmation for removed posts), `Removed from platform` → `removed: bool` and `trumpstruth_removed_at` = the minute-precision
value parsed from the `confirmed removed <ET text>` part, replaced by the Capture Date's precise `<time datetime>` when that
falls within the same minute. The reblog marker class is `status__reblog-indicator`.
The deletion banner has class `alert--deletion`. Kind: `reblog` when the page carries the `ReTruthed` indicator or links a
different status than the details-table id as the main external link; `quote` if a nested status is present; else `original`.

### 6.3 trumpstruth search results
`parse_search_results(html) -> dict(total: Optional[int], results: List[dict], next_cursor: Optional[str])`.
Items are `class="search-result"`: `trumpstruth_id`/`trumpstruth_url` from the `/statuses/N` link, `removed` = has
`status__deleted-badge`, `snippet_text` from `snippet-clean-content`, `created_at_utc` from a `<time datetime>` when present,
`reblog_of_id` when the snippet starts with `RT: https://truthsocial.com/users/<acct>/statuses/<id>` (that id is the
reblogged post, never the removed status itself). `total` from the `N results` text.

### 6.4 trumpstruth feed and stats
`parse_feed(xml) -> List[dict(ts_id, trumpstruth_id, trumpstruth_url, created_at_utc, title, description_html)]` using the
namespace `https://truthsocial.com/ns` (`originalId`, `originalUrl`).
`parse_stats(html) -> dict(total, original, quote, reblog, coverage_start, coverage_end)` (ints; dates `YYYY-MM-DD`).

### 6.5 API objects
`api_status_to_partial(obj) -> dict` (source `api`): kind = `reblog` if `obj["reblog"]`, else `reply` if `in_reply_to_id`,
else `quote` if `quote_id` or `quote`, else `original`. For a reblog: `content_html`, `media`, card fields, `mentions`, `tags`
come from `obj["reblog"]`; `reblog_of_id`, `reblog_of_acct = reblog.account.acct`, `reblog_of_created_at`. For a quote:
`quote_id`, `quote_of_acct = quote.account.acct` when the `quote` object is present. Media from `media_attachments`
(`type`, `url`, `preview_url`, `meta.original.width/height/duration`). `card_url/card_domain/card_title` from `card`.
`mentions` from `mentions[].acct`, `tags` from `tags[].name`. `raw_api` = deep copy with every `account` key removed.
`_engagement` from the top-level counts. `api_account_from_status(obj) -> dict(statuses_count, followers_count, last_status_at)`.

### 6.6 CNN rows
`cnn_row_to_partial(row) -> dict` (source `cnn`): `ts_id = id`, `created_at_utc`, `content_text = content`; if the content
starts with `RT @` → kind `reblog`: if it starts with the exact prefix `RT @realDonaldTrump`, `reblog_of_acct = realDonaldTrump` and `content_text` = the remainder; otherwise match `^RT @([A-Za-z0-9_]{1,30})` and take the remainder (CNN glues the handle to the text with no separator, so the boundary is ambiguous when the text starts with a word character; document this and rely on precedence); else kind `original`
(CNN cannot distinguish quotes or replies; the merge never lets `cnn` override a known kind). `media` from the `media` URLs
(type by extension: mp4/m3u8/mov → video, jpg/jpeg/png/webp/gif → image, else unknown). `_engagement` from the counts.

### 6.7 HTML to text
`html_to_text(html) -> str`: drop `span.quote-inline` blocks entirely; `<br>` and block ends (`</p>`, `</div>`) become
newlines; strip tags; unescape entities; collapse runs of spaces; strip each line; collapse 3+ newlines to 2; strip the ends.

## 7. Merge (`scripts/merge.py`) — pure

`merge_partial(existing: Optional[dict], partial: dict, *, source: str, observed_at: str, run_id: str) -> MergeResult`
with fields `record`, `changed: bool`, `is_new: bool`, `deletion_event: Optional[dict]`, `anomalies: List[str]`.

1. New record: fill every §2 field (nulls where unknown), `first_seen_*` from this observation, `seen_sources = [source]`,
   `status = deleted` if the partial carries a deletion signal, else `present`.
2. `seen_sources`: union, sorted. `first_seen_*`: never changed.
3. Scalar content fields (`kind`, `content_html`, `lang`, `in_reply_to_id`, `quote_id`, `quote_of_acct`, `reblog_of_id`,
   `reblog_of_acct`, `reblog_of_created_at`, `card_url`, `card_domain`, `card_title`, `mentions`, `tags`, `edited_at`, `pinned`):
   a value from a source overwrites an existing value only if the existing value is null/empty **or** the new source has
   higher precedence than the source recorded in `field_sources` for that field. A lower-precedence, non-empty, different value
   is dropped and reported as an anomaly like `kind_disagreement:<ts_id>:api=original,cnn=reblog`.
4. `created_at_utc`: precedence api > cnn > trumpstruth; if two sources differ by more than 2 s → anomaly, keep the higher
   precedence value. Recompute `created_at_et/et_date/et_hour/et_dow` whenever `created_at_utc` changes.
5. `content_text`: recomputed from `content_html` whenever `content_html` changes; if `content_html` is empty and the partial
   carries `content_text` (cnn), use it under the same precedence rule.
6. `media`: list precedence like scalars, **plus** if the incoming list has the same length as the existing one, copy any
   non-null `mirror_url`/`preview_url`/`width`/`height`/`duration` into positions where the existing item has null.
7. `status`: `present` → `deleted` when the partial carries a deletion signal (`removed=True` from trumpstruth, or
   `api_404=True` from the API). `deleted` → `present` only when the source is `api` and the partial is a live status object;
   report anomaly `resurrected:<ts_id>`.
8. Deletion bounds: incoming `lower` = the latest non-null of `last_verified_live_at` and (trumpstruth case)
   `trumpstruth_captured_at`; incoming `upper` = `trumpstruth_removed_at` (trumpstruth) or `observed_at` (api404).
   Merge: `deleted_lower = max(existing, incoming)`, `deleted_upper = min(existing, incoming)`, null-safe.
   If `deleted_lower > deleted_upper` → anomaly `inverted_bounds:<ts_id>` (keep the values). `deleted_source` = the source that
   first set `deleted` (never changes). Emit `deletion_event` once per (ts_id, source) — the caller passes the set of
   (ts_id, source) pairs already logged via the optional keyword `logged_deletions`.
9. `last_verified_live_at`: api live observations only; keep the maximum.
10. `trumpstruth_id`, `trumpstruth_captured_at`: set from trumpstruth partials (latest wins); `trumpstruth_removed_at` is never
    overwritten once set.
11. `raw_api`: replaced by the latest api observation.
12. `changed` = merged record differs from `existing` ignoring `updated_at`/`updated_run_id`; set those two only when changed.
    Merging the same partial twice yields `changed=False` the second time.

## 8. Collectors (`scripts/collect_*.py`) — each exposes `run(ctx, **opts) -> dict` (the run row of §3)

`ctx` (a small dataclass in `scripts/common.py`, `Context`) bundles `http`, `clock`, `data_root`, `state`, `run_id`, `logger`.
Collectors keep only statuses authored by `realDonaldTrump` (trumpstruth also archives the reposted author's original post as its own entry, e.g. trumpstruth 41515 is MichaelCohen212's post; parsers report `account` and collectors skip other accounts, counting them in `notes`). Each collector loads the posts index once, applies partials through `merge_partial`, appends deletion events and engagement
rows, saves posts once at the end, appends a run row, and returns it. One bad post never aborts the run (log, count in
`errors`), but a `ParseError` or a page below its `min_yield` aborts with an exception.

- **trumpstruth** `run(ctx, backfill=False, removed_days=14)`: (a) listing page 1 (`per_page=100`, `min_yield=50`): merge every
  card by realDonaldTrump as a partial (cards flagged `retruthed` are the target's card, merged as the target; the flag itself
  is not stored), and note the largest trumpstruth id on the page; (b) **sequential resolution**: trumpstruth ids are
  sequential, so for every id from `state.max_trumpstruth_id + 1` through the largest id seen on the listing, plus one probe
  beyond it, fetch `/statuses/<id>` (1.5 s pacing; 404 = gap, skip; stop probing past the listing max at the first 404) and
  merge it when `account == realDonaldTrump` (this is the only way to obtain reposts' own ts_ids and times); ids by other
  accounts are counted in `notes` and skipped; persist `max_trumpstruth_id` after each page so a crash resumes; cap at 200 ids
  per run; (c) removed search for the last `removed_days` days (`per_page=100`; paginate with `next_cursor` when present, else
  `page=2,3,...` until a page yields no results); for each result whose trumpstruth id is not in `processed_removed_ids`, fetch
  its status page, merge as removed, then record the id; (d) backfill: crawl the listing from page 1 following cursors until a
  page yields 0 cards (persist `listing_cursor` after every page), then the removed search over `2022-01-01..today`, status page
  per result; sequential resolution is NOT run over history (17 h at 1.5 s per id): it starts from the max id seen at backfill
  time, so historical reposts come from CNN (deduplicated) until the deferred crawl in TODO.md.
- **cnn** `run(ctx, force=False)`: skip unless `force` or at least 2 h since `last_ok_at`; GET the JSON with `If-None-Match`
  when an etag is stored (304 → skip); merge every row (source cnn); engagement rows under the throttle; store the etag.
- **api** `run(ctx, max_pages=5, max_verify=3)`: the first page request doubles as the probe; on 403/429/`TransportError`
  set `reachable=False`, record `last_probe_status`, return a run row with `ok=True` and a note. Otherwise paginate with
  `max_id` until a page contains only known ids (or `max_pages`); merge (source api) with `last_verified_live_at = observed_at`;
  engagement rows; record `statuses_count`. Deletion candidates: posts with `status=present`, `last_verified_live_at` not null,
  `created_at_utc` within [oldest fetched, newest fetched], not in the fetched id set → up to `max_verify` single-status GETs;
  404 → merge `{"api_404": True}`; 200 → merge as live.
- **collect** (`python -m scripts.collect [--sources trumpstruth,cnn,api] [--backfill] [--force-cnn] [--data-root] [--summary-file PATH]`; `--summary-file` writes the one-line commit summary `collect: +N posts, +M deletions, checks ok|checks FAILED` for the workflow):
  one `run_id`, lock file `data/.lock` (ignored when older than 30 min), sources in that order, then `check_data`
  (hard failure → exit 2, `output/checks.json` still written), then `build_db` and exports (`output/posts.csv`,
  `output/metrics.json`). Exit 0 on success, 1 on a collector exception, 2 on failed hard checks.

## 9. Integrity checks (`scripts/check_data.py`)

`run_checks(data_root, *, run_id=None, api_statuses_count=None, trumpstruth_totals=None, now=None) -> dict(ok, hard, soft, stats)`,
written to `output/checks.json` by the CLI. Hard: schema/types per §2; `ts_id` regex; unique ids across all month files;
each record in its correct month file; files sorted; timestamps well-formed; `created_at_utc <= deleted_upper` when both set;
deletion events reference known posts and are unique on (ts_id, source); engagement rows reference known posts; no two
engagement rows for one post within 60 min; `field_sources` valid; a run row exists for `run_id` when given.
Soft: `deleted_lower <= deleted_upper`; `present` count vs `api_statuses_count` (tolerance 50); `present + deleted` vs the
trumpstruth total (tolerance 50); posts between 24 h and 30 days old seen by exactly one source (count + sample; older single-source posts are
expected, see TODO.md); newest post older than 12 h; any day with at least 20 posts whose count exceeds 3× the trailing
28-day median; `cnn_ambiguous_handles` = count (and up to 10 sample
ids) of reblogs whose `field_sources["reblog_of_acct"]` is `cnn` and whose `content_text` starts with a word character
(the glued `RT @handle` boundary problem, see TODO.md). CLI exit 2 on hard failures.

## 10. Derived database (`scripts/build_db.py`)

Rebuild `data/truths.sqlite` from `data/`: tables `posts` (§2 columns; list/dict fields as JSON text; plus `media_count`,
`media_types` (comma-joined), `content_len`), `media` (one row per item: `ts_id, idx, ...`), `engagement`, `deletions`,
`runs`. Views: `v_posts_et` (analysis columns incl. `is_deleted`, `lifetime_min` = minutes from `created_at_utc` to
`deleted_upper`, `deletion_window_min` = minutes between the bounds), `v_deletions`, `v_engagement_latest` (latest row per
post). Indexes on `created_at_utc`, `et_date`, `kind`, `status`. Full rebuild under 10 s for 40k posts.

## 11. Metrics (`scripts/metrics.py`) and renderers

Pure functions taking an open `sqlite3.Connection` and ET date strings (`start`, `end`, inclusive), returning JSON-able data:
`posts_by_day` (rows: et_date, original, quote, reblog, reply, total, deleted), `hour_histogram` (24 ET counts),
`overnight_share` (00:00–05:59 ET share), `bursts(window_min=10, min_posts=5)`, `deletions` (with lifetime and window
minutes and a content snippet), `top_reblogged_accounts(n=10)`, `link_domains(n=10)`, `media_mix`, `engagement_stats`
(median and p90 of the latest favourites/reblogs/replies by kind), `longest_silence` (largest gap between consecutive posts),
`edits`, `baseline(start, end, trailing_weeks=8)` = all of the above for the window plus the same for the trailing period,
`iso_week_bounds("2026-W37") -> (start, end)` (Monday..Sunday, ET dates).
`weekly.py --week 2026-W37 | --start --end` writes `output/reports/<label>.md` plus one csv per table; `query.py` runs SQL
(`--sql "..."` or `--file queries/x.sql`, output table/csv/markdown).

## 12. Workflows

`.github/workflows/collect.yml`: `schedule: cron '*/30 * * * *'`, `workflow_dispatch`;
`concurrency: {group: collect, cancel-in-progress: false}`; `permissions: {contents: write}`; steps: checkout (fetch-depth 1),
setup-python 3.12 with pip cache, `pip install -r requirements.txt`, `python -m scripts.collect`, then commit `data/ output/`
if changed as `truth-collector <actions@github.com>` with message `collect: +N posts, +M deletions, checks ok`,
`git pull --rebase` then push (retry once). A non-zero collect exit fails the job before the commit step.
`.github/workflows/test.yml`: on push and pull_request, Python 3.9 and 3.12 matrix, `pip install -r requirements-dev.txt`, `pytest -q`.
