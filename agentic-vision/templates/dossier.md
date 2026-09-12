---
source: api | trumpstruth | cnn
canonical_name: <the string used in seen_sources and field_sources>
role: <one line: what this source is trusted for>
precedence: <rank in SOURCE_RANK and CREATED_AT_RANK>
verified: YYYY-MM-DD
reachable_from:
  cloud: yes | no (<reason, e.g. Cloudflare 403>)
  desktop: yes | no
  sandbox: yes | no | unknown
rate_limit: <requests per minute and the pacing the client uses>
cost_per_run: <typical requests and seconds from data/runs>
fixtures:
  - tests/fixtures/<file>  # <what it proves>
parsers:
  - scripts/parsers.py::<function>
collector: scripts/collect_<x>.py
state_keys:
  - <key>: <meaning; who reads it>
---

# Source dossier: <name>

## What it is

Two to four sentences: who runs it, what it archives, its license, its update cadence.

## What it knows and does not know

| Capability | Yes / No / Partial | Note |
|---|---|---|
| New posts within minutes | | |
| Deletions with a timestamp | | |
| Reposts with their own id and time | | |
| Replies | | |
| Quotes distinguished from originals | | |
| Engagement counts | | |
| Media originals / mirrors | | |
| Edits | | |
| History before <date> | | |

## Quirks (facts about the world, each dated)

- YYYY-MM-DD: <quirk>. Evidence: <fixture or lesson id>. Handled by: <code path or merge rule>.

## Failure modes and what they look like

| Failure | Symptom in run records / checks | First move |
|---|---|---|

## Endpoints

| Purpose | URL pattern | Parameters honored | Notes |
|---|---|---|---|

## Open questions

- <what we have not verified about this source>
