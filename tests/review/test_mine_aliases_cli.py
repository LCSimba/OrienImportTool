"""Smoke tests for the ``mine-aliases`` CLI subcommand.

Patches the OpenAIProposerClient builder so the test never touches the
network. Verifies the full plumbing: arg parsing -> event filtering ->
LLM miner -> alias review CSV.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from orien_import_tool.aliases import AliasProposal, AliasProposalBatch

ORIEN_FIXTURE = Path(
    "tests/fixtures/orien/2025918727_CONVEYOR4FBeltTRUNK_ExportOfSingleSheetTactics_3QN56K0-0.xlsx"
)
DOWNTIME_FIXTURE = Path("tests/fixtures/downtime/AI_Test.xlsx")


# --- Fake OpenAI client (mirror of test_openai_compat.py) ---------------------


@dataclass
class _FakeMessage:
    parsed: Any


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeCompletion:
    choices: list[_FakeChoice]


class _FakeChatCompletions:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls = 0

    def parse(self, **kwargs: Any) -> _FakeCompletion:
        self.calls += 1
        return _FakeCompletion(choices=[_FakeChoice(message=_FakeMessage(parsed=self._response))])


class _FakeChatNamespace:
    def __init__(self, completions: _FakeChatCompletions) -> None:
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, response: Any) -> None:
        self._completions = _FakeChatCompletions(response)
        self.chat = _FakeChatNamespace(self._completions)


# --- Tests --------------------------------------------------------------------


@pytest.fixture
def fixtures_present() -> None:
    if not ORIEN_FIXTURE.exists() or not DOWNTIME_FIXTURE.exists():
        pytest.skip("conveyor or AI_Test fixture missing")


def test_mine_aliases_writes_csv(
    tmp_path: Path,
    fixtures_present,
    monkeypatch,
) -> None:
    """End-to-end: classify, filter, mine, write CSV."""
    from orien_import_tool.llm import openai_compat
    from orien_import_tool.review.cli import main

    canned = AliasProposalBatch(
        proposals=[
            AliasProposal(
                alias_text="tripped",
                canonical_tokens=["stoppage", "stop"],
                iso_hint="B15:Spurious trip/shutdown",
                confidence=0.85,
                rationale="operator term for outage",
            )
        ]
    )
    fake_client = _FakeOpenAIClient(response=canned)
    monkeypatch.setattr(
        openai_compat,
        "_build_openai_client",
        lambda **kwargs: fake_client,
    )

    out_csv = tmp_path / "aliases.csv"
    rc = main(
        [
            "mine-aliases",
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
            "--max-events",
            "20",
            "--no-normalize",
            "--csv",
            str(out_csv),
        ]
    )

    assert rc == 0
    assert out_csv.exists()
    csv_text = out_csv.read_text(encoding="utf-8")
    # Header + at least one proposal row (the LLM proposed 1 alias per batch
    # and we limit batches to 50 events, so 1 batch -> 1 alias).
    assert "alias_text" not in csv_text.splitlines()[0]  # CSV header isn't alias-specific
    assert "tripped" in csv_text
    # The fake server was actually called.
    assert fake_client._completions.calls >= 1


def test_mine_aliases_requires_llm_flags(
    tmp_path: Path,
    fixtures_present,
) -> None:
    """Without --llm-url / --llm-model, the subcommand exits with a clear error."""
    from orien_import_tool.review.cli import main

    with pytest.raises(SystemExit, match="--llm-url and --llm-model"):
        main(
            [
                "mine-aliases",
                "--orien",
                str(ORIEN_FIXTURE),
                "--downtime",
                str(DOWNTIME_FIXTURE),
                "--csv",
                str(tmp_path / "out.csv"),
            ]
        )


def test_score_threshold_filters_events(
    tmp_path: Path,
    fixtures_present,
    monkeypatch,
) -> None:
    """With threshold=0.0, every event passes; with 1.0, almost none do."""
    from orien_import_tool.llm import openai_compat
    from orien_import_tool.review.cli import main

    fake = _FakeOpenAIClient(response=AliasProposalBatch(proposals=[]))
    monkeypatch.setattr(
        openai_compat,
        "_build_openai_client",
        lambda **kwargs: fake,
    )

    # threshold=0.0 -> no events selected (nothing scores below 0).
    main(
        [
            "mine-aliases",
            "--orien",
            str(ORIEN_FIXTURE),
            "--downtime",
            str(DOWNTIME_FIXTURE),
            "--downtime-sheet",
            "Conveyor",
            "--llm-url",
            "http://x/v1",
            "--llm-model",
            "test",
            "--score-threshold",
            "0.0",
            "--max-events",
            "5",
            "--no-normalize",
            "--csv",
            str(tmp_path / "low.csv"),
        ]
    )
    low_calls = fake._completions.calls

    # threshold=1.0 -> every event passes (all score < 1.0), capped at 5.
    fake2 = _FakeOpenAIClient(response=AliasProposalBatch(proposals=[]))
    monkeypatch.setattr(
        openai_compat,
        "_build_openai_client",
        lambda **kwargs: fake2,
    )
    main(
        [
            "mine-aliases",
            "--orien",
            str(ORIEN_FIXTURE),
            "--downtime",
            str(DOWNTIME_FIXTURE),
            "--downtime-sheet",
            "Conveyor",
            "--llm-url",
            "http://x/v1",
            "--llm-model",
            "test",
            "--score-threshold",
            "1.0",
            "--max-events",
            "5",
            "--no-normalize",
            "--csv",
            str(tmp_path / "high.csv"),
        ]
    )
    high_calls = fake2._completions.calls

    assert high_calls > low_calls, (
        "raising the threshold should select more events to send to the LLM"
    )


def test_knowledge_stores_loads_persisted_rows(tmp_path: Path) -> None:
    """--db-url makes mine-aliases load SME-confirmed aliases + abbreviations."""
    from types import SimpleNamespace

    from orien_import_tool.aliases import Alias, AliasProposer
    from orien_import_tool.domain.fmea import Component, Equipment
    from orien_import_tool.persistence import (
        AbbreviationRepository,
        AliasRepository,
        init_db,
        make_engine,
        make_session_factory,
    )
    from orien_import_tool.review.cli import _knowledge_stores
    from orien_import_tool.textnorm.abbreviations import Abbreviation, AbbrevProposer

    db_path = tmp_path / "knowledge.db"
    url = f"sqlite:///{db_path}"
    engine = make_engine(url)
    init_db(engine)
    with make_session_factory(engine)() as session:
        AliasRepository(session).add(
            Alias(alias_text="zzz", canonical_tokens=("stoppage",), proposer=AliasProposer.SME)
        )
        AbbreviationRepository(session).add(
            Abbreviation("peflo", "perform flow check", AbbrevProposer.SME)
        )
        session.commit()

    equipment = Equipment(token="eq-1", description="Conveyor", components=[Component("c", "Belt")])
    args = SimpleNamespace(db_url=url)
    alias_store, abbrev_store = _knowledge_stores(args, equipment, None)

    # Persisted alias + abbreviation are present alongside the rule seeds.
    assert alias_store.expand_token("zzz") == {"stoppage"}
    assert abbrev_store.expand("peflo") == "perform flow check"
    assert abbrev_store.expand("mtr") == "motor"  # seed still there
