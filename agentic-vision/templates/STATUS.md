# STATUS  (generated {{meta.generated_at}} by run {{meta.run_id}}, profile {{meta.profile}}, commit {{meta.commit}})

HEALTH: {{health.verdict|upper}}  — {{health.reasons|join(", ")}}
MISSION: completeness {{mission.completeness.value}} / ~{{mission.completeness.reference}} API ({{mission.completeness.note}})  |  deletion latency median {{mission.deletion_latency.value}} min (30 d)
         provenance: 2-source {{mission.provenance.two_source_share}}, api-verified {{mission.provenance.api_verified_share}}  |  honesty flags: presumed-live {{mission.honesty.presumed_live}}, guessed-handle {{mission.honesty.guessed_handle}}

FRESHNESS: newest post {{freshness.newest_post_at}} ({{freshness.age_min}} min ago)  [ok < 12 h]
{{#each freshness.sources}}
  {{name|pad 12}} {{last_leg.ok|okword}}  {{age_min}} min ago  {{last_leg.requests}} req  +{{last_leg.new}} new  {{last_leg.updated}} updated   {{last_leg.notes}}
{{/each}}

DRIFT:
{{#each drift}}
  {{name|pad 30}} {{value}}  (threshold {{threshold}}, background {{expected_background}}, 7 d trend {{trend_7d}})  {{verdict}}
{{/each}}

CHECKS FIRING:
{{#each checks.hard}}
  HARD {{name}} = {{value}}   reading: {{reading}}   verb: {{playbook}}
{{/each}}
{{#each checks.soft}}
  soft {{name}} = {{value}}   reading: {{reading}}   verb: {{playbook}}
{{/each}}
{{#if checks.none}}  none{{/if}}

PENDING:  P0 backlog: {{pending.backlog_p0|ids_or_none}}.  Open interventions: {{pending.interventions_open|ids_or_none}}.  Open decisions: {{pending.decisions_open|ids_or_none}}

LAST CHANGE (since run {{last_change.since_run}}): +{{last_change.new_posts}} records, {{last_change.updated_posts}} updated, {{last_change.deletions_found}} deletions, {{last_change.anomalies}} anomalies, checks {{last_change.checks_summary}}.

NEXT: {{next|join("; ")}}

---
## Last 5 runs
{{#each runs_recent}}
- {{run_id}} {{profile}} {{health}} | {{legs|legline}}
{{/each}}

## Last 10 anomalies
{{#each anomalies_recent}}
- {{detected_at}} {{kind}} {{ts_id}} {{field}} kept {{kept}} dropped {{dropped}}
{{/each}}

## Open backlog
{{#each backlog_open}}
- {{id}} {{priority}} {{title}} (cost {{cost.build}}; blocked_by {{blocked_by|join(",")|or "none"}})
{{/each}}

## Mission, 30 days
completeness    {{sparkline.completeness}}
deletion latency {{sparkline.deletion_latency}}
2-source share  {{sparkline.two_source_share}}

## Links
AGENTS.md · knowledge/sources/{api,trumpstruth,cnn}.md · knowledge/decisions/ · knowledge/lessons/ · knowledge/backlog.json · scripts/check_data.py (registry) · `ts help`
