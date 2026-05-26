# ruff: noqa: E501
"""LLM component extractor — open extraction of component mentions.

Given cleaned operator text (one row per event), the LLM returns the physical
component(s)/equipment named, as the operator wrote them — *not* matched to the
FMEA. Failure words, actions, and category codes are excluded; that's the
deterministic tagger's job (failure modes) or noise.

Same architectural shape as the alias / abbreviation miners: any
:class:`ProposerClient` (Anthropic or the OpenAI-compatible local adapter),
cached system prompt, ``client.messages.parse()`` with a Pydantic schema,
mocked in tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from orien_import_tool.llm.protocols import ProposerClient

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_BATCH_SIZE = 40


class RowComponents(BaseModel):
    """Components extracted from one input row."""

    index: int = Field(description="The 0-based index of the input row.")
    components: list[str] = Field(
        default_factory=list,
        description="Physical component/equipment names mentioned, as written. Empty if none.",
    )


class ComponentExtractionBatch(BaseModel):
    """Top-level LLM response: one entry per input row that has components."""

    rows: list[RowComponents] = Field(default_factory=list)


class LLMComponentExtractor:
    """Extracts component mentions from cleaned operator text via an LLM."""

    def __init__(
        self,
        client: ProposerClient | None = None,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._batch_size = batch_size
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self._system_prompt = self._build_system_prompt()

    def extract(self, texts: list[str]) -> list[list[str]]:
        """Return component lists aligned 1:1 with ``texts`` (empty list if none)."""
        out: list[list[str]] = [[] for _ in texts]
        for start in range(0, len(texts), self._batch_size):
            chunk = texts[start : start + self._batch_size]
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system_prompt,
                messages=[{"role": "user", "content": self._build_user_message(chunk)}],
                output_format=ComponentExtractionBatch,
            )
            for row in response.parsed_output.rows:
                gi = start + row.index
                if 0 <= gi < len(out):
                    out[gi] = [c.strip() for c in row.components if c.strip()]
        return out

    # --- prompt construction ----------------------------------------------------

    def _build_system_prompt(self) -> list[dict[str, Any]]:
        text = "\n".join(
            [
                "You extract the physical component(s) / equipment named in short maintenance notes.",
                "",
                "Return the component as the operator wrote it (lowercase, trimmed). Multi-word is fine ('sequence roller', 'pull key', 'chute detector').",
                "Do NOT return:",
                "- failure words or states (broken, faulty, tripped, blocked, leaking),",
                "- actions (replace, repair, inspect, reset),",
                "- category codes / departments (elec, mech, inst, bmak, control - system),",
                "- bare adjectives or quantities.",
                "If a row names no concrete component, return an empty list for it.",
                "Echo the row index you were given. Omit rows that have no components.",
            ]
        )
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    def _build_user_message(self, texts: list[str]) -> str:
        lines = ["Extract components from each row (index: text):", ""]
        for i, text in enumerate(texts):
            lines.append(f"{i}: {text}")
        return "\n".join(lines)
