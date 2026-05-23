"""Tests for operator-text normalisation.

A deterministic FakeSpellEngine substitutes for pyspellchecker so tests run
fast and don't need the bundled English dictionary. Vectors are chosen to
exercise each branch: abbreviation, real-word passthrough, typo correction,
ratio gate, domain gate, compound guard, code/short guards, unknown flagging.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orien_import_tool.textnorm import (
    DomainDictionary,
    TextNormalizer,
    build_domain_dictionary,
    build_initial_abbreviations,
)
from orien_import_tool.textnorm.abbreviations import Abbreviation, AbbreviationStore, AbbrevProposer

# --- Fake spell engine ----------------------------------------------------------------


class FakeSpellEngine:
    def __init__(self, words: set[str], suggestions: dict[str, str] | None = None) -> None:
        self._words = {w.casefold() for w in words}
        self._suggestions = {k.casefold(): v for k, v in (suggestions or {}).items()}

    def is_word(self, token: str) -> bool:
        return token.casefold() in self._words

    def suggest(self, token: str) -> str | None:
        return self._suggestions.get(token.casefold())


def _dictionary(*terms: str) -> DomainDictionary:
    d = DomainDictionary()
    for t in terms:
        d.add_text(t)
    return d


# --- Dictionary -----------------------------------------------------------------------


def test_build_domain_dictionary_harvests_fmea_tokens(iso_dir: Path) -> None:
    from orien_import_tool.domain.fmea import (
        Component,
        Equipment,
        FailureMode,
        Function,
        FunctionalFailure,
    )
    from orien_import_tool.iso14224 import load_all

    eq = Equipment(
        token="eq-1",
        description="Conveyor Belt Assembly",
        components=[
            Component(
                token="c-1",
                description="Drive Motor",
                functions=[
                    Function(
                        description="Drive the belt",
                        failures=[
                            FunctionalFailure(
                                description="Motor stops",
                                failure_modes=[
                                    FailureMode(
                                        token="fm-1",
                                        what="Bearing",
                                        mechanism_and_cause="Wears due to overload",
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    d = build_domain_dictionary(eq, load_all(iso_dir))
    assert "conveyor" in d
    assert "bearing" in d
    assert "wears" in d
    # ISO vocabulary too
    assert "corroded" in d or "worn" in d


def test_correction_targets_excludes_short_terms() -> None:
    d = _dictionary("bearing belt of in")
    targets = set(d.correction_targets())
    assert "bearing" in targets
    assert "of" not in targets  # below min_correction_length


# --- Abbreviations --------------------------------------------------------------------


def test_abbreviation_store_expands() -> None:
    store = build_initial_abbreviations()
    assert store.expand("c/v") == "conveyor"
    assert store.expand("mtr") == "motor"
    assert store.expand("notanabbrev") is None


def test_abbreviation_precedence_sme_over_rule() -> None:
    store = AbbreviationStore()
    store.add(Abbreviation("xyz", "rule-expansion", AbbrevProposer.RULE))
    store.add(Abbreviation("xyz", "sme-expansion", AbbrevProposer.SME))
    assert store.expand("xyz") == "sme-expansion"


# --- Normalizer branches --------------------------------------------------------------


def test_abbreviation_expansion() -> None:
    nz = TextNormalizer(
        _dictionary("conveyor"),
        FakeSpellEngine({"conveyor"}),
        build_initial_abbreviations(),
    )
    result = nz.normalize("c/v stopped")
    assert "conveyor" in result.cleaned_text
    assert any(c.method == "abbreviation" for c in result.corrections)


def test_real_word_left_alone() -> None:
    """A valid word is never corrected even if a domain term is edit-close."""
    nz = TextNormalizer(
        _dictionary("present"),
        FakeSpellEngine({"reset"}, suggestions={"reset": "present"}),
    )
    result = nz.normalize("reset the trip")
    assert result.cleaned_text == "reset the trip"
    assert not result.changed


def test_typo_corrected_when_domain_and_high_ratio() -> None:
    nz = TextNormalizer(
        _dictionary("bearing"),
        FakeSpellEngine(set(), suggestions={"beraing": "bearing"}),
    )
    result = nz.normalize("beraing failure")
    assert "bearing" in result.cleaned_text
    assert result.corrections[0].method == "spelling"


def test_low_ratio_suggestion_rejected() -> None:
    """freq->free is edit-distance-1 but ratio 0.75 < 0.80, so it's not applied."""
    nz = TextNormalizer(
        _dictionary("free"),
        FakeSpellEngine(set(), suggestions={"freq": "free"}),
    )
    result = nz.normalize("freq drive")
    assert "free" not in result.cleaned_text
    assert "freq" in result.unknown_tokens


def test_non_domain_suggestion_rejected() -> None:
    """esrl->earl: earl isn't a domain term, so the correction is rejected."""
    nz = TextNormalizer(
        _dictionary("bearing", "motor"),  # 'earl' deliberately absent
        FakeSpellEngine(set(), suggestions={"esrl": "earl"}),
    )
    result = nz.normalize("esrl tripped")
    assert "earl" not in result.cleaned_text
    assert "esrl" in result.unknown_tokens


def test_compound_word_not_corrected() -> None:
    """pull+key are both words, so 'pullkey' is a compound, not a typo of 'pulley'."""
    nz = TextNormalizer(
        _dictionary("pulley"),
        FakeSpellEngine({"pull", "key", "pulley"}, suggestions={"pullkey": "pulley"}),
    )
    result = nz.normalize("pullkey damaged")
    assert "pulley" not in result.cleaned_text
    assert "pullkey" in result.unknown_tokens


def test_codes_with_digits_left_alone() -> None:
    nz = TextNormalizer(
        _dictionary("conveyor"),
        FakeSpellEngine(set(), suggestions={"4fc025": "conveyor"}),
    )
    result = nz.normalize("4FC025 down")
    assert "4FC025" in result.cleaned_text
    assert not result.changed


def test_short_tokens_left_alone() -> None:
    nz = TextNormalizer(
        _dictionary("oil"),
        FakeSpellEngine(set(), suggestions={"oik": "oil"}),
    )
    result = nz.normalize("oik")  # 3 chars, below min_token_length
    assert result.cleaned_text == "oik"


def test_unknown_tokens_flagged_for_mining() -> None:
    nz = TextNormalizer(_dictionary("conveyor"), FakeSpellEngine(set()))
    result = nz.normalize("simocode fault")
    assert "simocode" in result.unknown_tokens


def test_corrections_are_auditable() -> None:
    nz = TextNormalizer(
        _dictionary("bearing"),
        FakeSpellEngine(set(), suggestions={"beraing": "bearing"}),
    )
    result = nz.normalize("beraing")
    assert len(result.corrections) == 1
    c = result.corrections[0]
    assert c.original == "beraing"
    assert c.replacement == "bearing"
    assert 0.0 <= c.confidence <= 1.0


def test_punctuation_preserved_around_corrected_core() -> None:
    nz = TextNormalizer(
        _dictionary("bearing"),
        FakeSpellEngine(set(), suggestions={"beraing": "bearing"}),
    )
    result = nz.normalize("(beraing)")
    assert result.cleaned_text == "(bearing)"


def test_token_cache_reuses_results() -> None:
    nz = TextNormalizer(
        _dictionary("bearing"),
        FakeSpellEngine(set(), suggestions={"beraing": "bearing"}),
    )
    nz.normalize("beraing beraing beraing")
    # Only one distinct raw token computed; cache holds it plus any others.
    assert "beraing" in nz._token_cache


def test_accept_only_domain_off_accepts_any_suggestion() -> None:
    nz = TextNormalizer(
        _dictionary(),  # empty domain
        FakeSpellEngine(set(), suggestions={"beraing": "bearing"}),
        accept_only_domain_corrections=False,
    )
    result = nz.normalize("beraing")
    assert "bearing" in result.cleaned_text


# --- PySpellEngine (only if the [textnorm] extra is installed) ------------------------


def test_pyspell_engine_if_available() -> None:
    pytest.importorskip("spellchecker")
    from orien_import_tool.textnorm import PySpellEngine

    d = _dictionary("bearing", "conveyor")
    engine = PySpellEngine(d)
    # Real English words are known.
    assert engine.is_word("reset")
    assert engine.is_word("tripping")
    # Domain term known.
    assert engine.is_word("conveyor")
    # Genuine typo suggests the domain term.
    assert engine.suggest("beraing") == "bearing"
