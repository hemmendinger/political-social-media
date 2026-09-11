# political-social-media

A deletion-aware record of @realDonaldTrump's Truth Social posts, collected every 30 minutes by GitHub Actions and
analyzed locally with SQL. The data files under `data/` are the source of truth; `data/truths.sqlite` is rebuilt from them.

## How it works

```
GitHub Actions (cron */30) -> python -m scripts.collect -> check_data -> commit data/ + output/ -> this repo
Desktop:                     git pull -> python -m scripts.build_db -> data/truths.sqlite -> query.py / weekly.py
```

Sources and their roles (verified 2026-09-11; details in `docs/SPEC.md`):

| Source | Role | Notes |
|---|---|---|
| Truth Social API (`truthsocial.com/api/v1/...`) | ground truth for existence, richest fields, engagement snapshots | unauthenticated; ~6 requests/min; may be unreachable from GitHub runners (the job logs a probe result every run) |
| trumpstruth.org | new posts every run, **the deletion record** (removal timestamps), kinds, mirrored media | project of Defending Democracy Together; crawled politely (1 request per 1.5 s) |
| CNN-hosted Stiles archive (`ix.cnn.io/data/truth-social/truth_archive.json`) | bulk history, gap filler, engagement counts | CC0; refreshed every 5 min; cumulative; excludes replies; de-duplicates reposts |

## Setup (desktop)

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Python 3.9 or newer. The cloud job uses 3.12; the code stays 3.9-compatible.

## Running

| Task | Command |
|---|---|
| One collection run (all sources) | `python -m scripts.collect` |
| One-time history backfill (CNN + full trumpstruth crawl, ~30 min) | `python -m scripts.collect --backfill` |
| Rebuild the SQLite database from `data/` | `python -m scripts.build_db` |
| Integrity checks only | `python -m scripts.check_data` |
| Weekly baseline snapshot | `python -m scripts.weekly --week 2026-W37` |
| Ad-hoc SQL | `python -m scripts.query --sql "select et_date, count(*) from v_posts_et group by 1 order by 1 desc limit 14"` |
| Saved query | `python -m scripts.query --file queries/deletions.sql` |
| Tests | `python -m pytest -q` (add `-m live` to also hit the real sources) |

Weekly routine: `git pull`, `python -m scripts.build_db`, then ask questions with `query.py` or start from `weekly.py`.

## Layout

```
scripts/      collectors, store, parsers, merge, check_data, build_db, metrics, query, weekly (see docs/SPEC.md)
queries/      starter SQL
tests/        pytest suite; tests/fixtures/ are real captured responses (see its README)
data/posts/   YYYY-MM.jsonl, one current record per post (source of truth)
data/deletions.jsonl, data/engagement/, data/runs/, data/state.json
output/       posts.csv, checks.json, metrics.json, reports/
docs/SPEC.md  module contract
MISTAKES.md   dated log of build errors and data anomalies
```

## Data conventions (cite these in analyses)

- **A post** is any status on the account: `original`, `quote`, `reblog` (ReTruth), or `reply`. When sources disagree on a
  field, precedence is API > trumpstruth > CNN (for `created_at_utc`: API > CNN > trumpstruth). Disagreements are logged as
  anomalies in the run notes, never silently overwritten.
- **Times** are stored in UTC (`...Z`). Analysis columns (`et_date`, `et_hour`, `et_dow`, `created_at_et`) are
  America/New_York. Day boundaries are Eastern. For a reblog, `created_at_utc` is when Trump reposted;
  `reblog_of_created_at` is the reposted post's own time.
- **Deletion is an interval, not a point.** `deleted_lower` = last moment the post was known to exist (our last live sighting,
  or trumpstruth's capture time); `deleted_upper` = first moment it was confirmed gone (trumpstruth's confirmed-removed time,
  or our API 404). Lifetime analyses must use both bounds. `deleted_source` names the signal that first confirmed it.
- **Status** is `present` or `deleted`. `present` posts seen only in archives (before polling began) are presumed live, not
  individually verified; `last_verified_live_at` is set only by the API. `deleted -> present` happens only if the API returns
  the post again and is logged as an anomaly. Records are never physically removed.
- **Engagement** rows are snapshots at observation time (at most one per post per hour, and for posts older than 14 days only
  one baseline row). They are not final counts.
- **Known blind spots.** Posts deleted faster than the sources poll (minutes) can be missed by every source. The CNN archive
  de-duplicates reposts (on 2026-09-08 it kept 1 of 4 deleted self-reposts) and excludes replies, and it glues the `RT @handle`
  prefix to the text so handles parsed from it can be wrong when no better source knows the post. trumpstruth removal times
  are upper bounds on the deletion moment. trumpstruth also archives the reposted author's original post as its own entry;
  the collectors keep only statuses authored by realDonaldTrump.

## Integrity

`scripts/check_data.py` runs after every collection. Hard failures (schema, duplicate ids, ordering, impossible deletion bounds,
parser yield below minimum) fail the cloud run and nothing is committed. Soft checks (counts versus the API's `statuses_count`
and trumpstruth's totals, one-source-only posts, freshness, volume spikes) are written to `output/checks.json`. Tests run on
every push (`.github/workflows/test.yml`).

## Known issues and deferred work

See `TODO.md`. The first item there, the CNN archive's glued `RT @handle` prefix, affects `reblog_of_acct` and the first word
of `content_text` on CNN-only reposts; `output/checks.json` reports how many rows are affected.
