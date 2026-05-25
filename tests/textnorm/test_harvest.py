"""Tests for inline ``CODE - EXPANSION`` abbreviation harvesting.

Operators routinely spell a code out in the same free-text cell
(``BMAK - BOILER MAKING``). The harvester turns those into abbreviation seeds
deterministically, so the LLM miner never has to guess (and can't get them
wrong, as it did proposing ``bmak -> brake``).
"""

from __future__ import annotations

from orien_import_tool.textnorm import harvest_inline_abbreviations
from orien_import_tool.textnorm.abbreviations import AbbrevProposer


def _by_short(abbrevs):
    return {a.short: a.expansion for a in abbrevs}


def test_harvests_simple_code_expansion() -> None:
    [a] = harvest_inline_abbreviations(["BMAK - BOILER MAKING"])
    assert a.short == "bmak"
    assert a.expansion == "boiler making"
    assert a.proposer == AbbrevProposer.RULE


def test_splits_on_pipe_and_harvests_per_segment() -> None:
    text = "TAIL END GUARD REPLACED | GUARD REPAIRS | BMAK - BOILER MAKING"
    assert _by_short(harvest_inline_abbreviations([text])) == {"bmak": "boiler making"}


def test_keeps_ampersand_and_multiword_expansions() -> None:
    assert _by_short(harvest_inline_abbreviations(["INST - CONTROL & INSTR"])) == {
        "inst": "control & instr"
    }


def test_rejects_narrative_dash() -> None:
    # Left of ' - ' is multi-word operator prose, not a code.
    assert harvest_inline_abbreviations(["CONVEYOR STOP START - BLOCKED CHUTE DETECTOR"]) == []
    assert harvest_inline_abbreviations(["CONV STOP AND START X5 - START BELT MANUALLY"]) == []


def test_rejects_degenerate_and_too_short_expansion() -> None:
    # ComponentCodeDescription often just repeats the code (SPLC - SPLC).
    assert harvest_inline_abbreviations(["SPLC - SPLC"]) == []
    # Expansion no longer than the code is not informative.
    assert harvest_inline_abbreviations(["ABCD - XY"]) == []


def test_rejects_runaway_expansion() -> None:
    # More than six words: this is prose that happens to start with a token.
    assert harvest_inline_abbreviations(["FOO - one two three four five six seven"]) == []


def test_dedupes_first_seen_wins() -> None:
    out = harvest_inline_abbreviations(["BMAK - BOILER MAKING", "BMAK - BOILERMAKING DEPARTMENT"])
    assert _by_short(out) == {"bmak": "boiler making"}


def test_ignores_empty_and_dashless_segments() -> None:
    assert harvest_inline_abbreviations(["", "GUARD REPAIRS", "NO COMMS/NETWORK"]) == []
