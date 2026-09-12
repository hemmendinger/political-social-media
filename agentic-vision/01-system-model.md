# 01. System model: the tower of abstractions and the one vocabulary

This is the map. Every other document is a floor of this tower. Read it once; afterwards, `AGENTS.md` (the
door) and `STATUS.md` (the situation) are the only two files a session must read.

## 1. What the system is, in one paragraph

An epistemic engine. Unreliable, partial, differently-timed observations from three sources are turned into a
single belief state about one account's posts: which exist, which existed and were removed, when, what they
said, and how sure we are. The belief state lives in git as text, is checked against invariants on every
change, and is projected into views for analysis. Every belief carries provenance; every change carries a run
id or an intervention id; every contradiction between sources is kept as an anomaly rather than resolved by
overwriting. The engine runs itself every thirty minutes in the cloud, and is driven by people and agents from
the desktop and from sandboxes. The mission is completeness, correctness, and honesty about uncertainty, at the
lowest cost in requests, minutes, and attention.

## 2. The tower

Ten layers, bottom to top. Each row says what the layer is, what artifacts realize it today, what the vision
adds, and the single artifact through which the layer above sees it ("legible via"). Laws are from
`00-principles.md`.

| # | Layer | Definition | Today | Vision adds | Legible via |
|---|---|---|---|---|---|
| 0 | **Evidence** | Raw bytes from a source at a moment: URL, time, status, body. Immutable. | `tests/fixtures/*` (frozen captures with a README); `Context.raw_dir` declared, never used | `data/raw/<run_id>/<name>` rolling capture (gitignored, kept 7 days); uploaded as a workflow artifact when a run is red; a fixture bundle manifest (`tests/fixtures/manifest.json`) with URL, capture date, and what each proves | an **Observation** names the evidence file it came from |
| 1 | **Observation** | What one source claimed at one time, parsed into fields. Pure function of evidence. | parser "partials": dicts with `_source`, plus `_engagement` (api, cnn), `retruthed` (listing cards), `account` (trumpstruth) | the name `Observation` for the concept; `observed_at` and `url` carried on every partial; parse-time anomalies emitted as events (other account: today a count and a state list; yield below min: today a `ParseError`) | `ts explain <ts_id>` lists the observations behind a record |
| 2 | **Belief** | The current merged record for one post, with per-field provenance and the deletion interval. | `data/posts/YYYY-MM.jsonl` records (SPEC section 2); `field_sources`; `merge_partial` | `schemas/post-record.schema.json` as the source of truth; `confidence` as a derived view, not a stored field | the record itself; `ts explain` |
| 3 | **Invariant** | A predicate the belief state must satisfy (hard) or should satisfy (soft), plus stats to watch. | `check_data.run_checks`, `output/checks.json` strings, OPERATIONS section 4 tables written by hand | a **check registry**: each check carries a `CheckDescriptor` (why, condition, threshold, reading, playbook, since, expected background); `checks.json` becomes objects; the OPERATIONS table is generated | `STATUS.md` shows every firing check with its reading and its playbook verb |
| 4 | **Ledger** | Append-only event logs: what happened, when, by whom. | `runs/*.jsonl` (per run and source), `deletions.jsonl`, `engagement/*.csv`; failed runs leave no trace on `main` | `anomalies.jsonl` (stops the current leak: `MergeResult.anomalies` is discarded by every collector), `interventions.jsonl` (repairs, resets, hand edits, with reason and undo), `incidents/<run_id>.json` (a failed run's record, committed even when its data is not), `observations/api/*.jsonl` (the desktop's sightings, folded by the next collect) | `ts status` summarizes the last 24 h of each ledger; `ts explain` filters them by `ts_id` |
| 5 | **View** | Derived, disposable projections for analysis. | `data/truths.sqlite`, `v_posts_et`, `v_deletions`, `v_engagement_latest`, `output/posts.csv`, `output/metrics.json`, `output/checks.json` (written by every run), `output/reports/*.md` (by `weekly.py` on the desktop), `queries/*.sql` | columns generated from a registry that names each one's bound; `v_confidence` (per-post evidence flags and grade), `v_coverage` (per-source and per-signal windows, detection floor, last sweep), a generated data dictionary, every metric carrying computed `caveats`, named questions with answer envelopes | `ts ask`, `ts query`, `ts report`; the data dictionary |
| 6 | **Verb** | A named operation with declared inputs, outputs, side effects, network, and cost. | six `python -m scripts.<x>` entry points with their own flags | one dispatcher `python -m scripts.ts <verb>` with a fixed vocabulary, `--json`, `--dry-run`, an output envelope, a cost line, and a `next` hint; profiles and guard rails | `ts help` (generated from the verb registry) and `03-verbs.md` |
| 7 | **Situation** | The state of the whole system right now, and what changed since last time. | pieces spread across `checks.json`, `metrics.json`, `state.json`, run rows, and the commit message | `output/status.json` and `STATUS.md`, regenerated every run; a commit-message protocol that makes `git log` a timeline | `STATUS.md` is the first file read after the door |
| 8 | **Knowledge** | What the system knows about its sources, its own history, and its open questions. | `docs/SPEC.md`, `docs/OPERATIONS.md`, `TODO.md`, `MISTAKES.md`, `tests/fixtures/README.md`, `docs/dead-code-review.md`, out-of-repo plan | `knowledge/decisions/D-*.md` (status, enforced_by, reversal_signal), `knowledge/lessons/L-*.md` (each linked two ways to a test), `knowledge/sources/<source>.md` dossiers with addressable quirks `Q-<src>-<nn>`, `knowledge/backlog.json`, `knowledge/audits/` with dispositions, `knowledge/measurements.jsonl`; knowledge trailers on commits; coherence tests that fail when knowledge and code disagree | `AGENTS.md` links every knowledge artifact by purpose |
| 9 | **Mission** | Why the system exists, as measurable objectives. | one sentence in the README | a `MISSION` section in `AGENTS.md` with four measured objectives (below) reported in `status.json` | the four numbers at the top of `STATUS.md` |

### The four mission numbers

Everything in the tower exists to move these. They are reported in `status.json` on every run so that an
agent can tell whether its work moved the mission.

1. **Completeness**: share of the account's posts we hold. Proxy today: `present + deleted` against the API's
   `statuses_count` and trumpstruth's total (both drift; the dossiers explain why).
2. **Deletion latency**: median width of the deletion interval (`deleted_upper - deleted_lower`) for deletions
   found in the last 30 days. Narrower is better; the floor is the polling interval.
3. **Provenance coverage**: share of records with at least two sources, and share verified live by the API
   (`last_verified_live_at` not null).
4. **Honesty**: number of records whose uncertainty flags are set (presumed-live, guessed handle, single
   source, engagement baseline only), reported, never hidden.

## 3. The one vocabulary

Canonical term, definition, and the existing words it replaces. Code identifiers keep their current names
where renaming would churn the tests; the vocabulary governs docs, verbs, file names, and new code.

| Term | Definition | Replaces / disambiguates |
|---|---|---|
| **source** | One of `api`, `trumpstruth`, `cnn`. Always the short name. | `archive`, `CNN-hosted Stiles archive`, `collect_archive` (module keeps its name; verbs say `cnn`) |
| **evidence** | A captured raw response (fixture or `data/raw`). | `fixture` (a frozen, documented piece of evidence), `raw response` |
| **observation** | A parsed claim from one source at one `observed_at`. | `partial`, `partial record` |
| **record** | The merged current belief about one post. | `post` (the real-world thing), `row` (a database row) |
| **post** | The real-world status on Truth Social. A record is about a post. | |
| **signal** | An observation field that changes existence: `removed` (trumpstruth), `api_404` (api), or a live sighting (api 200). | `deletion signal`, `resurrection` |
| **interval** | The deletion interval `[deleted_lower, deleted_upper]`. | `bounds`, `window` (the width, in minutes, is `deletion_window_min`) |
| **event** | One line of a ledger: deletion event, engagement snapshot, run record, anomaly, intervention. | `row`, `entry`, `line` |
| **run** | One invocation of `collect` with one `run_id`. A run has one **leg** per source. | `run row` (now: run record, one per leg) |
| **check** | A named invariant: `hard` (blocks commit), `soft` (recorded), or `stat` (a number). | `integrity check`, `soft metric`, `stats-only` |
| **anomaly** | A contradiction between sources that the merge kept instead of resolving. | `disagreement`, `MergeResult.anomalies` |
| **intervention** | A deliberate non-routine change to data or state, with a reason and an undo. | `hand edit`, `one-off script`, `repair` (the verb that performs one) |
| **verb** | A named operation of the dispatcher. | `script`, `entry point`, `CLI` |
| **profile** | Where the agent is running and what it may do: `cloud`, `desktop`, `sandbox`. | `GitHub`, `runner`, `the PC`, `locally` |
| **situation** | The whole-system state as written to `status.json` / `STATUS.md`. | `health`, `state` (reserved for `state.json`, the per-source cursors) |
| **state** | `data/state.json`: per-source cursors and memory. Never the situation. | |
| **lesson** | A dated, structured entry about something that went wrong, linked to its test. | `mistake`, `MISTAKES.md` entry |
| **decision** | A dated record of a choice with status. | `open decision`, `design decision`, `the approved plan` |
| **dossier** | The per-source knowledge file. | `source notes`, the Sources table in the README, MISTAKES "data anomalies (source side)" |
| **backlog item** | A structured piece of known, unscheduled work with evidence and acceptance. | `TODO`, `deferred feature`, `known issue` |
| **bound** | A derived number's relation to the truth: `exact`, `lower`, `upper`, `interval`. Every view column and answer states its bound. | `lifetime_min` (an upper bound under a point name) |
| **verdict** | The result of a predicate over an interval: `confirmed`, `possible`, `excluded`. | a count |
| **detection floor** | The narrowest interval a signal can resolve, measured from its ledger (deletions: 76 min). | |
| **coverage window** | The span in which a source or signal could have observed something (history start, polling since, removal tracking since, search lookback). | `blind spot` (README); `horizon`, the vision's own word for the earliest instant a class of event is observable at all |
| **lookback gap** | Events an incremental collector structurally misses (removals of posts older than the search window). | |
| **caveat** | A named flag with scope (record or window), a count or value, and one sentence, attached to an answer as data. | the static Caveats paragraph |
| **evidence grade** | `A` api-verified, `B` two or more sources, `C` single source. | |
| **question** | A named, versioned analysis with parameters, unit, bound, and golden answer (`ts ask`). | `saved query`, `starter SQL` |
| **incident** | The committed record of a run that did not land, with legs, error, checks, fingerprints, and a diagnosis. | `red run` |
| **failure class** | One of the fixed diagnoses `ts doctor` can return. | |
| **leg phase** | Where inside a leg something happened (`listing`, `resolve:<id>`, `removed_search:<range>:page<n>`, ...). | |
| **fingerprint** | The structural summary of a page a parser depends on (classes, keys, counts), stored per fixture and compared on every fetch. | `canary` (a weekly live comparison), `drift` (the difference) |
| **budget** | The per-host request cap inside one leg; exhaustion is a recorded truncation. | `cap` (a module constant or a `run()` parameter default; cnn has none) |
| **sweep** | One removed-search window actually covered by a leg, recorded on its run record. | |
| **seam** | Records whose UTC month partition and Eastern analysis day disagree. | |
| **forget** | The pure inverse of a merge signal on one record (`forget_deletion`, `forget_source`); a repair is forget, then re-observe. | `edit-in-place`, `one-off script` |
| **re-observation** | A targeted fetch of one page by its own id, merged like any observation, to refill what was forgotten. | |
| **retraction** | A ledger line removed by a repair, copied verbatim into the intervention record. | `delete the line` |
| **lease** | `data/lease.json`, committed, with holder and expiry; the cloud collector exits without writing while it is unexpired. What other actors must see lives in git with an expiry; the local **lock** (pid liveness, gitignored) is only this machine's. | `pause`, `.lock` shared through git |
| **capability manifest** | `profiles.json`, tracked: per profile, the hosts, api access, data writes, commit rights, repair rights, and default data root. | prose tables of what each profile may do |
| **observation ledger** | `data/observations/<source>/YYYY-MM.jsonl`: idempotent sightings appended by an actor that must not rewrite records, folded by the next collect anywhere. | |
| **carry-forward set** | Provenance a rebuild cannot regenerate (`first_seen_*`, which are write-once; `last_verified_live_at`, which only grows; event `detected_at`) extracted before a rebuild and re-applied after. | |
| **deleted** vs **removed** | `deleted` is our belief (`status`). `removed` is trumpstruth's word for its own signal. Docs say deleted; only the trumpstruth dossier and parser say removed. | |
| **present** vs **live** | `present` is our belief. `live` means verified by the API at a time (`last_verified_live_at`). Archive-only records are present but not verified live. | `presumed live` |

## 4. How the layers link (the reading moves)

An agent moves through the tower with a fixed set of questions, each answered by one artifact:

| Question | Move | Artifact |
|---|---|---|
| Is the system healthy? | start at 7 | `STATUS.md` (first screen) |
| Why is that check firing? | 7 to 3 | the check's descriptor (reading, playbook) shown inline in `STATUS.md` |
| Which records does it concern? | 3 to 2 | `ts check --json` lists ids; `ts explain <ts_id>` |
| Why does this record say that? | 2 to 1 to 0 | `ts explain` shows observations, their sources, times, URLs, and the anomalies kept |
| What did the last run do? | 7 to 4 | run records and the last 24 h of ledgers in `status.json` |
| Who changed this and why? | 4 | `interventions.jsonl`, then `git log` for the commit |
| What can I do about it? | 3 to 6 | the playbook verb named by the descriptor; `ts help <verb>` |
| What will it cost? | 6 | the verb's cost line, or the backlog item's cost block |
| Has this happened before? | 8 | `knowledge/lessons/` (by component) and the source dossier |
| Is this decided? | 8 | `knowledge/decisions/` (by status) |
| Did my work matter? | 9 | the four mission numbers, before and after |

## 5. Module map (where the layers live in code)

The code already separates the layers well; the vision keeps the module boundaries and adds a thin control
layer.

```
scripts/
  common.py          layer 0-1 plumbing: Clock, Transport, Http, Context, time helpers
  parsers.py         layer 1: evidence -> observation (pure)
  merge.py           layer 2: observation + record -> record, anomalies, deletion event (pure)
  store.py           layers 2 and 4: the only module that reads or writes data/
  collect_*.py       layer 1-4 orchestration per source (a leg)
  check_data.py      layer 3: the check registry and run_checks
  build_db.py        layer 5: data/ -> sqlite views
  metrics.py         layer 5: sqlite -> JSON-able metrics with caveats
  weekly.py, query.py  layer 5 renderers
  collect.py         layer 6 today; becomes the `collect` verb
  ts.py              layer 6 dispatcher (new): verbs, envelope, profiles, guards
  situation.py       layer 7 (new): builds status.json and STATUS.md from layers 3-5 and 8
  explain.py         layer 2/4 (new): the evidence trail for one record
  ask.py, caveats.py layer 5 (new): the question registry and the caveat registry
  sources.py         layers 1-4 (new): the source registry (ranks, hosts, signals, state defaults) and the shared Leg
  schema.py          layer 2 (new): derives RECORD_FIELDS (the field list), SCALAR_FIELDS (the rule-3 subset), defaults, and columns from schemas/
  migrate.py         layer 2 (new): ordered schema migrations applied by repair migrate
  replay.py          layer 0-4 (new): runs the pipeline against a fixture bundle with a FakeClock
schemas/             layer 2-7 shapes (JSON Schema)
knowledge/           layer 8
AGENTS.md            the door
STATUS.md            layer 7, generated
```

## 6. What "coherent, cohesive, modular, interconnected" mean for this tower

- **Coherent**: one vocabulary (section 3) and one set of laws. A term means the same thing in a check name,
  a verb name, a schema field, and a doc heading.
- **Cohesive**: each layer has one job and one artifact type. Parsers do not merge; the store does not check;
  checks do not repair; the situation does not decide.
- **Modular**: a layer can be replaced without touching the others (a fourth source is one registry entry,
  a parser, a fetch function, a dossier, and a bundle; nothing else changes because the schema and the
  registries are the seams, and `ts scaffold` writes the entry and the stubs).
- **Interconnected**: every artifact links up (why it matters) and down (what it is made of) by id: a check
  names its playbook verb; a lesson names its test and its dossier; a backlog item names its check; an
  intervention names its commit; a record names its observations; an observation names its evidence.
