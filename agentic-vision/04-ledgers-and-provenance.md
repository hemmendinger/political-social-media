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
plan path, before/after summaries (counts and check results), the undo (`git revert <sha>` plus any state key
to restore), and a status that moves `planned -> applied -> verified` (or `reverted`).

Why a ledger and not just git: git says what changed; the ledger says why, whether it was finished, and how
to undo it. `STATUS.md` shows interventions that are applied but not verified, so nothing half-done is
forgotten across sessions.

## 4. Run records, extended

Today: `{run_id, source, started_at, finished_at, ok, requests, new_posts, updated_posts, deletions_found,
errors, notes}`. Vision adds, all optional so old lines still validate:

| Field | Meaning |
|---|---|
| `profile` | `cloud`, `desktop`, `sandbox` |
| `anomalies` | count appended to `anomalies.jsonl` by this leg |
| `skipped` | reason string when the leg did not run (`profile=cloud`, `ran 99 min ago`, `unreachable at last probe ...`); today these are mixed into `notes` |
| `error` | `{type, message, url, status}` when `ok=false`; the message is not truncated, the URL is the request that failed |
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
3. **Existence**: status, the interval with its width in minutes, the signal that set it, and the deletion
   events in order.
4. **Observations**: which legs touched this record. Cheap and exact without a new index: `git log
   --format=%H -S'"ts_id":"<id>"' -- data/posts/<month>.jsonl` gives every commit that changed the line, and
   each commit's message names the run. Engagement snapshots and anomalies come from the ledgers by `ts_id`.
5. **Interventions** that named this id.
6. **URLs**: `https://truthsocial.com/@realDonaldTrump/<ts_id>`, `https://www.trumpstruth.org/statuses/<trumpstruth_id>`,
   and the raw capture path if any.
7. **Related**: the reblog target or quote target record, one line each.

`--json` returns the same as one object. Under 3 s (one JSONL month file, three ledgers, one git log).

## 7. Provenance conventions kept from today

- `field_sources` remains the per-field truth of *which source* set a value. The vision does not add
  *which run* per field to the record (it would double the record size); the git history answers that
  question when asked, through `explain`.
- Precedence rules do not change. What changes is that a losing value is now stored (in the anomaly), so a
  future precedence change can be evaluated against real disagreements instead of guessed.
- `deleted_source` and `first_seen_*` stay write-once.
