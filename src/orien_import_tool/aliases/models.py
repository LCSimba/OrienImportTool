"""Alias dataclass and proposer enum."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AliasProposer(StrEnum):
    """Where the alias came from."""

    RULE = "rule"
    LLM = "llm"
    SME = "sme"


@dataclass(frozen=True, slots=True)
class Alias:
    """Maps an operator-vocabulary term to one or more canonical FMEA tokens.

    ``alias_text`` is normalised lowercase. ``canonical_tokens`` are tokens
    that already appear in the seed index — the classifier just unions them
    into the event's token set before scoring.

    ``scope_equipment_token`` lets an alias be active only within an Equipment
    subtree. ``None`` means global.

    ``iso_hint`` is an optional, free-text reference to the ISO 14224 code
    the alias conceptually targets — purely for SME review readability,
    ignored by the classifier.
    """

    alias_text: str
    canonical_tokens: tuple[str, ...]
    proposer: AliasProposer
    confidence: float = 1.0
    scope_equipment_token: str | None = None
    iso_hint: str = ""
    rationale: str = ""
