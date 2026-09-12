# 10. Migration plan: from today's repository to the vision, by leverage

Four phases. Each phase has a goal, its items (ids from `knowledge-seed/backlog.yaml`), an acceptance
test an agent can run, and what it costs to build. The ordering rule: a phase contains only work that
everything after it stands on, and nothing that a later phase would make cheaper. Phase 0 can be done in
one sitting and changes no data semantics; it is what makes every later session cheaper.

## Phase 0: stop the leaks, open the door (foundation)

Goal: an agent can orient in three commands, nothing computed is lost, and the docs stop lying.

| Item | What | Build |
|---|---|---|
| B-014 | `data/anomalies.jsonl` + `store.append_anomaly` + `anomalies` count on run records; the three merge loops append; correct README/OPERATIONS (C2) | S |
| B-101 | profiles: detection, printed on every invocation; `cloud` skips the api leg; `sandbox` guards | S |
| B-102 | `scripts/ts.py` dispatcher wrapping the existing functions; envelope; cost line; `help`; verbs `status check build query report collect`; old entry points untouched | M |
| B-105 | `schemas/` at the root (from `agentic-vision/schemas/`); stdlib validator; `_validate_record_schema` reads the schema; check registry with descriptors; `checks.json` v2 (`firing` objects added, strings kept) | M |
| B-103 | `scripts/situation.py`: `output/status.json` and `STATUS.md` after exports; `output/history/checks-*.jsonl`; bot commits `STATUS.md` | M |
| B-104 | `AGENTS.md` from `templates/AGENTS.md` | S |
| B-029 (D-017) | widen the removed search (since 2022-01-01 while under about 500 removals) and record the `sweep` on the run record; the cheapest accuracy win in the plan | S |
| B-030, B-042 | incident records committed `if: always()`; `checks.json` carries `run_id` and `checked_at` | S |
| B-036 | `lifetime_lo_min` / `lifetime_hi_min`, bound basis and precision columns, `detection_floor_min` in coverage; the weekly report labels the bound | S |
| B-051, B-054 | repair-state invariants (a half-finished repair fails a hard check); split the ambiguous-handle stat (1,157 self-reposts versus 15 glued handles) | S |
| B-013, B-028, B-015 | fixture manifest; ignore `data/.lock`; persist `max_trumpstruth_id` per id | S |
| C1 to C33 | the doc corrections in `11-doc-deltas.md` section 1 (the restructurings wait for phase 2) | S |
| D-007, D-008, D-009, D-013 | decide (recommendations in `knowledge-seed/decisions.md`); they gate B-025, B-003/B-004, B-012, and the pandas removal | maintainer |

Acceptance (run from a clean clone):
```
cat AGENTS.md                              # under 120 lines
python -m scripts.ts status --json | python -c "import json,sys; s=json.load(sys.stdin); print(s['result']['health']['verdict'])"
python -m scripts.ts check --json | grep -c '"firing"'
tail -1 data/anomalies.jsonl               # exists after one collect (or the smoke bundle)
python -m pytest -q                        # green on 3.9 and 3.12
```
The bot's next commit carries `STATUS.md` and the structured message body. Reading cost for "is it
healthy?" drops from about 1,800 tokens to about 600 (`09-economy.md` section 2).

## Phase 1: see, reproduce, repair (high leverage)

Goal: any red run can be reproduced offline and any repair is one command with a receipt.

| Item | What | Build |
|---|---|---|
| B-106 | raw capture through `Context.raw_dir`; `index.jsonl`; artifact upload when not green; 7-day prune | S |
| B-107 | `ts replay` with bundles (six ship), golden diff, `--from-raw`, `--update-golden` | M |
| B-108 | `ts explain`, `ts doctor` (nine diagnoses), `ts diff` | M |
| B-109 | `ts repair` with the seven plans, plan/apply, `data/interventions.jsonl`; OPERATIONS section 5 recipes become one command each | M |
| B-110 | `tests/test_coherence.py` (eleven rows) and `ts verify`; `test.yml` runs `ts verify --ci` | M |
| B-117 (D-014) | commit successful legs when one leg fails | S |
| B-018, B-019, B-020, B-021, B-016, B-017, B-023 | the audit's correctness items: standalone check parity; write ordering; torn-line recovery; content_text provenance; exit 3 for the lock; refuse unknown sources; drop `removed=include` | S each |
| B-024, B-026, B-027 | measure cron delivery in `status.json`; load posts once; expose caps as flags | S each |
| B-031, B-032, B-033, B-034 | error envelope with leg phase; request budgets and undercollection guards; union merge, rebase abort, JSON lock; fingerprints on every fetch | S to M each |
| B-041 | `utc_date`, `utc_seam`, `metrics.window()` with both bounds | S |
| B-050, B-052, B-053 | `forget_deletion` / `forget_source`; `repair undo` and `ts pause`; carry-forward across `redo-history` | S each |
| B-011 | share the collector helpers (do it while touching all three merge loops) | S |

Acceptance:
```
python -m scripts.ts verify --quick                       # green, under 30 s
python -m scripts.ts replay tests/bundles/removal-of-old-post --json | grep '"deletions_found": 1'
python -m scripts.ts replay tests/bundles/red-parse-error --json | grep '"diagnosis": "markup_drift"'
python -m scripts.ts repair regenerate-deletion --ts-id 117238345561593751 --data-root /tmp/scratch  # plan only, exit 4
python -m scripts.ts explain 117238345561593751 | head -40
```
A production failure goes from symptom to a bundle in `tests/bundles/` in one session without reading the
Actions console.

## Phase 2: knowledge, uncertainty, and the docs that generate themselves

Goal: the system remembers in the right places, analyses carry their caveats, and docs cannot rot.

| Item | What | Build |
|---|---|---|
| B-112 | populate `knowledge/` from `knowledge-seed/` (dossiers, decisions, lessons, backlog); retire `TODO.md`, `MISTAKES.md`, `docs/dead-code-review.md` to pointers; `ts note` | S |
| B-111 | `v_confidence`, `v_coverage`, `caveats` on every metric, weekly renders them | M |
| B-114 | `ts dictionary --write` and the generated blocks inside SPEC, OPERATIONS, README, the fixtures README, and AGENTS.md; README to 40 lines | M |
| B-043, B-044, B-045 | the source registry and the shared Leg; schema version and `repair migrate`; refuse unregistered hosts | M, S, S |
| B-113 | canaries and `canary.yml` | M |
| B-115 | `repair.yml`; desktop `--commit` path | S |
| B-116 (D-010) | untrack `posts.csv`; `output/history`; engagement throttle change (B-025 under D-007) | S |
| B-001 | resolve the 15 glued handles (dictionary first, then one trumpstruth search each) as the first real `repair` plan with an intervention record | S |
| B-022 | decide and document empty-list semantics; property test | S |
| B-012 (D-009) | wire the trumpstruth total check | S |
| B-035, B-037, B-038 | `ts ask` with the question registry and answer envelope; engagement snapshot semantics; epistemic golden cases | M |
| B-046, B-047, B-048 | metric registry with SQL parity; strict observations in tests and replay; `ts scaffold` | M, S, M |
| B-039 | module headers and the generated module map | S |

Acceptance:
```
python -m scripts.ts verify                               # includes coherence tests against knowledge/
python -m scripts.ts query --sql "select count(*) from v_confidence where guessed_handle=1"   # 0 after B-001
python -m scripts.ts dictionary                          # prints no diff: every generated block matches its registry
```

## Phase 3: coverage and reach

Goal: close the historical gaps the sources allow, from the desktop, as declared repairs.

| Item | What | Build |
|---|---|---|
| B-003 | `repair api-backfill` (desktop, chunked commits, resumable); deletions before March 2026 become known with unknown timing | M |
| B-002 | historical id crawl from the desktop with `--max-ids` | S |
| B-004 | desktop poller as a scheduled task calling `ts collect --sources api --commit` | S |
| B-049 | sub-resource hook on the source registry | M |
| B-005, B-006, B-007, B-008 | dashboard from `status.json`; media mirroring and transcripts through the sub-resource hook; Factba.se spot checks | M each |
| B-010 (D-006) | desktop Python upgrade; drop the 3.9 constraint and the matrix job | S |
| B-040 | watchdog workflow filing the doctor verdict as an issue | S |
| retire the old entry points | `python -m scripts.<x>` prints a one-line pointer to the verb, then is removed | S |

Acceptance: `coverage.presumed_live_count == 0`, `v_confidence.cnn_dedup_risk` count 0, and the four
mission numbers in `STATUS.md` show the change.

## 5. Ordering inside a phase

Within a phase, do the items in the order listed; each was placed after the items it reads. Two rules of
thumb: touch each file once per phase (the three merge loops change in B-014, B-011, B-019, and B-106, so do
those together), and land the doc corrections (C1 to C33) in the same pull request as the code that makes
them true.

## 6. The task benchmark (how we know it worked)

Six tasks, each timed as reads, writes, network requests, and wall clock, before and after each phase. The
"before" column is from the 2026-09-12 audit (`09-economy.md`).

| Task | Before | Target after phase |
|---|---|---|
| Orient: is it healthy, what changed, what is pending? | 3 data files + 1 doc, about 1,800 tokens | 1 file, about 600 tokens (phase 0) |
| Diagnose a red run to a root cause | 4 files + the Actions console, about 3,500 tokens; often impossible from a sandbox | `ts doctor` + one artifact, about 800 tokens (phase 1) |
| Reproduce a red run offline | not possible | `ts replay --from-raw`, under 1 minute (phase 1) |
| Regenerate one deletion | 6 files read, 3 hand edits, no receipt | one command with `--dry-run`, an intervention record (phase 1) |
| Answer "how many deletions within an hour in August, and how sure?" | build, query, read build_db.py for column meaning, answer 0 (wrong: every lower bound is creation time; the floor is 76 min) | after phase 0: `lifetime_lo_min`/`hi_min` make the interval visible; after phase 2: `ts ask deleted_within --start 2026-08-01 --end 2026-08-31 --param minutes=60` returns 0 confirmed, 6 possible, 0 excluded, with the detection floor and the lookback gap as caveats |
| Add a fourth source | about 14 files and 25 literal sites by hand; an unregistered host is paced at 0 s; a forgotten rank table raises KeyError | `ts scaffold source` writes the registry entry, stubs, fixture slot, dossier stub; a parser and a fetch function are the only hand-written code (phase 2) |
| Add a record field | 12 files and about 20 sites; a required field fails the hard check for all 37,002 records | one schema property with `x-` keys plus a migration; `ts repair migrate` rewrites the data with a receipt (phase 1) |

## 7. What this plan does not do

- It does not change the record shape, the precedence rules, or the deletion semantics. The vision is about
  legibility and control, not about the data model (which the audit found sound).
- It does not add a dependency to the pipeline. The stdlib validator, the dispatcher, and the situation
  builder are small Python files.
- It does not require the maintainer to change how the bot commits, beyond adding `STATUS.md` to `git add`
  and reading the structured summary.
