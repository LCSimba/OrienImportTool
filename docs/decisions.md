# Open Questions & Recommended Decisions

These need answers before implementation begins. Each item carries a recommendation that becomes the default unless overridden.

## D-1 Tech Stack — LOCKED
- **Decision:** Python (FastAPI), Postgres + pgvector, S3-compatible object storage. ML in PyTorch / HuggingFace. UI in TypeScript / React.
- **Rationale:** ML / LLM ecosystem is Python-native; Postgres handles relational + JSONB + vector needs in one engine; React aligns with the workbench and queue UX.

## D-2 Deployment
- **Recommendation:** Containerized; cloud-hosted; Anthropic API for the LLM. Per-tenant DB schema.
- **Open:** offline plant-floor mode? If yes, the classifier must run on-prem and LLM calls become opt-in.

## D-3 Orien Tactics Export Format — DOCUMENTED
- **Status:** fixture received. Schema captured in `tests/fixtures/orien/SCHEMA.md`.
- **Format:** `.xlsx` with two sheets — `r8DropdownValues` (controlled vocabularies) and `Single Sheet Tactics` (denormalized FMEA + tactics, 132 columns, rows 1-10 metadata header, row 9 machine-readable column names).
- **Stable identifiers:** `locationToken`, `structureToken`, `failureModeToken`, `activityToken` — basis for idempotent re-import.
- **Open follow-ups:** multi-location exports, `componentLibrary=true` exports, language variation, column-order stability across Orien versions — collect more fixtures over time.

## D-4 Scale Target
- **Open:** number of plants, equipment units, events / month?
- **Default sizing:** 1 plant, ~50 equipment units, 100k events / month — fits a single Postgres instance and a small GPU.

## D-5 Real-time vs Batch Downtime — LOCKED
- **Decision:** hourly batch ingestion. Streaming deferred until a concrete latency requirement appears.
- **Rationale:** batch keeps ops simple and is enough for analytical use; streaming adds infra and observability cost without obvious early payoff.

## D-6 Multi-tenant — LOCKED
- **Decision:** single-tenant, single-plant deployment. Aliases plant-scoped. Multi-tenancy reconsidered only if a clear second-plant requirement appears.

## D-7 ISO 14224 Source — RESOLVED
- **Decision:** use the curated CSVs in `data/iso14224/` (B2 mechanisms, B3 causes, B4 detection methods, B5 maintenance activities, B15 failure modes). Schema in `data/iso14224/SCHEMA.md`.
- **Coverage gap:** Annex A (equipment-taxonomy hierarchy) not in this set. Equipment ISO mapping is deferred until that table is added.
- B2 was re-emitted with the same hierarchical schema as B3 (`main_code, main_category, sub_code, sub_name, description`), making `sub_code` the unambiguous PK.

## D-8 LLM Provider
- **Recommendation:** Anthropic Claude. Sonnet for routine review; Opus for ambiguous escalations and FMEA-gap synthesis. Prompt caching on the failure-mode catalogue and ISO 14224 reference.

## D-9 Annotation UI
- **Recommendation:** lightweight bespoke queue UI; avoid Label Studio dependency to keep the loop tight and aligned with the canonical model.

## D-10 Identifier Strategy
- **Recommendation:** UUIDv7 across the canonical model so IDs are sortable and portable across environments.

## Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | Orien export schema undocumented or inconsistent | Med | High | Fixture suite, parser fuzzing, adapter contract tests |
| R-2 | ISO 14224 mappings disputed by SMEs | High | Med | Provenance + override + version every mapping |
| R-3 | Long-tail failure modes have no labels | High | Med | LLM few-shot + alias mining for the tail |
| R-4 | LLM cost spirals on large downtime volumes | Med | Med | Prompt caching, batch, route only low-confidence to LLM |
| R-5 | Drift unnoticed | Med | High | Drift monitor + scheduled SME audit |
| R-6 | Operator PII leaks into ML training | Low | High | Redaction at ingest |
| R-7 | Adapter rot (Orien format change) | Med | Med | Contract tests pinned to real fixtures |
| R-8 | Feedback bias from a small SME pool | Med | Med | Track inter-annotator agreement; rotate reviewers |

## Decision Log

| Date | Decision | Rationale | Owner |
|---|---|---|---|
| 2026-05-08 | D-1 Tech stack: Python + Postgres + React | ML-native ecosystem; single engine for relational + JSONB + vector; aligned with workbench UX | User |
| 2026-05-08 | D-5 Hourly batch downtime ingest | Simpler ops, sufficient for analytical use | User |
| 2026-05-08 | D-6 Single-tenant single-plant deployment | No multi-plant requirement on the table | User |
| 2026-05-08 | D-3 Orien export format documented | Fixture received; `tests/fixtures/orien/SCHEMA.md` is the parser contract | Claude |
| 2026-05-08 | D-7 ISO 14224 reference set adopted | User-provided B2/B3/B4/B5/B15 CSVs; Annex A deferred | User |
