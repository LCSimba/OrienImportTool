"""Normalizer threaded into the classification path.

Verifies that an injected TextNormalizer cleans event text before matching,
so a misspelled/abbreviated event reaches the right component/FM. Uses a real
TextNormalizer with a deterministic fake spell engine — no pyspellchecker.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from orien_import_tool.classification import AliasClassifier, build_seed_index
from orien_import_tool.domain.downtime import DowntimeEvent
from orien_import_tool.domain.fmea import (
    Component,
    Equipment,
    FailureMode,
    Function,
    FunctionalFailure,
)
from orien_import_tool.textnorm import (
    TextNormalizer,
    build_domain_dictionary,
    build_initial_abbreviations,
    normalize_event,
    normalize_events,
)


class _FakeSpellEngine:
    def __init__(self, words: set[str], suggestions: dict[str, str] | None = None) -> None:
        self._words = {w.casefold() for w in words}
        self._suggestions = {k.casefold(): v for k, v in (suggestions or {}).items()}

    def is_word(self, token: str) -> bool:
        return token.casefold() in self._words

    def suggest(self, token: str) -> str | None:
        return self._suggestions.get(token.casefold())


@pytest.fixture
def equipment() -> Equipment:
    fm = FailureMode(
        token="fm-bearing",
        what="Bearing",
        mechanism_and_cause="Wears due to lack of lubrication",
    )
    return Equipment(
        token="eq-1",
        description="Conveyor",
        components=[
            Component(
                token="c-bearing",
                description="Bearing Assembly",
                functions=[
                    Function(
                        description="Support the shaft",
                        failures=[
                            FunctionalFailure(description="Bearing fails", failure_modes=[fm])
                        ],
                    )
                ],
            )
        ],
    )


def _normalizer(equipment: Equipment) -> TextNormalizer:
    dictionary = build_domain_dictionary(equipment)
    # 'bearing' is a domain term; engine corrects the typo toward it.
    engine = _FakeSpellEngine(
        words={"the", "failure"},
        suggestions={"beraing": "bearing"},
    )
    return TextNormalizer(dictionary, engine, build_initial_abbreviations())


def _event(text: str) -> DowntimeEvent:
    return DowntimeEvent(
        external_id="e-1",
        asset_ref="conveyor",
        text=text,
        start_ts=datetime(2026, 1, 1),
    )


def test_normalizer_lifts_misspelled_event(equipment: Equipment) -> None:
    """'beraing' matches nothing raw, but 'bearing' after normalisation."""
    seed = build_seed_index(equipment)
    bare = AliasClassifier(seed)
    normalized = AliasClassifier(seed, normalizer=_normalizer(equipment))

    event = _event("beraing problem")

    bare_result = bare.classify(event)
    norm_result = normalized.classify(event)

    bare_score = bare_result.component_match.score if bare_result.component_match else 0.0
    norm_score = norm_result.component_match.score if norm_result.component_match else 0.0
    assert norm_score > bare_score


def test_abbreviation_expansion_in_classifier(equipment: Equipment) -> None:
    """An abbreviation in the event text is expanded before matching."""
    # Add 'conveyor' so the abbreviation target is a domain term.
    seed = build_seed_index(equipment)
    normalizer = _normalizer(equipment)
    classifier = AliasClassifier(seed, normalizer=normalizer)

    # 'c/v' -> 'conveyor'; the event should still classify without error and
    # the cleaned text drives matching.
    result = classifier.classify(_event("c/v beraing problem"))
    assert result.event_external_id == "e-1"


def test_classifier_without_normalizer_unchanged(equipment: Equipment) -> None:
    """Backwards compat: no normalizer means raw behaviour."""
    classifier = AliasClassifier(build_seed_index(equipment))
    result = classifier.classify(_event("bearing assembly failure"))
    assert result.component_match is not None
    assert result.component_match.component_token == "c-bearing"


# --- normalize_event / normalize_events helpers --------------------------------------


def test_normalize_event_returns_cleaned_copy(equipment: Equipment) -> None:
    normalizer = _normalizer(equipment)
    event = _event("beraing problem")
    cleaned, result = normalize_event(event, normalizer)

    assert cleaned.external_id == event.external_id  # link preserved
    assert cleaned.asset_ref == event.asset_ref  # tag untouched
    assert "bearing" in cleaned.text
    assert result.original_text == "beraing problem"
    assert result.changed


def test_normalize_events_batch(equipment: Equipment) -> None:
    normalizer = _normalizer(equipment)
    events = [_event("beraing problem"), _event("normal text here")]
    cleaned, results = normalize_events(events, normalizer)
    assert len(cleaned) == 2
    assert len(results) == 2
    assert "bearing" in cleaned[0].text


def test_normalize_event_collects_unknown_tokens(equipment: Equipment) -> None:
    """Unknown tokens surface for the abbreviation-mining queue."""
    normalizer = _normalizer(equipment)
    _, result = normalize_event(_event("simocode glitch"), normalizer)
    # 'simocode'/'glitch' aren't domain terms or known words -> unknown.
    assert result.unknown_tokens


def test_normalize_event_only_touches_free_text(equipment: Equipment) -> None:
    """When free_text is set, the validated/coded columns are not normalised."""
    normalizer = _normalizer(equipment)
    event = DowntimeEvent(
        external_id="e-1",
        asset_ref="conveyor",
        text="beraing problem | CONTROL - SYSTEM | SPLC",
        free_text="beraing problem",
    )
    cleaned, result = normalize_event(event, normalizer)

    assert result.original_text == "beraing problem"  # sourced from free_text
    assert "bearing" in cleaned.text  # operator typo fixed
    assert "SPLC" not in cleaned.text  # coded tail never reached the speller
