# Open Questions & Recommended Decisions

These need answers before implementation begins. Each item carries a recommendation that becomes the default unless overridden.

## D-1 Tech Stack
- **Recommendation:** Python (FastAPI), Postgres + pgvector, S3-compatible object storage. ML in PyTorch / HuggingFace. UI in TypeScript / React.
- **Rationale:** ML / LLM ecosystem is Python-native; Postgres handles relational + JSONB + vector needs in one engine; React aligns with the workbench and queue UX.
- **Alternatives:** .NET if existing plant systems are Microsoft-stack; Streamlit for a faster MVP UI at the cost of polish.

## D-2 Deployment
- **Recommendation:** Containerized; cloud-hosted; Anthropic API for the LLM. Per-tenant DB schema.
- **Open:** offline plant-floor mode? If yes, the classifier must run on-prem and LLM calls become opt-in.

## D-3 Orien Tactics Export Format
- **Open:** what does Orien actually produce? CSV, XML, Excel, proprietary archive? A sample export will harden the importer (FR-1).
- **Action:** request a fixture export and a schema description before parser work starts.

## D-4 Scale Target
- **Open:** number of plants, equipment units, events / month?
- **Default sizing:** 1 plant, ~50 equipment units, 100k events / month — fits a single Postgres instance and a small GPU.

## D-5 Real-time vs Batch Downtime
- **Recommendation:** batch first (hourly), stream later if latency demands it.
- **Rationale:** batch keeps ops simple and is enough for analytical use; streaming adds infra and observability cost without obvious early payoff.

## D-6 Multi-tenant
- **Recommendation:** single-tenant deployment per plant; plant-scoped aliases. Multi-tenant only if a clear customer pattern emerges.

## D-7 ISO 14224 Source
- **Open:** license the standard tables or build a curated subset?
- **Recommendation:** build a working subset from the public taxonomy levels and the failure-mode list, document deviations explicitly. License full tables only if needed for compliance reporting.

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
| _pending_ | _to be filled as decisions land_ | | |
