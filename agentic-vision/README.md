# agentic-vision

A design for making this repository maximally legible to, and controllable by, an autonomous agent: one
vocabulary, one door, one control surface, one situation artifact, and a knowledge layer that accretes.
Written 2026-09-12 against commit `9b7af34`, after reading every module, test, data file, and document, and
after a ten-lens analysis of what an agent needs when driving the system cold.

The thesis in one sentence: **this system is an epistemic engine (unreliable observations become beliefs
with provenance and quantified uncertainty), and an agent drives it well when every layer of that engine,
from raw evidence to mission, is legible through exactly one artifact and every action leaves a trace where
the next agent will look.**

## Reading order

| # | File | What it settles | Read when |
|---|---|---|---|
| 0 | `00-principles.md` | definitions of agent-intuitive, agent-ergonomic, agent-accretive; sixteen design laws; anti-patterns | first |
| 1 | `01-system-model.md` | the tower of ten abstractions; the one vocabulary; how layers link; the module map | first |
| 2 | `02-situation.md` | `status.json` and `STATUS.md`; the commit-message protocol; trends | designing what an agent reads first |
| 3 | `03-verbs.md` | the dispatcher, the envelope, profiles and guard rails, twenty verbs | designing what an agent can do |
| 4 | `04-ledgers-and-provenance.md` | the anomaly leak and its fix; interventions; raw capture; `ts explain` | the accretive half of the data layer |
| 5 | `05-invariants-and-schema.md` | schemas as the contract; registries for sources, checks, metrics, verbs, questions; migrations; bounds, confidence, coverage, caveats, questions; coherence and property tests; generated blocks | the correctness half |
| 6 | `06-simulation-and-verification.md` | replay bundles; from a red run to a bundle; canaries; `ts verify` | before touching a parser |
| 7 | `07-knowledge.md` | layout and tiers; migrating the existing docs; the accretion loop; open decisions | before writing any doc |
| 8 | `08-roles-and-coordination.md` | cloud, desktop, sandbox; ownership; hazards; the never-do list | before running anything with side effects |
| 9 | `09-economy.md` | measured costs; reading costs before and after; cheap wins; repository growth | when choosing what to build first |
| 10 | `10-migration-plan.md` | four phases with items, acceptance commands, and a task benchmark | to start |
| 11 | `11-doc-deltas.md` | 37 corrections to the current docs (verified against the code) and the restructuring of each file | when editing the existing docs |

Supporting artifacts, all concrete enough to copy into place:

- `schemas/` — JSON Schemas for the post record (derived from SPEC section 2 and `merge.py`), anomaly and
  intervention events, the check descriptor, the backlog item, the status object, and the verb envelope.
- `templates/` — `AGENTS.md` (the door), `STATUS.md` (the rendered situation), and the decision, lesson,
  and dossier templates.
- `knowledge-seed/` — the knowledge layer already populated from what the repository knows today: three
  source dossiers, a 76-item structured backlog (migrating `TODO.md`, the dead-code review, and the
  2026-09-12 audit findings), 18 decisions (7 accepted, 11 proposed with recommendations), and 8 lessons.

## What was found along the way

The audit behind this design surfaced things worth knowing even if none of the vision is built:

- The removed search asks trumpstruth for posts *created* in the last 14 days (the site filters by creation
  date), so a removal of any older post is never seen: 35 of the 98 known deletions were older than 14 days
  at removal. The fix costs 0 to 4 requests per run. (`05` section 3, B-029, D-017)
- Every one of the 98 deletions has a lower bound equal to its creation time, the narrowest interval any
  source has resolved is 76 minutes, and `lifetime_min` is that upper bound under a point name; "deleted
  within an hour" returns a structural zero today. (`05` section 3, B-036)
- When a cloud run fails, its run record and checks file are never committed (the commit step is skipped),
  so the ledger on `main` records only successes and a sandboxed agent cannot tell a red run from a dropped
  schedule. (`04` sections 1 and 3b, B-030)
- Merge anomalies (source disagreements, resurrections, inverted bounds) are computed on every run and
  discarded by every collector; the README says they are logged. (`04`, B-014)
- The 1,172 "ambiguous handle" rows that head `TODO.md` are 1,157 self-reposts the parser already resolves
  by exact prefix plus 15 glued other handles, 8 of them already known; the P0 item was a 15-row problem
  misdirected by its own check definition. (B-054, B-001, L-008)
- The merge is monotone and has no inverse, so every repair today is edit-in-place through a one-off script,
  and a half-finished repair passes every hard check. (`03` Repair, B-050, B-051)
- A source is about 25 literal sites in six modules; an unregistered host is paced at 0 s; adding a
  required record field would fail the hard check for all 37,002 records with no migration path. (`05`
  sections 1.1 to 1.3, B-043 to B-045)
- A higher-ranked source's overwrite of a non-empty value leaves no trace; only the losing side is flagged,
  and then dropped. (`11` C14)
- `max_trumpstruth_id` is not persisted per id despite the docstring and SPEC; a crash mid-walk re-fetches.
  (B-015)
- GitHub delivered 2 of about 16 scheduled runs in the first day; the effective cadence was 2 to 5 hours.
  (`09` section 6, B-024)
- The blocked API probe spends 36 s of pure sleep per 6 h in the cloud; `pandas` is installed every run and
  imported by nothing; `posts.csv` (12.7 MB) is rewritten and committed every run. (`09` section 3)
- 33 places where the docs disagree with the code or each other, including the cron, the backfill cost, the
  `--backfill` flag's scope, and an inert check presented as live. (`11` section 1)

## How to use this directory

Start with phase 0 of `10-migration-plan.md`. Copy `templates/AGENTS.md` to the root and `schemas/` to
the root; wire the anomaly ledger; build `scripts/ts.py` and `scripts/situation.py`. Then move this
directory to `docs/agentic-vision/` and let `knowledge/backlog.yaml` (seeded from `knowledge-seed/`) carry
the plan forward, so that the plan and the backlog are one thing and `STATUS.md` shows what is pending.
