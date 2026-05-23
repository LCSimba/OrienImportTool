"""Build the known-good domain dictionary from an Equipment tree + ISO catalog.

The dictionary is the *correction target* for the normaliser: operator tokens
are corrected toward these terms and only these. That keeps spelling
correction safe and asset-agnostic — we never invent a correction to a word
that isn't part of the reliability vocabulary we actually care about.

Terms are harvested from every text field that describes the equipment and
its failure modes, plus the ISO 14224 B15/B2/B3 vocabulary. Token frequency
is tracked so a future ranker can prefer common domain terms when several are
equidistant from a misspelling.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from orien_import_tool.domain.fmea import Equipment
from orien_import_tool.iso14224 import Iso14224ReferenceSet

_TOKEN_RE = re.compile(r"[a-z]+")


def _tokens(text: str) -> list[str]:
    """Alphabetic tokens, lowercased. Drops digits and punctuation."""
    return _TOKEN_RE.findall(text.casefold())


@dataclass
class DomainDictionary:
    """A set of known-good domain terms with frequencies.

    ``min_length`` terms shorter than this are excluded from fuzzy-correction
    targets (too many false matches on 2-3 letter words), though they remain
    valid "known" tokens so they're not flagged as unknown.
    """

    terms: set[str] = field(default_factory=set)
    frequencies: Counter[str] = field(default_factory=Counter)
    min_correction_length: int = 4

    def __contains__(self, token: object) -> bool:
        return isinstance(token, str) and token.casefold() in self.terms

    def __len__(self) -> int:
        return len(self.terms)

    def correction_targets(self) -> list[str]:
        """Terms long enough to be safe fuzzy-correction targets."""
        return [t for t in self.terms if len(t) >= self.min_correction_length]

    def add_text(self, text: str) -> None:
        for token in _tokens(text):
            self.terms.add(token)
            self.frequencies[token] += 1


def build_domain_dictionary(
    equipment: Equipment,
    iso_ref: Iso14224ReferenceSet | None = None,
    *,
    min_correction_length: int = 4,
) -> DomainDictionary:
    """Harvest known-good terms from the FMEA tree and (optionally) ISO catalog."""
    dictionary = DomainDictionary(min_correction_length=min_correction_length)
    dictionary.add_text(equipment.description)
    dictionary.add_text(equipment.make)
    dictionary.add_text(equipment.model)

    for component in equipment.components:
        dictionary.add_text(component.description)
        dictionary.add_text(component.parent_description)
        dictionary.add_text(component.make)
        dictionary.add_text(component.model)
        for function in component.functions:
            dictionary.add_text(function.description)
            for failure in function.failures:
                dictionary.add_text(failure.description)
                for fm in failure.failure_modes:
                    dictionary.add_text(fm.what)
                    dictionary.add_text(fm.mechanism_and_cause)
                    for activity in fm.activities:
                        dictionary.add_text(activity.description)

    if iso_ref is not None:
        for mode in iso_ref.failure_modes.values():
            dictionary.add_text(mode.code)
            dictionary.add_text(mode.description)
        for mech in iso_ref.failure_mechanisms.values():
            dictionary.add_text(mech.sub_name)
            dictionary.add_text(mech.description)
        for cause in iso_ref.failure_causes.values():
            dictionary.add_text(cause.sub_name)
            dictionary.add_text(cause.description)

    return dictionary
