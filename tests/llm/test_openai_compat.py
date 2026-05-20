"""Tests for the OpenAI-compatible adapter.

A hand-rolled fake openai.OpenAI client substitutes for the real SDK so the
tests never hit a network endpoint. The fake captures the request shape
(model, messages, response_format) and returns a canned parsed response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from orien_import_tool.aliases import AliasProposalBatch, LLMAliasMiner
from orien_import_tool.domain.downtime import DowntimeEvent
from orien_import_tool.iso14224 import load_all
from orien_import_tool.llm import OpenAIProposerClient
from orien_import_tool.mapping import FailureModeProposal, LLMProposer
from orien_import_tool.mapping.llm_proposer import B15Suggestion

# --- Fake OpenAI SDK ------------------------------------------------------------------


@dataclass
class FakeMessage:
    parsed: Any


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeCompletion:
    choices: list[FakeChoice]


class FakeChatCompletions:
    def __init__(self, response_payload: Any | None) -> None:
        self._payload = response_payload
        self.captured_kwargs: dict[str, Any] | None = None

    def parse(self, **kwargs: Any) -> FakeCompletion:
        self.captured_kwargs = kwargs
        return FakeCompletion(choices=[FakeChoice(message=FakeMessage(parsed=self._payload))])


class FakeChatNamespace:
    def __init__(self, completions: FakeChatCompletions) -> None:
        self.completions = completions


class FakeOpenAIClient:
    """Drop-in for ``openai.OpenAI`` covering only the call our adapter makes."""

    def __init__(self, response_payload: Any | None) -> None:
        self._completions = FakeChatCompletions(response_payload)
        self.chat = FakeChatNamespace(self._completions)

    @property
    def captured(self) -> dict[str, Any] | None:
        return self._completions.captured_kwargs


# --- Adapter-level tests --------------------------------------------------------------


class _Tiny(BaseModel):
    name: str
    score: float


def test_parse_returns_parsed_output_in_anthropic_shape() -> None:
    fake = FakeOpenAIClient(response_payload=_Tiny(name="alpha", score=0.5))
    adapter = OpenAIProposerClient(base_url="http://x/v1", client=fake)

    response = adapter.messages.parse(
        model="qwen2.5-32b",
        max_tokens=512,
        system="you are a tester",
        messages=[{"role": "user", "content": "go"}],
        output_format=_Tiny,
    )
    assert response.parsed_output.name == "alpha"
    assert response.parsed_output.score == 0.5


def test_anthropic_system_blocks_are_flattened_to_a_string() -> None:
    """Anthropic-style ``system=[{type:text, text:..., cache_control:...}]`` becomes
    a single OpenAI system message."""
    fake = FakeOpenAIClient(response_payload=_Tiny(name="a", score=0.0))
    adapter = OpenAIProposerClient(base_url="http://x/v1", client=fake)

    system_blocks = [
        {"type": "text", "text": "rule 1", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "rule 2"},
    ]
    adapter.messages.parse(
        model="m",
        max_tokens=10,
        system=system_blocks,
        messages=[{"role": "user", "content": "x"}],
        output_format=_Tiny,
    )

    sent = fake.captured["messages"]
    assert sent[0] == {"role": "system", "content": "rule 1\n\nrule 2"}
    assert sent[1] == {"role": "user", "content": "x"}


def test_response_format_is_pydantic_class() -> None:
    fake = FakeOpenAIClient(response_payload=_Tiny(name="a", score=0.0))
    adapter = OpenAIProposerClient(base_url="http://x/v1", client=fake)
    adapter.messages.parse(
        model="m",
        max_tokens=10,
        system="",
        messages=[{"role": "user", "content": "x"}],
        output_format=_Tiny,
    )
    assert fake.captured["response_format"] is _Tiny


def test_empty_system_omits_system_message() -> None:
    fake = FakeOpenAIClient(response_payload=_Tiny(name="a", score=0.0))
    adapter = OpenAIProposerClient(base_url="http://x/v1", client=fake)
    adapter.messages.parse(
        model="m",
        max_tokens=10,
        system="",
        messages=[{"role": "user", "content": "x"}],
        output_format=_Tiny,
    )
    sent = fake.captured["messages"]
    assert sent == [{"role": "user", "content": "x"}]


def test_unparseable_response_raises() -> None:
    """Server returned no parsed object (e.g. schema not enforced + invalid JSON)."""
    fake = FakeOpenAIClient(response_payload=None)
    adapter = OpenAIProposerClient(base_url="http://x/v1", client=fake)
    with pytest.raises(ValueError, match="no parsed output"):
        adapter.messages.parse(
            model="m",
            max_tokens=10,
            system="",
            messages=[{"role": "user", "content": "x"}],
            output_format=_Tiny,
        )


# --- Proposer integration -------------------------------------------------------------


@pytest.fixture(scope="module")
def ref(iso_dir: Path):
    return load_all(iso_dir)


def test_llm_proposer_drives_openai_compat_client(ref) -> None:
    """End-to-end: feed a FailureMode through LLMProposer using the adapter."""
    from orien_import_tool.domain.fmea import FailureMode

    canned = FailureModeProposal(
        mode=B15Suggestion(code="Worn", confidence=0.92, rationale="local model decided")
    )
    fake = FakeOpenAIClient(response_payload=canned)
    adapter = OpenAIProposerClient(base_url="http://x/v1", client=fake, model_name="qwen2.5-32b")
    proposer = LLMProposer(ref, client=adapter, model="qwen2.5-32b")

    mappings = proposer.propose_for_failure_mode(
        FailureMode(
            token="t-1",
            what="Bearing",
            mechanism_and_cause="Wears due to Mechanical overload",
        )
    )

    assert len(mappings) == 1
    assert mappings[0].iso_code == "Worn"
    assert fake.captured["model"] == "qwen2.5-32b"
    # Anthropic-style cached system blocks were flattened to a single string.
    system_msg = fake.captured["messages"][0]
    assert system_msg["role"] == "system"
    assert "B.15 Failure Mode Descriptions" in system_msg["content"]


def test_alias_miner_drives_openai_compat_client(ref) -> None:
    """End-to-end: feed events through LLMAliasMiner using the adapter."""
    canned = AliasProposalBatch(proposals=[])  # empty batch, just verify wiring
    fake = FakeOpenAIClient(response_payload=canned)
    adapter = OpenAIProposerClient(base_url="http://x/v1", client=fake)
    miner = LLMAliasMiner(ref, client=adapter, model="llama3:70b")

    aliases = miner.mine(
        [
            DowntimeEvent(
                external_id="e-1",
                asset_ref="x",
                text="Belt tripped",
                start_ts=datetime(2026, 1, 1),
            )
        ]
    )
    assert aliases == []
    assert fake.captured["model"] == "llama3:70b"
