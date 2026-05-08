# Data Model

Conceptual model. Persistence choice deferred (see `decisions.md`). The intent is to keep the domain model independent of the eventual storage technology.

## Entities

### Equipment
- `id`, `parent_id` (nullable, self-FK)
- `machine_type`, `name`, `tag`, `iso14224_node_id`
- N-level hierarchy; ISO 14224 mapping attached at each node.

### Function
- `id`, `equipment_id`, `description`

### FunctionalFailure
- `id`, `function_id`, `description`

### FailureMode
- `id`, `functional_failure_id`, `description`
- `severity`, `occurrence`, `detection`, `rpn`
- `criticality_class` (enriched)
- `iso14224_failure_mode_id` (nullable, with `unmapped` flag if absent)

### FailureCause
- `id`, `failure_mode_id`, `description`

### FailureEffect
- `id`, `failure_mode_id`, `scope` (local / system / plant), `description`

### DetectionMethod
- `id`, `failure_mode_id`, `method`, `effectiveness`

### RecommendedAction
- `id`, `failure_mode_id`, `action`, `interval`

### Term / Alias
- `term_id` (canonical reference), `text`, `language`, `kind` (component | failure-mode | function)
- `alias_id`, `term_id`, `text`, `kind` (spelling | abbreviation | slang | code)
- Optional `equipment_scope_id` for context-specific aliases.

### Iso14224Mapping
- `id`, `source_entity_type`, `source_entity_id`, `iso_node_id`
- `confidence`, `rationale`, `version`, `proposer` (rule | llm | sme)

### DowntimeEvent
- `id`, `asset_id`, `start_ts`, `end_ts`, `duration_s`, `text`
- `raw_payload_id`, `source_system`, `external_id`

### Classification
- `id`, `event_id`, `failure_mode_id`, `score`, `model_run_id`
- `auto_accepted` (bool), `llm_critique_id` (nullable)

### Annotation
- `id`, `classification_id`, `sme_user_id`, `decision` (accept | reject | correct)
- `corrected_failure_mode_id` (nullable), `note`, `ts`

### ModelRun
- `id`, `model_name`, `version`, `dataset_hash`, `metrics`, `created_at`, `promoted_at`

### LlmCritique
- `id`, `model`, `prompt_hash`, `response`, `agree` (bool), `suggested_aliases` (jsonb), `ts`

### AuditLog
- `id`, `actor`, `action`, `entity_type`, `entity_id`, `before`, `after`, `ts`

## Relationships

```
Equipment (tree)
  └─ Function
       └─ FunctionalFailure
            └─ FailureMode ──► Iso14224Mapping
                 ├─ FailureCause
                 ├─ FailureEffect
                 ├─ DetectionMethod
                 └─ RecommendedAction

Term ──► Alias (n)
  └─ optional scope: Equipment subtree

DowntimeEvent ──► Classification ──► Annotation
                       │
                       └─► LlmCritique
                       ▲
                  ModelRun
```

## Invariants

- Every `FailureMode` either has an explicit `iso14224_failure_mode_id` or carries an `unmapped` flag — no silent gaps.
- Aliases are unique within `(text, language, scope)`.
- Every `Classification` references a `ModelRun` for reproducibility (NFR-2).
- `AuditLog` captures all writes; the domain has no "stealth" mutation paths.
- Mappings are versioned: corrections create a new mapping row, never overwrite.

## Identity & Versioning

- Use deterministic IDs (e.g. UUIDv7) for portability across environments.
- Soft deletion via `deleted_at` for entities that participate in historical reports; hard delete only via admin path with audit entry.
- Schema migrations versioned and forward-only; transformation steps logged.

## Notes on Persistence

- A relational store (Postgres) fits the tree, FK, and audit needs; JSONB handles flexible Orien payloads and LLM critiques.
- Vector store (pgvector or external) needed for embedding-based alias search (FR-5.2).
- Raw imports go to object storage with the row referencing the blob hash (FR-1.3).
