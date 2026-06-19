"""Unit tests for the forgiving speech-to-text interpretation layer."""

from __future__ import annotations

import pytest

from orien_import_tool.downtime_bot.matching import (
    ACCEPT,
    Option,
    is_dont_know,
    match_options,
    parse_ordinal,
    parse_yes_no,
)


@pytest.mark.parametrize(
    "utterance,expected",
    [
        ("yes", True),
        ("Yeah", True),
        ("that's right", True),
        ("no", False),
        ("nope", False),
        ("that is wrong", False),
        ("maybe later", None),
        ("", None),
    ],
)
def test_parse_yes_no(utterance: str, expected: bool | None) -> None:
    assert parse_yes_no(utterance) is expected


@pytest.mark.parametrize(
    "utterance",
    ["I don't know", "not sure", "no idea", "skip", "unknown"],
)
def test_is_dont_know_true(utterance: str) -> None:
    assert is_dont_know(utterance) is True


def test_is_dont_know_false() -> None:
    assert is_dont_know("the drive motor") is False


@pytest.mark.parametrize(
    "utterance,expected",
    [
        ("number two", 2),
        ("the third one", 3),
        ("2", 2),
        ("first", 1),
        ("number nine", None),  # out of range for a 3-item list
        ("the motor", None),
    ],
)
def test_parse_ordinal(utterance: str, expected: int | None) -> None:
    assert parse_ordinal(utterance, count=3) == expected


def _options() -> list[Option]:
    return [
        Option(value="Drive motor", token="C-MOTOR"),
        Option(value="Head pulley bearing", token="C-BEARING"),
        Option(value="Conveyor belt", token="C-BELT"),
    ]


def test_match_options_exact_is_full_confidence() -> None:
    best = match_options("drive motor", _options())[0]
    assert best.token == "C-MOTOR"
    assert best.score == 1.0


def test_match_options_fuzzy_ranks_best_first() -> None:
    results = match_options("the bearing on the head pulley", _options())
    assert results[0].token == "C-BEARING"
    assert results[0].score >= ACCEPT


def test_match_options_ordinal_short_circuits() -> None:
    results = match_options("number three", _options())
    assert len(results) == 1
    assert results[0].token == "C-BELT"


def test_match_options_no_match_returns_empty() -> None:
    assert match_options("hydraulic accumulator", _options()) == []
