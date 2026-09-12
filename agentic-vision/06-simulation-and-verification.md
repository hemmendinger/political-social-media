# 06. Simulation and verification: prove it offline before it touches production

Serves Laws 10, 16, and the "one validated push beats three speculative ones" rule. The code was built for
this: `Clock` and `Transport` are injected, `FakeClock` advances on `sleep`, `FakeTransport` routes URLs to
canned responses and records calls, and the fixtures are real captures. What is missing is the packaging
that lets an agent use those pieces on the whole pipeline in one command.

## 1. Replay bundles

A bundle is a directory that fully determines one run:

```
tests/bundles/normal-run-2026-09-11/
  manifest.json
  responses/
    001-trumpstruth-listing-p1.html
    002-trumpstruth-status-41695.html
    ...
    017-cnn-archive.json
    018-api-statuses-p1.json        # or a 403 stub in the cloud bundle
  seed/                             # data/ as it was before the run (may be a small synthetic seed)
    posts/2026-09.jsonl  deletions.jsonl  engagement/2026-09.csv  runs/2026-09.jsonl  state.json
  golden/                           # data/ as it must be after the run
    ...
```

`manifest.json`:

```json
{
  "name": "normal-run-2026-09-11",
  "proves": "a normal cloud run: 4 new trumpstruth posts, 1 sequential id, cnn not modified (304), api 403",
  "clock_start": "2026-09-11T20:08:53Z",
  "profile": "cloud",
  "routes": [
    {"url": "https://www.trumpstruth.org/?sort=desc&per_page=100&removed=include", "file": "responses/001-trumpstruth-listing-p1.html", "status": 200},
    {"url_prefix": "https://www.trumpstruth.org/statuses/", "file_by_suffix": "responses/status-{id}.html", "status": 200, "missing": 404},
    {"url": "https://ix.cnn.io/data/truth-social/truth_archive.json", "status": 304},
    {"url_prefix": "https://truthsocial.com/api/", "status": 403}
  ],
  "args": {"sources": ["trumpstruth", "cnn", "api"], "backfill": false}
}
```

`ts replay <bundle>` builds a `FakeTransport` from the routes, a `FakeClock` from `clock_start`, copies
`seed/` to a temporary data root, runs `collect.run_all` and `check`, and diffs the resulting data root
against `golden/` byte for byte. Output: pass/fail, the diff, the run records, the anomalies produced, and
the cost the fake clock recorded (the sum of `sleep` calls is the wall time the run would have taken).
`--update-golden` rewrites `golden/` after a deliberate behavior change; the diff is then reviewed in the
pull request like any other change.

Two rules make a replay trustworthy. **A harness fault is louder than a source fault**: `FakeTransport`
raises `BundleIncomplete`, a `BaseException`, for a missing route or an exhausted list, naming the URL and the
routes tried, so the collectors' catch-all `except Exception` cannot turn an incomplete bundle into a green run
with fewer records (B-075); `run_all` writes the failure record and re-raises, and `ts replay` exits 3. And
**the first replay found a bug**: with 500 four times on status 41686 and 200 on 41687, the walk sets
`max_trumpstruth_id` to 41687 and never fetches 41686 again (B-074, L-010), which is exactly the class of
silent loss a production run cannot reveal.

Bundles to ship in phase 1 (each small, under 2 MB):

| Bundle | Proves |
|---|---|
| `smoke` | 3 posts, one new, one deletion, all three sources; under 5 s; used by `ts verify --quick` |
| `normal-run-cloud` | the example above; the api 403 path and the 6-hour re-probe skip |
| `deletion-found` | a removed status page becomes a deletion event with correct bounds (the L-003 lesson) |
| `retruthed-listing` | the ReTruthed target-card quirk and sequential resolution of a repost's own id |
| `red-parse-error` | a listing with the `statuses` container renamed: `parse_listing` raises `ParseError`, the run fails, the run record carries the error, `ts doctor` says `markup_drift` (a second variant keeps the container but under 50 cards, the `min_yield` path) |
| `backfill-tail` | the last two listing pages of a backfill and the removed search over 2022-01-01 to today |
| `red-walk-blip` | a 5xx on one status page mid-walk; the id lands in `pending_ids` and is fetched on the next run (B-074) |

## 2. From a red run to a bundle

`ts replay --from-raw data/raw/<run_id>` (or from the downloaded workflow artifact) builds a bundle:
routes from `index.jsonl`, `clock_start` from the run record, `seed/` from the git commit before the run
(found today by timestamp; with the `Run-Id` trailer of `02-situation.md`, by `git log --grep`). The agent then reproduces the failure offline, fixes the
parser, replays until green, and promotes the bundle into `tests/bundles/` with a `proves` line. The
failure becomes a permanent regression test in one motion (Law 13).

## 3. Fingerprints on every fetch, canaries weekly

Two mechanisms, one pure function. `parsers.fingerprint(kind, text)` returns the structural summary a parser
depends on: for a trumpstruth listing the count of `div.status` cards and the presence of each CSS class the
parsers read (`status__external-link`, `status__reblog-indicator`, `status-details-table__key`,
`search-result`, `status__deleted-badge`; `alert--deletion` appears on removed pages but no parser reads it
today, so it joins the token list rather than the parser), the details-table keys, the feed
namespace; for the CNN file the row key set; for the API the status object key set. The fixture manifest
stores each fixture's fingerprint.

- **Every production fetch** is fingerprinted and compared with its fixture's fingerprint (B-034). A
  difference is an anomaly `markup_changed` (with the missing and added names), never an exception: the
  parser still runs, and the run stays green if it yields. This catches a class rename the parser tolerates
  today and a page that changed but still parses, days before a listing finally yields under `min_yield`. A
  200 with an empty fingerprint is the signature of a challenge page (`ts doctor` class `challenge_page`).
- **Weekly canaries** (`canary.yml`, Sundays; also `ts doctor --live --canaries`) fetch the page named in
  each manifest row and compare it with the fixture, so drift is seen even in a week with no collection.
  A change opens a backlog item (`ts note backlog --from-canary`) with the diff as evidence.

Bundles to ship in phase 1 also include `removal-of-old-post` (a 40-day-old post is removed; the 14-day
search never returns it, the full sweep does, and it becomes a deletion event: the regression test for B-029) and `challenge-page` (a 200 with no
container produces an incident with class `challenge_page`, not `markup_drift`).

## 4. `ts verify`: the pre-push checklist

Fixed order, stop at first failure, print what ran and what it cost:

| Step | Command | Time | `--quick` |
|---|---|---|---|
| 1 | `python -m pytest -q tests/test_coherence.py` | 2 s | yes |
| 2 | `python -m pytest -q` (305+ tests) | about 15 s | changed modules only (`pytest --lf` and the tests naming the changed modules) |
| 3 | `ts replay tests/bundles/smoke` | 5 s | yes |
| 4 | `ts check` on the real `data/` | 3 s | yes |
| 5 | round trip: `save_posts(load_posts())` byte-identical | 5 s | no |
| 6 | `ts status --refresh` and `git diff --stat STATUS.md output/status.json` (a change here is not an error, it is shown so the agent knows the situation moved) | 3 s | yes |
| 7 | `python -m compileall -q scripts` under Python 3.9 syntax rules (a small AST check for `match`, `X | Y`, walrus-free is not required) | 1 s | yes |
| 8 | fix receipt: if the diff touches a parser, the merge, a collector, or a check, the commit message draft (or `--trailers`) names a lesson, quirk, fixture, backlog, or `Knowledge: none` with a reason (B-063); a warning, not a failure | 0 s | yes |

`test.yml` runs `ts verify --ci`, which is steps 1, 2, 3, and 7 (no real data needed).

## 5. Determinism rules that make replay possible

Already mostly true, and enforced by `tests/test_determinism.py` (B-076): an AST walk over `scripts/*.py`
fails on `datetime.now`, `utcnow`, `date.today`, `time.time`, `secrets.*`, `random.*`, and on `urllib.request`
or `curl_cffi` imports outside `scripts/common.py`, with an allowlist for `SystemClock`, `new_run_id`,
`acquire_lock`, and `validate_backfill`. The bundle manifest lists every clock-derived URL (the removed-search
window, the CNN skip decision) so an author knows what `clock_start` pins.

- No module reads the wall clock or the network except through `Context.clock` and `Context.http`.
- `new_run_id` takes the clock; the random suffix is replaced in replay by a fixed one from the manifest.
- `save_posts` and every ledger write are byte-deterministic (sorted keys, compact separators, LF).
- `check_data.run_checks` takes `now`.
- `situation.build()` takes the clock and the commit sha as arguments.

## 6. Epistemic golden cases

The synthetic dataset in `tests/conftest.py` has no record shaped like the real uncertainty modes. A group E
is added (B-038): a deletion with `deleted_lower == created_at_utc` and `deleted_upper` 80 minutes later (every real
deletion has the first property; about 31 of 98 have an interval near 80 minutes, 45 are longer than a day,
the median is about 705 minutes), an api-tightened lower bound, a cnn-only repost pair sharing a target with one
sibling missing, a present post from 2025-12 never verified, a post at 2026-08-31T23:30-04:00 (the UTC seam; `EASTERN` is defined in `scripts/common.py`),
a late-baseline engagement row, a reblog with a glued cnn handle. `tests/test_epistemics.py` asserts that
`deleted_within` partitions `v_deletions` into confirmed, possible, and excluded; that the August-shaped case
yields 0 confirmed and 1 possible; that caveat counts equal the `v_confidence` counts; and that every
registered question reproduces its golden answer in `tests/golden/answers.json` (`ts ask --update-golden`
rewrites it after a deliberate change, reviewed like any diff).

## 7. What verification costs the agent

Before: read `OPERATIONS.md` section 5, guess whether a change is safe, run `pytest -q`, push, wait for the
cloud run at :07 or :37, read the console. About 3,000 tokens and up to 30 minutes of wall time per attempt.
After: `ts verify --quick` (under 30 s, one screen of output), then push. A production failure is reproduced
with `ts replay --from-raw` in under a minute instead of being reasoned about from a truncated note.
