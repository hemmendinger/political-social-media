# Decision index (seed for knowledge/decisions/)

One line per decision; each becomes a `D-nnn-<slug>.md` from `templates/decision.md`. Accepted decisions
are the six one-liners from `docs/OPERATIONS.md` section 6 plus the out-of-repo plan; proposed decisions are
the two from OPERATIONS section 7 plus those this vision raises. `STATUS.md` lists proposed ones under
Pending until their status changes.

| Id | Title | Status | Date | Context in one line | Recommendation |
|---|---|---|---|---|---|
| D-000 | The original approved plan governs where SPEC is silent | accepted | 2026-09-11 | SPEC.md says the design rationale lives outside the repo | write a one-page summary of what still governs into the record; everything else is superseded by `docs/agentic-vision/` |
| D-001 | Text files in git are the truth; SQLite is derived | accepted | 2026-09-11 | cloud jobs can write text safely; every change is a readable diff | keep |
| D-002 | trumpstruth is the deletion record | accepted | 2026-09-11 | the only free source that timestamps removals; the API only says 404 | keep; the dossier holds the caveats (March 2026 horizon, upper bound) |
| D-003 | Deletions are intervals, never points | accepted | 2026-09-11 | no source observes the moment itself | keep; `v_confidence.wide_interval` makes the width visible |
| D-004 | A losing source never overwrites; provenance per field | accepted | 2026-09-11 | every value must be explainable | keep; D-016 extends it |
| D-005 | Hard checks block commits; soft checks stay visible | accepted | 2026-09-11 | a broken parser must never poison main | keep; the registry adds meaning and playbooks |
| D-006 | Python 3.9 syntax everywhere | accepted | 2026-09-11 | the desktop runs the Windows Store 3.9 build | keep until B-010 |
| D-007 | CNN download cadence | proposed | 2026-09-11 | every 2 h is 240 MB/day and drives engagement growth; the archive is a backstop | daily at 09:00 UTC plus `--force-cnn`; with B-025 |
| D-008 | Role of the api collector given the cloud 403 | proposed | 2026-09-11 | it cannot run from GitHub; it is the only way to do B-003 | keep, desktop-only by profile; cloud never probes; monthly canary records whether the block persists |
| D-009 | Wire or remove the trumpstruth total check | proposed | 2026-09-12 | `trumpstruth_totals` has no caller; docs present the check as live | wire it: one stats-page request per run; it is the only completeness signal independent of the API |
| D-010 | Stop committing `output/posts.csv` | proposed | 2026-09-12 | 12.7 MB rewritten per run; pure derivation of `data/` | untrack; `ts build --csv` on demand; weekly release asset if a URL is wanted |
| D-011 | Schemas live at the repo root `schemas/` | proposed | 2026-09-12 | check_data imports `RECORD_FIELDS` from merge.py today and build_db keeps its own field list; docs generate from the schema | accept |
| D-012 | Branch protection on `main` | proposed | 2026-09-12 | the bot commits every 30 min; a force push would lose data | enable, allowing the bot's linear pushes; maintainer setting |
| D-013 | Drop pandas from `requirements.txt` | proposed | 2026-09-12 | imported by nothing; installed on every cloud run | move it to the existing `requirements-dev.txt` (which today holds `-r requirements.txt` and `pytest`) |
| D-014 | Commit successful legs when one leg fails | proposed | 2026-09-12 | today exit 1 skips the commit and discards the other legs' work | commit when checks pass; the run record carries the failed leg; `health` goes yellow |
| D-015 | One dispatcher (`scripts/ts.py`) as the control surface | proposed | 2026-09-12 | seven entry points, no structured output, no dry-run, no cost line | accept; the old entry points stay until phase 2 |
| D-016 | The anomaly ledger records losing values and winning overwrites of non-empty values | proposed | 2026-09-12 | today a higher-ranked overwrite leaves no trace; a lower-ranked disagreement is computed then discarded | accept; expected volume is small; `anomaly_rate` guards regressions |
| D-017 | Removed-search window policy | proposed | 2026-09-12 | the search filters by post creation date; the 14-day window misses removals of older posts (35 of 98 known deletions were older than 14 days at removal) | search since 2022-01-01 on every run while the previous full total fits in one page of 100 (today's cost exactly), else 14 days daily plus the full window weekly; record the sweep on the run record |
| D-018 | Split `state.json` per source | proposed | 2026-09-12 | one file holds three actors' memory and every bot commit rewrites it | `data/state/<source>.json` plus `meta.json`; a migration writes the split (B-071) |
| D-019 | The desktop appends observations; it never rewrites month files | proposed | 2026-09-12 | desktop api legs rewrite the same files the bot rewrites; their engagement rows were lost to the throttle | `data/observations/api/YYYY-MM.jsonl`, union-mergeable, folded by the next collect anywhere (B-070) |
| D-020 | Resurrection keeps the deletion fields | proposed | 2026-09-12 | the merge flips deleted to present on an api live sighting and keeps deleted_lower/upper/source; a hard check on that state would block commits on every resurrection | keep the fields as evidence, record the anomaly event, fire the soft check present_with_deletion_fields; `explain` shows both |
| D-021 | raw_api storage policy | proposed | 2026-09-12 | raw_api averages about 2.3 KB per record; a full API backfill would add about 86 MB to the month files | keep inline for deleted records only; store the rest under data/raw/api/<ts_id>.json with a sha256 on the record, gitignored, refetchable |
