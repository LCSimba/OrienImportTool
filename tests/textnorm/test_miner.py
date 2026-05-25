"""Tests for the LLM abbreviation miner. The Anthropic-shaped client is mocked."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from orien_import_tool.textnorm import (
    AbbreviationProposal,
    AbbreviationProposalBatch,
    LLMAbbreviationMiner,
    build_initial_abbreviations,
)
from orien_import_tool.textnorm.abbreviations import AbbrevProposer


@dataclass
class FakeParseResponse:
    parsed_output: AbbreviationProposalBatch


class FakeMessages:
    def __init__(self, responses: list[AbbreviationProposalBatch]) -> None:
        self._responses = list(responses)
        self.captured_kwargs: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> FakeParseResponse:
        self.captured_kwargs.append(kwargs)
        if not self._responses:
            return FakeParseResponse(AbbreviationProposalBatch(proposals=[]))
        return FakeParseResponse(self._responses.pop(0))


class FakeClient:
    def __init__(self, *responses: AbbreviationProposalBatch) -> None:
        self.messages = FakeMessages(list(responses))


def test_mine_returns_expandable_only() -> None:
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
                rationale="Siemens product name, not an abbreviation",
            ),
        ]
    )
    miner = LLMAbbreviationMiner(client=FakeClient(canned))
    result = miner.mine(["instr", "simocode"])

    # Only the expandable proposal becomes an Abbreviation.
    assert len(result) == 1
    assert result[0].short == "instr"
    assert result[0].expansion == "instrument"
    assert result[0].proposer == AbbrevProposer.LLM


def test_group_label_carried_to_abbreviation() -> None:
    """The LLM's family label rides through to the mined Abbreviation."""
    canned = AbbreviationProposalBatch(
        proposals=[
            AbbreviationProposal(
                short="iplc",
                expansion="input plc",
                is_expandable=True,
                confidence=0.7,
                rationale="plc variant",
                group="plc-variant",
            )
        ]
    )
    [abbrev] = LLMAbbreviationMiner(client=FakeClient(canned)).mine(["iplc"])
    assert abbrev.group == "plc-variant"


def test_mine_uses_opus_by_default() -> None:
    miner = LLMAbbreviationMiner(client=FakeClient(AbbreviationProposalBatch(proposals=[])))
    miner.mine(["splc"])
    assert miner._client.messages.captured_kwargs[0]["model"] == "claude-opus-4-7"


def test_mine_skips_known_abbreviations() -> None:
    """Tokens already in the store aren't re-sent to the LLM."""
    miner = LLMAbbreviationMiner(client=FakeClient(AbbreviationProposalBatch(proposals=[])))
    known = build_initial_abbreviations()  # contains 'mtr', 'elec', etc.
    miner.mine(["mtr", "elec", "novelterm"], skip_known=known)
    user_msg = miner._client.messages.captured_kwargs[0]["messages"][0]["content"]
    assert "novelterm" in user_msg
    assert "mtr" not in user_msg
    assert "elec" not in user_msg


def test_counter_orders_by_frequency() -> None:
    miner = LLMAbbreviationMiner(client=FakeClient(AbbreviationProposalBatch(proposals=[])))
    miner.mine(Counter({"rare": 1, "common": 99, "mid": 10}))
    user_msg = miner._client.messages.captured_kwargs[0]["messages"][0]["content"]
    # 'common' should be listed before 'rare'.
    assert user_msg.index("common") < user_msg.index("rare")


def test_batches_large_inputs() -> None:
    miner = LLMAbbreviationMiner(
        client=FakeClient(
            AbbreviationProposalBatch(proposals=[]),
            AbbreviationProposalBatch(proposals=[]),
        ),
        batch_size=5,
    )
    miner.mine([f"tok{i}" for i in range(8)])
    assert len(miner._client.messages.captured_kwargs) == 2


def test_empty_input_no_calls() -> None:
    miner = LLMAbbreviationMiner(client=FakeClient())
    assert miner.mine([]) == []
    assert miner._client.messages.captured_kwargs == []


def test_system_prompt_cached() -> None:
    miner = LLMAbbreviationMiner(client=FakeClient(AbbreviationProposalBatch(proposals=[])))
    miner.mine(["splc"])
    system = miner._client.messages.captured_kwargs[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_context_is_folded_into_prompt() -> None:
    """Per-token TokenContext (examples + co-occurring labels) reaches the prompt."""
    from orien_import_tool.textnorm import TokenContext

    miner = LLMAbbreviationMiner(client=FakeClient(AbbreviationProposalBatch(proposals=[])))
    miner.mine(
        ["safeline"],
        context={
            "safeline": TokenContext(
                examples=("SAFE LINE FAULT | TRIP ON SAFELINE FAULT",),
                cooccurring=("SAFETY - SYSTEM",),
            )
        },
    )
    user_msg = miner._client.messages.captured_kwargs[0]["messages"][0]["content"]
    assert "appears alongside: SAFETY - SYSTEM" in user_msg
    assert "TRIP ON SAFELINE FAULT" in user_msg


def test_prompt_without_context_has_no_context_lines() -> None:
    miner = LLMAbbreviationMiner(client=FakeClient(AbbreviationProposalBatch(proposals=[])))
    miner.mine(["splc"])
    user_msg = miner._client.messages.captured_kwargs[0]["messages"][0]["content"]
    assert "- splc" in user_msg
    assert "appears alongside" not in user_msg
