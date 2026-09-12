# Lesson index (seed for knowledge/lessons/)

One line per lesson; each becomes an `L-nnn-<slug>.md` from `templates/lesson.md` with `encoded_in`
pointing at the test that prevents a recurrence. L-001 to L-004 migrate `MISTAKES.md`; L-005 is from the
2026-09-12 audit.

| Id | Date | Component | Source | What went wrong | Rule | Encoded in |
|---|---|---|---|---|---|---|
| L-001 | 2026-09-11 | tooling | none | Two shell heredoc scripts died on unbalanced single quotes and created nothing | multi-line files go through the editor's file tool, then run; keep inline shell free of stray apostrophes | none (tooling habit; AGENTS.md conventions) |
| L-002 | 2026-09-11 | collect_api | api | The first probe assumed a generous unauthenticated limit and got a 429 after a burst of manual checks | pace at 12 s per request; honor Retry-After; never loop on 429 | `tests/test_http.py` (429 and Retry-After cases) |
| L-003 | 2026-09-11 | merge | trumpstruth | trumpstruth's Capture Date was used as the "last known alive" bound; 93 of 98 deletions had a lower bound months after removal because removed pages are re-processed | the deletion lower bound never uses `trumpstruth_captured_at`; only `last_verified_live_at` or creation time | `tests/test_merge.py` (deletion bound tests); bundle `deletion-found` |
| L-004 | 2026-09-11 | parsers | trumpstruth | The first listing parser labeled the ReTruthed target card as a reblog and would have mislabeled originals | listing cards carry `retruthed` and are merged as the target; a repost's own id and time come only from its status page, resolved sequentially | `tests/test_parsers.py` (41655, cursor listing); `tests/test_collect_trumpstruth.py` (sequential resolution) |
| L-005 | 2026-09-12 | collect_* | none | Merge anomalies were computed on every run and discarded by every collector for the project's whole life; the docs said they were logged | anything the code computes for a human is also stored as data (Law 6); a coherence test checks that `MergeResult.anomalies` reaches the ledger | to be written with B-014 (`tests/test_collect.py::test_anomalies_reach_ledger`) |
