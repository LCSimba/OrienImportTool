"""Smoke test for the ``mine-abbreviations`` CLI subcommand (client mocked)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from orien_import_tool.textnorm import AbbreviationProposal, AbbreviationProposalBatch

ORIEN_FIXTURE = Path(
    "tests/fixtures/orien/2025918727_CONVEYOR4FBeltTRUNK_ExportOfSingleSheetTactics_3QN56K0-0.xlsx"
)
DOWNTIME_FIXTURE = Path("tests/fixtures/downtime/AI_Test.xlsx")


@dataclass
class _Msg:
    parsed: Any


@dataclass
class _Choice:
    message: _Msg


@dataclass
class _Completion:
    choices: list[_Choice]


class _FakeChatCompletions:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls = 0

    def parse(self, **kwargs: Any) -> _Completion:
        self.calls += 1
        return _Completion(choices=[_Choice(message=_Msg(parsed=self._response))])


class _FakeOpenAIClient:
    def __init__(self, response: Any) -> None:
        self._c = _FakeChatCompletions(response)
        self.chat = type("C", (), {"completions": self._c})()


@pytest.fixture
def fixtures_present() -> None:
    if not ORIEN_FIXTURE.exists() or not DOWNTIME_FIXTURE.exists():
        pytest.skip("conveyor or AI_Test fixture missing")


def test_mine_abbreviations_writes_csv(tmp_path: Path, fixtures_present, monkeypatch) -> None:
    pytest.importorskip("spellchecker")  # the CLI path builds a real PySpellEngine
    from orien_import_tool.llm import openai_compat
    from orien_import_tool.review.cli import main

    canned = AbbreviationProposalBatch(
        proposals=[
            AbbreviationProposal(
                short="instr",
                expansion="instrument",
                is_expandable=True,
                confidence=0.9,
                rationale="standard abbreviation",
            ),
            AbbreviationProposal(
                short="simocode",
                expansion="",
                is_expandable=False,
                confidence=0.8,
                rationale="product name",
            ),
        ]
    )
    monkeypatch.setattr(
        openai_compat, "_build_openai_client", lambda **kwargs: _FakeOpenAIClient(canned)
    )

    out = tmp_path / "abbr.csv"
    rc = main(
        [
            "mine-abbreviations",
            "--orien",
            str(ORIEN_FIXTURE),
            "--downtime",
            str(DOWNTIME_FIXTURE),
            "--downtime-sheet",
            "Conveyor",
            "--llm-url",
            "http://192.168.50.75:8000/v1",
            "--llm-model",
            "Qwen3.6-27B-FP8",
            "--max-unknowns",
            "30",
            "--max-events",
            "40",
            "--csv",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    # Now a review-queue CSV (round-trippable through `apply`).
    assert "item_id,item_type" in text.splitlines()[0]
    # The expandable proposal is present as an abbreviation review item...
    assert "abbr:instr:instrument" in text
    assert "abbreviation" in text
    # ...and the non-expandable product name is surfaced as its own category
    # (so the SME can confirm or override the 'not an abbreviation' call).
    assert "unknown:simocode" in text
    assert "unknown_token" in text
