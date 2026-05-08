# Requirements

## Mission

Import FMEA data from Orien Tactics, enrich it with criticality and detection coverage, normalize it to ISO 14224, and use the result as supervised seed data to classify free-text downtime entries from operators. Improve continuously via SME feedback and LLM review.

## Stakeholders

| Stakeholder | Concerns | Interaction |
|---|---|---|
| Reliability Engineer (RE) | FMEA quality, traceability of changes | Owns FMEA import + enrichment workbench |
| Maintenance Planner | ISO 14224-compliant taxonomy, work-order linkage | Consumes mapped hierarchy |
| Operator | Quick downtime entry, no rigid forms | Source of free text |
| SME / Failure Analyst | Classification correctness | Annotates the queue |
| Plant Manager | Pareto reports, KPI accuracy | Consumes dashboards |
| Data / ML Engineer | Pipeline reproducibility, model drift | Owns training and registry |

## Context

External actors and systems:

- **Orien Tactics** — source of FMEA exports.
- **CMMS / Historian** — source of downtime events.
- **LLM provider** — review and alias mining (advisory).
- **ISO 14224 reference** — taxonomy and failure-mode codes.

System Under Design (SUD): the Orien Import Tool, comprising importers, canonical store, enrichment workbench, classification pipeline, annotation queue, and reporting.

## Functional Requirements

### FR-1 FMEA Import
- FR-1.1 Parse Orien Tactics export into a canonical FMEA model.
- FR-1.2 Validate schema; capture and surface parsing failures.
- FR-1.3 Preserve original source artifacts for audit.
- FR-1.4 Support re-import / diff against existing data.

### FR-2 Canonical FMEA Model
- FR-2.1 Represent Machine Type → Equipment → Component as an n-level hierarchy.
- FR-2.2 Capture Function → Functional Failure → Failure Mode → Cause → Effect.
- FR-2.3 Carry Severity, Occurrence, Detection scores and RPN where present.
- FR-2.4 Capture detection methods and recommended actions.

### FR-3 Enrichment
- FR-3.1 Apply a configurable criticality matrix (e.g. Severity × Probability).
- FR-3.2 Add or override detection methods.
- FR-3.3 Add failure modes not present in the original FMEA.
- FR-3.4 Record provenance (author, timestamp, source) for every change.

### FR-4 ISO 14224 Mapping
- FR-4.1 Map equipment hierarchy to ISO 14224 taxonomy levels.
- FR-4.2 Map failure modes to ISO 14224 failure-mode codes.
- FR-4.3 Allow many-to-one mappings with confidence and rationale.
- FR-4.4 Version mapping tables; never mutate historical mappings in place.

### FR-5 Alias / Seed Management
- FR-5.1 Maintain canonical terms with multiple aliases (misspellings, abbreviations, slang, codes).
- FR-5.2 Support exact, edit-distance, phonetic, and embedding-based matching.
- FR-5.3 Scope aliases globally and per machine-type / per plant.
- FR-5.4 Generate an initial alias seed list from FMEA text.

### FR-6 Downtime Ingestion
- FR-6.1 Ingest downtime events from CSV, file drop, and API.
- FR-6.2 Required fields: timestamp, asset reference, duration, free-text description.
- FR-6.3 Idempotent ingestion keyed on natural identifiers.
- FR-6.4 Quarantine malformed rows for review without blocking the batch.

### FR-7 ML Extraction
- FR-7.1 Identify the asset / component referenced in free text (span extraction).
- FR-7.2 Classify failure mode (multi-label) per event.
- FR-7.3 Emit per-prediction confidence.
- FR-7.4 Use FMEA + alias store as supervised seed labels.
- FR-7.5 Route low-confidence predictions to an active-learning queue.

### FR-8 LLM Review
- FR-8.1 LLM produces a natural-language rationale per prediction.
- FR-8.2 LLM suggests new aliases / failure modes from unmatched text.
- FR-8.3 LLM checks predictions for ISO 14224 consistency.
- FR-8.4 LLM responses are logged with prompt and model version; never auto-applied without SME confirmation.

### FR-9 Feedback Loop
- FR-9.1 SME accepts, rejects, or corrects predictions in the queue.
- FR-9.2 Corrections feed the alias store and the training set.
- FR-9.3 Track per-class precision / recall over time.
- FR-9.4 Trigger retraining on threshold (data volume or drift).

### FR-10 Reporting & Export
- FR-10.1 Pareto charts by failure mode, equipment, plant.
- FR-10.2 ISO 14224-compliant exports (CSV / XML).
- FR-10.3 Audit log of all manual edits and model decisions.

## Non-Functional Requirements

| ID | Requirement | Verification |
|---|---|---|
| NFR-1 | Auditability — every change traceable to user/system, timestamp, prior value | Audit-log review |
| NFR-2 | Reproducibility — ML runs reproducible from versioned data + code + config | Re-run from snapshot |
| NFR-3 | Throughput — sustain 100k downtime events / month / plant | Load test |
| NFR-4 | Latency — single-event classification under 2 s p95 | Benchmark |
| NFR-5 | Extensibility — new importers added without changing the core domain model | Adapter contract test |
| NFR-6 | Privacy — operator names and PII redactable at ingest | Schema review |
| NFR-7 | Internationalization — Unicode and multilingual aliases | I18n test set |
| NFR-8 | Resilience — partial parse failures do not block the rest of an import | Fault injection |

## Requirements Traceability (FR → Verification Owner)

| FR | Verification | Owner |
|---|---|---|
| FR-1 | Round-trip import test against fixture exports | Backend |
| FR-2 | Schema unit tests + sample FMEA validation | Backend |
| FR-3 | UI integration tests; provenance assertions | Frontend |
| FR-4 | Mapping-table snapshot tests; SME spot-check | RE |
| FR-5 | Alias matching benchmark (precision / recall) | ML |
| FR-6 | Ingest fixtures with known good and bad rows | Backend |
| FR-7 | Held-out test set per machine type | ML |
| FR-8 | LLM rationale audit by SME on sample | RE |
| FR-9 | Queue UX walkthrough; metric trend test | Frontend / ML |
| FR-10 | Report golden files; ISO 14224 schema lint | Backend |

## Verification Levels (V-model)

- **Unit** — parsers, mappers, alias matchers.
- **Integration** — adapter ↔ canonical store ↔ pipeline.
- **System** — end-to-end FMEA → classify → annotate → retrain.
- **Acceptance** — SME walkthrough on a real plant dataset; classification quality gates.
