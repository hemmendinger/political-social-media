# 04. Ledgers and provenance: nothing computed is lost, everything can be explained

Serves Laws 6, 8, 12. The system already has three ledgers (run records, deletion events, engagement
snapshots) and per-field provenance (`field_sources`). This document closes the two leaks and adds the verb
that reads it all back.

## 1. The leak that exists today

`scripts/merge.py` computes `MergeResult.anomalies` for every merge: `kind_disagreement:<ts_id>:api=...,cnn=...`,
`created_at_utc` disagreements beyond 2 s, `inverted_bounds:<ts_id>`, `resurrected:<ts_id>`. No collector reads
that list (`grep -n anomalies scripts/collect_*.py` returns nothing). The README states that disagreements
"are logged as anomalies in the run notes"; they are not. Every run silently discards the only evidence the
system has about where the sources contradict each other. That evidence is exactly what an agent needs to
tell a parser bug from a source quirk, and it is the raw material for source dossiers.

A second, smaller leak: a collector exception lands in a run record's `notes` truncated to 500 characters
(`collect.py::_failure_row`), with no URL, no response status, and no captured body. Diagnosis then requires
the GitHub Actions console, which a sandboxed agent often cannot read.

A third leak, found by walking a red run from a sandbox: **the ledger on `main` can only record success.**
When a collector raises or a hard check fails, `collect` exits non-zero, the workflow's Collect step fails,
and the Commit step (which has no `if: always()`) never runs. The failure run record that `_failure_row`
wrote, the failing `checks.json`, and any records the other legs collected die with the runner. OPERATIONS
section 1 calls the run records "the first thing to read when something looks off"; for a failed run there
is nothing to read. Section 3 below fixes this with incident records.

## 2. `data/anomalies.jsonl` (schema `schemas/anomaly-event.schema.json`)

Append-only, one line per anomaly, written by the collectors through `store.append_anomaly(root, event)`.
Each collector's merge loop becomes:

```python
result = merge_partial(existing, partial, source=SOURCE, observed_at=observed_at, run_id=ctx.run_id, ...)
for a in result.anomalies:
    store.append_anomaly(ctx.data_root, anomaly_event(a, ctx, source=SOURCE, ts_id=ts_id, url=url))
counts["anomalies"] += len(result.anomalies)
```

`anomaly_event` parses the legacy string into `kind`, `field`, `kept`, `dropped` and keeps the string in
`detail`, so old formats stay greppable and `merge.py` does not change. Two page-level kinds are added at the
collector level: `other_account` (today only a count in `notes`) and `yield_below_min` (today an exception
with no record of what the page contained).

Expected volume: a few per run at most (cnn disagreeing on `kind` for quotes and replies is the known
background). A soft check `anomaly_rate` fires when a single run produces more than 50, which is what a
parser regression or a source change looks like.

The run record gains an `anomalies` integer so the run line in `STATUS.md` can show it.

## 3. `data/interventions.jsonl` (schema `schemas/intervention-event.schema.json`)

Append-only, one line per deliberate non-routine change, written by `ts repair` (plan and apply) and by
`ts repair manual --note` for anything done outside the verbs. The record carries actor, profile, reason,
plan path, before/after summaries (counts, check results, and the git shas), every ledger line it removed
copied verbatim (`retractions`, so nothing is ever merely gone), the undo (`ts repair undo <id>` plus any
state key to restore), and a status that moves `planned -> applied -> verified` (or `reverted`). Ledgers are
append-only for automation; only the repair verb may remove a line, and it records the line it removed.

Why a ledger and not just git: git says what changed; the ledger says why, whether it was finished, and how
to undo it. `STATUS.md` shows interventions that are applied but not verified, so nothing half-done is
forgotten across sessions.

## 3a. `data/observations/api/YYYY-MM.jsonl`: the desktop's hand-off

The API-capable actor appends one line per sighting `{observed_at, source: "api", ts_id, kind: live | 404,
partial, engagement, run_id}` instead of rewriting month files; the next `collect` in any profile folds
unapplied observations (tracked by a cursor in the api state) through `merge_partial` and the per-(post,
source) engagement throttle, then records the fold on its run record. Idempotent, union-mergeable, and the
reason the desktop and the bot never touch the same file (B-070; `08-roles-and-coordination.md` section 3b).

## 3b. `data/incidents/<run_id>.json`: a failed run leaves a trace

Written by `ts collect` on every non-zero exit, before the process ends, and committed by a workflow step
that runs `if: always()` and adds only `data/incidents/` and `STATUS.md` (never `data/posts` when a hard
check failed, which keeps D-005). One small JSON file per failed run:

```json
{
  "run_id": "20260913T030714Z-1a2b", "profile": "cloud", "exit_code": 1,
  "commit_before": "9b7af34",
  "legs": [{"source": "trumpstruth", "ok": false, "phase": "listing", "requests": 1,
            "error": {"type": "ParseError", "message": "no <div class=\"statuses\"> container found",
                      "url": "https://www.trumpstruth.org/?sort=desc&per_page=100", "status": 200,
                      "sha256": "…", "head": "<!doctype html><title>Just a moment...</title>…"}},
           {"source": "cnn", "ok": true, "new": 2, "updated": 0}],
  "checks": {"run_id": "…", "checked_at": "…", "ok": true, "hard": [], "soft": []},
  "fingerprints": {"listing": {"missing": ["statuses", "status__external-link"], "count": 0}},
  "raw_artifact": "raw-20260913T030714Z-1a2b",
  "diagnosis": {"class": "challenge_page", "confidence": 0.9, "next": ["ts replay --from-raw …"]}
}
```

`ts doctor` reads the newest incident first; `STATUS.md` turns red while an incident is newer than the last
successful run; `ts replay --from-raw` rebuilds the run from the artifact it names. A lesson scaffolded with
`ts note lesson --from-incident <run_id>` is pre-filled from it. Incidents are kept forever (a few KB each).

## 4. Run records, extended

Today: `{run_id, source, started_at, finished_at, ok, requests, new_posts, updated_posts, deletions_found,
errors, notes}`. Vision adds, all optional so old lines still validate:

| Field | Meaning |
|---|---|
| `profile`, `host` | `cloud`, `desktop`, `sandbox`, and the machine, so cadence and contribution per actor can be read (`STATUS.md`: desktop last api leg N hours ago) |
| `anomalies` | count appended to `anomalies.jsonl` by this leg |
| `skipped` | reason string when the leg did not run (`profile=cloud`, `leased by human:… until …`, `ran 99 min ago`, `unreachable at last probe ...`); today these are mixed into `notes`. A refused or leased run still writes its records, so the absence of a run record has exactly one meaning: the schedule was dropped |
| `error` | `{type, message, url, status, sha256, head, phase}` when `ok=false`; the message is not truncated, the URL is the request that failed, `head` is the first 2 KB of the body, `phase` is where in the leg it happened (`listing`, `resolve:41699`, `removed_search:2026-08-30..2026-09-13:page2`, `removed_status:41644`, `cnn:download`, `api:probe`, `api:verify:<ts_id>`) |
| `sweep` | the removed-search window this leg covered, `{start_date, end_date, pages, results}`; `v_coverage` derives the observable-lifetime limit from it (B-029) |
| `budget` | `{host: {limit, used}}`; a truncation entry when a limit was hit (B-032) |
| `cost` | `{requests, requests_by_host, bytes_in, slept_s, wall_s, files_written, bytes_written}` measured, plus `estimate` from `--plan` when one was made (B-055, B-058) |
| `facts` | what the leg measured, as data: `{listing_max_id, imported_rows, statuses_count, followers_count, ...}`; `notes` stays free text for humans (B-065) |
| `raw_dir` | `data/raw/<run_id>/` when captures were kept |
| `truncated` | caps that applied (`ids_per_run=200`) |

## 5. Raw capture (layer 0)

`Context.raw_dir` exists and is unused. The vision wires it: when set, `Http.get` writes each response as
`<raw_dir>/<n>-<host>-<slug>.<ext>` plus one `index.jsonl` line `{n, url, status, headers, file, at}`. Policy:

- `cloud`: on for every run (about 1 MB per run; trumpstruth pages are 100 to 300 KB), kept in the runner's
  workspace only; uploaded as a workflow artifact when the job fails or when `ts doctor` reports anything but
  `healthy`; never committed.
- `desktop` and `sandbox`: on with `--capture`; `data/raw/` is gitignored already.
- Retention on disk: 7 days, pruned by `ts collect`.

A red run's artifact becomes a replay bundle with `ts replay --from-raw <dir>`
(`06-simulation-and-verification.md`), which is how an agent reproduces a production failure offline.

## 6. `ts explain <ts_id>`: the evidence trail

Output sections, in order:

1. **Record**, every field printed with its `field_sources` entry in the margin, derived fields marked
   `derived`, nulls collapsed into one line.
2. **Confidence flags** in words (from `v_confidence`, see `05-invariants-and-schema.md`): "present but never
   verified live by the API", "single source: cnn", "handle guessed from a glued cnn prefix".
3. **Existence**: status, the interval with its width in minutes, the basis and precision of each bound,
   the detection floor, the three-valued verdicts for a few thresholds (within 60 min: possible; within
   24 h: confirmed), the signal that set it, and the deletion events in order. For a reblog, a **Siblings**
   line: other records with the same target within six hours, with the cnn de-duplication note when the
   record is cnn-only.
4. **Observations**: which legs touched this record. Cheap and exact without a new index: `git log
   --format=%H -S'"ts_id":"<id>"' -- data/posts/<month>.jsonl` gives every commit that changed the line, and
   each commit's message names the run. Engagement snapshots and anomalies come from the ledgers by `ts_id`.
5. **Interventions** that named this id.
6. **URLs**: `https://truthsocial.com/@realDonaldTrump/<ts_id>`, `https://www.trumpstruth.org/statuses/<trumpstruth_id>`,
   and the raw capture path if any.
7. **Related**: the reblog target or quote target record, one line each.

`--json` returns the same as one object. Under 3 s (one JSONL month file, three ledgers, one git log).

## 6b. `checks.json` and the lock, tied to a run

`checks.json` v2 carries `run_id` and `checked_at` (B-042) so an incident can embed the exact result and a
stale file is detectable. `data/.lock` becomes a JSON record `{pid, run_id, started_at, host, profile}`
with a liveness check (a dead pid is stale regardless of age), is gitignored (B-028), and a held lock exits
3 with a `refused` block instead of the collector-failure exit 1 (B-016, B-033).

## 7. Provenance conventions kept from today

- `field_sources` remains the per-field truth of *which source* set a value. The vision does not add
  *which run* per field to the record (it would double the record size); the git history answers that
  question when asked, through `explain`.
- Precedence rules do not change. What changes is that a losing value is now stored (in the anomaly), so a
  future precedence change can be evaluated against real disagreements instead of guessed.
- `deleted_source` and `first_seen_*` stay write-once.
