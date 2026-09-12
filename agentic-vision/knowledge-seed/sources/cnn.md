---
source: cnn
canonical_name: cnn
role: bulk history (2022-02-14 onward), gap filler when trumpstruth misses a post, and baseline engagement counts
precedence: SOURCE_RANK 1 of 3 (lowest for content fields); CREATED_AT_RANK 2 of 3 (its timestamps beat trumpstruth's parsed Eastern text)
verified: 2026-09-11
reachable_from:
  cloud: yes
  desktop: yes
  sandbox: unknown (needs --live)
rate_limit: none; one GET per download; no auth; conditional GET with If-None-Match (etag) returns 304 when unchanged
cost_per_run: 1 request of about 20 MB, 3-6 s, at most once every 2 h (SKIP_INTERVAL; D-007 proposes daily); each download appends about 328 engagement rows (about 19.5 KB) for posts under 14 days old
fixtures:
  - tests/fixtures/cnn_archive_sample.json   # 420 rows: newest 400, the deleted self-repost 117238345561593751, oldest 20
parsers:
  - scripts/parsers.py::cnn_row_to_partial
collector: scripts/collect_archive.py   # module name predates the vocabulary; verbs and docs say cnn
state_keys:
  - etag: sent as If-None-Match; delete to force a download
  - last_ok_at: read by the 2-hour skip gate
  - last_modified: written, never sent as If-Modified-Since
  - last_run_at: written, never read
---

# Source dossier: CNN-hosted Stiles archive

## What it is

A single cumulative JSON file, `https://ix.cnn.io/data/truth-social/truth_archive.json`, CC0, refreshed
about every 5 minutes, maintained by Matt Stiles and hosted by CNN. About 36,250 rows on 2026-09-12. One
row per post with id, created time, text, media URLs, and engagement counts. It excludes replies and
de-duplicates repeated reposts of the same target, and it stores a repost as `RT @<handle><text>` with no
separator.

## What it knows and does not know

| Capability | Yes / No / Partial | Note |
|---|---|---|
| New posts within minutes | Yes, within the download cadence | refreshed every 5 minutes upstream; we fetch every 2 h |
| Deletions with a timestamp | No | rows are never removed as far as observed; a post present here and absent from the live account is a deletion of unknown timing (B-003) |
| Reposts with their own id and time | Partial | one row per distinct target; repeated reposts of the same target are collapsed (kept 1 of 4 on 2026-09-08) |
| Replies | No | excluded |
| Quotes distinguished from originals | No | everything not starting with `RT @` is `original`; the merge never lets cnn override a known kind |
| Engagement counts | Yes | replies, reblogs, favourites at the archive's refresh time; no upvotes/downvotes |
| Media originals / mirrors | URLs | type inferred from the extension |
| Edits | No | |
| History | Yes | back to 2022-02-14 |

## Quirks (facts about the world, each dated)

- 2026-09-11: De-duplicates reposts. Of the four self-reposts posted and deleted on 2026-09-08 (117238301772357460, 117238326295991805, 117238345561593751, 117238414290995787), the archive kept only 117238345561593751; trumpstruth captured all four with removal times. Flag `cnn_dedup_risk` in `v_confidence`.
- 2026-09-11: Glues the `RT @handle` prefix to the text (`RT @realDonaldTrumpThe Failing New York Magazine...`), so the handle boundary is ambiguous when the text starts with a word character. The parser special-cases `RT @realDonaldTrump` and otherwise takes the longest `[A-Za-z0-9_]{1,30}` run. 1,172 cnn-only reblogs are affected (`cnn_ambiguous_handles`; B-001). The merge never lets cnn override a handle known from the API or trumpstruth.
- 2026-09-11: Cannot see quotes or replies; every cnn `kind` disagreement with a higher-ranked source is expected background in the anomaly ledger.
- 2026-09-11: Its `created_at` is a proper UTC timestamp and outranks trumpstruth's Eastern-text time for `created_at_utc`.
- 2026-09-11: Row count (36,236 on 2026-09-11) is below the API's `statuses_count` (no replies, de-duplicated reposts) and below trumpstruth's total.
- 2026-09-12: One download appends about 328 engagement rows because every post under 14 days old gets a row per hour; this, not new posts, is the main growth of `data/engagement/` (`09-economy.md`; B-025).

## Failure modes and what they look like

| Failure | Symptom in run records / checks | First move |
|---|---|---|
| File unreachable | leg `error.type=HttpError`; posts still arrive via trumpstruth | `ts doctor` says `source_down`; wait |
| Format change | `KeyError` per row counted in `errors`; `new=0` with `imported=N` in notes | capture a fresh sample as a fixture; adjust `cnn_row_to_partial` |
| Etag never changes | every leg `not modified` while trumpstruth finds new posts | delete `cnn.etag` (`repair reset-source --source cnn --key etag`) and see if the upstream refresh stalled |

## Endpoints

| Purpose | URL pattern | Parameters honored | Notes |
|---|---|---|---|
| The archive | `https://ix.cnn.io/data/truth-social/truth_archive.json` | `If-None-Match` | about 20 MB; `Last-Modified` present but unused |

## Open questions

- Does the archive ever drop rows (which would make "present here, absent live" a weaker deletion signal)? Compare row ids across downloads (a cheap check to add).
- What is the exact row schema and has it changed? The parser reads `id`, `created_at`, `content`, `media`, and the count fields; a schema fixture with all keys would let a canary detect additions.
- Would the maintainer publish a separator between handle and text if asked? That would close B-001 upstream.
