# 02. Situation: what the agent reads first

Serves Laws 4, 6, 14, 15. The situation is a generated artifact, written on every run by `scripts/situation.py`,
in two forms from one source: `output/status.json` (machine) and `STATUS.md` at the repo root (human, and
what an agent reads). It replaces the current practice of reconstructing the state from `checks.json`,
`metrics.json`, `state.json`, run records, and the commit message.

## 1. Design constraints

- **One screen.** `STATUS.md` fits in about 60 lines and 1,200 tokens. Everything below the first screen is a
  link, not content.
- **Answer the five questions in order.** Is it healthy? Is it fresh? Is it drifting? What is pending? What
  changed? Each is a section with a one-line verdict first and evidence second.
- **Every firing check carries its reading and its verb.** The descriptor (see `05-invariants-and-schema.md`)
  supplies both, so the agent never opens OPERATIONS to interpret a check.
- **Every number has a threshold and a trend.** A drift value alone is not information; `350 (threshold 365,
  7-day trend +4)` is.
- **Nothing is computed twice.** `situation.py` reads `checks.json`, the ledgers, `state.json`,
  `knowledge/backlog.yaml`, `knowledge/decisions/`, and `git`. It does not re-run checks or metrics.
- **Generated, never edited.** A coherence test fails if `STATUS.md` differs from a fresh render of
  `status.json`.

## 2. `output/status.json`

Schema: `schemas/status.schema.json`. Top-level sections, in reading order:

| Section | Content | Source |
|---|---|---|
| `meta` | `generated_at`, `run_id`, `profile`, `commit`, `schema_version` | the run |
| `health` | `verdict` (`green`, `yellow`, `red`) and `reasons[]`: red = a hard check fired, an incident record is newer than the last successful run, or the last run had a leg with `ok=false` for a source that was not expected to fail; yellow = a soft check outside its expected background, freshness past threshold, or schedule delivery under 50%; green otherwise | checks.json, incidents, run records, descriptors |
| `cadence` | `runs_expected_24h` (from the cron), `runs_actual_24h` (run records), `ratio`; GitHub delivered 2 of about 16 slots on the first day (B-024) | run records |
| `checkout` | `head`, `behind_bot_commits`, `behind_bot_minutes`, `bot_last_run` from `git` (after `git fetch` where the profile allows it), so a sandbox agent knows it is looking at stale data before editing anything the bot owns | git |
| `mission` | the four mission numbers with their previous value (last run) and 30-day trend | ledgers |
| `freshness` | `newest_post_at`, `age_min`; per source: `last_ok_at`, `age_min`, `last_leg` (`ok`, `requests`, `new`, `updated`, `notes`), `expected` (whether this source is expected to work in this profile) | run records, state.json |
| `drift` | each coverage stat with `value`, `threshold`, `expected_background`, `trend_7d` | checks.json stats over the last 7 days (kept in `output/history/checks-YYYY-MM-DD.jsonl`, one line per run) |
| `checks` | `hard[]`, `soft[]`, each `{name, value, threshold, reading, playbook, since_firing}` | checks.json + descriptors |
| `anomalies_24h` | counts by kind and the top three `ts_id`s per kind | anomalies.jsonl |
| `pending` | `backlog_p0[]`, `interventions_open[]` (status planned or applied but not verified), `decisions_open[]`, `incidents_open[]` (incident records newer than the last successful run) | knowledge/, data/incidents/ |
| `coverage` | `deletions_tracked_since`, `api_verified_share`, `two_source_share`, `presumed_live_count`, `guessed_handle_count` | records |
| `last_change` | `new_posts`, `updated_posts`, `deletions_found`, `anomalies`, `checks_started[]`, `checks_stopped[]`, `commit` | ts diff since previous run |
| `next` | one to three verbs, chosen by the same rules as `ts doctor` | derived |

## 3. `STATUS.md` layout

Rendered from `status.json` by a fixed template (`templates/STATUS.md`). The first screen:

```
# STATUS  (generated 2026-09-12T04:58Z by run 20260912T045806Z-7e76, profile cloud, commit 9b7af34)

HEALTH: YELLOW  — soft: single_source_recent_posts (53; background <=60), spike_days (2 days; real bursts); schedule delivery 12%
MISSION: completeness 36,997 / ~36,554 API (+443 archive-only)  |  deletion latency median 87.9 min (30 d)
         provenance: 2-source 83.1%, api-verified 0.05%  |  honesty flags: presumed-live 36,884, guessed-handle 1,172

INCIDENTS: none open.   CADENCE: 2 of 16 scheduled runs in 24 h (12%)   CHECKOUT: at bot head (0 behind)

FRESHNESS: newest post 2026-09-12T03:53Z (65 min ago)  [ok < 12 h]
  trumpstruth  ok  65 min ago   7 req  +4 new  6 updated   max_id 41698
  cnn          ok  65 min ago   1 req  +0 new  4 updated   etag unchanged
  api          skipped: profile cloud (Cloudflare 403; desktop only)      last live 2026-09-11T20:10Z

DRIFT:  present vs api statuses_count  350  (threshold 365, background ~350, 7 d trend +4)  ok
        cnn_ambiguous_handles          1,172 (B-001, shrinking only via repair resolve-handles)

CHECKS FIRING:
  soft single_source_recent_posts = 53   reading: a few dozen cnn-only reposts near the id-walk boundary are normal;
       a jump means a source is missing posts.   verb: ts doctor
  soft spike_days = 2026-07-26 (57), 2026-08-04 (69)   reading: real bursts; a parser duplicating cards would also land here
       (duplicate_id is clean).   verb: none

PENDING:  P0 backlog: none.  Open interventions: none.  Open decisions: D-002 (cnn cadence), D-003 (api collector role)

LAST CHANGE (since run 20260912T001255Z-5139): +4 records, 10 updated, 0 deletions, 0 anomalies, checks unchanged.

NEXT: nothing required.  (ts diff for details; ts doctor if anything above surprises you)
```

Below the first screen, in order and each one line per item: open incidents with their diagnosis, the last 5 runs (one line per run with its
legs), the last 10 anomalies, open backlog by priority, the four mission numbers as a 30-day sparkline in
text, and a link list (AGENTS.md, the dossiers, the check registry, the verb list).

## 4. Commit message protocol (the git log as a timeline)

The bot's message today: `collect: +4 posts, +0 deletions, checks ok`. The protocol keeps the first line
compatible and adds structure:

```
collect: +4 posts, +0 deletions, checks ok | health yellow | 8 req 15 s   <- first line: the old prefix stays grep-stable; health and cost make `git log --oneline` tier 0

run: 20260912T045806Z-7e76 profile=cloud health=yellow
legs: trumpstruth ok 7req +4/6 | cnn ok 1req +0/4 | api skipped(profile)
checks: soft single_source_recent_posts=53 spike_days=2
anomalies: 0
```

Human and agent commits use a prefix vocabulary that matches the layers: `verb:` (dispatcher or verb
changes), `parser:`, `merge:`, `check:`, `view:`, `situation:`, `knowledge:`, `repair: <intervention id>`,
`lesson: L-0xx`, `decision: D-0xx`. A coherence test does not enforce this; `AGENTS.md` asks for it.

## 5. History for trends

Git already holds every past `checks.json`, so trends can be read from history with `git log --format=%H:%ct
-- output/checks.json` and `git show <sha>:output/checks.json`, at zero growth. That works only where the
clone is deep enough (the cloud checkout fetches 50 commits, about a day at nominal cadence; a sandbox clone
may be shallower), so `situation.py` reads git when it can and otherwise `output/history/checks-YYYY-MM-DD.jsonl`,
a compact line per run `{run_id, generated_at, stats}` (about 2 KB per run) committed by the bot. Files older
than 90 days are folded into a monthly summary by `ts build`. `drift.trend_7d`, the cadence ratio, and the
mission sparklines come from whichever series is available, and `status.json` says which.

## 6. Where `status.json` is produced in the run

`collect.run_all` today ends with `check`, then exports. The vision inserts `situation.build()` after the
exports and before the summary line is written, so the commit that carries the data also carries the
situation that describes it. `ts status --refresh` calls the same function outside a run.
