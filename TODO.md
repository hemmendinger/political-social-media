# TODO

Work that is known but not scheduled. Data-quality items first because they affect every analysis.

## Data quality

### 1. CNN archive: ambiguous repost handles (glued `RT @handle` prefix)

**Problem.** The CNN archive stores a repost as `RT @<handle><text>` with no separator, e.g.
`RT @realDonaldTrumpThe Failing New York Magazine...` and `RT @MichaelCohen212"The Weaponized State"...`.
When the text starts with a word character the handle boundary is ambiguous (`RT @MichaelCohen212Great...` parses as
handle `MichaelCohen212Great`). Today the parser special-cases the exact prefix `RT @realDonaldTrump` and otherwise takes the
longest `[A-Za-z0-9_]{1,30}` run, and the merge never lets CNN override a handle known from the API or trumpstruth. So the
damage is confined to **CNN-only rows**: historical reposts from before polling began, plus reposts that CNN kept and
trumpstruth lacks. For those rows `reblog_of_acct` may be wrong and `content_text` may be missing its first word.

**Candidate fixes, cheapest first.**
1. **Known-handle dictionary.** Collect every handle seen anywhere (API `reblog.account.acct`, `mentions`, trumpstruth inner
   handles, the `RT: https://truthsocial.com/users/<acct>/statuses/<id>` snippets in trumpstruth search results). For a CNN row,
   choose the *longest known handle that is a prefix* of the text after `RT @`; fall back to the regex only when nothing
   matches, and record `field_sources["reblog_of_acct"] = "cnn-guess"` so analyses can filter. Pure, offline, covers the
   common repeat targets.
2. **Trumpstruth cross-reference.** For CNN-only reposts, look the post up on trumpstruth by id (listing cursor around
   `created_at`, or its search) and take the exact handle from the inner status. Costs one request per row; fine for the
   few hundred historical cases if done once and persisted.
3. **Account lookup validation.** Verify a candidate handle exists via `GET /api/v1/accounts/lookup?acct=<handle>`
   (rate-limited, ~6/min unauthenticated): try the longest candidate, then progressively shorter prefixes ending at a
   non-alphanumeric boundary. Slow; only for rows the first two steps leave unresolved.
4. **Measure it.** `check_data` reports a soft metric: number of CNN-only reblogs whose text after the parsed handle starts
   with a word character (the ambiguous ones). Watch it go to zero as fixes land.

**Acceptance.** No CNN-only reblog has a handle that is not a known Truth Social account; `content_text` of those rows
starts with the first word of the reposted text; the soft metric reads 0.

### 2. Historical reposts before 2026-09-11 lack their own ids on trumpstruth listings

trumpstruth.org's listing pages render a repost as a "ReTruthed" label plus the target post's card; the repost's own status
id and time exist only on its own status page. Going forward the collector fetches every new trumpstruth id sequentially, so
new reposts are complete. Historically, reposts come from the CNN archive only (which de-duplicates repeated reposts of the
same target). Options: a slow sequential crawl of trumpstruth ids 1..41,700 (about 17 hours at 1.5 s per page, resumable),
or the deferred full API backfill, which resolves the same gap with richer fields.

### 3. Historical posts are presumed live, not verified; deletions before March 2026 are unknown

Until the deferred API backfill runs, posts known only from the archives carry `status = present` without
`last_verified_live_at`. trumpstruth's removal tracking only reaches back to March 2026 (98 removed posts in total as of
2026-09-11), and our `present` count exceeds the live account's `statuses_count` by roughly 340, which is the size of the
unflagged historical deletions plus structural differences. The API backfill resolves this: any archived post the live
account no longer returns is a deletion (with unknown timing).

## Deferred features

- **Full API backfill** (~1,830 pages at 5 requests/min, about 6 hours, resumable via `state.json`): verifies every historical
  post live/deleted and adds canonical fields (kinds, cards, mentions, media metadata). A throwaway Truth Social account would
  raise the budget roughly tenfold.
- **Desktop API poller** (Task Scheduler, only while the PC is on) if GitHub runners cannot reach the API and finer engagement
  or deletion timing is wanted.
- **HTML dashboard** over `scripts/metrics.py`, published with GitHub Pages.
- **Media mirroring** at first sight so deleted posts keep their images and video posters (trumpstruth's mirrors cover most cases
  meanwhile); **video transcripts** from trumpstruth's VTT caption tracks.
- **Factba.se spot checks** of deletion counts (browse-only source).
- **Raw responses as workflow artifacts** for forensic debugging of a bad collection run.
- **Desktop Python upgrade** from the Windows Store 3.9 build; the code already runs on 3.12 in the cloud.
