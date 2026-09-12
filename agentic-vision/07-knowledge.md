# 07. Knowledge: where the system remembers, and how memory accretes

Serves Laws 13, 15, 16, and the "agent-accretive" definition. The repository already remembers well by the
standards of small projects (dated `MISTAKES.md`, a fixtures README that is an evidence log, a SPEC that is a
real contract). The leaks are structural: knowledge is stored as prose in files organized by document type
rather than by the thing the knowledge is about, and nothing links a lesson to the test that enforces it.

## 1. Layout

```
AGENTS.md                      the door (tier 0), at the repo root; templates/AGENTS.md is the draft
CLAUDE.md                      one line, `@AGENTS.md`, so Claude Code loads the door without a second copy
STATUS.md                      the situation (generated; see 02-situation.md)
knowledge/
  backlog.json                 structured work items (schema: backlog-item.schema.json); JSON because the stdlib-only pipeline reads it
  decisions/D-001-....md       decision records with status, enforced_by, reversal_signal (template: templates/decision.md)
  lessons/L-001-....md         dated lessons, each linked two ways to a test (template: templates/lesson.md)
  sources/api.md               one dossier per source, quirks with ids Q-<src>-<nn> (template: templates/dossier.md)
  sources/trumpstruth.md
  sources/cnn.md
  audits/<date>-<slug>.md      reviews and audits, each ending with a Disposition table (B-062)
  measurements.jsonl           dated numeric facts about the sources, written by the code that observes them (B-064)
docs/
  SPEC.md                      the module contract (kept; its fact tables become generated blocks rewritten in place)
  OPERATIONS.md                the playbook (kept; sections 2, 4, 5 carry generated blocks; section 5 recipes become verbs)
  agentic-vision/              this directory, moved under docs/ once the migration is underway
```

`TODO.md`, `MISTAKES.md`, and `docs/dead-code-review.md` are retired after their content is migrated (section
3); each is replaced by a two-line file pointing at its successor so old links still resolve. This migration is phase 0, not
phase 2: the seeds under `agentic-vision/knowledge-seed/` are the best-structured knowledge in the repository
and should be wired in before anything else is built on them (B-112).

## 2. Reading tiers (Law 15)

| Tier | File | Budget | Answers |
|---|---|---|---|
| 0 | `AGENTS.md` | 120 lines, about 1,000 tokens | what this is, the laws in ten lines, the verbs, the profiles, what never to do, where everything else is |
| 0 | `STATUS.md` first screen | 60 lines | the situation |
| 1 | `01-system-model.md` | one page | the tower and the vocabulary |
| 1 | `knowledge/sources/*.md` | one page each | everything known about one source |
| 2 | `docs/SPEC.md` (with its generated blocks) | reference | exact contracts |
| 2 | `docs/OPERATIONS.md` | reference | the playbook, as verbs |
| 3 | `knowledge/lessons/`, `knowledge/decisions/`, `knowledge/backlog.json` | on demand, by id | history and rationale |

No fact is stated in two tiers. Tier 0 links down; tier 3 links up (a lesson names its dossier).

## 3. Migrating what exists

| Today | Becomes | Notes |
|---|---|---|
| `MISTAKES.md` "Build" entries (heredoc failure x2, the 429 burst, the Capture Date bound) | `L-001` to `L-004` (L-005 is new) | L-003 (Capture Date is not a liveness bound) links to `tests/test_merge.py` and the `deletion-found` bundle; L-004 is the ReTruthed mislabel; L-002 (429) becomes a line in the api dossier rate-limit block |
| `MISTAKES.md` "Data anomalies (source side)" (7 entries) | quirk lines in the three dossiers, each dated with its fixture | these are facts about the world, not mistakes |
| `TODO.md` items 1 to 3 and the seven deferred features | `B-001` to `B-010` in `backlog.json` with acceptance and cost | B-001 (ambiguous handles) acceptance: `stats.cnn_ambiguous_handles.count == 0`; B-003 (historical deletions) blocked by D-008 |
| `OPERATIONS.md` section 6 (six one-line design decisions) | `D-001` to `D-006`, status accepted, dated 2026-09-11 | context and consequences filled from SPEC and README |
| `OPERATIONS.md` section 7 (two open decisions) | `D-007` cnn cadence, `D-008` api collector role, status proposed | both surface in `STATUS.md` pending until decided |
| `docs/dead-code-review.md` (an audit never acted on) | `knowledge/audits/2026-09-11-dead-code.md` with a Disposition table: `B-011` (share collector helpers), `B-012` (wire or remove `trumpstruth_totals`, decided by D-009), `B-013` (fixtures README rows), the rest dropped with a one-line reason | an audit either becomes work or is discarded on the record; a coherence test refuses an open audit older than 14 days |
| `11-doc-deltas.md` section 1 (this vision's own audit) | `knowledge/audits/2026-09-12-doc-deltas.md`, each C-item dispositioned to a phase-0 fix or a backlog id | the vision holds itself to its own rule |
| README "Sources" table and "Known blind spots" | dossiers | the README keeps a three-line pointer |
| `tests/fixtures/README.md` | `tests/fixtures/manifest.json` plus a generated README | `ts capture` appends to the manifest |
| the out-of-repo "approved plan" | `D-000` summarizing what of it still governs, status accepted; the rest is superseded by this vision | nothing important lives outside the repo |

## 4. The accretion loop

Every fix that touches a parser, the merge, a collector, or a check follows one loop, and `ts note` scaffolds
each step. The unit of accretion is the fix: one commit whose trailers index what it owes:

1. **Evidence**: `ts capture` (or `ts replay --from-raw`) saves the page that revealed the problem, with a
   `proves` line, into the manifest.
2. **Test**: a test or a bundle fails on the old code and passes on the new.
3. **Lesson**: `ts note lesson` creates `L-0nn` with `encoded_in` pointing at that test and `component` set;
   the test carries `@pytest.mark.lesson("L-0nn")` so the link is two-way (B-060). The coherence test fails
   if either direction is missing. A lesson marked `general: true` has its Rule rendered into the generated
   rules block of `AGENTS.md`, so remembering does not depend on knowing where to look.
4. **Dossier**: if the cause was source behavior, the quirk line goes into the dossier as `Q-<src>-<nn>` with
   the date, the manifest entry, and the code path that handles it; the lesson and the parser comment cite the
   id (B-061). Numbers go to `knowledge/measurements.jsonl`, never into prose (B-064).
5. **Backlog**: the item that tracked it is closed with `--evidence`, or a new item is opened for follow-up.
6. **Docs**: `ts dictionary --write` regenerates the blocks in place; hand-written prose changes only if a rule or a verb changed.

7. **Receipt**: the commit carries knowledge trailers (`Lesson: L-0nn`, `Quirk: Q-tt-02`, `Fixture: <file>`,
   `Backlog: B-0nn`, `Decision: D-0nn`, `Docs: <paths>`, or `Knowledge: none` with a reason); `ts verify` warns
   when a changed parser, merge rule, collector, or check has no receipt (B-063).

`ts verify` runs the coherence tests, so a lesson without a test, a fixture without a manifest entry, a
descriptor without a playbook, or an audit without dispositions cannot be pushed.

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
lines), conventions (Python 3.9, LF, commit prefixes, 8 lines). Two of its sections are generated blocks
(`05-invariants-and-schema.md` section 6): the verb list from the registry, and a rules block rendered from
lessons marked `general` and from accepted decisions, so a tooling lesson learned in one session binds the
next without anyone remembering to copy it. `CLAUDE.md` holds the single line `@AGENTS.md`. It is the only
document a session must read in full.
