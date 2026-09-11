# Operations guide

For whoever has to keep this running. What runs, why each piece exists, what each check means, and what to do when
something is red. Design rationale is kept to one line per decision; the module contract is in `SPEC.md`.

## 1. What runs, where, when

| Where | What | When |
|---|---|---|
| GitHub Actions `collect` | `python -m scripts.collect` then commit `data/` and `output/` | cron `7,37 * * * *` (UTC), on `workflow_dispatch`, and on any push that changes `collect.yml` |
| GitHub Actions `tests` | `pytest -q` on Python 3.9 and 3.12 | every push and pull request, except pushes touching only `data/` or `output/` |
| Desktop | `git pull`, `build_db`, `weekly`, `query`; optionally `collect` | when you analyze |

One collection run, in order (`scripts/collect.py`):

1. Take `data/.lock` (ignored if older than 30 min, so a crashed run never blocks the next one).
2. `collect_trumpstruth`: listing page 1 (newest 100 cards) → sequential status pages for every new trumpstruth id → removed-only search for the last 14 days, one status page per new removal.
3. `collect_archive` (CNN): full JSON download, at most once every 2 h (see §7 for the planned change to daily).
4. `collect_api`: probe Truth Social; skipped for 6 h after a failed probe (from GitHub it always fails, see §7).
5. `check_data`: hard checks stop the run (exit 2, nothing committed); soft checks are only recorded.
6. `build_db` → `data/truths.sqlite`; exports `output/posts.csv`, `output/metrics.json`, `output/checks.json`.
7. (cloud only) commit `data/ output/` with the message `collect: +N posts, +M deletions, checks ok` and push, retrying the pull/rebase three times.

Each source writes one row per run to `data/runs/YYYY-MM.jsonl` (`ok`, `requests`, `new_posts`, `updated_posts`,
`deletions_found`, `errors`, `notes`). That file is the first thing to read when something looks off.

## 2. Sources: why each exists and how it fails

| Source | Why it is here | Typical failure | What you see |
|---|---|---|---|
| trumpstruth.org | Only free record of **deletions** (removal timestamps), and the fastest feed of new posts with kinds and media. Status ids are sequential, so nothing is skipped. | Markup changes → `ParseError`; site slow or down → `HttpError`; both fail the trumpstruth row and the run | run row `ok=false`, notes carry the exception; workflow red |
| CNN-hosted archive | Backstop for anything trumpstruth missed, engagement counts, and the pre-2026 history. | File unreachable → `HttpError`; format change → `KeyError` on rows | cnn row `ok=false`; posts still arrive via trumpstruth |
| Truth Social API | Ground truth for existence and richest fields. Blocked from GitHub runners (Cloudflare 403); works from a home connection. | 403/429 → marked unreachable, re-probed after 6 h | api row `notes=unreachable: 403` or `skipped: unreachable ...` |

Precedence when sources disagree: API > trumpstruth > CNN (for `created_at_utc`: API > CNN > trumpstruth). A losing
value is dropped and logged as an anomaly in the run notes; it never overwrites. Empty values never overwrite non-empty ones.

## 3. Data files (what may be edited by hand)

| File | Contents | Hand edits |
|---|---|---|
| `data/posts/YYYY-MM.jsonl` | one current record per post, month of `created_at_utc`, sorted by id | never; run a collector or a one-off script through `scripts.store` |
| `data/deletions.jsonl` | append-only log of deletion detections (one per post and source) | never |
| `data/engagement/YYYY-MM.csv` | append-only count snapshots, ≤1 per post per hour, older posts one baseline row | never |
| `data/runs/YYYY-MM.jsonl` | one row per run and source | never |
| `data/state.json` | per-source cursors and memory (see below) | yes, carefully, to reset a source |
| `data/truths.sqlite`, `data/raw/` | derived database, scratch | delete freely; rebuilt by `build_db` |

`state.json` keys worth knowing: `trumpstruth.max_trumpstruth_id` (next sequential fetch starts after it; lower it to
re-walk ids), `trumpstruth.processed_removed_ids` (removed pages already merged; remove an id to re-fetch it),
`trumpstruth.backfill.phase` (`listing`/`removed`/`done`; set `removed` with `removed_page: 1` to redo the removal search
from 2022), `cnn.etag`/`last_ok_at` (delete to force a download), `api.reachable`/`last_probe_at` (delete to re-probe now).

## 4. Integrity checks: what each means and what to do

Hard checks (`output/checks.json` → `hard`; the run exits 2 and commits nothing):

| Check | Why it exists | What to do when it fires |
|---|---|---|
| `missing_fields`, `bad_*` (`ts_id`, `timestamp`, `kind`, `status`, `pinned`, `media`, `field_sources`, `et_hour`, `et_dow`) | a record no longer matches the schema in `SPEC.md` §2; usually a parser or merge change | fix the code, then rewrite the bad records with a one-off script; tests should have caught it, add one |
| `duplicate_id` | the same post in two month files; would double-count everything | keep the record in the month of `created_at_utc`, delete the other |
| `wrong_month_file`, `unsorted_file` | store invariant broken; `build_db` and diffs rely on it | `python -c "from scripts import store; from pathlib import Path; r=Path('data'); store.save_posts(r, store.load_posts(r))"` rewrites files canonically |
| `created_after_deleted_upper` | a deletion earlier than the post's creation is impossible; a timestamp or timezone bug | check `parse_et_text` / the removed page; fix, then regenerate that deletion (§5) |
| `deletion_unknown_post`, `duplicate_deletion_event` | the deletion log points at a post that was never saved, or logs one detection twice; only possible after a crash between writes | rerun `collect --sources trumpstruth`; if the post is really gone from all sources, delete the orphan line |
| `engagement_unknown_post`, `engagement_too_close` | count rows for a post we do not have, or two rows within the 60-minute throttle | usually a collector bypassed `store.filter_engagement`; fix the code, delete the offending rows |
| `missing_run_row` | a run finished without logging itself; the orchestrator is broken | look at `collect.py` |

Soft checks (`soft`; recorded, run continues, commit still happens):

| Check | Why it exists | Reading it |
|---|---|---|
| `inverted_deletion_bounds` | `deleted_lower` after `deleted_upper`: two signals contradict (e.g. API saw it live after trumpstruth said removed) | inspect the post; if the newer evidence is right the deletion may be wrong; otherwise leave, the bounds stay as recorded |
| `present_count_drift` | our `present` count vs the account's `statuses_count` (only when the API was reachable); drift beyond 1% | expected ~340 today: pre-March-2026 deletions nobody flagged (TODO.md); a sudden jump means a source started missing posts |
| `trumpstruth_total_drift` | our total vs trumpstruth's stats total (only when passed in) | same reading; trumpstruth counts other accounts' originals too |
| `single_source_recent_posts` | posts 1 to 30 days old seen by only one source; a source outage shows up here first | check which source is missing them in the run rows; a few dozen CNN-only reposts around the id-walk boundary are normal |
| `stale_newest_post` | newest post older than 12 h | either Trump is quiet or trumpstruth polling broke; compare with trumpstruth.org by hand |
| `spike_days` | a day in the last 60 days with ≥20 posts and >3× the trailing median | real bursts land here; a parser suddenly duplicating cards would too (check `duplicate_id` is clean) |
| stats only: `cnn_ambiguous_handles` | CNN-only reposts whose handle parse is ambiguous (TODO.md item 1) | watch it shrink; not an anomaly |

## 5. Playbook

**Workflow run is red.** Open the run, read the `Collect` step. Classify:
- `ParseError` → markup drift. Fetch the page named in the error with the URL from `tests/fixtures/README.md`, save it
  as a new fixture, adjust the parser, keep the old fixture test passing if the old markup can still appear.
- `HttpError`/`TransportError` → the site was slow or down; the next run resumes from state. If it persists for hours,
  check the site in a browser.
- exit 2 → a hard check; see §4. Nothing was committed, so `data/` on `main` is still consistent.
- push failed after retries → someone pushed at the same time; the next run picks the data up again (state was not saved
  to `main`, so the same work is redone, which is harmless).

**Reproduce locally without touching the real data:** `python -m scripts.collect --data-root %TEMP%\ts --output-dir %TEMP%\ts_out`.
Tests never use the network; `pytest -q` is the first thing to run after any change.

**Regenerate one deletion:** remove its trumpstruth id from `state.json` → `processed_removed_ids`, delete its lines
from `data/deletions.jsonl`, set the record's `status` to `present` and its `deleted_*`/`trumpstruth_removed_at` to
null (through `scripts.store`, keep the file sorted), then run `collect --sources trumpstruth`. To redo all of them,
set `backfill.phase` to `removed` and run `collect --sources trumpstruth --backfill`.

**Walk trumpstruth ids again** (e.g. after a parser fix): lower `max_trumpstruth_id`; each run resolves at most 200 ids
at 1.5 s each.

**Redo the whole history:** delete `data/posts/`, `data/deletions.jsonl`, `data/engagement/`, `data/state.json`, then
`collect --sources cnn --force-cnn --no-export` and `collect --sources trumpstruth --backfill --no-export`
(about 15 minutes), then `python -m scripts.validate_backfill --cnn data/raw/truth_archive.json` and note the result in
`MISTAKES.md`.

**Rate limits.** trumpstruth: 1.5 s between requests, no auth. Truth Social API: about 6 requests per minute
unauthenticated, then 429 with `Retry-After`; the client honors it and never loops. CNN: one request.

**Re-capture fixtures.** URLs and what each page must contain are in `tests/fixtures/README.md`. Keep the capture date
in that table; a fixture is evidence of how the site looked on that day.

## 6. Design decisions, one line each

- Text files in git are the truth; SQLite is derived. Cloud jobs can write text safely and every change is a readable diff.
- trumpstruth is the deletion record because it is the only free source that timestamps removals; the API only says 404.
- Deletions are intervals (`deleted_lower`, `deleted_upper`), never points, because no source observes the moment itself.
- A losing source never overwrites; provenance per field (`field_sources`) makes every value explainable.
- Hard checks block commits so a broken parser can never poison `main`; soft checks stay visible in `checks.json`.
- Python 3.9 syntax because the desktop runs the Windows Store 3.9 build; the cloud runs 3.12; tests run on both.

## 7. Open decisions

- CNN download cadence: currently every 2 h (240 MB/day); daily is enough for a backstop and baseline engagement.
- Truth Social API collector: blocked from GitHub; either keep it as a desktop-only opt-in (it is the only way to run the
  historical deletion backfill in TODO.md) or delete it. Until decided it stays in the pipeline with the 6-hour re-probe.
