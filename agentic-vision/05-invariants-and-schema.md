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
| `post-record.schema.json` | the record | `_validate_record_schema` (validate against the schema; keep the hand-written fast path only if measured to matter), `RECORD_FIELDS` and `SCALAR_FIELDS` (from `x-merge`), `build_db` column list and types, `POSTS_CSV_COLUMNS` (properties tagged `x-csv: true`), the SPEC section 2 generated block, `ts dictionary` |
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

### 1.1 Extension keys the code reads

Beyond the documentation keys, properties carry keys that generate the parallel lists `merge.py` keeps by
hand today (`RECORD_FIELDS`, `SCALAR_FIELDS`, the default sets, `POSTS_CSV_COLUMNS`, the `build_db` column
list): `x-merge` in `identity | created_at | content | media | scalar | derived | sighting | existence |
source-meta | provenance | evidence | bookkeeping` (which merge rule applies), `x-default`, `x-sql`, `x-csv`,
`x-view`, `x-sources` (which sources can supply it), `x-since`, `x-decision`. `scripts/schema.py` derives
the lists from the schema at import time, so a field added to the schema is merged, validated, stored, and
documented without touching five files, and a field in `RECORD_FIELDS` but not `SCALAR_FIELDS` (silently
ignored by the merge today) cannot happen.

### 1.2 Schema version and migrations

`missing_fields` is a hard check and the merge deep-copies existing records, so adding a required field
today would fail the cloud run for all 37,002 records until an ad-hoc script rewrote 55 month files (B-044).
The schema carries `x-schema-version`; `data/state.json` carries `schema_version` (absent means 1);
`scripts/migrate.py` holds ordered, reasoned migrations; `ts repair migrate` plans (files, records, diff
size) and applies through `store.save_posts` under an intervention record; a hard check `schema_behind`
fires when the data version is behind the code version, with the playbook `ts repair migrate --apply`.

### 1.3 Registries for every closed vocabulary

The same principle, declare once and derive everywhere, applies to the other closed vocabularies. Each
becomes a registry that the code iterates and the docs are generated from, replacing branch chains and
literal sets:

| Vocabulary | Registry | Replaces | Generates |
|---|---|---|---|
| sources | `scripts/sources.py`: `Source(name, rank, created_at_rank, order, hosts: {host: min_interval}, headers, fallback_on_403, deletion_signal: Signal(key, upper_from, deleted_source), live_sighting, meta_fields, state_defaults, collector, dossier, fixture_prefix)` (B-043) | `SOURCE_RANK`, `CREATED_AT_RANK`, the hidden `cnn` default for unknown provenance, `VALID_SOURCES`, `SOURCE_ORDER` and the if/elif in `collect.py`, the paced-host table, the `source ==` branches in `merge.py` | the sources table in the README, the precedence line in SPEC, `Http` pacing (an unregistered host is refused, never paced at 0 s: B-045), the `Leg` skeleton that runs the merge, checkpoint, engagement, and run-record loop so a collector is fetch-and-parse only |
| checks | `CHECKS` (section 2) | inline string formatting, thresholds as literals | `checks.json` objects, the OPERATIONS section 4 tables, the `STATUS.md` readings |
| metrics | `@metric(name, section, shape, columns, caveats, since, sql, parity)` (B-046) | three sites in `metrics.py`, three in `weekly.py`, two hard-coded test lists, the `== 11` starter-query assertion | the report, the CSVs, the starter query set, and a SQL-versus-Python parity test |
| verbs | `REGISTRY` in `scripts/ts.py` (`03-verbs.md`) | seven `main()` functions | `ts help`, the verb block in OPERATIONS section 5 and in `AGENTS.md` |
| questions | `QUESTIONS` in `scripts/ask.py` (section 3.6) | ad-hoc SQL | `ts ask` listing, golden answers |

The source registry also carries a pseudo-source `repair` at rank 0: a value written by a repair plan is
provenance-stamped `repair` and is overridden by any real source's next observation.

Observations become strict at the seams where that is cheap: `merge_partial(strict=True)` in tests and
replay raises on a partial key that is not a schema field, a registered signal, or a registered private key
(`_source`, `_engagement`, `account`, `retruthed`, `retruthed_by`, `trumpstruth_url`, `snippet_text`), so a
parser field can no longer vanish silently (B-047); production stays lenient and counts unknown keys as an
anomaly.

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
| `deletion_lookback_gap` | soft | the last full removed-search sweep is older than 7 days (B-029) |
| `removed_search_mismatch` | soft | a removed-search hit whose status page carries no `Removed from platform` row; never mark it processed (B-032) |
| `budget_exhausted` | soft | a leg hit its request budget and was truncated (B-032) |
| `markup_changed` | soft | a fetched page's structural fingerprint differs from the fixture's (B-034) |
| `other_account_ratio` | soft | more than 20% of sequentially resolved ids skipped as other accounts in one run (a parse failure of `account` looks like this) |
| `incident_unresolved` | soft | an incident record exists for a run newer than the last successful run (B-030) |
| `deleted_without_event` | hard | `status = deleted` with no line in `deletions.jsonl`: a half-finished repair (B-051) |
| `present_with_deletion_fields` | hard | `status = present` with any of `deleted_lower`, `deleted_upper`, `deleted_source`, `trumpstruth_removed_at` set: a forgotten `forget_deletion` (B-051) |
| `deleted_without_upper` | hard | `status = deleted` and `deleted_upper` null (B-051) |
| `deletion_bounds_drifted_from_event` | soft | the record's interval no longer matches its first event; expected as bounds tighten, but a large drift is a repair to review (B-051) |
| `schema_behind` | hard | `state.json.schema_version` is behind the code's `x-schema-version`; playbook `ts repair migrate --apply` (B-044) |
| `cnn_self_repost_prefix_assumed` | stat | cnn-only reblogs resolved by the exact `RT @realDonaldTrump` prefix (1,157 today); split from `cnn_ambiguous_handles`, which now counts only glued other handles (15) (B-054) |

## 3. Uncertainty as data (Law 9)

Three findings from the 2026-09-12 analysis walkthrough drive this section. First, `v_posts_et.lifetime_min`
is an upper bound (creation to `deleted_upper`) exposed under a point name, and every one of the 98 deletions
has `deleted_lower` equal to its creation time, so "deleted within an hour" returns a structural zero that
reads as evidence (L-007). Second, the narrowest interval any source has resolved is 76 minutes (median 742),
94 of 98 removal times are minute precision, and that floor is recorded nowhere. Third, the removed search
covers only posts created in the last 14 days, so lifetimes over 14 days are structurally unobservable going
forward (B-029, L-006). None of these is visible from a query today.

### 3.1 Bounds have names

`build_db` views are generated from a column registry, `ColumnDoc(name, type, sql, bound, unit, tz, doc,
flags, since)` in `scripts/build_db.py`, so a column cannot exist without stating which bound it is: `exact`,
`lower`, `upper`, or `interval`. `ts dictionary` renders the registry; a coherence test diffs the sqlite schema
against it. Changes to `v_posts_et`:

| Column | Bound | Definition |
|---|---|---|
| `lifetime_lo_min` | lower | minutes from creation to `deleted_lower` (0 when the lower bound is creation) |
| `lifetime_hi_min` | upper | minutes from creation to `deleted_upper` (today's `lifetime_min`, kept as a deprecated alias for one release) |
| `lower_basis` | exact | `api_live` when `deleted_lower` came from `last_verified_live_at`, else `created` |
| `upper_basis` | exact | `deleted_source` (`trumpstruth` or `api404`) |
| `upper_precision` | exact | `minute` when the trumpstruth removal time ends in `:00`, else `second` |
| `utc_date` | exact | `substr(created_at_utc, 1, 10)`; month files are UTC partitions while analysis days are Eastern (B-041) |

A predicate over an interval returns a three-valued verdict, never a count: `deleted_within(N)` is
`confirmed` when `lifetime_hi_min <= N`, `excluded` when `lifetime_lo_min > N`, else `possible`. For August
2026 the honest answer to "within an hour" is 0 confirmed, 6 possible, 0 excluded, with the detection floor
(76 min) attached because the threshold is finer than the floor.

### 3.2 `v_confidence`

One row per post, flags derived from the record, plus an evidence grade:

| Flag | Definition | Why an analyst cares |
|---|---|---|
| `presumed_live` | `status = 'present' AND last_verified_live_at IS NULL` (36,884 of 36,904 today) | existence never confirmed by the API |
| `single_source`, `single_source_name` | `seen_sources` has one element | no corroboration |
| `guessed_handle` | `kind = 'reblog' AND field_sources.reblog_of_acct = 'cnn' AND content_text starts with a word character` | `reblog_of_acct` may be wrong; first word of text may be missing |
| `cnn_dedup_risk` | `kind = 'reblog' AND seen_sources = ['cnn']` (5,491 of 5,575 reblogs, all with `reblog_of_id` null) | repeated reposts of one target are collapsed; siblings may be missing |
| `reply_unobservable` | `api` not in `seen_sources` | neither trumpstruth nor cnn can see replies; `kind = 'reply'` has never occurred (0 of 37,002) |
| `before_removal_horizon` | `created_at_utc < '2026-03-06' AND status = 'present'` | a deletion before the observed start of removal tracking would be unknown |
| `wide_interval` | `deletion_window_min > 1440` | lifetime analyses must use both bounds |
| `engagement_baseline_only` | exactly one engagement row, observed more than 14 days after creation | counts are a late snapshot |
| `utc_seam` | `utc_date != et_date` | the record's UTC month file and its Eastern day disagree |
| `grade` | `A` api-verified, `B` two or more sources, `C` single source | filter by evidence quality with a WHERE clause |

### 3.3 `v_coverage` and `output/coverage.json`

What each source and each signal could have seen, generated at build time from the ledgers, never written
by hand. Per source: `history_start`, `history_end`, `records`, `polling_since` (earliest ok run record),
`last_ok_at`, `api_verified`. Per signal: `removal_tracking_since` as `{declared: 2026-03-01,
observed_min: 2026-03-06T04:02Z}`; `removal_search` as `{window_days, lookback_semantics: "post creation
date", last_full_sweep}` (from the `sweep` field on run records, `04-ledgers-and-provenance.md`);
`detection_floor_min` (76, the minimum interval width in `deletions.jsonl`); `removal_time_precision`
(share of minute-precision values); `engagement` as `{policy, tracked_rows, late_baseline_rows}`;
`reply_observable` (false unless the api leg ran inside the window). Every windowed answer consults it.

### 3.4 Caveats are computed, never written

`scripts/caveats.py` holds a registry `Caveat(flag, scope, text, fn)` with `scope` `record` (a
`v_confidence` flag counted over the rows aggregated) or `window` (`removal_horizon`,
`deletion_lookback_gap`, `detection_floor`, `reply_unobservable_window`, `api_not_polled_in_window`,
`utc_seam`, computed from coverage and the window bounds). Every function in `scripts/metrics.py` returns
its data plus `caveats: [{flag, scope, count | value, of, text}]`, including zero counts. `weekly.py` renders
the list under each table in place of the single static paragraph it prints today; `metrics.json` carries
them.

### 3.5 Engagement snapshot semantics

All 37,226 engagement rows today are cnn; 35,909 were observed more than 14 days after creation; 5,366 of
5,597 reblog rows have favourites 0 because the archive reports zeros for reposts. `v_engagement_latest`
gains `age_at_observation_min`, `snapshot_kind` (`tracked` under 14 days, else `late_baseline`), and
`source`; `engagement_stats` excludes reblogs by default and reports the kind and snapshot breakdown as
caveats (B-037).

### 3.6 Questions, not queries

`ts ask <question>` (`03-verbs.md`) runs a named, versioned analysis from a registry `QUESTIONS` in
`scripts/ask.py`: `Question(name, purpose, params, fn, unit, bound: point | interval | count3, version)`.
The answer envelope is `{question, version, args, window: {tz, et: [start, end], utc: [first, last],
seam_posts}, answer, bounds, n, coverage, caveats, method, provenance: {data_commit, built_at}}`, so a
figure quoted to a journalist can be reproduced or shown to have changed. Initial questions:
`deleted_within`, `volume --compare before | after DATE | trailing N`, `deletions --by created | removed`,
`top_reblogged` (`--include-guessed` off by default, excluded count reported), `engagement`, `hours`,
`bursts`. Ad-hoc SQL through `ts query` stays as the escape hatch and travels in the same envelope. Golden
answers over synthetic cases shaped like the real data (B-038) guard against regressions in honesty.

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
| lessons vs tests | every `encoded_in` test id in `knowledge/lessons/*.md` exists (collected with `pytest --collect-only -q`), and every test marked `@pytest.mark.lesson("L-nnn")` names a lesson that lists it (two-way) |
| quirk ids | every `Q-<src>-<nn>` cited in code, tests, or lessons exists in that source's dossier, and every dossier quirk has a date and an evidence pointer |
| audits | every file under `knowledge/audits/` has a Disposition table covering every finding, or is younger than 14 days |
| backlog | `knowledge/backlog.json` validates against the schema; every `blocked_by` and `decision` id exists; every `acceptance_expr` parses |
| rules block | the generated rules block in `AGENTS.md` equals the render of lessons marked `general` plus accepted decisions |
| workflow vs docs | the cron in `collect.yml` equals the cron stated in `AGENTS.md`; the Python versions in `test.yml` equal those in `AGENTS.md` |
| status render | `render(status.json)` equals the committed `STATUS.md` |
| columns vs registry | every column of every view in the built sqlite has a `ColumnDoc`, and every `ColumnDoc` has a column |
| questions vs golden | every registered question has a golden answer over the synthetic dataset and reproduces it |
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

## 6. Generated blocks inside the documents agents already read

Rather than a second directory of generated files that drifts from the first, the tables that restate code
facts stay where they are and become generated blocks:

```
<!-- generated:record-table source=schemas/post-record.schema.json -->
| field | type | merge | sources | since | notes |
...
<!-- /generated -->
```

`ts dictionary --write` rewrites every block in place from its source (`record-table`, `media-item-table`,
`sources-table`, `precedence-line`, `state-keys`, `checks-hard`, `checks-soft`, `checks-stats`, `verbs`,
`questions`, `fixtures-table`, `module-map`); `ts dictionary` with no flag prints the diff. Blocks live in
`docs/SPEC.md` sections 0 (module map), 1, 2, 3, 9, 11, `docs/OPERATIONS.md` sections 2, 4, 5,
`README.md` (sources table), `tests/fixtures/README.md`, and `AGENTS.md` (verbs). A coherence test
regenerates them and fails on any difference, so a fact cannot be edited by hand in a generated block and a
registry cannot change without its documentation.
