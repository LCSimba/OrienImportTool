"""Operator-text normalisation — clean noisy CMMS comments before matching.

Operator downtime comments are noisy: typos (``beraing``), abbreviations
(``c/v``, ``t/end``), inconsistent casing, and colloquialisms. This module
cleans them *before* any classifier sees them, so the alias and embedding
matchers work on cleaner input.

The generalising idea: correct operator text **toward the FMEA vocabulary
itself**. The FMEA + ISO 14224 + component descriptions form a clean,
authoritative dictionary; we fuzzy-match operator tokens against it and only
correct when a token is close to a known domain term. Tokens that are neither
known nor close are left untouched and surfaced as abbreviation-mining
candidates. No per-asset hand-curation of the dictionary — it's whatever
Equipment tree you loaded.

Pipeline position: ``normalize -> alias-expand -> classify``.
"""

from orien_import_tool.textnorm.abbreviations import (
    AbbreviationStore,
    build_initial_abbreviations,
    harvest_inline_abbreviations,
)
from orien_import_tool.textnorm.dictionary import DomainDictionary, build_domain_dictionary
from orien_import_tool.textnorm.miner import (
    AbbreviationProposal,
    AbbreviationProposalBatch,
    LLMAbbreviationMiner,
)
from orien_import_tool.textnorm.normalizer import (
    Correction,
    NormalizationResult,
    TextNormalizer,
)
from orien_import_tool.textnorm.pipeline import normalize_event, normalize_events
from orien_import_tool.textnorm.spell_engine import PySpellEngine, SpellEngine

__all__ = [
    "AbbreviationProposal",
    "AbbreviationProposalBatch",
    "AbbreviationStore",
    "Correction",
    "DomainDictionary",
    "LLMAbbreviationMiner",
    "NormalizationResult",
    "PySpellEngine",
    "SpellEngine",
    "TextNormalizer",
    "build_domain_dictionary",
    "build_initial_abbreviations",
    "harvest_inline_abbreviations",
    "normalize_event",
    "normalize_events",
]
