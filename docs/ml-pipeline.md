# ML & Feedback Pipeline

## Seed Generation

**Inputs**
- Canonical FMEA: failure-mode strings, function strings, component strings.
- Alias store: SME-curated synonyms, abbreviations, codes.
- Optional: historical CMMS work-order text already labeled.

**Outputs**
- Labeled dataset: `(text, equipment_id, failure_mode_id)`.
- Per-class examples for few-shot prompting.

**Strategy** — every FMEA failure-mode string is a positive example for its label. Aliases multiply examples. Augment with operator-style template variation and back-translation if multilingual. Never let augmentation cross class boundaries.

## Pipeline Stages

```
[Raw downtime text]
   ↓ Preprocess (normalize, deunit, lowercase, strip codes)
[Normalized text]
   ↓ Alias matcher (deterministic, fast)
[Candidate labels + spans]
   ↓ ML classifier (transformer encoder, multi-label)
[Scored predictions]
   ↓ LLM reviewer (rationale, ISO consistency check, novelty flag)
[Final predictions + critique]
   ↓ Confidence policy
[Auto-accept]   or   [Annotation queue]
```

Stage outputs are persisted with the `ModelRun` reference so any decision can be replayed.

## ML Model Choice (initial)

- Encoder fine-tune (e.g. DeBERTa or a domain-adapted encoder) for multi-label classification, scoped per machine type.
- NER head for component span extraction (BIO tagging) trained from FMEA component strings + aliases.
- Per-machine-type heads with a shared backbone, to handle small per-class data without losing transfer.

The first iteration may be a pure alias-matcher baseline; the encoder is added once labeled volume justifies the cost.

## LLM Roles

1. **Reviewer** — given event text + top-k predictions, returns a structured critique (`agree`, `disagree`, `missing label`, `iso fit`).
2. **Alias miner** — given unmatched events, proposes new alias candidates linked to canonical terms.
3. **FMEA gap finder** — clusters of unclassified events drive proposals for new failure modes.
4. **Mapper assist** — proposes ISO 14224 mappings with rationale during enrichment.

LLM outputs are advisory until SME-confirmed (FR-8.4, FR-9). Prompts are versioned; cached on the failure-mode catalogue to control cost.

## Confidence Policy

- Combine alias-match exactness, classifier softmax, and LLM agreement into a single composite score.
- Auto-accept threshold per class, calibrated against held-out data — not a global cutoff.
- Below threshold → annotation queue. Mid-band → LLM review then re-decide. High band → auto-accept.

## Active Learning

- Queue prioritization: high uncertainty × high downtime impact × business-critical equipment.
- Batch SME review; corrections feed:
  - alias store (new terms / context-scoped synonyms)
  - training set (new labels and harder negatives)
  - prompt few-shot pool (LLM)

## Metrics

| Metric | Why |
|---|---|
| Precision / Recall / F1 per failure mode | Class-level quality |
| Coverage (fraction with confident label) | Operational usefulness |
| SME effort (queue throughput, correction rate) | Cost of the loop |
| Inter-annotator agreement (sampled) | Catch SME bias |
| Drift (KL divergence on predicted-class distribution) | Trigger retraining |
| LLM cost / 1k events | Budget guardrail |

## Retraining Triggers

- New annotated volume threshold (e.g. +N labeled events).
- Per-class F1 drop > X over Y events.
- New machine type onboarded.
- Manual trigger from the model registry.

## Risks (ML-specific)

- **Class imbalance** — long-tail failure modes; mitigate with focal loss + LLM few-shot for rare classes.
- **Concept drift** — operator vocabulary shifts; mitigate with periodic alias mining.
- **LLM hallucination** — never auto-accept LLM-only suggestions; always SME-gated.
- **Feedback bias** — SMEs may over-correct toward familiar classes; track inter-annotator agreement and rotate reviewers.
- **Leakage** — operator notes in the training set leaking into test set; enforce time-based splits.
