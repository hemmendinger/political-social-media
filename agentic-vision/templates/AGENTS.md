# AGENTS.md

A deletion-aware, provenance-rich record of @realDonaldTrump's Truth Social posts. Three sources are merged
into one belief per post with per-field provenance and a deletion *interval*, checked against invariants on
every change, stored as text in git (`data/` is the truth; SQLite is derived), and collected every 30 minutes
by GitHub Actions. This file is the door: read it in full, then `STATUS.md`, then act. Everything else is
linked from here.

## First sixty seconds

```
cat STATUS.md                         # health, freshness, drift, firing checks, pending work, what changed
python -m scripts.ts doctor           # only if STATUS is not green: the cause and the next verb
python -m scripts.ts help             # the verbs, with cost and side effects
```

## The rules that bind you here

1. One vocabulary: source = `api` | `trumpstruth` | `cnn`; observation (one source's claim), record (our
   belief), event (a ledger line), run (one `run_id`, one leg per source), check (`hard` | `soft` | `stat`),
   anomaly (a contradiction the merge kept), intervention (a deliberate data change with a reason).
2. Verbs, not scripts. Everything goes through `python -m scripts.ts <verb>`; every writing verb has
   `--dry-run`; every verb prints its cost.
3. Your profile decides what you may do (see table). Sandboxes never touch `main` or the real `data/`.
4. Nothing computed is lost: anomalies go to `data/anomalies.jsonl`, repairs to `data/interventions.jsonl`.
5. Uncertainty is data: deletion is an interval (every lower bound is creation time today; the floor is
   about 76 min); archive-only posts are presumed live; answer with `ts ask`, filter with `v_confidence`.
6. Schemas in `schemas/` are the contract; sources, checks, metrics, verbs, and questions are registries;
   the fact tables in the docs are generated blocks. `ts verify` fails if any of them disagree.
7. Every fix leaves evidence, a test, a lesson (`knowledge/lessons/`), and a dossier line
   (`knowledge/sources/`). `ts note` scaffolds them.
8. Python 3.9 syntax everywhere (the desktop runs 3.9; the cloud runs 3.12). LF line endings. Stdlib only in
   the pipeline.
9. Push only after `ts verify --quick` is green. One validated push beats three speculative ones.
10. When in doubt about a source's behavior, read its dossier before reading its parser.

## Profiles

| Profile | Detected by | Network | Writes `data/` | Commits `main` |
|---|---|---|---|---|
| `cloud` | `GITHUB_ACTIONS` | trumpstruth, cnn (api is blocked: Cloudflare 403) | yes | the bot's commit step only |
| `desktop` | `data/.profile-desktop` | all, including the api at ~6 req/min | yes | `--commit` on `collect` and `repair` |
| `sandbox` | otherwise | only with `--live` | only a scratch `--data-root` (`ts scratch`) | never; push a branch, open a pull request |

## Verbs

`status` `diff` `doctor` `explain <ts_id>` `check` `collect` `capture` `repair <plan>` `build` `query`
`ask <question>` `report` `dictionary` `verify` `replay <bundle>` `note` `scaffold` `pause` `scratch` `help` — one line each in `ts help`; full
specifications in `docs/agentic-vision/03-verbs.md`.

## Never

- Edit `data/posts`, `deletions.jsonl`, `engagement/`, `runs/`, `anomalies.jsonl`, or `state.json` by hand.
  Use `ts repair <plan> --apply --reason "..."`.
- Delete a ledger (`repair redo-history` moves to `data/.trash/`).
- Force-push or rebase `main`; the bot commits there every 30 minutes.
- Run `collect` against the real `data/` in a sandbox.
- Commit `data/raw/`, `data/truths.sqlite`, or scratch roots.
- Skip, disable, or quarantine a test to get green.
- Leave a fact about a source in a chat or commit message only; it goes in the dossier.
- Change a record field, a check name, a source, or a verb without its schema or registry entry (use `ts scaffold`).

## Where things are, by question

| Question | Read |
|---|---|
| What is the state right now? | `STATUS.md` (generated from `output/status.json`) |
| Why is a check firing and what do I do? | its line in `STATUS.md` (reading + verb); the registry in `scripts/check_data.py`; the generated check tables in `docs/OPERATIONS.md` section 4 |
| Why does this record say that? | `ts explain <ts_id>` |
| What happened in the last run? | `ts diff`; `data/runs/YYYY-MM.jsonl` |
| What is a source like, and how does it fail? | `knowledge/sources/<source>.md` |
| What fields does a record have? | `schemas/post-record.schema.json`; the generated table in `docs/SPEC.md` section 2 |
| What are the exact module contracts? | `docs/SPEC.md` |
| What is known but not scheduled? | `knowledge/backlog.yaml` (`ts status` shows P0) |
| What was decided, and what is open? | `knowledge/decisions/` (open ones appear in `STATUS.md`) |
| What went wrong before? | `knowledge/lessons/` (by component; each links to its test) |
| How do I reproduce a red run? | `ts replay --from-raw <artifact dir>`; bundles in `tests/bundles/` |
| How does the system fit together? | `docs/agentic-vision/01-system-model.md` |

## Conventions

- Commit prefixes: `collect:` (bot), `verb:`, `parser:`, `merge:`, `check:`, `view:`, `situation:`,
  `knowledge:`, `repair: <intervention id>`, `lesson: L-nnn`, `decision: D-nnn`.
- Tests: `pytest -q` (offline); `-m live` for canaries; `ts verify` before every push.
- Times: stored UTC `...Z`; analysis columns are America/New_York; day boundaries are Eastern.
- Ids: `ts_id` is an 18-digit string, sort numerically; `run_id` is `YYYYMMDDTHHMMSSZ-hex4`; interventions
  `int-...`, lessons `L-nnn`, decisions `D-nnn`, backlog `B-nnn`.
- The cron is `7,37 * * * *` UTC; Python 3.9 and 3.12 in CI. (A coherence test checks these two lines.)
