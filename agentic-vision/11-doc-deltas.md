# 11. Deltas to the existing documents

Concrete changes to `README.md`, `docs/SPEC.md`, `docs/OPERATIONS.md`, `TODO.md`, `MISTAKES.md`,
`docs/dead-code-review.md`, `tests/fixtures/README.md`, and the two workflows. Two kinds: **corrections**
(the doc is wrong about the code today; fix regardless of the vision) and **restructurings** (what each
doc becomes once the vision's artifacts exist). Every correction was verified against the code on
2026-09-12; line numbers refer to the files at commit `9b7af34`.

## 1. Corrections: the docs are wrong today

These are independent of the vision and should land first (phase 0), because an agent reading the docs
today is misled by each of them. When the knowledge layer exists, this table becomes
`knowledge/audits/2026-09-12-doc-deltas.md` with a Disposition column mapping each row to the phase-0 fix or
the backlog id that carries it (B-062), so the vision's own audit obeys the rule it sets.

| # | File | Says | Truth | Fix |
|---|---|---|---|---|
| C1 | `README.md:3,9`; `docs/SPEC.md:314` | cron `*/30`, "every 30 minutes" | `collect.yml:5` is `7,37 * * * *`; observed delivery in the first day was 2 of about 16 slots | say "scheduled at :07 and :37 UTC; GitHub delivers a fraction of scheduled runs, see `STATUS.md` for actual cadence" |
| C2 | `README.md:62-63`; `docs/OPERATIONS.md:36` | disagreements "are logged as anomalies in the run notes" | `MergeResult.anomalies` is never read by any collector (`collect_api.py:135-148`, `collect_archive.py:108-118`, `collect_trumpstruth.py:92-113`); nothing is logged | until `anomalies.jsonl` exists: "disagreements are detected by the merge and currently discarded (B-014)"; after: "recorded in `data/anomalies.jsonl`" |
| C3 | `README.md:83-84` | "parser yield below minimum" is a `check_data` hard failure | it is a `ParseError` in `collect_trumpstruth.py:184-187`, a collector failure, exit 1 with checks ok | move it to the collector-failure sentence |
| C4 | `README.md:35` | `--backfill` = "CNN + full trumpstruth crawl" | `--backfill` only changes the trumpstruth leg (`collect.py:86`); cnn still obeys the 2 h skip unless `--force-cnn` | use the two-command recipe from OPERATIONS section 5 |
| C5 | `README.md:35`; `docs/OPERATIONS.md:104` | backfill "~30 min" / "about 15 minutes" | measured 747 s (12.5 min, 477 requests); removed-phase-only rerun 159 s (105 requests) | state both measured figures |
| C6 | `README.md:9` | cloud line omits `build_db` and exports | the cloud run rebuilds the sqlite and writes `posts.csv` and `metrics.json` (`collect.py:115-116,180-198`) | add them to the diagram |
| C7 | `README.md:41`; `docs/SPEC.md:15`; `pytest.ini` | "add `-m live` to also hit the real sources" (README, pytest.ini); "tests marked live are skipped by default" (SPEC) | no test carries `@pytest.mark.live`; the marker selects nothing | remove until canaries exist (`06-simulation-and-verification.md` section 3) |
| C8 | `README.md:84-85`; `docs/SPEC.md:285-286`; `docs/OPERATIONS.md:74` (which already qualifies it with "only when passed in") | present + deleted vs trumpstruth total is a running soft check | `run_checks(trumpstruth_totals=...)` has no caller (`collect.py:100-102`); the check is inert | mark inert and cite D-009 |
| C9 | `docs/SPEC.md:314-318` | fetch-depth 1; plain `python -m scripts.collect`; retry once; no push trigger; no timeout | fetch-depth 50; `--summary-file`; three attempts with `sleep 15`; `push: paths: collect.yml`; `timeout-minutes: 25` | rewrite section 12 from the workflow (or generate it) |
| C10 | `docs/SPEC.md:319` | test.yml "on push and pull_request" | plus `paths-ignore: data/**, output/**` | add |
| C11 | `docs/SPEC.md:273` | collect flags list | omits `--output-dir` and `--no-export` (`collect.py:243,245`), both used by OPERATIONS | add |
| C12 | `docs/SPEC.md:97-100` | store API list | omits `load_engagement` and `filter_engagement` (`store.py:162,194`) | add |
| C13 | `docs/SPEC.md:212` | `merge_partial` signature | omits the `logged_deletions` keyword that rule 8 and `merge.py:373` rely on | add |
| C14 | `docs/SPEC.md:223-224` (rule 4) | "if two sources differ by more than 2 s, anomaly" | only when the *lower-ranked* source differs (`merge.py:221-225`); a higher-ranked or same-source value replaces silently at any distance; same for rules 3, 5, 6 | state the asymmetry; the vision records winning overwrites too (`04-ledgers-and-provenance.md`) |
| C15 | `docs/SPEC.md` section 7 | (nothing) | a field with no `field_sources` entry is treated as `cnn`, the lowest rank (`merge.py:190,212,240,271`) | document the default |
| C16 | `docs/SPEC.md:269` | api merges "with `last_verified_live_at = observed_at`" as a partial field | no collector sets it on a partial; `merge.py:308` reads a dead input; the value is set inside `_apply_live_sighting` | correct the wording; remove the dead read |
| C17 | `docs/SPEC.md:62`; `merge.py:319-321` | `deleted_source` = `api404` | the partial key is `api_404` (underscore); the stored value is `api404` | state both spellings in the schema description (done in `schemas/post-record.schema.json`) |
| C18 | `docs/SPEC.md:258`; `collect_trumpstruth.py:11-12` | SPEC: persisted "after each page"; the docstring: "after every id fetched" | state is saved per id but `max_trumpstruth_id` is assigned only after both loops (`collect_trumpstruth.py:244`); a crash mid-walk re-fetches the same ids next run (bounded by the 200 cap) | document the actual behavior, then fix the code (B-015) |
| C19 | `docs/SPEC.md:298` | indexes list | omits `ix_engagement_ts_id_observed_at` (`build_db.py:103`) | add |
| C20 | `docs/SPEC.md:112-113` | FakeClock | omits `advance(seconds)` (`common.py:168`) | add |
| C21 | `docs/SPEC.md:308` | weekly writes "one csv per table" | 8 CSVs; `overnight_share`, `longest_silence`, `edits` get none | say which |
| C22 | `docs/OPERATIONS.md:20` | hard checks "stop the run" | `write_exports` still runs after failed checks (`collect.py:115-116`); on the desktop the sqlite, csv, and metrics are rebuilt from bad data | say "block the commit"; the vision skips exports on hard failure |
| C23 | `docs/OPERATIONS.md:85-86` | after an `HttpError` "the next run resumes from state" | in the cloud, exit 1 skips the commit step, so state and the other legs' results never reach `main`; only desktop runs resume | say so; the vision commits successful legs even when one leg fails (D-014) |
| C24 | `docs/OPERATIONS.md:104` | validate against `data/raw/truth_archive.json` | nothing writes `data/raw/` (`Context.raw_dir` unused); the file must be downloaded by hand | say so until raw capture exists |
| C25 | `docs/OPERATIONS.md:122-126` vs `TODO.md:3` | TODO claims to be the list of unscheduled work | the two open decisions live only in OPERATIONS section 7 | migrate both to `knowledge/` (`07-knowledge.md` section 3) |
| C26 | `MISTAKES.md:41` vs `:47` | `statuses_count` 36,549 and 36,554 for the same date | `state.json` says 36,554 | keep one value |
| C27 | `TODO.md:47`; `docs/OPERATIONS.md:73` | drift "~340" | 350 today | say "about 350" and point at `STATUS.md` for the live number |
| C28 | `scripts/parsers.py:11,13-14,341-342,373-380` | "SPEC MISMATCH" comments and an "implementation report" | SPEC 6.2 already says `status__reblog-indicator` and describes the minute-precision removed text; no implementation report exists | delete the stale comments |
| C29 | `docs/dead-code-review.md:7,49,9-11,128-130` | 305 tests; a Windows scratchpad path; SPEC "calls out" library surface; api state keys write-only | 307 tests; path does not exist; SPEC says no such thing; `collect_api.py:88-91` reads `reachable` and `last_probe_at` since commit `7e447c9` | retire the file into backlog items (`07-knowledge.md` section 3) |
| C30 | `tests/fixtures/README.md` | lists 20 of 24 fixtures | four used fixtures are missing (41514, 41515, `search_removed_2026-08-28_to_09-11`, `search_removed_page2_empty`) | add rows; then replace with the generated manifest |
| C31 | `requirements.txt:3`; `docs/SPEC.md:16` | SPEC calls pandas "analysis only"; requirements pins it without comment | imported by nothing; installed on every cloud run | move to `requirements-dev.txt` or remove (D-013) |
| C32 | `.gitignore` | (nothing) | `data/.lock` is not ignored; a crashed desktop run leaves a file that `git add data` would commit | add `data/.lock` |
| C34 | `docs/OPERATIONS.md:24-25` | the run records are "the first thing to read when something looks off" | a failed run's record never reaches `main` (the commit step is skipped on a non-zero exit); the ledger records only successes | say so; the vision commits an incident record on failure (B-030) |
| C35 | `docs/SPEC.md:259-260` ("removed search for the last `removed_days` days"); `docs/OPERATIONS.md:17` | the search is described as a window over removals | the site filters by the post's creation date, so the 14-day window finds only removals of posts younger than 14 days; 35 of 98 known deletions were older than that at removal | state the semantics; change the default per D-017 (B-029) |
| C36 | `scripts/build_db.py:136-140`; `output/reports/2026-W37.md:60-63` | `lifetime_min` reads as a lifetime | it is an upper bound; every deletion's lower bound is its creation time; the report prints it next to an identical `deletion_window_min` | rename to `lifetime_hi_min`, add `lifetime_lo_min`, label the bound in the report (B-036) |
| C37 | `docs/SPEC.md:300-303`; `output/metrics.json` | `posts_by_day` reports a `reply` column | `kind = 'reply'` can only come from the api leg, which has never run in the cloud; the column is a structural zero, not a count | the caveat `reply_unobservable_window` on the metric (B-111) |
| C33 | `docs/OPERATIONS.md:99-100`; `TODO.md:44` | "17 hours" for the id walk | with `MAX_IDS_PER_RUN=200` it is about 209 cron runs (about 17.7 h of collector time at 305 s per capped run, days of calendar time); the cap is a constant, not a flag | say so; expose the cap (`09-economy.md` section 3) |

Code findings from the same audit that are not doc errors but belong in the backlog (they are listed in
`10-migration-plan.md`): exit code 1 is overloaded (lock held versus collector raised); a typo in
`--sources` runs nothing and then fails `missing_run_row`; `check_data` standalone runs a smaller check set
than the cloud run (no `run_id`, no `api_statuses_count`, no `now`); api and cnn legs append engagement
rows and deletion events before `save_posts`, so a crash between the writes leaves orphan rows (the
trumpstruth leg orders its writes correctly); append-only files have no torn-last-line recovery;
`content_text` provenance can lag `content_html` provenance (20 vs 17 records with `api`); empty lists from
a higher-ranked source never clear `mentions` or `tags`; the listing is requested with `removed=include`,
which the site ignores.

## 2. Restructurings: what each document becomes

| Document | Becomes | Keeps | Loses (moved to) |
|---|---|---|---|
| `README.md` | a 40-line front page for humans arriving from GitHub: one paragraph, the sources table as a generated block, "how to use the data" (three commands), and links to `AGENTS.md`, `STATUS.md`, the dossiers | the project statement; setup | Data conventions (the SPEC section 2 block and the dossiers), Integrity (the OPERATIONS section 4 blocks), Known issues (`knowledge/backlog.json`), Layout (`AGENTS.md`) |
| `docs/SPEC.md` | the module contract for implementers; the prose rules stay hand-written and corrected; the fact lists become generated blocks | the prose rules that cannot be generated (parsers, merge rules, collectors) | nothing leaves; section 1's source and precedence bullets, section 2's table, section 3's formats and state keys, section 9's check list, section 11's metric list, and a new module map in section 0 are rewritten in place by `ts dictionary --write`; section 12 is dropped in favor of the workflow files themselves |
| `docs/OPERATIONS.md` | the playbook, rewritten as verbs: section 1 unchanged in content; section 2 a generated sources block plus one dossier link per source; section 3 the generated state key block and the ownership table from `08-roles-and-coordination.md`; section 4 generated check blocks; section 5 rewritten so every recipe is one `ts` command with `--dry-run`, with the generated verb block; sections 6 and 7 moved to `knowledge/decisions/` | the run order; the red-run classification (now `ts doctor`'s diagnoses, documented) | hand-edit recipes |
| `TODO.md` | two lines pointing at `knowledge/backlog.json` | nothing | everything (B-001 to B-010) |
| `MISTAKES.md` | two lines pointing at `knowledge/lessons/` and the dossiers | nothing | build errors (L-001 to L-004); source-side anomalies (dossier quirk lines) |
| `docs/dead-code-review.md` | deleted | nothing | actionable rows become B-011 to B-013; the rest are recorded as dropped in the backlog file |
| `tests/fixtures/README.md` | its table becomes a generated block from `tests/fixtures/manifest.json` | the capture-date discipline | the hand-maintained table |
| `AGENTS.md` (new) | the door; `templates/AGENTS.md` | | |
| `STATUS.md` (new, generated) | the situation | | |
| `knowledge/` (new) | dossiers, decisions, lessons, backlog | | |
| `docs/agentic-vision/` | this directory, moved under `docs/` once phase 0 lands; `10-migration-plan.md` is the live plan until the backlog absorbs it | | |

## 3. Workflow deltas

`collect.yml`:
- `run: python -m scripts.ts collect --json > "$RUNNER_TEMP/collect.json"`; the commit step reads
  `result.summary` for the first line and `result.status_lines` for the body (`02-situation.md` section 4).
- `git add data output STATUS.md`.
- A step after Collect, `if: failure() || steps.collect.outputs.health != 'green'`, uploads `data/raw/<run_id>`
  as an artifact named by the run id.
- The api leg is not run in the cloud (profile rule), so the 6-hour re-probe and its 36 s disappear.
- Commit successful legs even when one leg failed (D-014): `ts collect` exits 1 but writes; the commit
  step runs when the checks passed (`result.checks.ok`), and the run record carries the failed leg. Today a
  single failed leg discards the whole run's work in the cloud.
- An `if: always()` step after the commit step adds only `data/incidents/` and `STATUS.md` and pushes, so a
  failed run leaves its incident record and a red `STATUS.md` on `main` (B-030).
- `git rebase --abort || true` between push attempts, and a `push_race` incident on the third failure
  (B-033).
- `.gitattributes`: `data/deletions.jsonl merge=union`, `data/runs/*.jsonl merge=union`,
  `data/engagement/*.csv merge=union`, `data/anomalies.jsonl merge=union`, `data/interventions.jsonl
  merge=union` (order does not matter; `check_data` enforces uniqueness).

`test.yml`:
- `run: python -m scripts.ts verify --ci` (coherence tests, unit tests, smoke replay, 3.9 syntax check).

New `data-guard.yml` (on any pull request or non-`main` push touching `data/`): `check_data` must be green,
an intervention record must accompany the change, and no forbidden file may be included (B-068); plus a
`CODEOWNERS` line routing `data/` to the maintainer and branch protection on `main` (D-012). The bot's commit
step becomes `python -m scripts.ts commit --run "$RUN_ID"` (B-067).

New `repair.yml` (`workflow_dispatch`, inputs `plan`, `args`, `reason`, under `concurrency: collect`): runs
`ts repair <plan> <args> --apply --reason "<reason>"` in the cloud, commits the intervention. New
`canary.yml` (weekly): `ts doctor --live --canaries`, opens a backlog item on structural drift.
