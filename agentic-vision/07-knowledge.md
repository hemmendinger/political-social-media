# 07. Knowledge: where the system remembers, and how memory accretes

Serves Laws 13, 15, 16, and the "agent-accretive" definition. The repository already remembers well by the
standards of small projects (dated `MISTAKES.md`, a fixtures README that is an evidence log, a SPEC that is a
real contract). The leaks are structural: knowledge is stored as prose in files organized by document type
rather than by the thing the knowledge is about, and nothing links a lesson to the test that enforces it.

## 1. Layout

```
AGENTS.md                      the door (tier 0), at the repo root; templates/AGENTS.md is the draft
STATUS.md                      the situation (generated; see 02-situation.md)
knowledge/
  backlog.yaml                 structured work items (schema: backlog-item.schema.json)
  decisions/D-001-....md       decision records with status (template: templates/decision.md)
  lessons/L-001-....md         dated lessons, each linked to a test (template: templates/lesson.md)
  sources/api.md               one dossier per source (template: templates/dossier.md)
  sources/trumpstruth.md
  sources/cnn.md
docs/
  SPEC.md                      the module contract (kept; sections 2, 3, 9 become links to generated files)
  OPERATIONS.md                the playbook (kept; sections 3, 4 become links; section 5 rewritten as verbs)
  generated/                   record.md, checks.md, verbs.md, state.md (from schemas and registries)
  agentic-vision/              this directory, moved under docs/ once the migration is underway
```

`TODO.md`, `MISTAKES.md`, and `docs/dead-code-review.md` are retired after their content is migrated (section
3); each is replaced by a two-line file pointing at its successor so old links still resolve.

## 2. Reading tiers (Law 15)

| Tier | File | Budget | Answers |
|---|---|---|---|
| 0 | `AGENTS.md` | 120 lines, about 1,000 tokens | what this is, the laws in ten lines, the verbs, the profiles, what never to do, where everything else is |
| 0 | `STATUS.md` first screen | 60 lines | the situation |
| 1 | `01-system-model.md` | one page | the tower and the vocabulary |
| 1 | `knowledge/sources/*.md` | one page each | everything known about one source |
| 2 | `docs/SPEC.md`, `docs/generated/*` | reference | exact contracts |
| 2 | `docs/OPERATIONS.md` | reference | the playbook, as verbs |
| 3 | `knowledge/lessons/`, `knowledge/decisions/`, `knowledge/backlog.yaml` | on demand, by id | history and rationale |

No fact is stated in two tiers. Tier 0 links down; tier 3 links up (a lesson names its dossier).

## 3. Migrating what exists

| Today | Becomes | Notes |
|---|---|---|
| `MISTAKES.md` "Build" entries (heredoc failure x2, the 429 burst, the Capture Date bound) | `L-001` to `L-004` (L-005 is new) | L-003 (Capture Date is not a liveness bound) links to `tests/test_merge.py` and the `deletion-found` bundle; L-004 is the ReTruthed mislabel; L-002 (429) becomes a line in the api dossier rate-limit block |
| `MISTAKES.md` "Data anomalies (source side)" (7 entries) | quirk lines in the three dossiers, each dated with its fixture | these are facts about the world, not mistakes |
| `TODO.md` items 1 to 3 and the seven deferred features | `B-001` to `B-010` in `backlog.yaml` with acceptance and cost | B-001 (ambiguous handles) acceptance: `stats.cnn_ambiguous_handles.count == 0`; B-003 (historical deletions) blocked by D-008 |
| `OPERATIONS.md` section 6 (six one-line design decisions) | `D-001` to `D-006`, status accepted, dated 2026-09-11 | context and consequences filled from SPEC and README |
| `OPERATIONS.md` section 7 (two open decisions) | `D-007` cnn cadence, `D-008` api collector role, status proposed | both surface in `STATUS.md` pending until decided |
| `docs/dead-code-review.md` (an audit never acted on) | `B-011` (share collector helpers), `B-012` (wire or remove `trumpstruth_totals`, decided by D-009), `B-013` (fixtures README rows), the rest dropped with a one-line note in the backlog file's `dropped` section | an audit either becomes work or is discarded on the record |
| README "Sources" table and "Known blind spots" | dossiers | the README keeps a three-line pointer |
| `tests/fixtures/README.md` | `tests/fixtures/manifest.json` plus a generated README | `ts capture` appends to the manifest |
| the out-of-repo "approved plan" | `D-000` summarizing what of it still governs, status accepted; the rest is superseded by this vision | nothing important lives outside the repo |

## 4. The accretion loop

Every fix that touches a parser, the merge, or a check follows one loop, and `ts note` scaffolds each step:

1. **Evidence**: `ts capture` (or `ts replay --from-raw`) saves the page that revealed the problem, with a
   `proves` line, into the manifest.
2. **Test**: a test or a bundle fails on the old code and passes on the new.
3. **Lesson**: `ts note lesson` creates `L-0nn` with `encoded_in` pointing at that test and `component` set.
   The coherence test fails if the test id does not exist.
4. **Dossier**: if the cause was source behavior, the quirk line goes into the dossier with the date and the
   fixture; the lesson links to it.
5. **Backlog**: the item that tracked it is closed with `--evidence`, or a new item is opened for follow-up.
6. **Docs**: generated files regenerate; hand-written tiers change only if a rule or a verb changed.

`ts verify` runs the coherence tests, so a lesson without a test, a fixture without a manifest entry, or a
descriptor without a playbook cannot be pushed.

## 5. Decisions: what needs deciding now

The vision surfaces these as `proposed` records so they appear in `STATUS.md` until the maintainer decides:

| Id | Question | Recommendation |
|---|---|---|
| D-007 | CNN download cadence (2 h vs daily) | daily at 09:00 UTC plus `--force-cnn` on demand; the etag already makes most fetches 304 |
| D-008 | Role of the api collector given the cloud 403 | keep, desktop-only by profile; never probe from cloud; the historical deletion backfill (B-003) depends on it |
| D-009 | Wire or remove the trumpstruth total check | wire: one stats-page request per run is cheap and the check is the only independent completeness signal besides the API |
| D-010 | Commit `output/posts.csv` (13 MB rewritten every run) | stop committing it; publish it as a release asset weekly from the desktop, or generate on demand with `ts build --csv` (see `09-economy.md`) |
| D-011 | Where the vision's schemas live | repo root `schemas/`, imported by `check_data` and `build_db` |

## 6. `AGENTS.md` (the door)

The draft is `templates/AGENTS.md`. Its sections, in order and with a line budget: what this is (5 lines),
the first sixty seconds (3 commands), the laws that bind an agent here (10 lines), the verbs (one line each),
the profiles and what each may do (a 3-row table), never do (8 lines), the map of files by question (15
lines), conventions (Python 3.9, LF, commit prefixes, 8 lines). It is the only document a session must read
in full.
