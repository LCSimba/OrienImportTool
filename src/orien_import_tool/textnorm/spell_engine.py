"""Spell-check engine abstraction.

The normaliser needs two judgements per token:

* ``is_word(token)`` — is this already a valid word? (English *or* a known
  domain term). Valid words are never "corrected" — that's what stops
  ``reset`` becoming ``present``.
* ``suggest(token)`` — for a genuine non-word, what's the best correction
  candidate? The normaliser then accepts it only if it lands in the domain
  dictionary, so ``beraing -> bearing`` is taken but ``esrl -> earl`` is not.

:class:`PySpellEngine` wraps ``pyspellchecker`` (bundled English frequency
dictionary) and boosts the domain vocabulary so corrections prefer
reliability terms. Tests inject a deterministic fake instead.
"""

from __future__ import annotations

from typing import Protocol

from orien_import_tool.textnorm.dictionary import DomainDictionary


class SpellEngine(Protocol):
    def is_word(self, token: str) -> bool: ...

    def suggest(self, token: str) -> str | None: ...


class PySpellEngine:
    """``pyspellchecker``-backed engine, augmented with domain vocabulary.

    Domain terms are loaded into the checker's frequency table so they count
    as known words *and* are preferred as correction targets (a misspelling
    near both a domain term and a generic word resolves to the domain term).
    """

    def __init__(
        self,
        domain_dictionary: DomainDictionary,
        *,
        distance: int = 2,
        domain_boost: int = 100_000,
    ) -> None:
        try:
            from spellchecker import SpellChecker
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "PySpellEngine requires the [textnorm] extra: "
                "pip install 'orien_import_tool[textnorm]'"
            ) from exc

        self._spell = SpellChecker(distance=distance)
        self._domain = domain_dictionary
        # Boost domain terms so they outrank generic English when both are
        # within edit distance of a misspelling. load_words counts each term
        # once; multiply for a heavier prior on reliability vocabulary.
        if domain_dictionary.terms:
            self._spell.word_frequency.load_words(
                list(domain_dictionary.terms) * max(1, domain_boost // 1000)
            )

    def is_word(self, token: str) -> bool:
        if token in self._domain:
            return True
        # pyspellchecker's ``known`` returns the subset it recognises.
        return bool(self._spell.known([token]))

    def suggest(self, token: str) -> str | None:
        correction = self._spell.correction(token)
        if correction is None or correction == token:
            return None
        return correction
