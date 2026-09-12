# 08. Roles and coordination: three profiles, one branch, no surprises

Serves Laws 11 and 12. Several actors share one repository and one `main` branch, with different
capabilities. The vision makes the capabilities explicit and the hand-offs mechanical.

## 1. Actors and profiles

| Actor | Profile | Can reach | Writes | Commits to `main` |
|---|---|---|---|---|
| GitHub Actions bot (`truth-collector`) | `cloud` | trumpstruth, cnn; **not** the API (Cloudflare 403 since the first cloud run) | `data/`, `output/`, `STATUS.md` | yes, every run with changes, under the `collect` concurrency group |
| Maintainer on the Windows desktop (Python 3.9) | `desktop` | everything, including the API at about 6 requests per minute | `data/` (api legs, repairs), code, docs, knowledge | yes, via `ts collect --commit` and `ts repair --apply --commit`, or through a pull request |
| A remote Claude session in a sandbox | `sandbox` | usually nothing; `--live` may reach trumpstruth and cnn depending on the environment's network policy | code, docs, knowledge, schemas, tests, bundles; scratch data roots only | never directly; pushes a branch and opens a pull request |
| A future desktop scheduled poller (B-004) | `desktop` | the API | `engagement/`, `last_verified_live_at` | yes, same verb as the maintainer |

Profile detection and the guard rails per profile are in `03-verbs.md` section 3.

## 2. Ownership: who may change what

| Path | Owner | Others |
|---|---|---|
| `data/posts`, `data/deletions.jsonl`, `data/engagement`, `data/runs`, `data/anomalies.jsonl` | the bot, by running `collect` | `desktop` by running `collect` or an applied repair; `sandbox` never on `main` |
| `data/state.json` | the bot | `desktop` through `ts repair reset-source` / `rewalk-ids` only |
| `data/interventions.jsonl` | whoever applies a repair | appended, never edited |
| `output/`, `STATUS.md` | generated: `checks.json` by every run, `posts.csv` and `metrics.json` by the export step, `reports/` by `weekly.py`, `STATUS.md` (once B-103 lands) by `situation.py` | never edited by hand |
| `scripts/`, `tests/`, `schemas/`, `docs/`, `knowledge/`, `AGENTS.md` | people and agents, through pull requests | the bot never touches them |

The bot's commit step stays `git add data output STATUS.md`, followed by an `if: always()` step that adds only
`data/incidents/` and `STATUS.md` so a failed run still leaves its trace. A coherence test in `ts verify` fails if a
pull request touches `data/` without an intervention record, which is how a sandbox agent's accidental data
write is caught before merge.

## 3. Hazards and their mechanisms

| Hazard | Today | Mechanism in the vision |
|---|---|---|
| A desktop run and a cloud run both append to `deletions.jsonl`, `runs/*.jsonl`, or `engagement/*.csv`; the bot's `git pull --rebase` conflicts | the retry loop has no `git rebase --abort` between attempts, so all three fail identically; the run's work is lost with no trace | the existing `.gitattributes` (today: `text=auto eol=lf` and binary markers) gains `merge=union` for the append-only ledgers (their order does not matter; `check_data` enforces uniqueness); the workflow aborts a failed rebase before retrying and writes a `push_race` incident on the third failure (B-033) |
| A run fails; nothing lands on `main` | the failure run record and `checks.json` die with the runner | an `if: always()` step commits `data/incidents/<run_id>.json` and `STATUS.md` (B-030; `04-ledgers-and-provenance.md` section 3b) |
| A repair lands while the bot is committing; the bot's rebase conflicts on a rewritten month file | the bot retries three times, then fails; the next run redoes the work | repairs that touch `data/` run **where the bot runs**: `repair.yml` (`workflow_dispatch` with inputs `plan`, `args`, `reason`) under the same `concurrency: collect` group, so they are serialized with collection. Desktop repairs that need the API commit with `--commit`, which does `pull --rebase` immediately before `push` and retries like the bot |
| Desktop api legs write engagement rows that the cloud never sees until pushed | the desktop must remember to push | `ts collect --sources api --commit` pulls, runs, commits, pushes in one verb; without `--commit` it warns that the rows are local only and `STATUS.md` shows `desktop-unpushed: N rows` (from `git status`) |
| An agent runs `collect` against real data in a sandbox | nothing prevents it | `sandbox` refuses network without `--live` and refuses writing `data/` without a scratch root (`ts scratch` prints the flag) |
| A force push over the bot | nothing prevents it | `AGENTS.md` never-do list; branch protection on `main` (a maintainer setting, recommended in D-012) |
| A hand edit to `state.json` nobody knows about | OPERATIONS section 3 says "yes, carefully" | every state change is a repair plan with an intervention record; `ts repair manual` for the exceptions |
| Deleting `data/posts` for a redo | OPERATIONS section 5 says to delete files | `repair redo-history` moves them to `data/.trash/<intervention id>/` and refuses in `cloud` |
| A desktop repair takes longer than the cron gap; the bot rewrites `state.json` (`last_run_at`, `etag`, `last_probe_at`) every run and the repair's push conflicts | nothing holds the bot | `ts lease take` commits `data/lease.json`; the cloud collector exits 0 without writing while it exists; `STATUS.md` shows LEASED; `ts lease release` when done (B-052) |
| Two people apply the same repair | no lock beyond `data/.lock` (30 min) | the intervention record's `target` is checked against open interventions; a duplicate plan is refused with the id of the open one |
| The API becomes reachable from the cloud again, or stops being reachable from the desktop | the api leg re-probes every 6 h from the cloud and burns 4 requests each time | `cloud` never probes; `desktop` probes on every run (it is cheap there); a monthly `canary.yml` probe from the cloud records whether the block persists, as a dossier line |

## 3b. Partition what two actors write

The routine desktop-and-cloud overlap cannot conflict if every shared file is either append-only and
union-mergeable, or owned by one actor:

| File | Rule | Mechanism |
|---|---|---|
| `deletions.jsonl`, `runs/*.jsonl`, `engagement/*.csv`, `anomalies.jsonl`, `interventions.jsonl`, `observations/**` | append-only, order irrelevant; union only where a hard check catches a duplicate line (`duplicate_deletion_event`, `engagement_too_close`, the new `duplicate_run_row`; anomalies and observations are idempotent by construction) | `.gitattributes merge=union` (B-033); `posts/*.jsonl` and the state files keep the default driver so a real double collection conflicts loudly instead of merging silently |
| `incidents/*.json` | one writer per file | `-merge` |
| `posts/*.jsonl` | rewritten only by `collect` in `cloud` and by applied repairs | the desktop never rewrites them: its api leg appends **observations** (`data/observations/api/YYYY-MM.jsonl`, one idempotent line per sighting with the partial and the engagement counts) and the next `collect` anywhere folds unapplied observations through `merge_partial`; folding twice is a no-op (B-070, D-019) |
| `state.json` | one file, three actors' memory, rewritten every run | split per source, `data/state/<source>.json` (B-071, D-018) |
| `lease.json` | one holder at a time | `ts lease` (B-069) |
| `output/`, `STATUS.md` | derived | regenerated, never merged |

The observation ledger also fixes a loss the audit found: the two desktop api legs on 2026-09-11 updated 20
records each but wrote no engagement rows, because the throttle compared against the CNN rows written minutes
earlier (B-072, L-009). With per-(post, source) throttling and observations folded by the cloud, the
desktop's unique contribution reaches `main` without touching a file the bot rewrites.

## 4. Coordination protocol (the hand-offs)

1. **Code and knowledge changes** go through a branch and a pull request. `ts verify` must be green. The
   pull request description names the lesson, decision, or backlog ids it touches. **Data changes on a
   branch** are checked by `data-guard.yml` (B-068): `check_data` green, an intervention record present, no
   forbidden file; `CODEOWNERS` routes `data/` to the maintainer; branch protection (D-012) makes `ts commit`
   the only path to `main`.
2. **Data changes** are either a bot run or an applied repair. A repair is proposed as a plan file in a pull
   request (`output/plans/<id>.json` is committed only for review, then removed), applied by `repair.yml`
   or on the desktop, and its intervention record is the receipt.
3. **The API backfill** (B-003, about 6 hours at 5 requests per minute, resumable via `state.json`) is a
   desktop repair plan (`repair api-backfill`) that commits in chunks (`--commit-every 500 records`) so a
   crash loses at most a few minutes and the bot's runs interleave cleanly.
4. **Decisions** are made by editing a `D-*` record's status; the pull request that does so is the record of
   who decided.
5. **Handing off between sessions** needs no message: the next session reads `STATUS.md`, sees open
   interventions and P0 items, and continues.

## 5. Never do (copied into `AGENTS.md`)

- Never edit `data/posts/*.jsonl`, `deletions.jsonl`, `engagement/*.csv`, `runs/*.jsonl`, or
  `anomalies.jsonl` by hand or with an ad-hoc script. Use a repair plan.
- Never delete a ledger or a ledger line by hand. `redo-history` moves; the repair verb retracts a line into the
  intervention record.
- Never force-push `main`. Never rebase the bot's commits.
- Never run `collect` with the real `data/` root in a sandbox.
- Never commit `data/raw/`, `data/truths.sqlite`, or a scratch root.
- Never change `RECORD_FIELDS` (which `check_data` requires every record to contain), a check name, or a
  verb name without updating the schema or registry and running `ts verify` (the coherence tests will stop
  you, but do it first).
- Never state a fact about a source in a chat or a commit message only. It goes in the dossier.
- Never skip, disable, or quarantine a test to get green.
