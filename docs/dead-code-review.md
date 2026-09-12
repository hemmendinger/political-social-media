# Dead code review

Read-only review of `scripts/*.py`, `tests/*.py`, `tests/fixtures/`, `queries/*.sql`, and
`.github/workflows/*.yml`, against the contract in `docs/SPEC.md`. Every "unused"/"unreferenced"
claim below was checked with a repo-wide grep (scripts, tests, queries, workflows, docs) before
being listed; confidence reflects how certain that check leaves it. The full suite passes
(`pytest -q` → 305 passed) and was run only as read-only context, not modified.

> **Verification (2026-09-12, against `33d8f79`):** every row was re-checked with `pyflakes`, `vulture`, and
> per-name greps. All category 1, 4, 5, 6, 7, 8 and 10 findings hold. Corrections are marked **[verified: …]**
> inline below. Summary of what changed: two `state.json` rows in category 9 are no longer write-only (a commit
> after this review, `7e447c9`, reads `api.reachable`/`api.last_probe_at`); category 2 is not empty (two
> unreferenced names in `scripts/common.py`); category 3 omitted the test-double classes that live in production
> code; one unused local in `tests/` was missed. `pytest -q` now reports 307 passed. Line numbers quoted for
> `scripts/collect_api.py` predate `7e447c9` and are off by 1–15 lines.

Per SPEC.md, `scripts/parsers.py`'s `parse_feed`/`parse_stats` and `scripts/store.py`'s helpers are
called out as intentionally-provided library surface that may be unused by production code today;
these are reported under category 3, not as bugs.

## Summary

| # | Category | Count |
|---|---|---|
| 1 | Unused imports | 5 (+1 unused local, see note) |
| 2 | Functions/classes/constants defined but never referenced anywhere | 2 **[verified: was 0]** |
| 3 | Names referenced only from tests (never production code) | 3, +1 fully isolated module |
| 4 | Unused function parameters / dead keyword options | 3 |
| 5 | Unreachable branches / dead exception arms | 3 |
| 6 | Duplicated helpers across collector modules | 5 |
| 7 | Fixture files / README mismatches | 0 unreferenced, 0 missing-file rows, 4 undocumented |
| 8 | SQL files in `queries/` not exercised by tests | 0 |
| 9 | Write-only `state.json` keys / unread record fields | 7 + 7 = 14 **[verified: was 9 + 7]** |
| 10 | Leftover TODO/FIXME markers / stale docstrings | 0 markers, 1 dangling reference |

All 11 files in `queries/` and all 24 fixture files in `tests/fixtures/` are exercised. `scripts/`
itself has **no** unused imports — every hit in category 1 is in `tests/`.

---

## 1. Unused imports

| File:Line | Name | Reason | Confidence | Action |
|---|---|---|---|---|
| `tests/test_collect.py:8` | `Path` (from `pathlib`) | Never referenced; every path in the file comes from the `tmp_path` fixture | High | Remove |
| `tests/test_collect.py:10` | `pytest` | Never referenced; no `@pytest.mark`/`pytest.raises` in the file | High | Remove |
| `tests/test_collect_api.py:9` | `pytest` | Never referenced anywhere in the file | High | Remove |
| `tests/test_merge.py:7-13` | `SOURCE_RANK` | Imported in the same statement as `CREATED_AT_RANK`/`RECORD_FIELDS`/`merge_partial`/`new_record`, but never used (only `CREATED_AT_RANK` appears, in `test_created_at_rank_lets_cnn_beat_trumpstruth`) | High | Remove |
| `tests/test_collect_trumpstruth.py:230` | `merge_partial` (local import) | Local `from scripts.merge import merge_partial` inside `test_backfill_listing_stops_on_a_page_with_zero_cards`; comment claims it's "needed for the tiny `_Merger` stand-in below", but `_Merger` already holds its own reference to `merge_partial` from `scripts.collect_trumpstruth`'s module scope — the locally-imported name is never used in the test body | High | Remove |

**[verified]** All five confirmed by `pyflakes`. `pyflakes` also reports one item this review missed:
`tests/test_collect_api.py:135` assigns a local `ids = [s["id"] for s in first_20]` in
`test_pagination_stops_when_a_page_has_only_known_ids` and never reads it (High, remove). The two bare
`import pytest` lines are harmless in a pytest module but are genuinely unreferenced.

## 2. Functions/classes/module-level constants defined but never referenced anywhere

**[verified: the original "None found" is wrong.]** `vulture scripts tests` plus a grep across `scripts/`,
`tests/`, `docs/` and `queries/` finds two module-level names in `scripts/common.py` that nothing references:

| File:Line | Name | Reason | Confidence | Action |
|---|---|---|---|---|
| `scripts/common.py:270` | `class Transport(Protocol)` | Never used as a base class, annotation, or runtime value; `Http.__init__` types its `transport` argument as `Any`, and `UrllibTransport`/`FakeTransport` do not inherit from it | High | Keep — it is the interface SPEC.md §5 documents (`class Transport(Protocol)`); optionally use it as the annotation on `Http.__init__` so it is exercised |
| `scripts/common.py:356` | `Http.DEFAULT_MIN_INTERVAL` (class attribute aliasing module-level `_DEFAULT_MIN_INTERVAL`) | No `Http.DEFAULT_MIN_INTERVAL` / `.DEFAULT_MIN_INTERVAL` access anywhere; the constructor and tests use the private module constant directly | High | Remove the alias, or keep as public API surface if SPEC intends it |

The original text below is retained for the record. Every *other* top-level `def`/`class`/constant in `scripts/*.py` is reached from at least
one other place (another script, a test, or — for the handful discussed in category 3 — is
explicitly-provided library surface). This was checked via an AST pass over every module-level
name plus a repo-wide occurrence grep for each (script at
`C:\Users\gameboto\AppData\Local\Temp\claude\G--projects-budget\47910596-612b-4cf3-a897-47580b7d4e2e\scratchpad\find_unused.py`,
read-only, run only against a copy of the repo path — nothing in the repo was changed).

## 3. Names referenced only from tests (never from production code)

| File:Line | Name | Reason | Confidence | Action |
|---|---|---|---|---|
| `scripts/parsers.py:529` | `parse_feed` | Called only from `tests/test_parsers.py::TestParseFeed`; no `scripts/collect_*.py` calls it | High | Keep as intentional API (pre-approved by SPEC.md) |
| `scripts/parsers.py:600` | `parse_stats` | Called only from `tests/test_parsers.py::TestParseStats`; no collector calls it | High | Keep as intentional API (pre-approved by SPEC.md) |
| `scripts/parsers.py:296` | `make_cursor` | Called only from `tests/test_parsers.py::TestNextCursorAndMakeCursor`; `scripts/collect_trumpstruth.py` never calls it (it only *reads* cursors via `parse_next_cursor`, never *builds* one) | High | Keep as intentional API — SPEC.md 6.1 documents it as a real part of the parser contract ("callers pass UTC plus 5 hours") for a caller that doesn't exist yet |

**[verified: omission]** Three more names in `scripts/common.py` are referenced only from `tests/`: `FakeClock`
(`common.py:151`, with its `advance()` method used only by `tests/test_http.py:90`) and `FakeTransport`
(`common.py:310`). They are test doubles that SPEC.md §5 places in production code deliberately, so the action is
**keep**; they are listed here only because the category is "referenced only from tests" and the review should
not imply the list above is complete.

**Also isolated (not test-referenced either):** `scripts/validate_backfill.py` — its own `validate()`
function (line 32) is called only by its own `main()` in the same file; no test file exists for
this module (no `tests/test_validate_backfill.py`), it is not imported by any other script, and it
is not mentioned in `docs/SPEC.md`'s module list (section 0/8-12) or `README.md`'s layout table
**[verified: partly stale — `docs/OPERATIONS.md:104`, added after this review, now documents the
`python -m scripts.validate_backfill --cnn ...` invocation as a playbook step; the missing test still holds]**.
It's a real, usable one-time CLI (`python -m scripts.validate_backfill --cnn ...`, per its own
docstring), so this is a coverage/documentation gap rather than dead code. Confidence: high that it
is unreferenced; recommendation: verify it's still wanted, then either add a smoke test or note it
in SPEC.md/README.md alongside `collect --backfill`.

## 4. Unused function parameters / dead keyword options

| File:Line | Name | Reason | Confidence | Action |
|---|---|---|---|---|
| `scripts/check_data.py:144` (param), `:248-257` (body) | `run_checks(..., trumpstruth_totals=None, ...)` | `collect.py`'s `run_all` (the only production caller of `run_checks`) never passes `trumpstruth_totals`; no test passes it either. The `local_total_vs_trumpstruth_total` soft-check branch it guards never executes anywhere in this codebase | High | Keep as intentional API (documented in SPEC.md section 9) but verify whether a caller was meant to supply it — currently the trumpstruth-total soft check is permanently inert |
| `scripts/common.py:358-365` (param) | `Http.__init__(..., min_interval=None, ...)` | No construction of `Http(...)` anywhere in `scripts/` or `tests/` passes `min_interval=`; every instance relies on `DEFAULT_MIN_INTERVAL` | High | Keep as intentional API (documented in SPEC.md section 5's constructor signature) |
| `scripts/common.py:216` | `Context.raw_dir` | Dataclass field with comment "when set, collectors may save raw responses here"; grepped repo-wide and the only occurrence is this declaration — no collector ever sets or reads `ctx.raw_dir` | High | Keep as intentional stub — matches TODO.md's deferred "Raw responses as workflow artifacts for forensic debugging" feature, not yet wired up |

## 5. Unreachable branches / always-true-false conditions / dead exception arms

| File:Line | What | Reason | Confidence | Action |
|---|---|---|---|---|
| `scripts/collect.py:91-92` | `else:  # pragma: no cover - SOURCE_ORDER is the only source of names` → `continue` | `selected` (line 79) is filtered from the fixed `SOURCE_ORDER = ["trumpstruth", "cnn", "api"]`, and the preceding `if`/`elif` chain covers exactly those three values, so this branch can't currently execute — already self-documented by the author | High | Keep as intentional defensive fallback (author already marked it `pragma: no cover`) |
| `scripts/common.py:253` | `Response.__repr__` | Marked `# pragma: no cover - debugging aid`; no test asserts on `repr(Response(...))` | High | Keep as intentional (debugging aid, self-documented) |
| `scripts/check_data.py:165-168` | `except (ValueError, KeyError):` around `store.month_of(r["created_at_utc"])` | This is only reached inside `if r.get("created_at_utc"):` (line 165), so the dict access can't raise `KeyError`, and neither `store.month_of` nor `parse_iso_utc` ever raises `KeyError` (only `ValueError`) | Medium | Remove the `KeyError` arm, or verify no other call path was intended to reach it |

## 6. Duplicated helpers across collector modules (report only, no refactor)

| Files:Lines | What's duplicated | Confidence | Action |
|---|---|---|---|
| `scripts/collect_api.py:28`, `scripts/collect_archive.py:24`, `scripts/collect_trumpstruth.py:59` | `_new_run_counts()` — byte-identical in all three: `{"new_posts": 0, "updated_posts": 0, "deletions_found": 0, "errors": 0}` | High | Share (move to `scripts/common.py`) |
| `scripts/collect_api.py:32`, `scripts/collect_archive.py:28`, `scripts/collect_trumpstruth.py:63` | `_build_row(ctx, started_at, *, requests, counts, notes)` — identical shape/keys in all three, differing only in the hardcoded `"source"` string (and a cosmetic `notes: str` vs `notes: Any` annotation in `collect_archive.py`) | High | Share (parameterize `source` and move to `scripts/common.py`) |
| `scripts/collect_api.py:65-76` vs `scripts/collect_archive.py:119-131` | Engagement-row dict construction — `collect_api.py` factors it into `_engagement_row(observed_at, partial)`; `collect_archive.py` builds the identical 7-key dict (`observed_at, ts_id, source, replies, reblogs, favourites, upvotes, downvotes` from `partial.get("_engagement") or {}`) inline instead of reusing/sharing that helper | Medium | Share |
| `scripts/common.py:19` (`ACCOUNT_ID`), `scripts/collect_api.py:23` (`ACCOUNT_ID`) | Same literal `"107780257626128497"` defined independently in both files; `collect_api.py` does not import `scripts.common.ACCOUNT_ID` | High | Share (import from `scripts.common` instead of redefining) |
| `scripts/collect_api.py:48-57`, `scripts/collect_archive.py:44-51`, `scripts/collect_trumpstruth.py:145-154` | `_source_state(ctx)` — same `state.setdefault("version",1); sources=state.setdefault("sources",{}); src=sources.setdefault(<name>, {defaults})` skeleton repeated per source, only the default dict's keys differ | Low | Share (a small `store.init_source(state, name, defaults)` helper), or keep — the per-source defaults are different enough that sharing buys less here |

## 7. `tests/fixtures/` coverage and `README.md` accuracy

- **Unreferenced fixture files:** none. All 24 data files under `tests/fixtures/` are loaded by at
  least one test (checked by grep for each filename across `tests/*.py`).
- **README rows pointing at missing files:** none. Every file named or pattern-expanded in
  `tests/fixtures/README.md`'s table (including the `trumpstruth_status_41641/41644/41646/41649_removed_reblog.html`
  shorthand, which expands to 4 real files) exists on disk.
- **Undocumented fixtures (exist + used, but missing from the README table):**

| File | Used by | Confidence | Action |
|---|---|---|---|
| `tests/fixtures/trumpstruth_status_41514_reblog_other.html` | `tests/test_parsers.py::test_41514_reblog_of_other_account` | High | Add a README row |
| `tests/fixtures/trumpstruth_status_41515_reblog_other.html` | `tests/test_parsers.py::test_41515_michael_cohens_own_post`, `tests/test_collect_trumpstruth.py::test_other_account_id_skipped_and_recorded_in_other_account_ids` | High | Add a README row |
| `tests/fixtures/trumpstruth_search_removed_2026-08-28_to_09-11.html` | `tests/test_collect_trumpstruth.py::_week_search_routes` (used by 2 tests) | High | Add a README row |
| `tests/fixtures/trumpstruth_search_removed_page2_empty.html` | `tests/test_parsers.py::test_search_results_page_past_the_last_page_is_empty_not_drift`, `tests/test_collect_trumpstruth.py::_week_search_routes` | High | Add a README row |

## 8. SQL files in `queries/` not exercised by tests

**None.** `tests/test_query.py::test_every_starter_query_executes` asserts `len(sql_files) == 11`
(matching all 11 files currently in `queries/`) and runs each one against the synthetic database.

## 9. `state.json` keys written but never read / record fields (SPEC.md §2) nothing reads

### `state.json` keys (SPEC.md §3)

| Key | Write sites | Confidence | Action |
|---|---|---|---|
| `sources.trumpstruth.last_run_at` | `scripts/collect_trumpstruth.py:136,457` | High | Remove, or keep for operators reading `state.json` by hand |
| `sources.cnn.last_run_at` | `scripts/collect_archive.py:48,70` | High | Same |
| `sources.api.last_run_at` | `scripts/collect_api.py:54,83` | High | Same |
| `sources.trumpstruth.last_ok_at` | `scripts/collect_trumpstruth.py:137,476` | High | Same (contrast: `sources.cnn.last_ok_at` *is* read, at `collect_archive.py:59-61`, to gate the 2-hour skip window — only the trumpstruth/api copies are write-only) |
| `sources.api.last_ok_at` | `scripts/collect_api.py:55,235` | High | Same |
| `sources.cnn.last_modified` | `scripts/collect_archive.py:48,50,142` | High | Remove, or wire it into an `If-Modified-Since` header alongside the existing `If-None-Match`/etag logic |
| ~~`sources.api.reachable`~~ | `scripts/collect_api.py:55,111,123` | — | **[verified: no longer write-only.** Read at `collect_api.py:89` (`if src.get("reachable") is False and last_probe:`) to gate the 6-hour re-probe added in `7e447c9`. Keep.] |
| `sources.api.last_probe_status` | `scripts/collect_api.py:55,112,124` | High | Remove, or keep as an operator-visible health flag (still write-only after `7e447c9`) |
| ~~`sources.api.last_probe_at`~~ | `scripts/collect_api.py:56,113,125` | — | **[verified: no longer write-only.** Read at `collect_api.py:88` to compute the re-probe age. Keep.] |

**[verified]** `docs/OPERATIONS.md:52` now tells operators to read/delete `cnn.etag`/`last_ok_at` and
`api.reachable`/`last_probe_at` by hand, so the "keep for operators" option in this table is the documented
one for those keys; `last_run_at` (all three sources), `trumpstruth.last_ok_at`, `api.last_ok_at`,
`cnn.last_modified` and `api.last_probe_status` remain write-only.

All of the remaining rows are asserted on in `tests/test_collect_api.py`/`tests/test_store.py` (the tests
confirm they're *written* correctly) but no production code path reads the value back to make a
decision — they are currently diagnostic-only fields in a durable file.

### Record fields (SPEC.md §2)

Fields below are written by `scripts/parsers.py` and passed through the generic merge/store/build_db
machinery (which touches every field uniformly and doesn't count as a field-specific "read" here),
but have no field-specific consumer: not in `scripts/collect.py`'s `POSTS_CSV_COLUMNS`, not in
`scripts/build_db.py`'s `v_posts_et` view, not read by any `scripts/metrics.py`/`scripts/weekly.py`
function, and not selected by any `queries/*.sql` file.

| Field | Write site | Confidence | Action |
|---|---|---|---|
| `lang` | `scripts/parsers.py:695` | High | Verify — likely fine to keep (cheap to retain, useful if non-English-post analysis is ever wanted) |
| `in_reply_to_id` | `scripts/parsers.py:675,696` | Medium | Verify — its *presence* already drives `kind="reply"` at parse time (`parsers.py:679`), but the raw id itself is never read back once stored |
| `card_title` | `scripts/parsers.py:657,664` | High | Verify — `card_domain` is read (`metrics.link_domains`) but `card_title` never is |
| `pinned` | `scripts/parsers.py:698` | Medium | Verify — touched by `check_data.py:110-111`'s boolean-type check, `merge.py:123`'s `False` default rule and `build_db.py:36` `BOOL_FIELDS` **[verified: the latter two were omitted]**, but by no metric or query |
| `raw_api` | `scripts/parsers.py:721` | Low | Keep as intentional — SPEC.md §2 documents it as deliberate forensic/archival data ("latest API object with every `account` key removed"), not a computed analysis field |
| `reblog_of_created_at` | `scripts/parsers.py:404,410,706,713` | High | Verify — `reblog_of_acct`/`reblog_of_id` are both read (CSV + `metrics.top_reblogged_accounts`) but the timestamp sibling is not |
| `updated_run_id` (on post records) | `scripts/merge.py:432` | Medium | Verify — distinct from the `run_id` field on *run* rows (which is read, e.g. by `check_data.py`'s "run row exists" check); this per-post copy is write-only, and is explicitly excluded from the record-diff comparison (`merge.py:108`) |

## 10. Leftover comments, TODO/FIXME markers, stale docstrings

- **TODO/FIXME/XXX/HACK markers:** none in `scripts/` or `tests/`. The only two hits for `TODO` are
  legitimate cross-references to the project's real `TODO.md` file (`scripts/check_data.py:301`,
  `scripts/collect_trumpstruth.py:17`), not leftover markers.
- **Dangling doc reference (low confidence):** `scripts/parsers.py:11` says "also summarized in the
  implementation report" — no file matching "implementation report" exists anywhere in this repo.
  SPEC.md's own header notes "the approved plan... lives outside the repo", so this is plausibly a
  reference to that same external document rather than a stale leftover; recommend verifying the
  out-of-repo report is still the right pointer rather than treating it as dead.
- No other docstring was found describing behavior the code has since dropped — the module and
  function docstrings across `scripts/*.py` (including the explicit "SPEC MISMATCH" callouts in
  `parsers.py`) match the code they document.
- `.github/workflows/collect.yml` and `.github/workflows/test.yml` were checked against
  `scripts/collect.py` and the test invocation; both reference real, current entry points
  (`python -m scripts.collect --summary-file ...`, `pytest -q`) with no stale steps.
