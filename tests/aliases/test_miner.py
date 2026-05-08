"""Tests for the LLM-based alias miner.

The Anthropic client is mocked — these tests never touch the real API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from orien_import_tool.aliases import (
    AliasProposal,
    AliasProposalBatch,
    AliasProposer,
    LLMAliasMiner,
)
from orien_import_tool.domain.downtime import DowntimeEvent
from orien_import_tool.iso14224 import load_all

# --- Mock Anthropic --------------------------------------------------------------


@dataclass
class FakeParseResponse:
    parsed_output: AliasProposalBatch


class FakeMessages:
    def __init__(self, responses: list[AliasProposalBatch]) -> None:
        self._responses = list(responses)
        self.captured_kwargs: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> FakeParseResponse:
        self.captured_kwargs.append(kwargs)
        if not self._responses:
            return FakeParseResponse(parsed_output=AliasProposalBatch(proposals=[]))
        return FakeParseResponse(parsed_output=self._responses.pop(0))


class FakeAnthropicClient:
    def __init__(self, *responses: AliasProposalBatch) -> None:
        self.messages = FakeMessages(list(responses))


# --- Fixtures --------------------------------------------------------------------


@pytest.fixture(scope="module")
def ref(iso_dir: Path):
    return load_all(iso_dir)


def _event(text: str, eid: str = "e-1") -> DowntimeEvent:
    return DowntimeEvent(
        external_id=eid,
        asset_ref="conveyor",
        text=text,
        start_ts=datetime(2026, 1, 1),
    )


# --- Tests -----------------------------------------------------------------------


def test_mine_returns_alias_rows(ref) -> None:
    canned = AliasProposalBatch(
        proposals=[
            AliasProposal(
                alias_text="tripped",
                canonical_tokens=["stoppage", "stop"],
                iso_hint="B15:Spurious trip/shutdown",
                confidence=0.9,
                rationale="operator term for unplanned outage",
            ),
        ]
    )
    miner = LLMAliasMiner(ref, client=FakeAnthropicClient(canned))
    aliases = miner.mine([_event("Belt tripped at trunk 13")])

    assert len(aliases) == 1
    assert aliases[0].alias_text == "tripped"
    assert aliases[0].canonical_tokens == ("stoppage", "stop")
    assert aliases[0].proposer == AliasProposer.LLM
    assert aliases[0].iso_hint == "B15:Spurious trip/shutdown"


def test_mine_uses_opus_4_7_by_default(ref) -> None:
    miner = LLMAliasMiner(ref, client=FakeAnthropicClient(AliasProposalBatch(proposals=[])))
    miner.mine([_event("anything")])
    assert miner._client.messages.captured_kwargs[0]["model"] == "claude-opus-4-7"


def test_system_prompt_is_cached_and_holds_iso_catalog(ref) -> None:
    miner = LLMAliasMiner(ref, client=FakeAnthropicClient(AliasProposalBatch(proposals=[])))
    miner.mine([_event("anything")])

    system = miner._client.messages.captured_kwargs[0]["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    text = system[0]["text"]
    assert "B.15" in text
    assert "B.2" in text
    assert "B.3" in text
    # The verb vocabulary the classifier knows must be advertised.
    assert "wears" in text
    assert "stoppage" in text


def test_mine_batches_large_inputs(ref) -> None:
    """A 75-event input with batch_size=50 must produce 2 API calls."""
    miner = LLMAliasMiner(
        ref,
        client=FakeAnthropicClient(
            AliasProposalBatch(proposals=[]),
            AliasProposalBatch(proposals=[]),
        ),
        batch_size=50,
    )
    events = [_event(f"event-text-{i}", eid=f"e-{i}") for i in range(75)]
    miner.mine(events)
    assert len(miner._client.messages.captured_kwargs) == 2


def test_user_message_lists_event_text(ref) -> None:
    miner = LLMAliasMiner(ref, client=FakeAnthropicClient(AliasProposalBatch(proposals=[])))
    miner.mine([_event("Belt tripped at trunk 13", eid="e-test")])

    user_msg = miner._client.messages.captured_kwargs[0]["messages"][0]["content"]
    assert "Belt tripped at trunk 13" in user_msg
    assert "e-test" in user_msg


def test_empty_input_no_api_calls(ref) -> None:
    miner = LLMAliasMiner(ref, client=FakeAnthropicClient())
    aliases = miner.mine([])
    assert aliases == []
    assert miner._client.messages.captured_kwargs == []
