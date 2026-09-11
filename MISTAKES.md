# Mistakes and anomalies

Honest, dated log. Build errors first, then data anomalies on the source side.

## Build

- **2026-09-11** A single Git Bash heredoc script that was meant to create `pytest.ini`, `tests/fixtures/README.md`, and
  `docs/SPEC.md` died with a quoting error and created nothing. Long markdown now goes through the editor's file tool, not
  heredocs.
- **2026-09-11** The first API probing script assumed the unauthenticated rate limit was generous and got a 429 on its first
  request after a burst of manual checks. Measured limit: about 6 requests per minute, `Retry-After` honored. Collectors pace
  at one request per 12 s and never loop on 429.

- **2026-09-11** Second shell failure of the same kind: the Bash tool breaks on any *unbalanced single quote* in the
  command text, even inside a quoted heredoc (apostrophes in prose the first time, Python triple single quotes the second).
  Rule: multi-line scripts and documents go to a file via the editor tool and are then executed; keep inline shell
  commands free of stray apostrophes.

- **2026-09-11** I assumed trumpstruth's "Capture Date" on a removed post was the moment it was found gone and used it as
  the "last known alive" bound. After the backfill, 93 of 98 deletions had a lower bound months after their removal:
  trumpstruth re-processes removed pages (all carried September capture dates). Fixed: the lower bound from trumpstruth is
  the creation time only; the 98 deletions were regenerated through the corrected code.

## Data anomalies (source side)

- **CNN archive de-duplicates reposts.** Of the four self-reposts Trump posted and deleted on 2026-09-08 (ids
  117238301772357460, 117238326295991805, 117238345561593751, 117238414290995787), the archive kept only 117238345561593751.
  trumpstruth.org captured all four with removal times.
- **CNN archive glues the `RT @handle` prefix to the text** (`RT @realDonaldTrumpThe Failing New York Magazine...`), so a
  handle parsed from it is ambiguous when the text starts with a word character. The merge never lets CNN override a handle
  known from the API or trumpstruth.
- **trumpstruth.org stores reposted originals as their own entries.** Status 41515 is Michael Cohen's post
  117190624268499306 (the target of Trump's repost 117213738409833358, stored as 41514). Collectors skip entries not
  authored by realDonaldTrump, and trumpstruth's stats total therefore overstates Trump's own post count slightly.
- **trumpstruth.org listing pages render a repost as a `ReTruthed` label followed by the target post's own card** (same
  trumpstruth id, ts_id and time as the target). The first parser draft therefore labeled the *target* as a reblog and would
  have mislabeled originals. Fixed 2026-09-11: listing cards carry a `retruthed` flag and are merged as the target; a repost's
  own id and time come only from its status page, which the collector now fetches for every new trumpstruth id in sequence.
- **trumpstruth.org listing ignores `removed` and date parameters**; only `/search` honors them (with an empty query a date
  range is required). The feed caps dated queries at 10 items.
- **Truth Social API `statuses_count` (36,549 on 2026-09-11) differs from the archives** (CNN 36,236; trumpstruth 37,105).
  Expected: deletions, replies, and the other-account entries above. Tracked as a soft check with tolerance.
- **trumpstruth.org removal tracking starts in March 2026.** The full removed-only search over 2022-01-01..2026-09-11
  returned 98 posts, all removed between 2026-03 and 2026-09 (6 / 44 / 16 / 8 / 14 / 6 / 4 per month). Deletions before
  March 2026 are unknown to every free source; the deferred API backfill (present in archives but missing from the live
  account) is the only way to recover them.
- **Our `present` count exceeds the API's `statuses_count` by ~340** (36,898 vs 36,554 on 2026-09-11): the archives keep
  posts deleted before March 2026 that nothing has flagged, and the API count excludes them. Tracked as a stat; warned
  only beyond 1%.
