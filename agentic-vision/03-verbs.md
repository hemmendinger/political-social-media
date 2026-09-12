# 03. Verbs: the control surface

One dispatcher, a fixed vocabulary, one output envelope, one set of guard rails. Serves Laws 3, 5, 11, 14.

## 1. The dispatcher

```
python -m scripts.ts <verb> [args] [--json] [--dry-run] [--profile cloud|desktop|sandbox] [--data-root PATH]
```

`scripts/ts.py` is thin: it parses the verb, detects the profile, applies the guard rails, calls the existing
module function (`collect.run_all`, `check_data.run_checks`, `build_db.build`, ...), wraps the result in the
envelope, prints the cost line, and prints the `next` hint. The existing `python -m scripts.<x>` entry points
keep working during migration and are removed in the last phase (see `10-migration-plan.md`).

Every verb is registered with a descriptor:

```python
Verb(
    name="check",
    purpose="Run the integrity checks against data/ and write output/checks.json",
    reads=["data/"], writes=["output/checks.json"], network=False,
    cost="~2 s, 0 requests", supports_dry_run=False,
    next=["ts status", "ts doctor"],
)
```

`ts help` is generated from the registry, so the verb list in this document and the dispatcher cannot
disagree (a coherence test compares them, see `05-invariants-and-schema.md`).

## 2. The envelope (every verb, `--json`)

```json
{
  "verb": "check",
  "ok": true,
  "profile": "sandbox",
  "run_id": null,
  "started_at": "2026-09-12T08:00:00Z",
  "finished_at": "2026-09-12T08:00:02Z",
  "cost": {"requests": 0, "seconds": 1.9, "files_written": ["output/checks.json"]},
  "result": {"...": "verb-specific, schema in schemas/verb-envelope.schema.json"},
  "warnings": ["stats.cnn_ambiguous_handles.count=1172 (B-001)"],
  "truncated": [],
  "next": ["ts status"]
}
```

Rules:
- `ok` means the verb completed and its own success criterion held (for `check`: no hard failures).
- `cost` is always present and always measured, never estimated.
- `truncated` lists every cap applied to the output (sample sizes, id caps), by name and limit, so silence
  never reads as completeness.
- `next` is one to three verbs that make sense after this one given its result.
- Without `--json`, the same content prints as a compact human block ending with the same cost line.
- Exit codes are the current ones (0 ok, 1 collector exception, 2 hard check) plus 3 = refused by a guard
  rail, 4 = plan produced but not applied (dry-run).

## 3. Profiles and guard rails (Law 11)

A profile is where the verb runs and what it may do. Detection happens before argument parsing: `TS_PROFILE`
if set; else `cloud` when `GITHUB_ACTIONS` is set; else `desktop` when the marker file `data/.profile-desktop`
exists (the maintainer creates it once); else `sandbox`. The detected profile is printed on every invocation.
Capabilities are declared once, in a tracked manifest `profiles.json` at the repo root (hosts, `api`,
`write_data`, `commit`, `repair`, `data_root` per profile; B-066); the table below is its rendering, and the
dispatcher enforces it, so no verb carries its own profile branches. In `sandbox` the default data root is a
scratch copy under `$TMPDIR/ts-scratch/<HEAD sha>/data` (made by `ts scratch` on first use, about 60 MB, under
2 s) and the transport is an empty `FakeTransport`, so a verb that would fetch fails by naming the exact URL
it wanted and the flag that would allow it; `--data-root ./data` in `sandbox` is refused.

| Capability | cloud | desktop | sandbox |
|---|---|---|---|
| Reach trumpstruth and cnn | yes | yes | only with `--live` |
| Reach the Truth Social API | no (Cloudflare 403; `api` leg is skipped with a note, not probed every run) | yes | no (assumed; `--live` will probe once and record the result) |
| Write `data/` | yes (the bot) | yes | only with `--data-root` outside the repo, or with `--apply` on a repair |
| Commit and push `data/` | yes, only the bot's own commit step | with `--commit` | never (writes go to a branch, never to `main`) |
| Run repairs | plan only | plan and apply | plan only, unless `--data-root` is a scratch copy |
| Run the API backfill | no | yes | no |

Guard rails are refusals with a clear message and exit 3, never silent downgrades:

- A verb that would use the network in `sandbox` without `--live` refuses and says which URLs it would fetch.
- A verb that would write `data/` in `sandbox` without a scratch `--data-root` refuses and offers
  `ts scratch` (which copies `data/` to a temp directory and prints the flag to use).
- `ts repair` never applies without `--apply`, and `--apply` requires a `--reason` that lands in the
  intervention record.
- `ts collect` in `cloud` never runs the `api` leg (the leg is recorded as `skipped: profile=cloud` so the
  run record is honest and the six-hour re-probe cost disappears).
- No verb ever deletes a ledger file. `repair redo-history` moves them to `data/.trash/<intervention id>/`
  and the intervention record says so.

## 4. The vocabulary

Twenty-one verbs. Grouped by the layer they operate on (see `01-system-model.md`). Each entry: purpose,
reads, writes, network, cost, and the shape of `result`.

### Situation (layer 7)

**`ts status [--refresh]`**
Print `STATUS.md`. With `--refresh`, rebuild `output/status.json` and `STATUS.md` from the current data first
(runs `check` internally). Includes open incidents, the schedule delivery ratio, and how far this checkout
is behind the bot's last run (`checkout` block), so a sandbox agent knows whether it is looking at stale data. Reads `data/`, `output/checks.json`, `knowledge/backlog.json`,
`knowledge/decisions/`. Writes nothing unless `--refresh`. No network. Under 3 s.
`result` = the `status.json` object (schema `schemas/status.schema.json`).

**`ts diff [--since RUN_ID|SHA|ISO] [--roots A B]`**
What changed: new records, changed records (by field, with the source that changed them), deletions found,
anomalies, interventions, and check transitions (a check that started or stopped firing). Default: since the
previous run. With `--roots`, the same report between two data roots (a scratch rehearsal against the real
data). Reads ledgers and `git`. No network. Under 5 s.
`result` = `{since, until, records: {new: [...], changed: [{ts_id, fields: {...}}]}, deletions: [...],
anomalies: {by_kind: {...}}, interventions: [...], checks: {started: [...], stopped: [...]}}`.

### Diagnosis (layers 3, 4, 2)

**`ts doctor [--run RUN_ID]`**
Classify the situation into a cause and a next move. Looks at the last run's legs (`ok`, `errors`, `notes`),
firing checks with their descriptors, the last 24 h of anomalies, freshness per source, the profile, and, if
present, `data/raw/<run_id>/`. Emits one of a fixed set of diagnoses, each with evidence and a next verb:
`markup_drift` (ParseError, yield below min, or a fingerprint change; names the URL and the fixture to
recapture), `challenge_page` (an HTTP 200 whose body has no container: a Cloudflare challenge or a maintenance
page, told apart from drift by the body head in the error envelope), `source_down` (HttpError /
TransportError; says whether it persisted across runs), `hard_check` (names the check, its playbook),
`push_race` (the commit step's rebase failed), `stale_lock`, `budget_exhausted` (a leg hit its request budget),
`removal_semantics` (removed-search hits whose pages are not removed), `api_blocked_expected`,
`schedule_dropped` (green runs but `runs_actual_24h` far below `runs_expected_24h`), `quiet_account` (stale
newest post but sources healthy and on schedule), `silent_undercollection` (green runs, zero new posts, but
trumpstruth's listing shows newer ids than `max_trumpstruth_id`; needs `--live`), `healthy`. It reads
`data/incidents/` first (`04-ledgers-and-provenance.md` section 3), so a failed cloud run is diagnosable from
the repository alone.
No network unless `--live`. Under 5 s.
`result` = `{diagnosis, confidence, evidence: [...], next: [...], playbook: "..."}`.

**`ts explain <ts_id> [--raw]`**
The evidence trail for one record: the record with every field annotated by its `field_sources` entry; every
run record whose leg touched it (via `updated_run_id` history in git, cheap: `git log -S<ts_id>` on the month
file); every deletion event, engagement snapshot, anomaly, and intervention for it; the trumpstruth and
truthsocial URLs; with `--raw`, the latest raw capture and `raw_api`. Also prints the uncertainty flags from
`v_confidence` in words. No network. Under 3 s.
`result` = `{record, provenance: {field: {source, set_at_run}}, observations: [...], events: {deletions, engagement, anomalies, interventions}, confidence: {...}, urls: {...}}`.

**`ts check [--only NAME]`**
`check_data.run_checks` with structured output: each firing check as an object `{name, severity, value,
threshold, ids_sample, descriptor}`. Writes `output/checks.json`. No network. About 2 s.

### Collection (layers 0 to 4)

**`ts collect [--sources trumpstruth,cnn,api] [--backfill] [--force-cnn] [--plan] [--dry-run] [--live] [--capture] [--removed-days N] [--max-ids N] [--budget host=N]`**
The existing orchestrator. Adds: `--plan` prints, with zero requests, which legs would run or skip and why
(from the policy table and the state), when each is next due, and an estimated cost range (B-058); `--dry-run` runs every leg against the network (subject to profile) but
writes nothing under `data/`; instead it writes the would-be changes to `output/plans/collect-<run_id>.json`
(records new and changed, events, anomalies) so an agent can inspect a collection before it lands.
`--capture` saves every response under `data/raw/<run_id>/` (on by default in `cloud`; the workflow uploads
the directory as an artifact when the run is red). Anomalies go to `data/anomalies.jsonl`. The collector
caps that are module constants today (`MAX_IDS_PER_RUN`, `removed_days`, `max_pages`, `max_verify`) become
flags with the same defaults (B-027); `--removed-days` defaults to the policy in D-017 and the window
searched is recorded as `sweep` on the run record. Each leg declares a request budget per host; exhaustion is
recorded as a truncation, never reached as a job timeout (B-032). On any non-zero exit the verb writes
`data/incidents/<run_id>.json` before returning, so the failure is committed even when the data is not. Cost: printed
per leg from the run records (today: trumpstruth 3 to 7 requests and 5 to 15 s on a normal run; cnn 1 request
and about 6 s when not skipped; the backfill about 15 minutes).

**`ts lease take --reason "..." --until ISO [--intervention ID]` / `ts lease release`**
Commits `data/lease.json` (`{holder, profile, host, taken_at, expires_at, reason, intervention}`); while it
is unexpired the cloud collector exits 0 without writing (a `leased` run record, no incident) and `STATUS.md`
shows LEASED with the holder and expiry. The way to hold the bot during a long desktop repair or the API
backfill instead of racing it on `state.json` (B-069). Coordination state other actors must see lives in git
with an expiry; the local lock (JSON, pid liveness, gitignored) is only this machine's.

**`ts commit [--run RUN_ID] [--dry-run]`**
The single path by which data reaches `main` (B-067): refuses in `sandbox`; refuses when anything outside
`data/`, `output/`, `STATUS.md` is staged or a forbidden file (`.lock`, `raw/`, `*.sqlite`, a scratch path) is
included; runs `check`; commits data only with the structured message; `git pull --rebase` with `git rebase
--abort` between the three attempts; pushes; on the third failure writes a `push_race` incident and pushes
that alone. The workflow's commit step and `--commit` on `collect` and `repair` call it.

**`ts capture <url> --as tests/fixtures/<name> --source S --parser scripts.parsers:fn --proves "<one line>"`**
Fetch one page through the paced client, save it as a fixture, and append the manifest entry (`file, url,
captured_at, status, sha256, source, parser, proves, fingerprint`). Tests and bundles build their routes with
`FakeTransport.from_manifest(names)` instead of hand-typed route dicts. `--live` required in `sandbox`. One
request.

### Repair (layers 2 and 4, Law 12)

**`ts repair <plan> [...] [--apply --reason "..." [--commit]]`**
Every repair is a named plan with the same life cycle: plan (default) writes `output/plans/<intervention
id>.json` listing exactly which records and fields would change (before and after, differing fields only),
which ledger lines would be removed (copied verbatim as retractions) and added, which state keys would change,
the estimated cost, and the checks that will run afterwards, then exits 4; `--apply` performs it inside one
intervention record and runs `check` after; a failed check after apply reverts the working tree to the
pre-apply state and marks the intervention `reverted`; `--commit` makes the applied repair one commit that
touches only `data/` (`repair(<plan>): <reason> [<id>]`), pulls with rebase first, pushes with the bot's retry
loop, and stores the before and after shas in the record.

Two principles from the repair walkthrough shape every plan. The merge is monotone (`deleted_upper` only
narrows, `trumpstruth_removed_at` is set once, an event is emitted once per source), so it needs an explicit
inverse: `merge.forget_deletion(record)` and `merge.forget_source(record, source)` live beside the rules they
invert, and a repair is **forget, then re-observe**, never edit-in-place (B-050). And a single record is
re-observed by its own id with one request (`/statuses/<trumpstruth_id>`), never routed through the windowed
search or a whole-history phase. Values written by a repair carry the source `repair` at rank 0, so the next
genuine observation overrides them. Plans:

| Plan | Replaces (OPERATIONS section 5) | Touches |
|---|---|---|
| `regenerate-deletion --ts-id X [--all]` | the six manual steps | `forget_deletion`, one status-page request, re-merge with the `(X, trumpstruth)` pair removed from the logged set so a fresh event is produced; the old event line is retracted into the record |
| `rewalk-ids --from N [--to M] [--forget-source trumpstruth] [--now]` | lowering `max_trumpstruth_id` by hand | `state.json`; with `--forget-source` every affected record first loses its trumpstruth-sourced values (an empty value from the fixed parser could never clear them otherwise); `--now` walks immediately with `--max-ids`; cost printed as `(M - N + 1) * 1.5 s` |
| `reset-source --source S [--key K]` | deleting keys from `state.json` | `state.json` |
| `rewrite-records` | the one-liner through `scripts.store` | `posts/*.jsonl` canonical rewrite |
| `redo-history [--from-raw DIR...] [--live]` | deleting `data/posts` etc. by hand | extracts the carry-forward set (`first_seen_*`, `last_verified_live_at`, event `detected_at`), moves ledgers to `.trash`, rebuilds from raw captures (0 requests) or live, re-applies the carry-forward set (B-053) |
| `api-backfill [--commit-every 500] [--keep-raw]` | B-003, never had a code path | resumable walk of every API page from the desktop, verify pass for absent records, `raw_api` stripped by default, chunked commits so the bot interleaves |
| `undo <intervention id>` | git archaeology | reverts the intervention's commit and restores its retractions; refuses if a later intervention touched the same targets (B-052) |
| `resolve-handles` | backlog B-001 | `reblog_of_acct` and `content_text` on cnn-only reblogs; marks `field_sources` `cnn-guess` or the resolved source |
| `migrate [--to N]` | ad-hoc scripts after a schema change | rewrites every record to the code's schema version through `store.save_posts` (B-044) |
| `manual --note "..."` | any hand edit | records an intervention for something done outside the verbs (the escape hatch that keeps the ledger honest) |

### Views and analysis (layer 5)

**`ts build`** = `build_db.build`. Adds `v_confidence` and `v_coverage`. Under 10 s.
**`ts query --sql|--file [--format table|csv|markdown|json]`** = `query.py`. Adds `--json`.
**`ts report --week 2026-W37 | --start --end`** = `weekly.py`. Every table gains a `caveats` list.
**`ts ask <question> [--start --end] [--tz ET|UTC] [--param k=v] [--compare before|after DATE|trailing N] [--save]`**
A named, versioned analysis from the question registry (`05-invariants-and-schema.md` section 3.6). Returns
the answer envelope: answer, bounds or a three-valued count, `n`, the window in both zones with the seam
count, the coverage subset, computed caveats, method, and provenance (data commit, build time). `--save`
writes it under `output/answers/<question>-<args>.json` so a quoted figure is reproducible. `ts ask` with
no question lists the registry. Under 2 s after `build`.
**`ts dictionary [--write]`** prints (or rewrites in place) every generated block in the documents from the
schemas and registries (`05-invariants-and-schema.md` section 6): the record and media tables, sources and
precedence, state keys, the check tables, the verb and question lists, the fixtures table, the module map.

### Verification (Law 10, 16)

**`ts verify [--quick]`**
The fixed pre-push checklist, in order, stopping at the first failure: `pytest -q` (or the changed modules
with `--quick`), the coherence tests, `ts check` on the real data, `ts replay --smoke`, and a diff of
`STATUS.md` against a `--refresh`. Prints what it ran and what it cost. This is what an agent runs before
every push and what `test.yml` runs in CI.

**`ts replay <bundle> [--golden PATH] [--update-golden]`**
Run the whole pipeline (collect all sources, check, build) against a bundle of evidence with a `FakeClock`
and a `FakeTransport`, into a temporary data root, and diff the result against a golden data root. Bundles
live in `tests/bundles/<name>/` with a manifest mapping URLs to files and a fixed clock. `--smoke` uses the
smallest bundle. No network. Under 20 s.

### Knowledge (layer 8)

**`ts note lesson|decision|backlog|quirk|audit [--from-template] [--from-incident RUN_ID] [--from-canary]`**
Scaffold a knowledge entry with the next free id and today's date from `templates/`, and open it in `$EDITOR`
if any. `ts note backlog --close B-001 --evidence "stats.cnn_ambiguous_handles.count=0"` closes an item with
its acceptance evidence; an item with an `acceptance_expr` closes itself when `ts status` observes it true.
`ts note quirk --source trumpstruth` appends the next `Q-tt-nn` line to the dossier. `ts note trailers`
prints the knowledge trailers a commit should carry for the current diff (B-063). Pure file operations.

**`ts scaffold source|field|check|metric <name> [...]`**
The extension checklist that writes itself (B-048). `scaffold source factbase --hosts factba.se=2.0
--rank below:cnn --created-at-rank below:trumpstruth --deletion-signal none --order after:cnn` writes the
registry entry, the collector and parser stubs, the test stub, the fixture slot in the manifest, the dossier
stub, and regenerates the generated blocks; `scaffold field video_transcript --merge scalar --sources
trumpstruth` also writes the migration. Every stub carries a `# scaffold: fill me` marker that `ts verify`
refuses, so a half-finished extension cannot be pushed. `--dry-run` lists the files.

**`ts help [verb]`**
Generated from the registry: purpose, flags, reads, writes, network, cost, next.

**`ts scratch [--ids <ts_id,...> | --months 2026-09]`**
Copy `data/` to a temporary directory outside the repository and print the `--data-root` flag to use with
it; with `--ids` or `--months`, copy only the month files, filtered ledger lines, and state the rehearsal
touches (B-077). The sandbox profile uses it automatically. Pure file copy, about 60 MB in full, under 2 s.

## 5. The first sixty seconds (Law 3)

```
cat AGENTS.md            # the door: what this is, the laws in one screen, the verbs, what never to do
python -m scripts.ts status     # the situation: health, freshness, drift, firing checks, pending, open decisions
python -m scripts.ts doctor     # only if status is not green: the cause and the next verb
```

Three commands, about 1,500 tokens read, and the agent knows what to do. Everything else is reached by
following a link from one of these three outputs.

## 6. What this replaces

| Today | Vision |
|---|---|
| `python -m scripts.collect --summary-file ...` | `ts collect --json` (the workflow reads `result.summary`) |
| `python -m scripts.check_data` | `ts check` |
| `python -m scripts.build_db` | `ts build` |
| `python -m scripts.query`, `weekly` | `ts query`, `ts report` |
| `python -m scripts.validate_backfill` | `ts replay` with the history bundle, or `ts check --only coverage` |
| six manual steps to regenerate a deletion | `ts repair regenerate-deletion --ts-id X --apply --reason "..."` |
| reading five files to know the state | `ts status` |
| reading the workflow console to diagnose | `ts doctor` (+ `data/raw/<run_id>` artifact) |
