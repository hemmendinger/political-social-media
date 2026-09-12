---
id: L-000
date: YYYY-MM-DD
component: parsers | merge | store | collect_trumpstruth | collect_archive | collect_api | check_data | build_db | metrics | workflow | tooling | docs
source: api | trumpstruth | cnn | none
severity: data-wrong | data-missing | run-failed | wasted-effort
encoded_in:
  - tests/test_x.py::test_name      # the regression test that now prevents this
  - tests/fixtures/<file>           # the evidence captured
guards:
  - check_data:<check_name>         # a check that would fire if it happened again (or none)
links:
  - D-000 | B-000 | <commit sha>
---

# L-000: <one line, past tense, what went wrong>

## What happened

Three to six sentences, dated. State the wrong belief first, then how it was noticed, then the measured size
(how many records, which ids).

## Why it happened

The mechanism, not the blame. If a source behaves in a way we did not expect, state the source behavior as a
fact about the world so it can be moved into that source's dossier.

## What changed

Bullets, each naming a file. Code, tests, fixtures, docs, checks.

## Rule

One sentence an agent can apply without re-reading this lesson. It is copied verbatim into the relevant
dossier or into AGENTS.md if it is general.
