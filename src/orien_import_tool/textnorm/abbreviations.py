"""Abbreviation / shorthand expansion for operator text.

Abbreviations differ from typos: ``c/v`` -> ``conveyor`` isn't a fuzzy match,
it's a learned shorthand. They need an explicit map rather than edit-distance
correction.

The seed map below covers domain-general mechanical / electrical maintenance
shorthand observed across CMMS exports. Dataset-specific shorthand (plant
jargon, local codes) is *mined* — the normaliser flags unknown frequent
tokens, an LLM proposes expansions, and an SME confirms them into the store
with ``proposer="sme"``. Same rule/llm/sme provenance model as the alias
store.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum


class AbbrevProposer(StrEnum):
    RULE = "rule"
    LLM = "llm"
    SME = "sme"


@dataclass(frozen=True, slots=True)
class Abbreviation:
    """One shorthand -> expansion mapping.

    ``short`` is matched case-insensitively against the raw whitespace token
    (so internal punctuation like ``c/v`` is preserved for matching). The
    ``expansion`` is substituted into the cleaned text verbatim.
    """

    short: str
    expansion: str
    proposer: AbbrevProposer = AbbrevProposer.RULE
    confidence: float = 1.0
    rationale: str = ""


# Domain-general mechanical / electrical maintenance shorthand. Lowercase keys.
_SEED: tuple[tuple[str, str], ...] = (
    ("c/v", "conveyor"),
    ("conv", "conveyor"),
    ("t/end", "tail end"),
    ("h/end", "head end"),
    ("d/end", "drive end"),
    ("n/end", "non drive end"),
    ("brg", "bearing"),
    ("brng", "bearing"),
    ("mtr", "motor"),
    ("gbx", "gearbox"),
    ("g/box", "gearbox"),
    ("elec", "electrical"),
    ("mech", "mechanical"),
    ("inst", "instrument"),
    ("repl", "replace"),
    ("repld", "replaced"),
    ("replcd", "replaced"),
    ("insp", "inspect"),
    ("maint", "maintenance"),
    ("temp", "temperature"),
    ("press", "pressure"),
    ("hyd", "hydraulic"),
    ("pneu", "pneumatic"),
    ("lube", "lubricate"),
    ("lub", "lubricate"),
    ("vibn", "vibration"),
    ("vib", "vibration"),
    ("freq", "frequency"),
    ("instr", "instrument"),
    ("unsch", "unscheduled"),
    ("fusable", "fusible"),
    ("fuseable", "fusible"),
    ("sw", "switch"),
    ("emerg", "emergency"),
    ("e/stop", "emergency stop"),
    ("p/pack", "power pack"),
    ("p/u", "pulley"),
    ("seq", "sequence"),
    ("u/speed", "underspeed"),
    ("o/load", "overload"),
    ("c/w", "complete with"),
    ("fbm", "fusable plug"),
    ("ctrl", "control"),
    ("comms", "communications"),
    ("dwg", "drawing"),
    ("qty", "quantity"),
)


class AbbreviationStore:
    """Holds abbreviations keyed by normalised shorthand."""

    def __init__(self) -> None:
        self._by_short: dict[str, list[Abbreviation]] = defaultdict(list)

    def add(self, abbrev: Abbreviation) -> None:
        key = abbrev.short.casefold()
        if not key:
            return
        for existing in self._by_short[key]:
            if existing.expansion == abbrev.expansion and existing.proposer == abbrev.proposer:
                return
        self._by_short[key].append(abbrev)

    def add_many(self, abbreviations: object) -> None:
        for abbrev in abbreviations:  # type: ignore[attr-defined]
            self.add(abbrev)

    def expand(self, token: str) -> str | None:
        """Return the highest-precedence expansion for ``token``, or None.

        Precedence: SME > LLM > RULE. Within a tier, first-added wins.
        """
        matches = self._by_short.get(token.casefold())
        if not matches:
            return None
        order = {AbbrevProposer.SME: 0, AbbrevProposer.LLM: 1, AbbrevProposer.RULE: 2}
        best = min(matches, key=lambda a: order[a.proposer])
        return best.expansion

    def __contains__(self, token: object) -> bool:
        return isinstance(token, str) and token.casefold() in self._by_short

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_short.values())

    def __iter__(self):
        for entries in self._by_short.values():
            yield from entries


def build_initial_abbreviations() -> AbbreviationStore:
    """Construct an :class:`AbbreviationStore` seeded with the rule-tier map."""
    store = AbbreviationStore()
    for short, expansion in _SEED:
        store.add(
            Abbreviation(
                short=short,
                expansion=expansion,
                proposer=AbbrevProposer.RULE,
                rationale="Domain-general CMMS shorthand",
            )
        )
    return store
