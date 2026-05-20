"""Structural protocols for proposer clients.

The proposers only need one method: ``client.messages.parse(...)``. Defining
that surface as a :class:`Protocol` lets us type-check against it without
importing vendor SDKs at module load time. Anthropic's
``Anthropic`` class, our :class:`~orien_import_tool.llm.OpenAIProposerClient`
adapter, and test fakes all satisfy it structurally.
"""

from __future__ import annotations

from typing import Any, Protocol


class ParsedResponse(Protocol):
    """The shape returned by ``client.messages.parse(...)``.

    Both the Anthropic SDK and our OpenAI adapter expose ``parsed_output`` as
    the validated Pydantic instance. The exact type is the Pydantic class
    passed in as ``output_format``.
    """

    parsed_output: Any


class _MessagesNamespace(Protocol):
    def parse(
        self,
        *,
        model: str,
        max_tokens: int,
        system: Any,
        messages: list[dict[str, Any]],
        output_format: type,
    ) -> ParsedResponse: ...


class ProposerClient(Protocol):
    """Minimal client surface required by the LLM proposers."""

    messages: _MessagesNamespace
