"""Tests for the LLM-based ISO 14224 proposer.

The Anthropic client is mocked — these tests never touch the real API.
The mock asserts on the request shape (model, system prompt cache_control,
output_format) and returns canned Pydantic responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from orien_import_tool.domain.fmea import FailureMode
from orien_import_tool.iso14224 import load_all
from orien_import_tool.mapping import (
    B2Suggestion,
    B3Suggestion,
    B15Suggestion,
    FailureModeProposal,
    LLMProposer,
    MappingDimension,
    Proposer,
)

# --- Fake Anthropic client -----------------------------------------------------------


@dataclass
class FakeParseResponse:
    parsed_output: FailureModeProposal


class FakeMessages:
    def __init__(self, response: FailureModeProposal | Exception) -> None:
        self._response = response
        self.captured_kwargs: dict[str, Any] | None = None
        self.call_count = 0

    def parse(self, **kwargs: Any) -> FakeParseResponse:
        self.captured_kwargs = kwargs
        self.call_count += 1
        if isinstance(self._response, Exception):
            raise self._response
        return FakeParseResponse(parsed_output=self._response)


class FakeAnthropicClient:
    """Stand-in for ``anthropic.Anthropic`` exposing only what the proposer uses."""

    def __init__(self, response: FailureModeProposal | Exception) -> None:
        self.messages = FakeMessages(response)


# --- Fixtures ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ref(iso_dir: Path):
    return load_all(iso_dir)


def _proposer(ref, response: FailureModeProposal | Exception) -> tuple[LLMProposer, FakeMessages]:
    client = FakeAnthropicClient(response)
    return LLMProposer(ref, client=client), client.messages


# --- Tests ---------------------------------------------------------------------------


def test_propose_returns_valid_mappings(ref):
    canned = FailureModeProposal(
        mode=B15Suggestion(code="Worn", confidence=0.95, rationale="X verb 'wears' = B15 Worn"),
        mechanisms=[
            B2Suggestion(sub_code="2.4", confidence=0.9, rationale="B2 Wear"),
        ],
        causes=[
            B3Suggestion(
                sub_code="2.1", confidence=0.7, priority=0, rationale="overload = operating error"
            ),
            B3Suggestion(
                sub_code="1.1", confidence=0.5, priority=1, rationale="possibly undersized"
            ),
        ],
    )
    proposer, _ = _proposer(ref, canned)
    fm = FailureMode(
        token="t-1", what="Bearing", mechanism_and_cause="Wears due to Mechanical overload"
    )

    mappings = proposer.propose_for_failure_mode(fm)

    assert {m.dimension for m in mappings} == {
        MappingDimension.MODE,
        MappingDimension.MECHANISM,
        MappingDimension.CAUSE,
    }
    assert all(m.proposer == Proposer.LLM for m in mappings)
    assert all(m.source_entity_id == "t-1" for m in mappings)


def test_request_uses_opus_4_7_by_default(ref):
    canned = FailureModeProposal(mode=B15Suggestion(code="Worn", confidence=1.0, rationale=""))
    proposer, messages = _proposer(ref, canned)

    proposer.propose_for_failure_mode(
        FailureMode(token="t-2", mechanism_and_cause="Wears due to Mechanical overload")
    )

    assert messages.captured_kwargs["model"] == "claude-opus-4-7"


def test_system_prompt_is_cached(ref):
    """The ISO catalog is identical across calls — must carry cache_control."""
    canned = FailureModeProposal(mode=B15Suggestion(code="Worn", confidence=1.0, rationale=""))
    proposer, messages = _proposer(ref, canned)

    proposer.propose_for_failure_mode(
        FailureMode(token="t-3", mechanism_and_cause="Wears due to Mechanical overload")
    )

    system = messages.captured_kwargs["system"]
    assert isinstance(system, list)
    assert len(system) == 1
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # The catalog must actually be embedded.
    assert "B.15 Failure Mode Descriptions" in system[0]["text"]
    assert "B.2 Failure Mechanisms" in system[0]["text"]
    assert "B.3 Failure Causes" in system[0]["text"]
    # Spot-check a known code from each table.
    assert "Worn:" in system[0]["text"]
    assert "1.1: Mechanical failure" in system[0]["text"]
    assert "1.1: Design/manufacturing" in system[0]["text"]


def test_output_format_is_pydantic_schema(ref):
    canned = FailureModeProposal(mode=B15Suggestion(code="Worn", confidence=1.0, rationale=""))
    proposer, messages = _proposer(ref, canned)

    proposer.propose_for_failure_mode(
        FailureMode(token="t-4", mechanism_and_cause="Wears due to Mechanical overload")
    )

    assert messages.captured_kwargs["output_format"] is FailureModeProposal


def test_user_message_includes_rule_proposals(ref):
    """When rule proposals are passed, they appear in the user message as context."""
    from orien_import_tool.mapping.proposer import RuleProposer

    canned = FailureModeProposal(mode=B15Suggestion(code="Worn", confidence=1.0, rationale=""))
    proposer, messages = _proposer(ref, canned)

    fm = FailureMode(token="t-5", mechanism_and_cause="Wears due to Mechanical overload")
    rule = RuleProposer(ref).propose_for_failure_mode(fm)
    proposer.propose_for_failure_mode(fm, rule_proposals=rule)

    user_msg = messages.captured_kwargs["messages"][0]["content"]
    assert "Rule-based suggestion" in user_msg
    assert "MODE (B15): Worn" in user_msg
    # Multi-candidate B3 should be listed with priorities.
    assert "priority=0" in user_msg


def test_user_message_omits_rule_section_when_none(ref):
    canned = FailureModeProposal(mode=B15Suggestion(code="Worn", confidence=1.0, rationale=""))
    proposer, messages = _proposer(ref, canned)

    proposer.propose_for_failure_mode(
        FailureMode(token="t-6", mechanism_and_cause="Wears due to Mechanical overload")
    )

    user_msg = messages.captured_kwargs["messages"][0]["content"]
    assert "Rule-based suggestion" not in user_msg


def test_invalid_codes_are_filtered(ref):
    """LLM hallucinates a B15 code that doesn't exist — proposer drops it."""
    canned = FailureModeProposal(
        mode=B15Suggestion(code="Disintegrated", confidence=0.9, rationale="made up"),
        mechanisms=[
            B2Suggestion(sub_code="999.9", confidence=0.9, rationale="not real"),
            B2Suggestion(sub_code="2.4", confidence=0.9, rationale="real Wear"),
        ],
        causes=[B3Suggestion(sub_code="9.9", confidence=0.8, priority=0, rationale="invented")],
    )
    proposer, _ = _proposer(ref, canned)

    mappings = proposer.propose_for_failure_mode(
        FailureMode(token="t-7", mechanism_and_cause="Wears due to Mechanical overload")
    )

    # Only the real B2 (2.4 Wear) should survive.
    assert len(mappings) == 1
    assert mappings[0].dimension == MappingDimension.MECHANISM
    assert mappings[0].iso_code == "2.4"


def test_priority_preserved_from_llm(ref):
    canned = FailureModeProposal(
        causes=[
            B3Suggestion(sub_code="2.1", confidence=0.8, priority=0, rationale=""),
            B3Suggestion(sub_code="1.1", confidence=0.6, priority=1, rationale=""),
            B3Suggestion(sub_code="3.4", confidence=0.4, priority=2, rationale=""),
        ],
    )
    proposer, _ = _proposer(ref, canned)

    mappings = proposer.propose_for_failure_mode(
        FailureMode(token="t-8", mechanism_and_cause="Cracks due to Cyclic loading")
    )

    causes = sorted(
        (m for m in mappings if m.dimension == MappingDimension.CAUSE),
        key=lambda m: m.priority,
    )
    assert [m.iso_code for m in causes] == ["2.1", "1.1", "3.4"]
    assert [m.priority for m in causes] == [0, 1, 2]


def test_model_override(ref):
    canned = FailureModeProposal(mode=B15Suggestion(code="Worn", confidence=1.0, rationale=""))
    client = FakeAnthropicClient(canned)
    proposer = LLMProposer(ref, client=client, model="claude-sonnet-4-6")

    proposer.propose_for_failure_mode(
        FailureMode(token="t-9", mechanism_and_cause="Wears due to Mechanical overload")
    )

    assert client.messages.captured_kwargs["model"] == "claude-sonnet-4-6"


def test_no_mode_in_response_is_handled(ref):
    """LLM returns no B15 candidate — should yield zero MODE rows but still emit B2/B3."""
    canned = FailureModeProposal(
        mode=None,
        mechanisms=[B2Suggestion(sub_code="2.4", confidence=0.7, rationale="x")],
        causes=[B3Suggestion(sub_code="2.1", confidence=0.6, priority=0, rationale="y")],
    )
    proposer, _ = _proposer(ref, canned)

    mappings = proposer.propose_for_failure_mode(
        FailureMode(token="t-10", mechanism_and_cause="Disintegrates due to gremlins")
    )

    assert {m.dimension for m in mappings} == {
        MappingDimension.MECHANISM,
        MappingDimension.CAUSE,
    }
