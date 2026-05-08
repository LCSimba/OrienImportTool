# Architecture

## Context Diagram

```
       Orien Tactics ─────► [FMEA Importer] ─┐
                                              │
   CMMS / Historian ─────► [Downtime Adapter]─┼──► Canonical Store ──► API / UI
                                              │             │
       LLM Provider ◄─────► [LLM Reviewer] ◄──┤             ├──► Reports / Exports
                                              │             │
       SME (browser) ◄────► [Workbench] ◄─────┤             ▼
       SME (browser) ◄────► [Annotation Queue]┘       Model Registry
                                                            ▲
                                                  [Training Pipeline]
```

System boundary: everything in brackets plus the Canonical Store, Model Registry, and Training Pipeline. Orien, CMMS, the LLM provider, and the SME browser are external.

## Stakeholder → Function Mapping

| Stakeholder | Primary Functions Used |
|---|---|
| Reliability Engineer | FR-1, FR-2, FR-3, FR-4 |
| Maintenance Planner | FR-4, FR-10 |
| Operator | FR-6 (indirect, via CMMS) |
| SME / Failure Analyst | FR-9 |
| Data / ML Engineer | FR-7, FR-8, FR-9 |
| Plant Manager | FR-10 |

## Logical Components

1. **Importers**
   - `orien-adapter` — parses an Orien Tactics export and emits canonical FMEA events.
   - `downtime-adapter` — ingests CSV / API downtime, emits raw events with provenance.
   - Adapters sit behind an `ImportPort` interface so additional sources do not touch the core.

2. **Canonical Store**
   - Equipment hierarchy, FMEA, ISO 14224 mappings, aliases, downtime, classifications, annotations, model runs.
   - Append-only audit log for all mutations (NFR-1).

3. **Enrichment Workbench (UI)**
   - SME edits criticality, detection, and missing failure modes.
   - Side-by-side ISO 14224 mapping editor with LLM-suggested mappings.

4. **Classification Pipeline**
   - Stages: preprocess → alias match → ML classifier → LLM review → confidence merge → route.
   - Each stage independently versioned; runs in batch or stream.

5. **Annotation Queue**
   - Active-learning queue surfaced to SMEs.
   - Decisions update the alias store and the training set.

6. **Training & Model Registry**
   - Versioned datasets (DVC or content-hashed snapshots).
   - Models registered with metrics; promoted only via a quality gate.

7. **API & Reporting**
   - Read API for dashboards.
   - Export endpoints for ISO 14224-compliant outputs.

## Key Flows

### Flow A — FMEA bootstrapping
1. RE drops an Orien Tactics export → Importer parses → Canonical Store.
2. Workbench shows the hierarchy for review; RE adds criticality, detection.
3. ISO 14224 mapper proposes mappings (rule + LLM); RE confirms or overrides.
4. Alias seed list auto-generated from FMEA strings; RE prunes obvious noise.

### Flow B — Downtime classification
1. Downtime adapter ingests new events.
2. Pipeline runs: alias match → ML → LLM review.
3. High-confidence predictions auto-tagged; low-confidence routed to the queue.
4. SME corrections flow back into the alias store and the training set.

### Flow C — Continuous improvement
1. Drift monitor flags a per-class metric drop.
2. Retraining is triggered from the latest annotated set.
3. Candidate model evaluated against a held-out set; promoted only on gate pass.
4. New aliases proposed by the LLM are reviewed by SMEs before activation.

## Interfaces (initial)

- `ImportPort.parse(blob) → CanonicalFmea`
- `DowntimePort.ingest(batch) → [DowntimeEvent]`
- `ClassifyPort.classify(event) → [Prediction]`
- `ReviewPort.review(event, predictions) → LlmCritique`
- `AnnotationPort.submit(decision) → AnnotationResult`
- `MappingPort.propose(equipment | failure_mode) → [Iso14224Suggestion]`

These ports let us swap adapters and models without touching the core domain. They are the natural seam for contract tests.

## Cross-Cutting Concerns

- **Audit** — every mutation goes through a single write-path that emits an audit record.
- **Provenance** — all ML and LLM outputs reference the run / model / prompt that produced them.
- **Configuration** — criticality matrices, confidence thresholds, and alias scopes are versioned config, not code.
- **Idempotency** — importers and ingest paths are keyed on natural identifiers so re-runs converge.
