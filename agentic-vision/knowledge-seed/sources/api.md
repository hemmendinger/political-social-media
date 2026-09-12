---
source: api
canonical_name: api
role: ground truth for existence (200 vs 404), the richest fields (kinds, cards, mentions, media metadata), and fresh engagement counts
precedence: SOURCE_RANK 3 of 3 (highest); CREATED_AT_RANK 3 of 3 (highest)
verified: 2026-09-11
reachable_from:
  cloud: no (Cloudflare 403 on every request from GitHub runners since the first cloud run 2026-09-11, with both urllib and the curl_cffi browser-impersonating transport)
  desktop: yes (home connection)
  sandbox: unknown; assume no
rate_limit: about 6 requests per minute unauthenticated, then 429 with Retry-After (L-002); the client paces 1 request per 12 s, honors Retry-After (cap 120 s), never loops on 429; 403 triggers the curl_cffi fallback for the host
cost_per_run: desktop 1-8 requests (probe page, up to 4 more pages of 20, up to 3 verifies), 2-3 s each plus 12 s pacing; cloud (blocked) 4 requests and 36 s of sleep per probe, one probe per 6 h (the vision's cloud profile skips the leg entirely)
fixtures:
  - tests/fixtures/api_statuses_2026-09-04_to_09-11.json   # 180 statuses: originals, quotes, reblogs (one of MichaelCohen212), cards, media, account block
  - tests/fixtures/api_status_404.json                     # the 404 body for a deleted post
parsers:
  - scripts/parsers.py::api_status_to_partial
  - scripts/parsers.py::api_account_from_status
collector: scripts/collect_api.py
state_keys:
  - reachable, last_probe_at: read by the 6-hour re-probe gate
  - last_probe_status: written, never read
  - statuses_count: read by collect.run_all for the present_count_drift check
  - last_run_at, last_ok_at: written, never read
---

# Source dossier: Truth Social API

## What it is

The Mastodon-derived JSON API behind truthsocial.com, used unauthenticated with a Chrome user agent,
`Accept: application/json`, and `Referer: https://truthsocial.com/@realDonaldTrump`. Account id
`107780257626128497`. It is the only source that says whether a post exists *now*, and the only source of
`last_verified_live_at`. All 98 deletions on record so far came from trumpstruth; no `api404` deletion has
been recorded yet, because the API has only been reachable from the desktop for two runs.

## What it knows and does not know

| Capability | Yes / No / Partial | Note |
|---|---|---|
| New posts within minutes | Yes | when reachable |
| Deletions with a timestamp | Partial | a 404 on a single-status GET confirms deletion at `observed_at` (an upper bound); no removal time |
| Reposts with their own id and time | Yes | the status object with a nested `reblog` |
| Replies | Yes | `in_reply_to_id`; `exclude_replies=false` |
| Quotes distinguished from originals | Yes | `quote_id` / `quote` |
| Engagement counts | Yes | replies, reblogs, favourites, upvotes, downvotes at observation time |
| Media originals / mirrors | Originals | `media_attachments` with `meta.original` width/height/duration |
| Edits | Yes | `edited_at` |
| History | Yes, paginated | about 1,830 pages (20 per page, the collector's limit) at 5 requests per minute, about 6 hours per TODO.md (B-003) |
| Account totals | Yes | `statuses_count` (36,554 on 2026-09-11), `followers_count`, `last_status_at` (the last two are discarded today) |

## Quirks (facts about the world, each dated and addressable)

- Q-api-01 (2026-09-11): Unauthenticated rate limit measured at about 6 requests per minute; a burst of manual checks produced a 429 on the first scripted request (L-002). `Retry-After` is honored.
- Q-api-02 (2026-09-11): Cloudflare returns 403 to GitHub Actions runners for every request, including through curl_cffi impersonating Chrome. The desktop is unaffected. Consequence: the cloud record is complete for posts and deletions (trumpstruth + cnn); engagement snapshots and live verification happen only when the desktop runs a collection.
- Q-api-03 (2026-09-11): `statuses_count` (36,554) is lower than our `present` count (36,904, diff 350) because the archives keep posts deleted before March 2026 that nothing has flagged; and differs from CNN (36,236, no replies, de-duplicated reposts) and trumpstruth (37,105, includes other accounts' originals). Tracked as `present_count_drift` with a 1% tolerance.
- Q-api-04 (2026-09-11): Every `account` object is stripped before storage (`raw_api` keeps the rest); the stored `deleted_source` value for an API deletion is `api404` while the partial key is `api_404`.
- Q-api-05 (2026-09-11): A live 200 for a record marked `deleted` flips it back to `present` (anomaly `resurrected`); the deletion fields are retained. This has not happened in the data yet.

- Q-api-06 (2026-09-12): The two desktop API legs on 2026-09-11 (19:43 and 20:10 UTC) updated 20 records each but wrote no engagement rows: the store's throttle compared against the CNN rows written at 19:29, so the only fresh counts ever taken were discarded (tracked in the knowledge seed as B-072 and L-009; not in TODO.md or MISTAKES.md). Evidence: `data/engagement/2026-09.csv` has 37,226 rows, all `cnn`.

## Failure modes and what they look like

| Failure | Symptom in run records / checks | First move |
|---|---|---|
| 403 (cloud) | leg `notes=unreachable: 403`, `ok=true`, 4 requests, 36 s | expected in `cloud`; the vision skips the leg by profile |
| 429 | handled by the client; visible only as sleep time in `cost.slept_seconds` | nothing; do not lower the pacing |
| Network error | `TransportError`, marked unreachable for 6 h | `ts doctor` says `source_down`; retry from the desktop later |
| Schema change | `KeyError` per status, counted in `errors` | capture a new fixture; adjust `api_status_to_partial` |

## Endpoints

| Purpose | URL pattern | Parameters honored | Notes |
|---|---|---|---|
| Account statuses | `https://truthsocial.com/api/v1/accounts/107780257626128497/statuses?limit=20&exclude_replies=false[&max_id=<ts_id>]` | `limit` (max 20 observed), `max_id`, `exclude_replies` | first page doubles as the probe; the account block carries `statuses_count` |
| Single status | `https://truthsocial.com/api/v1/statuses/<ts_id>` | | 404 = deleted (fixture `api_status_404.json`) |
| Account lookup | `https://truthsocial.com/api/v1/accounts/lookup?acct=<handle>` | | candidate fix 3 of TODO.md item 1 (B-001 here); rate-limited like the rest |

## Open questions

- Would a throwaway account raise the budget about tenfold, as TODO.md assumed? Untested.
- Is the Cloudflare block tied to GitHub's IP ranges (in which case a self-hosted runner or a `repository_dispatch` from the desktop would bypass it)? A monthly cloud canary probe (`canary.yml`) records whether it persists.
- Does the API expose edit history or only `edited_at`?
