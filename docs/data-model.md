# Data Model

Conceptual model. Persistence choice deferred (see `decisions.md`). The intent is to keep the domain model independent of the eventual storage technology.

## Entities

### Equipment
- `id`, `parent_id` (nullable, self-FK)
- `machine_type`, `name`, `tag`
- N-level hierarchy. ISO 14224 equipment-taxonomy mapping (Annex A levels) deferred until taxonomy tables are added; not in the current `data/iso14224/` subset.

### Function
- `id`, `equipment_id`, `description`

### FunctionalFailure
- `id`, `function_id`, `description`

### FailureMode
- `id`, `functional_failure_id`, `description`
- `external_token` (Orien `failureModeToken`)
- `mechanism_text` — raw "X due to Y" string from Orien `mechanismAndCause`
- `what_text` — Orien `what`
- `severity`, `occurrence`, `detection`, `rpn`
- `criticality_class` (enriched)
- `custom_attributes` (jsonb) — for `Failure Mode.custom.*` Orien fields
- ISO 14224 mapping is multi-dimensional and lives in `Iso14224Mapping` (a single `FailureMode` typically has three rows: MODE / MECHANISM / CAUSE).

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

### Iso14224 Reference Tables (immutable seed data)
Loaded from `data/iso14224/*.csv` on bootstrap. Versioned by table; mappings reference the version they were created against.

- `Iso14224FailureMode` (B15) — `code` (= failure_mode), `description`
- `Iso14224FailureMechanism` (B2) — `sub_code` (PK, e.g. `1.1`), `main_code`, `main_category`, `sub_name`, `description`
- `Iso14224FailureCause` (B3) — `sub_code` (PK, e.g. `1.1`), `main_code`, `main_category`, `sub_name`, `description`
- `Iso14224DetectionMethod` (B4) — `code_number`, `method`, `description`, `examples`
- `Iso14224MaintenanceActivity` (B5) — `code_number`, `activity`, `description`, `use` (`C` | `P` | `C, P`), `examples`

### Iso14224Mapping (polymorphic)
- `id`
- `source_entity_type`, `source_entity_id` — what we are mapping (e.g. `FailureMode`, `Activity`, `DetectionMethod`)
- `dimension` (enum: `MODE` | `MECHANISM` | `CAUSE` | `DETECTION_METHOD` | `MAINTENANCE_ACTIVITY`) — selects the target ISO table
- `iso_entity_id` — FK into the table implied by `dimension`
- `iso_table_version` — which CSV version the mapping was made against
- `confidence` (0..1), `rationale`, `proposer` (`rule` | `llm` | `sme`)
- `superseded_by_id` (nullable) — versioning via supersession, never in-place updates
- Uniqueness: `(source_entity_type, source_entity_id, dimension, iso_entity_id)` for non-superseded rows

Typical row counts per source entity:
- Orien `FailureMode` → 3 mappings: `MODE` (B15), `MECHANISM` (B2), `CAUSE` (B3)
- Orien `Activity` → 1 mapping: `MAINTENANCE_ACTIVITY` (B5). **Always B5** — even for CM-technique activities (Vibration Analysis, Thermography, Oil/Fluid Analysis, Ultrasonic Testing), which map to B5:8 Test. B4 is reserved for detection metadata on discovered failures, not for activities.
- `DetectionMethod` (SME-entered fact on a failure record) → 1 mapping: `DETECTION_METHOD` (B4)

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
            └─ FailureMode ──► Iso14224Mapping (3×: MODE/MECHANISM/CAUSE)
                 ├─ FailureCause
                 ├─ FailureEffect
                 ├─ DetectionMethod ──► Iso14224Mapping (DETECTION_METHOD)
                 └─ RecommendedAction
                      └─ Activity ──► Iso14224Mapping (MAINTENANCE_ACTIVITY,
                                                       optionally DETECTION_METHOD)

Iso14224Mapping ──► one of:
  Iso14224FailureMode | Iso14224FailureMechanism | Iso14224FailureCause
  | Iso14224DetectionMethod | Iso14224MaintenanceActivity

Term ──► Alias (n)
  └─ optional scope: Equipment subtree

DowntimeEvent ──► Classification ──► Annotation
                       │
                       └─► LlmCritique
                       ▲
                  ModelRun
```

## Invariants

- Every `FailureMode` carries either an `Iso14224Mapping` row in each of `MODE`, `MECHANISM`, `CAUSE` dimensions, or an explicit `unmapped` flag per dimension — no silent gaps in any dimension.
- ISO 14224 reference tables are immutable from the application; updates land via new CSVs and a versioned reload.
- `Iso14224Mapping` rows are versioned via `superseded_by_id`; corrections never overwrite.
- Aliases are unique within `(text, language, scope)`.
- Every `Classification` references a `ModelRun` for reproducibility (NFR-2).
- `AuditLog` captures all writes; the domain has no "stealth" mutation paths.

## Identity & Versioning

- Use deterministic IDs (e.g. UUIDv7) for portability across environments.
- Soft deletion via `deleted_at` for entities that participate in historical reports; hard delete only via admin path with audit entry.
- Schema migrations versioned and forward-only; transformation steps logged.

## Notes on Persistence

- A relational store (Postgres) fits the tree, FK, and audit needs; JSONB handles flexible Orien payloads and LLM critiques.
- Vector store (pgvector or external) needed for embedding-based alias search (FR-5.2).
- Raw imports go to object storage with the row referencing the blob hash (FR-1.3).

## Mapping Notes from the Orien Export

Confirmed against `tests/fixtures/orien/SCHEMA.md` (single-equipment fixture):

- Orien provides stable tokens — `locationToken`, `structureToken`, `failureModeToken`, `activityToken` — these become the natural external keys on `Equipment`, `FailureMode`, `Activity`. Idempotent re-import (FR-1.4) keys on these.
- Orien's `mechanismAndCause` is a single combined string ("X due to Y") drawn from a curated 73-entry vocabulary. The canonical model represents this as a `FailureMode.mechanism` plus `FailureCause.description`, parsed from the combined string but kept linked back to the original token.
- Orien uses a `Failure Mode.custom.<Name>` column-naming convention. The canonical `FailureMode` carries a `custom_attributes` JSONB map for these without schema churn.
- The export is denormalized with up to 5 labour, 5 material, 5 cost line-items per activity. The canonical model normalizes these into per-row child tables (`ActivityLabour`, `ActivityMaterial`, `ActivityCost`).
- Some columns are present in headers but empty in real exports (`activityCode`, `costDescription*` in this fixture). The parser must tolerate this; the model treats them as optional.
- `componentLibrary` flag in row 7 of the metadata header may switch the export's semantics — flagged as an open unknown until a `true` fixture arrives.
