---
id: D-000
title: <short imperative or noun phrase>
status: proposed | accepted | superseded | rejected
date: YYYY-MM-DD
supersedes: null
superseded_by: null
area: sources | contract | verbs | situation | knowledge | coordination | economy
enforced_by: []          # tests or guard rails that make this decision hold, once accepted
reversal_signal: null    # the stat or check that would tell us this decision is wrong
blocks: []               # backlog ids waiting on this decision while proposed
---

# D-000: <title>

## Context

Two to six sentences. What situation forced a choice, and what constraints apply (rate limits, the 403 from
GitHub runners, Python 3.9 on the desktop, git as the database). Link the evidence: a lesson id, an anomaly
kind, a checks.json stat, a fixture file.

## Options considered

| Option | Cost | What it gives up |
|---|---|---|
| A. ... | S / M / L | ... |
| B. ... | ... | ... |

## Decision

One paragraph in the present tense: what the system does from now on.

## Consequences

- What becomes easier.
- What becomes harder or is now forbidden (name the guard rail that enforces it, if any).
- Which docs, checks, verbs, or schemas change (each one a file path).

## Reversal

How to undo this if it turns out wrong, and what signal would tell us it is wrong.
