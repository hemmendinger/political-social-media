# 09. Economy: what the system spends, and how an agent spends less

Serves Law 14 and the brief's "least expenditure of resources". Numbers below were measured in this
repository on 2026-09-12 (307 tests, 37,002 records, 25 run records in `data/runs/2026-09.jsonl`). Where a
number is derived rather than measured, it says so.

## 1. The resources

| Resource | Who pays | Measured today | Dominant driver |
|---|---|---|---|
| Agent attention (tokens read) | every session | 180 lines across 3 data files to answer "is it healthy?"; about 190 lines across 4 files plus the Actions console to classify a red run; 50 to 80 lines for "what fields does a post have?"; about 125 lines across 6 files plus three hand edits to regenerate one deletion (see `facts` in section 5) | overlapping docs; no situation artifact; playbooks written as prose |
| HTTP requests to rate-limited hosts | the sources; our reputation with them | trumpstruth: 3 to 7 per normal run, 202 when the id walk is capped; cnn: 1 per download (about 20 MB); api from the cloud: 4 requests and 36 s of pure sleep per probe every 6 h, always a 403 | the blocked API probe; the id-walk cap |
| GitHub Actions minutes | the maintainer's quota | 37 to 80 s per collect run, of which up to 36 s is the API probe sleeping; about a minute of runner time per push for tests (2-job matrix, 19 to 28 s per job; billable only if the repository were private) | the API probe; `pip install pandas` every run (pandas is imported by nothing) |
| Repository growth | every clone, every checkout | `data/posts` 57.3 MB; `output/posts.csv` 12.7 MB rewritten on every run and committed anew whenever the post set changed (3 of the first 4 bot commits); `output/metrics.json` 1,653 lines with a 10 to 150 line diff on every commit (12 to 14 lines when 0 posts were added); engagement snapshots about 328 rows (19.5 KB) per CNN download (one per download, at most every 2 h), up to 234 KB per day into a tracked CSV; pack 10.5 MiB after 15 commits | committing derived outputs; the 2-hour CNN cadence producing hourly engagement rows for every post under 14 days old |
| Wall clock | the run; the agent waiting | normal cloud run 9 to 51 s of collector time (5 s is a desktop run); `pytest` 1.8 s; `build_db` 2.6 to 3.9 s (51 MB sqlite); `check` about 2 to 3 s; exports about 4 to 6 s (all environment-dependent); posts are JSON-loaded from disk once per collector leg and three more times in the check and export phase (`run_checks`, `build`, the CSV export), up to six loads per run at about 1.3 s each | repeated loads; pacing sleeps |
| Deletion detection latency | the mission | nominal 30 min; observed cron delivery 2 of about 16 scheduled slots in the first 8 hours (effective cadence 2 to 5 hours); the trumpstruth removal time is itself an upper bound | GitHub's scheduler, not our code |
| Maintainer attention | the maintainer | reading the Actions console; hand edits with no receipt | no `doctor`; no intervention ledger |
| Deletion coverage | the mission | the removed search covers only posts created in the last 14 days (the site filters by creation date); 35 of 98 known deletions were older than that at removal | a window chosen for cost that costs almost nothing to widen (B-029) |

## 2. Reading costs, before and after (Law 15)

Approximate tokens an agent must read to answer each question correctly. "After" assumes the vision's
artifacts exist and the agent starts from `AGENTS.md`.

| Question | Today | After | How |
|---|---|---|---|
| Is the system healthy right now? | about 1,800 (checks.json 133 lines, tail of runs, the top of state.json's 141 lines, OPERATIONS section 4 to interpret) | about 600 (first screen of `STATUS.md`) | Law 4 |
| Why is the workflow red? | about 3,500 plus the Actions console, which a sandbox often cannot read | about 800 (`ts doctor` output with evidence and the next verb; the raw capture artifact if needed) | Laws 5, 6 |
| What fields does a post have, and what do they mean? | about 1,200 (SPEC section 2 and README conventions) | about 900 (the generated block in SPEC section 2, which also carries the merge rule and sources per field) | Law 7 |
| How do I regenerate one deletion safely? | about 2,500 across 6 files, then 3 hand edits | about 300 (`ts help repair`, then one command with `--dry-run`) | Laws 5, 12 |
| Why does this record say that? | not answerable without reading merge.py and grepping ledgers (about 3,000) | about 400 (`ts explain <ts_id>`) | Law 8 |
| What is this source like and how does it fail? | about 1,500 spread over README, OPERATIONS, MISTAKES, SPEC | about 700 (one dossier) | Law 13 |
| What should I work on? | about 1,200 (TODO.md plus OPERATIONS section 7, two disjoint lists) | about 200 (`STATUS.md` pending block, then one backlog item) | Law 13 |

Total for a typical "orient, diagnose, fix one thing" session: roughly 12,000 tokens of reading today
versus roughly 3,500 after, with fewer wrong turns (the drift list in `11-doc-deltas.md` shows how many of
today's reads mislead).

## 3. Network and minutes: the cheap wins

Each of these is a one-line change or a profile rule, and together they remove most of the waste.

| Change | Saves | Cost to build | Where |
|---|---|---|---|
| `cloud` profile never runs the api leg (records `skipped: profile=cloud`) | 4 requests and 36 s of sleep per 6 h; up to 45% of a run's wall time | S | `03-verbs.md` section 3 |
| Drop `pandas` from `requirements.txt` (nothing imports it; move it to the existing `requirements-dev.txt` if analysis wants it) | an estimated 10 to 20 s of pip per cloud run (not measured), and a cache key that changes less | S | D-013 |
| CNN daily at 09:00 UTC plus `--force-cnn` on demand (D-007) | 11 downloads of about 20 MB per day; engagement growth falls from about 234 KB per day to about 20 KB | S | `collect_archive.SKIP_INTERVAL` |
| Load posts once per run and pass the list to `run_checks`, `build`, and the CSV writer | about 2.6 s per run | S | `collect.run_all` |
| `MAX_IDS_PER_RUN` (a trumpstruth constant) and `removed_days`, `max_pages`, `max_verify` (run() parameter defaults of the trumpstruth and api collectors) exposed as verb flags with the same defaults | an id re-walk on the desktop takes one run at a larger cap instead of about 209 cron runs (about 17.7 h of collector time at 305 s per capped run) | S | `ts collect --max-ids` |
| Fail fast on a guaranteed 403: `max_attempts=1` for the probe request | the 36 s of pacing sleep becomes 0 s even where probing is kept (the 12 s pace applies between consecutive requests) | S | `collect_api` |
| Search removals since 2022-01-01 on every run (D-017) instead of the last 14 days | recovers about a third of future deletions for 0 to 4 extra requests per run (98 results fit in one page of 100 today; `processed_removed_ids` prevents re-fetching status pages) | S | `collect_trumpstruth.run(removed_days=...)` |
| Compact `checks.json` (`months_present` as `{first, last, count, gaps}`) and render integer lists in `state.json` on one line | about 800 tokens off every cold read of the two files an agent opens first (B-056) | S | `check_data`, `store.save_state` |
| Rewrite only the month files a run touched, and load the store once (B-057) | a 200-id walk stops performing up to 20 full 55-file rewrites (about 3 s each here, so roughly a minute); the run's diff touches only what changed | S | `store.save_posts(months=...)`, `Context.posts()` |
| `ts collect --plan`: a zero-request preview from a policy table (B-058) | an agent knows what a run will do and roughly cost before spending anything; skip rules become data with a `next_due` | M | `scripts/policy.py` |
| Per-leg request budgets (B-032) | a semantic change at the source cannot run a leg into the 25-minute timeout every run with no trace; the truncation is a recorded number | S | `Http` |

## 4. Repository growth: what to stop committing (D-010)

| File | Today | Proposal |
|---|---|---|
| `output/posts.csv` (12.7 MB) | committed on every run that changes anything; each commit adds a new blob (git delta-compresses, but a 12.7 MB text file with one changed line still costs a scan per checkout and grows the pack) | stop committing; `ts build --csv` writes it on demand (0.4 s); if a download URL is wanted, commit a 90-day `posts-recent.csv` (about 2,400 rows, 1.0 MB) instead |
| `output/metrics.json` | rewritten every run; its 7-day window slides, so the diff is never empty | split: `metrics-window.json` (about 4 KB) every run, `metrics-trailing.json` once a day at the ET day boundary |
| `data/engagement/*.csv` | one row per post per hour for every post under 14 days old, from CNN | one baseline row at first sight plus one row per day for posts under 14 days, plus one at 14 days; the api leg from the desktop keeps the hourly rule because it is the only source that samples counts at observation time (with upvotes and downvotes) |
| `output/history/status-YYYY-MM.jsonl` (new) | not yet | about 350 bytes per run, the time series behind trends, cadence, and `since_firing`; works in a shallow clone; folded yearly |
| `data/raw/` | never written | written in the cloud, never committed, uploaded as an artifact only on a non-green run |

Expected effect: the working-tree churn per day falls from roughly 1 to 3 MB of rewritten files (posts.csv, the
metrics diff, engagement rows; git delta-compresses the pack, so packed growth is smaller and dominated by the
engagement rows) to under 200 KB.

## 5. The cost line and the budget

Cost is measured in the units it is budgeted in and stored where the counts already are. `Http` counts
requests by host and bytes in; the clock exposes seconds slept; the store counts files and bytes written.
Every run record gains `cost: {requests, requests_by_host, bytes_in, slept_s, wall_s, files_written,
bytes_written}` (B-055) and every verb envelope carries the same block, so the 36 s the blocked api leg
spends sleeping is visible as `slept_s: 36` instead of being inferred from the pacing constants. A run also
reports `accuracy_per_request`: beliefs changed (new records, deletions found, records verified) divided by
requests, per leg, which is the number that says where requests are worth spending.

Every verb prints a cost line (`cost: 7 requests (trumpstruth 6, cnn 1), 14.2 s (9.0 s sleeping), 4 files`),
and the envelope carries it as data (`schemas/verb-envelope.schema.json`). Three habits follow:

- **Estimate before, measure after.** A repair plan prints its estimated requests and seconds (from the
  pacing constants and the count of ids), and the intervention record stores the measured values. The
  backlog's `cost` block is filled from these measurements, not guesses (the backfill was documented as
  30 minutes in the README, 15 in OPERATIONS, and measured at 12.5).
- **Plan before you spend.** `ts collect --plan` reads the policy table and the state and prints, with zero
  requests, which legs would run or skip and why, when each is next due, and an estimated cost range; the
  run record stores the estimate beside the measurement and a soft check fires when they diverge by more
  than three times (B-058).
- **Choose the cheapest sufficient action.** `ts doctor` and the playbooks name the cheapest verb first:
  regenerate one deletion (about 7 requests) before redoing the removed phase (105 requests, 159 s) before
  the full backfill (477 requests, 747 s); `ts check --only` before `ts check`; `ts verify --quick` before
  `ts verify`.

## 6. Latency: the honest number

The system's stated cadence is 30 minutes; the observed delivery of GitHub's cron in the first day was
2 of about 16 slots. The mission number "deletion latency" therefore reports what the record can actually
promise: the median deletion interval width over the last 30 days, and `STATUS.md` shows the gap between
scheduled and actual runs (`runs_expected_24h` versus `runs_actual_24h`, from the run records). If the gap
stays large, the cheapest remedy is a second trigger (`repository_dispatch` from a desktop scheduled task or
a free external cron service) rather than tighter code; that is a backlog item with its own measurement,
not an assumption.

## 7. The verification ladder

Four rungs, each with a fixed cost, and a rule for which rung a change class needs (`06-simulation-and-verification.md`
section 4 has the checklist):

| Rung | Command | Cost | Sufficient for |
|---|---|---|---|
| quick | `ts verify --quick` (coherence tests, changed-module tests, smoke replay) | 0 requests, under 30 s | docs, knowledge, a check descriptor, a metric |
| replay | `ts replay <bundle>` | 0 requests, under 20 s per bundle | a parser, the merge, a collector, a repair plan |
| plan | `ts collect --plan`, `ts repair <plan>` (no `--apply`) | 0 requests, seconds | anything that would spend requests or rewrite data |
| live | `ts collect --live` on a scratch root, from the profile that can reach the source | requests, minutes | a new source, a fixture recapture; never as a feedback loop for a parser fix |

## 8. What not to optimize

- The test suite (1.8 s) and `build_db` (under 4 s) are already cheap; do not add caching there.
- The 1.5 s trumpstruth pacing and the 12 s API pacing are courtesy and rate-limit compliance, not waste.
  The remedy for slow walks is doing them from the desktop with a larger per-run cap, never faster requests.
- Record size: `raw_api` is kept on 20 records today and would grow with the desktop api runs; it is
  forensic evidence and stays. Revisit only if the month files exceed 10 MB each.
