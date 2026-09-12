# 00. Principles: what "agent-intuitive, agent-ergonomic, agent-accretive" mean here

This document defines the three words in the brief as testable properties, then states the design laws that
follow from them. Every later document in `agentic-vision/` cites these laws by number. If a proposal cannot be
traced to a law, it does not belong in the vision.

The agent in question is a language-model agent (Claude Code or similar) that arrives in the repository cold,
with a bounded context window, tool access to the shell and the files, sometimes network access and sometimes
not, and a mandate to produce accurate results with the least reading, the fewest requests, and the fewest
irreversible actions. Its scarce resources, in order: attention (tokens read), certainty (how sure it can be
that an action is correct), and reversibility (how cheaply a mistake can be undone). Its cheap resources: CPU,
disk, and repetition of deterministic steps.

## 1. Definitions

**Agent-intuitive.** The system is organized the way an agent reasons: from concepts to invariants to verbs to
goals. An agent that knows the concepts can predict the names of the invariants, and an agent that knows the
invariants can predict which verb repairs a violation. Nothing important is hidden in a place the agent would
not think to look, and nothing is named two ways.

Test: given only the vocabulary in `01-system-model.md`, can an agent guess the name and location of the
artifact it needs? If it has to grep to discover that a concept exists, the system is not intuitive there.

**Agent-ergonomic.** Every common task is a small number of steps with structured input and output, safe
defaults, a dry-run, and a cheap verification. State the agent needs is either in a file it will read first
or returned by the verb it just ran. Nothing important lives only in a log the agent cannot see (a GitHub
Actions console) or in a person's head.

Test: for each task in `10-migration-plan.md` section 6 (the task benchmark), count reads, writes, and
network calls. Ergonomics improves when the counts go down without accuracy going down.

**Agent-accretive.** Each interaction leaves the system more knowledgeable in a place where the knowledge will
be found next time by the mechanism that needs it. A fix produces a fixture, a test, a lesson, and a doc delta.
A discovery about a source lands in that source's dossier. A decision lands in a decision record. A backlog
item carries its evidence and its acceptance test. Anomalies the code detects are stored, not printed.

Test: after any change, ask "where will the next agent find out about this without being told?" If the answer
is "the commit message" or "the conversation", the knowledge leaked.

## 2. Design laws

Each law has a number, a statement, and the failure it prevents. The laws are ordered so that earlier ones
constrain later ones.

**Law 1. One vocabulary.** Every concept has exactly one canonical name, used identically in code, files,
docs, checks, and verbs. Synonyms are listed once, in the glossary, as deprecated.
Prevents: the agent reading `archive`, `cnn`, and `collect_archive` and wondering whether they are three
things. (Today: `archive`/`cnn`, `partial`/`record`/`row`, `removed`/`deleted`, `run row`/`run`.)

**Law 2. A tower, not a pile.** Artifacts are arranged in layers from raw evidence to mission. Each layer is
legible through exactly one artifact of the layer above it, and each layer is explained by the one below it.
An agent can start at any layer and move up ("why does this matter?") or down ("what is this made of?").
Prevents: five overlapping documents that each explain part of everything.

**Law 3. One door.** There is a single entry point for orientation (`AGENTS.md`) and a single entry point for
control (`python -m scripts.ts <verb>`). Both list everything else. The first sixty seconds of any session are
scripted: read the door, read the situation, act.
Prevents: the agent deciding, each session, which of seven scripts and five docs to read first.

**Law 4. The situation is an artifact.** The system's current state (health, freshness, drift, open anomalies,
pending work, open decisions, what changed last) is written to a file on every run, in both a machine form
and a human form. The agent never reconstructs the situation from logs, commits, and state files.
Prevents: 2,000 tokens of reading to answer "is it healthy?".

**Law 5. Verbs, not scripts.** Every operation is a named verb with a declared purpose, inputs, outputs, side
effects, network use, and cost. Every verb that writes has `--dry-run`. Every verb can emit `--json` in one
envelope shape. Every verb suggests the next verb.
Prevents: composing shell pipelines from memory; discovering side effects after the fact.

**Law 6. Structured out, structured in.** Anything the code computes for a human (a check, an anomaly, a
summary) is also stored as data with a stable schema. Prose is generated from data where the data exists,
never the other way around.
Prevents: information computed then lost (merge anomalies today), and docs that drift from code.

**Law 7. Schema is the source of truth.** The record shape, event shapes, state shape, and status shape are
JSON Schemas in the repo. Validation, database columns, CSV columns, and the documentation tables derive from
them. A test fails if any derived artifact disagrees with its schema.
Prevents: nine places that must agree when a field is added.

**Law 8. Provenance everywhere.** Every belief can be traced to the observations that produced it, and every
change to the data can be traced to a run or an intervention with a reason. `explain <ts_id>` must work for
every record, and `git log` must be readable as a timeline.
Prevents: an agent unable to tell a bug from a source quirk.

**Law 9. Uncertainty is first-class.** Where the record is uncertain (deletion intervals, presumed-live
archive-only posts, guessed handles, engagement snapshots, the March 2026 removal horizon), the uncertainty is a
field or a view, not a paragraph in a README, and every metric carries its caveats as data.
Prevents: confident wrong answers to analysis questions.

**Law 10. Deterministic replay.** The whole pipeline can run offline against a bundle of captured responses
and a fake clock, and produce byte-identical data. Any red run can be reproduced from its captured inputs.
Prevents: fixing production by guessing.

**Law 11. Safe by default, powerful by flag.** Defaults are the reversible, local, offline option: a scratch
data root in sandboxes, no network without `--live`, no commit without `--commit`, plan before apply for
repairs. The profile (cloud, desktop, sandbox) is detected and printed, and each profile has a capability
manifest.
Prevents: an agent collecting against production data by accident, or pushing over the bot.

**Law 12. Every intervention is an event.** Non-routine changes to data (repairs, resets, hand edits) are
recorded in an append-only ledger with actor, reason, plan, before/after, and undo. Git is the undo mechanism,
and the ledger says which commit to revert.
Prevents: the next agent not knowing why `max_trumpstruth_id` was lowered.

**Law 13. Knowledge has a home and a link.** Lessons link to the tests that encode them and to the source
dossier they inform. Decisions have status. Backlog items carry evidence and acceptance. Audits become backlog
items or they are discarded. Nothing important lives outside the repo.
Prevents: the "approved plan lives outside the repo" problem, and audits that are never acted on.

**Law 14. Cost is visible.** Every verb prints what it spent (requests, seconds, files) and every backlog
item and playbook step estimates what it will cost. An agent chooses the cheapest sufficient action because it
can see the prices.
Prevents: a full rebuild when a partial one would do; a 17-hour crawl started without knowing it is 17 hours.

**Law 15. Layered reading.** Documentation is tiered by cost: a one-screen door, a one-page map, then
reference documents that are generated where possible. No fact is stated in two tiers; the upper tier links
down. The agent reads the cheapest tier that answers its question.
Prevents: reading 800 lines to learn a field name.

**Law 16. Coherence is tested.** Tests assert that the docs match the code, the schema matches the record,
the check registry matches the OPERATIONS table, the verb list matches the dispatcher, the fixtures README
matches the fixture files, and the README's commands run. Knowledge cannot rot silently.
Prevents: README saying cron `*/30` while the workflow says `7,37`.

## 3. Anti-patterns (things this vision rejects)

- **The wiki.** Adding more prose documents. Prose is for rationale and narrative; facts live in data.
- **The framework.** Introducing a plugin system, a DSL, or a dependency to get structure. The existing
  injection points (`Clock`, `Transport`, `Context`, `MergeResult`, run records, checks.json, `field_sources`)
  are enough. The vision adds files and verbs, not layers of indirection.
- **The dashboard first.** A web dashboard before the situation artifact exists is a second place for the
  truth to drift from.
- **Silent caps.** Any truncation (500-character notes, 10 sample ids, 200 ids per run) is stated in the
  output that was truncated.
- **Confidence by omission.** A metric without its caveats object. A count of `present` posts without the
  presumed-live share.
- **Hand edits without a trace.** Editing `state.json` in an editor. Every such edit is a verb with a plan
  and an intervention record, even if the verb is `ts repair manual --note "..."`.
- **Knowledge in the conversation.** A decision or discovery that exists only in a chat transcript.

## 4. How to use these laws

When proposing a change to the system, state which law it serves and which anti-pattern it avoids. When two
proposals conflict, the one serving the lower-numbered law wins, because the laws are ordered from vocabulary
(cheapest to get right, most expensive to fix later) to testing (which presupposes everything before it).
