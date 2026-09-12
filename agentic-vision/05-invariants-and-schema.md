# 05. Invariants and schema: one source of truth, generated everywhere else

Serves Laws 6, 7, 9, 16.

## 1. Schemas as the contract

Today the record shape is stated in four places that must agree by hand: `docs/SPEC.md` section 2 (table),
`scripts/merge.py` `RECORD_FIELDS` (order and defaults), `scripts/check_data.py::_validate_record_schema`
(types), and `scripts/build_db.py` (columns), plus `scripts/collect.py::POSTS_CSV_COLUMNS` (a subset). Adding
a field means touching all of them and the tests. The vision moves the truth into `schemas/` (the files in
`agentic-vision/schemas/` move to the repo root when implemented):

| Schema | Governs | Derived from it |
|---|---|---|
| `post-record.schema.json` | the record | `_validate_record_schema` (validate against the schema; keep the hand-written fast path only if measured to matter), `build_db` column list and types, `POSTS_CSV_COLUMNS` (properties tagged `x-csv: true`), the SPEC section 2 table, `ts dictionary` |
| `anomaly-event.schema.json`, `intervention-event.schema.json` | the two new ledgers | validation in `check_data`, docs |
| `run-record`, `deletion-event`, `engagement-row` (to be written in the same style from SPEC section 3) | existing ledgers | validation, docs |
| `state.schema.json` | `data/state.json` | validation on load, the OPERATIONS section 3 key table |
| `check-descriptor.schema.json` | the check registry | the OPERATIONS section 4 tables |
| `status.schema.json` | `output/status.json` | `STATUS.md` rendering |
| `verb-envelope.schema.json` | every `--json` output | `ts help` |

Validation uses the standard library only (a small validator for the subset of JSON Schema these files use:
type, enum, pattern, required, additionalProperties, items, oneOf with null). No new runtime dependency; the
desktop still runs Python 3.9.

`x-` extension keys carry what the docs need and the validator ignores: `x-role`, `x-provenance`,
`x-example`, `x-csv`, `x-invariants`.

## 2. The check registry

`scripts/check_data.py` gains a registry: one `CheckDescriptor` per check (schema
`schemas/check-descriptor.schema.json`), and `run_checks` returns firing checks as objects while keeping the
`hard` and `soft` string lists for compatibility.

```python
CHECKS = {
  "duplicate_id": CheckDescriptor(
      severity="hard", layer="store",
      why="The same post in two month files would double-count everything.",
      condition="ts_id appears in more than one posts/*.jsonl file",
      threshold=None,
      reading="Only possible after a crash between writes or a hand edit.",
      playbook="ts repair rewrite-records --apply",
      since="2026-09-11", expected_background=None),
  "present_count_drift": CheckDescriptor(
      severity="soft", layer="coverage",
      why="A source that starts missing posts shows up here first.",
      condition="abs(present - api_statuses_count) > threshold",
      threshold="max(50, 1% of api_statuses_count)",
      reading="About 350 is the known background (pre-March-2026 deletions nobody flagged, B-003). A sudden jump is a source outage.",
      playbook="ts doctor",
      since="2026-09-11", expected_background="~350 until B-003"),
  ...
}
```

`checks.json` v2:

```json
{
  "ok": true,
  "schema_version": 2,
  "hard": [], "soft": ["single_source_recent_posts:53 (e.g. ...)"],
  "firing": [
    {"name": "single_source_recent_posts", "severity": "soft", "value": 53, "threshold": "> 0",
     "sample_ids": ["117090736924416698", "..."], "truncated": {"sample_ids": 10}}
  ],
  "stats": {"...": "unchanged"}
}
```

Every check has a descriptor or the coherence test fails; every descriptor names a playbook verb that exists
in the dispatcher or the coherence test fails. The inert `trumpstruth_total_drift` (its `trumpstruth_totals`
argument is never passed by `collect.py`) is either wired (the trumpstruth leg already fetches the listing; the
stats page is one more request per run) or removed; the descriptor forces the decision (D-009).

New checks the vision adds, all soft or stat:

| Name | Severity | Why |
|---|---|---|
| `anomaly_rate` | soft | more than 50 anomalies in one run means a parser or source change |
| `unverified_interventions` | soft | an intervention applied but not verified for more than 24 h |
| `status_stale` | soft | `output/status.json` older than the newest run record |
| `raw_capture_missing` | stat | cloud run without a raw capture directory (a capture path regression) |
| `deletion_latency_median_30d` | stat | mission number 2 |
| `two_source_share`, `api_verified_share`, `presumed_live_count`, `guessed_handle_count` | stat | mission numbers 3 and 4 |

## 3. Uncertainty as data (Law 9)

`build_db` adds two views.

`v_confidence`, one row per post, boolean flags computed from the record:

| Flag | Definition | Why an analyst cares |
|---|---|---|
| `presumed_live` | `status = 'present' AND last_verified_live_at IS NULL` | existence never confirmed by the API |
| `single_source` | `seen_sources` has one element | no corroboration |
| `guessed_handle` | `kind = 'reblog' AND field_sources.reblog_of_acct = 'cnn' AND content_text starts with a word character` | `reblog_of_acct` may be wrong; first word of text may be missing |
| `cnn_dedup_risk` | `kind = 'reblog' AND seen_sources = ['cnn']` | CNN keeps one of repeated reposts; siblings may be missing |
| `before_removal_horizon` | `created_at_utc < '2026-03-01' AND status = 'present'` | a deletion before March 2026 would be unknown |
| `wide_interval` | `deletion_window_min > 1440` | lifetime analyses should use both bounds |
| `engagement_baseline_only` | exactly one engagement row, observed more than 14 days after creation | counts are a late snapshot |

`v_coverage`, one row per source: `first_post_at`, `last_post_at`, `records`, `deletions_confirmed`,
`removal_tracking_since` (trumpstruth: 2026-03-01), `engagement_rows`, `last_ok_at`.

Every function in `scripts/metrics.py` returns its data plus a `caveats` list of flag names that apply to
the rows it aggregated, with counts, e.g. `deletions()` returns `{"rows": [...], "caveats":
[{"flag": "wide_interval", "count": 3}, {"flag": "before_removal_horizon", "count": 0}]}`. `weekly.py`
renders the list under each table instead of the single generic Caveats paragraph.

## 4. Coherence tests (Law 16)

`tests/test_coherence.py`, all fast and offline:

| Test | Asserts |
|---|---|
| schema vs record | `RECORD_FIELDS` equals the schema's property order; `new_record()` validates; every record in `tests/factories.py` validates |
| schema vs validator | `_validate_record_schema` rejects exactly what the schema rejects on a fixed set of mutations |
| schema vs views | `build_db` posts columns equal the schema properties (plus the three computed columns); `POSTS_CSV_COLUMNS` equals the `x-csv` properties |
| registry vs emitted | every check name that `run_checks` can emit (extracted from the module's string constants) has a descriptor, and every descriptor is emitted somewhere |
| registry vs playbook | every descriptor's playbook verb exists in the dispatcher |
| verbs vs docs | the dispatcher's verb list equals the list in `03-verbs.md` (or the generated `docs/verbs.md`) |
| fixtures vs manifest | every file in `tests/fixtures/` has a manifest entry and vice versa |
| lessons vs tests | every `encoded_in` test id in `knowledge/lessons/*.md` exists (collected with `pytest --collect-only -q`) |
| workflow vs docs | the cron in `collect.yml` equals the cron stated in `AGENTS.md`; the Python versions in `test.yml` equal those in `AGENTS.md` |
| status render | `render(status.json)` equals the committed `STATUS.md` |
| README commands | every fenced command in `AGENTS.md` starting with `python -m scripts.ts` parses in the dispatcher with `--help` |

## 5. Property tests for the merge

`tests/test_merge_properties.py`, using only the stdlib and the existing factories (no hypothesis
dependency; a small generator of random partials is enough):

- **Idempotence**: merging the same observation twice yields `changed=False` the second time (SPEC rule 12,
  tested today for one case; make it a sweep).
- **Precedence monotonicity**: after merging observations in any order, each scalar field equals the value
  from the highest-ranked source that supplied a non-empty value.
- **Interval monotonicity**: `deleted_lower` never decreases and `deleted_upper` never increases across
  merges.
- **Write-once**: `first_seen_*`, `deleted_source`, `trumpstruth_removed_at` never change once set.
- **Round trip**: `save_posts(load_posts())` is byte-identical for every month file in `data/` (run in `ts
  verify`, not in the unit suite, because it reads 57 MB).

## 6. Generated documentation

`ts dictionary` and a `--write` flag produce `docs/generated/record.md`, `docs/generated/checks.md`,
`docs/generated/verbs.md`, `docs/generated/state.md`. `docs/SPEC.md` sections 2, 3 (state keys), and 9, and
`docs/OPERATIONS.md` sections 3 and 4, are replaced by one line each linking to the generated file. The
generated files are committed so they are readable on GitHub, and a coherence test regenerates them and
diffs.
