# Orien Import Tool

Reliability knowledge platform. Ingest FMEA exports from Orien Tactics, normalize them against ISO 14224, and use the resulting taxonomy to classify noisy, operator-entered downtime text with a feedback loop between ML, LLMs, and human SMEs.

## Goal

Turn high-quality FMEA reasoning that already lives in Orien Tactics into a working classifier for the messy reality of plant-floor downtime logs, and feed corrections back into both the taxonomy and the model.

## Scope (one paragraph)

The system ingests an Orien Tactics FMEA export, builds a canonical Equipment / Function / Failure-Mode hierarchy, lets reliability engineers enrich it (criticality, detection, missing modes), maps it to ISO 14224, and exposes it as supervised seeds plus an alias store. A pipeline ingests free-text downtime events, extracts components and failure modes with deterministic alias matching plus an ML classifier, asks an LLM to review low-confidence predictions, queues the rest for SMEs, and recycles every correction into the alias store and training set.

## Documentation

- [`docs/requirements.md`](docs/requirements.md) — functional and non-functional requirements, traceability matrix
- [`docs/architecture.md`](docs/architecture.md) — context diagram, stakeholders, logical components, key flows, interfaces
- [`docs/data-model.md`](docs/data-model.md) — canonical domain entities, relationships, invariants
- [`docs/ml-pipeline.md`](docs/ml-pipeline.md) — seed generation, classifier, LLM roles, active learning, metrics
- [`docs/decisions.md`](docs/decisions.md) — open questions, recommended choices, risk register

## Status

Architecture phase. No implementation yet. Open questions in `docs/decisions.md` should be resolved before code begins.
