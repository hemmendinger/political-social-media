---
source: trumpstruth
canonical_name: trumpstruth
role: the deletion record (the only free source that timestamps removals) and the fastest feed of new posts with kinds and media
precedence: SOURCE_RANK 2 of 3 (below api, above cnn); CREATED_AT_RANK 1 of 3 (lowest; its times are rendered in Eastern text and parsed back)
verified: 2026-09-11
reachable_from:
  cloud: yes
  desktop: yes
  sandbox: unknown (needs --live; depends on the environment's network policy)
rate_limit: none published; we pace 1 request per 1.5 s per host (scripts/common.py DEFAULT_MIN_INTERVAL), no auth, Chrome UA
cost_per_run: normal 3-7 requests, 3-10 s; 202 requests and 305 s when the sequential id walk hits MAX_IDS_PER_RUN=200; backfill 477 requests, 747 s (measured 2026-09-11); removed-phase-only rerun 105 requests, 159 s
fixtures:
  - tests/fixtures/trumpstruth_listing_page1.html          # 100 cards, 5 ReTruthed, quote cards with nested status, Next Page cursor
  - tests/fixtures/trumpstruth_listing_2026-09-09_cursor.html  # 5 ReTruthed indicators all preceding the same reused target card (41640)
  - tests/fixtures/trumpstruth_listing_2022_tail.html      # the first post, 2022-02-14
  - tests/fixtures/trumpstruth_home.html                   # 10 cards
  - tests/fixtures/trumpstruth_status_41686_original_video.html   # video, captions track, details table
  - tests/fixtures/trumpstruth_status_41678_quote.html     # nested status, image
  - tests/fixtures/trumpstruth_status_41655_original_retruthed_target.html  # a target's own page carries no reblog markup
  - tests/fixtures/trumpstruth_status_41641_removed_reblog.html   # (+41644, 41646, 41649) removed self-reposts: Removed from platform row, alert--deletion banner
  - tests/fixtures/trumpstruth_status_41514_reblog_other.html     # Trump's repost of MichaelCohen212
  - tests/fixtures/trumpstruth_status_41515_reblog_other.html     # MichaelCohen212's own post stored as its own entry (skipped)
  - tests/fixtures/trumpstruth_search_removed_2026.html    # removed=only search, 88 results for 2026-01-01..09-11
  - tests/fixtures/trumpstruth_search_removed_2026-09-07_to_11.html  # 4 results
  - tests/fixtures/trumpstruth_search_removed_2026-08-28_to_09-11.html  # the 14-day window the collector uses
  - tests/fixtures/trumpstruth_search_removed_page2_empty.html  # a page past the last page is empty, not drift
  - tests/fixtures/trumpstruth_search_query_trump.html     # query search with a result-count line
  - tests/fixtures/trumpstruth_stats.html                  # totals by kind, coverage dates
  - tests/fixtures/trumpstruth_feed.xml                    # RSS, 100 items, truth:originalId
  - tests/fixtures/trumpstruth_feed_dated_2025-12-01.xml   # 10 items for a day that has exactly 10 posts; consistent with the 10-item cap MISTAKES.md reports, not proof of it
parsers:
  - scripts/parsers.py::parse_listing
  - scripts/parsers.py::parse_status_page
  - scripts/parsers.py::parse_search_results
  - scripts/parsers.py::parse_next_cursor
  - scripts/parsers.py::make_cursor
  - scripts/parsers.py::parse_feed        # no production caller
  - scripts/parsers.py::parse_stats       # no production caller (dead-code review section 3); the vision's D-009 would wire it
collector: scripts/collect_trumpstruth.py
state_keys:
  - max_trumpstruth_id: highest status id resolved sequentially; the next run starts after it; lower it to re-walk (repair rewalk-ids). NOTE: assigned only at the end of the walk (collect_trumpstruth.py:244), so a crash mid-walk re-fetches (B-015)
  - processed_removed_ids: removed pages already merged; remove an id to re-fetch it (repair regenerate-deletion)
  - other_account_ids: ids skipped because another account authored them; read only for its own de-duplication, never for a decision
  - backfill.phase / listing_cursor / removed_cursor / removed_page: resumable backfill cursors; phase in listing | removed | done
  - last_run_at, last_ok_at: written, never read
---

# Source dossier: trumpstruth.org

## What it is

An archive of @realDonaldTrump's Truth Social posts run by Defending Democracy Together. It assigns its
own sequential integer ids (about 41,700 on 2026-09-12), stores each post's HTML, mirrors media to
`truth-archive.us-iad-1.linodeobjects.com`, keeps VTT caption tracks for videos, and marks posts it later
finds removed with a confirmed-removed time. It is crawled politely at one request per 1.5 s and needs no
authentication. Coverage starts 2022-02-14 (the first post).

## What it knows and does not know

| Capability | Yes / No / Partial | Note |
|---|---|---|
| New posts within minutes | Yes | listing page 1 with `per_page=100`; new ids are sequential so nothing is skipped |
| Deletions with a timestamp | Yes, since March 2026 | `Removed from platform` row on the status page; minute precision; an **upper bound** on the deletion moment |
| Reposts with their own id and time | Partial | only on the repost's own status page; listing pages show the target's card (see quirks) |
| Replies | Unknown | none observed in fixtures |
| Quotes distinguished from originals | Yes | nested `div.status` inside the card |
| Engagement counts | No | |
| Media originals / mirrors | Yes | `mirror_url` = linodeobjects copy; original truthsocial URL when the img points there |
| Edits | No | |
| History before 2026-03 | Posts yes; deletions no | removal tracking starts 2026-03; 98 removed posts found in the full 2022..2026 search, all removed 2026-03 to 2026-09 |
| Other accounts' posts | Yes, as its own entries | reposted authors' originals are stored as separate entries (e.g. 41515 = MichaelCohen212); collectors skip them |

## Quirks (facts about the world, each dated and addressable)

- Q-tt-01 (2026-09-11): Listing pages render a repost as a `status__reblog-indicator` (`<strong>Donald J. Trump</strong> ReTruthed`) followed by the **target** post's card reused verbatim (same trumpstruth id, ts_id, time, content). The repost's own ts_id and time never appear on listing pages; they exist only on the repost's status page (details table `TRUTH Social status ID`, `Original Post Date`). Evidence: `trumpstruth_listing_2026-09-09_cursor.html` (5 indicators, one reused target 41640). Handled by: `parse_listing` returns the card as the target with `retruthed: True`; the collector resolves every new id sequentially to get reposts (L-004).
- Q-tt-02 (2026-09-11): `Capture Date` on a status page is the site's last processing time, and removed pages are re-processed (all 98 removed posts carry September 2026 capture dates, 90 of them a month or more after removal; MISTAKES.md's "93 of 98" counts the deletions whose buggy lower bound landed after their removal). It is not evidence of life. Handled by: the deletion lower bound never uses it (L-003; `merge.py::_apply_deletion_signal`).
- Q-tt-03 (2026-09-11): The site stores reposted authors' originals as entries of their own (41515 is MichaelCohen212's post 117190624268499306, the target of Trump's repost 41514). Handled by: parsers return `account`; collectors skip other authors and count them in `notes` and `other_account_ids`. Consequence: the stats-page total overstates Trump's own count.
- Q-tt-04 (2026-09-11): The listing ignores `removed=` and date parameters; only `/search` honors them, and with an empty query a date range is required. The collector still sends `removed=include` on the listing (harmless, B-023).
- Q-tt-05 (2026-09-11): The feed caps dated queries at 10 items (`trumpstruth_feed_dated_2025-12-01.xml`).
- Q-tt-06 (2026-09-11): Removal tracking starts in March 2026: the full removed-only search over 2022-01-01..2026-09-11 returned 98 posts, all removed 2026-03 to 2026-09 (6 / 44 / 16 / 8 / 14 / 6 / 4 per month). Deletions before March 2026 are unknown to every free source (B-003).
- Q-tt-07 (2026-09-11): The `confirmed removed` text is minute precision; when the Capture Date's `<time datetime>` falls within the same minute the parser uses that precise value.
- Q-tt-08 (2026-09-12): The `/search` date filter applies to the **post's creation date**, not the removal date: the 2026-01-01..09-11 removed-only search returned 88 results while the 2022-01-01 search returned 98, and all 98 were removed in 2026. Consequence: a removed search over the last N days finds only removals of posts younger than N days; 35 of the 98 known deletions were older than 14 days at removal (B-029, L-006, D-017).
- Q-tt-09 (2026-09-12): Detection floor. The narrowest deletion interval on record is 76 minutes, the median about 705; 94 of 98 removal times are minute precision. Every deletion's lower bound equals its creation time because no API sighting has ever preceded a removal (B-036).
- Q-tt-10 (2026-09-11): Search results carry a `status__deleted-badge`, a snippet, and for reposts `RT: https://truthsocial.com/users/<acct>/statuses/<id>`; the collector uses only the trumpstruth id from search results and fetches the status page for everything else.
- Q-tt-11 (2026-09-11): A listing page 1 with fewer than 50 cards is treated as markup drift (`MIN_YIELD_PAGE1`), because the site has always returned 100.
- Q-tt-12 (2026-09-11): Cursor format for the listing: base64 of `{"status_created_at":"YYYY-MM-DD HH:MM:SS","_pointsToNextItems":true}`; the site interprets the timestamp in its own zone; the docstring says callers pass UTC plus 5 hours, but no production caller of `make_cursor` exists (only tests).

## Failure modes and what they look like

| Failure | Symptom in run records / checks | First move |
|---|---|---|
| Markup change | today: a run record with `ok=false` and `notes="ParseError: ..."` (a listing under 50 cards raises the same `ParseError`); in the vision: `error.type=ParseError` with the URL and phase, or a `yield_below_min` anomaly | `ts doctor` says `markup_drift`; `ts capture` the URL as a new fixture; adjust the parser; keep the old fixture test if the old markup can recur |
| Site slow or down | today `ok=false` with `notes="HttpError: ..."` or `"TransportError: ..."` after 4 attempts; in the vision `error.type` with the URL and phase | `ts doctor` says `source_down`; nothing to do unless it persists across runs |
| A 5xx or connection blip on one status page during the walk | nothing today: the id is skipped and the mark advances past it (B-074, L-010); in the vision an anomaly `walk_retry` and a `pending_ids` entry | let the next run drain `pending_ids`; if it keeps failing, `ts repair rewalk-ids --from N --to N` |
| Silent under-collection | green legs with `new=0` for many runs while the account is active | `ts doctor --live` compares the live listing's max id with `max_trumpstruth_id` |
| Site removes a post we hold | appears in the removed search only if the post's creation date is inside the search window (see the creation-date quirk); status page merged as removed | expected; a deletion event and an interval |
| Removal semantics change (search returns live posts as removed, or stops honoring `removed=only`) | many removed-search hits whose status page has no `Removed from platform` row | the vision's `removed_search_mismatch` anomaly (B-032); never mark an id processed unless the page confirmed removal |
| Search grows past the request budget | leg truncated with `budget_exhausted` (B-032); today a 50-page cap truncates the search itself, but a large number of newly removed ids (one status page each at 1.5 s) would run into the 25-minute job timeout with no trace | narrow the window or raise the budget from the desktop |

## Endpoints

| Purpose | URL pattern | Parameters honored | Notes |
|---|---|---|---|
| Listing | `https://www.trumpstruth.org/?sort=desc&per_page=100&cursor=<b64>` | `sort`, `per_page`, `cursor` | `removed=`, dates ignored |
| Status page | `https://www.trumpstruth.org/statuses/<id>` | | 404 = gap in the sequence |
| Removed search | `https://www.trumpstruth.org/search?query=&removed=only&sort=date_desc&per_page=100&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` | all; paginate with `cursor` when present, else `page=N` | empty query needs a date range |
| Feed | `https://www.trumpstruth.org/feed[?start_date&end_date]` | dates (capped at 10 items) | namespace `https://truthsocial.com/ns` |
| Stats | `https://www.trumpstruth.org/stats` | | totals by kind, coverage dates; not used in production (D-009) |

## Open questions

- Is there a rate limit or bot policy? 1.5 s has never produced a 429; not tested faster and should not be.
- Do removed posts ever reappear on the site (which would look like a resurrection without an API signal)?
- Does the site capture replies at all?
