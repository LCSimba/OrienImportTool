# ruff: noqa: E501
"""LLM-based mapping proposer — second opinion on hard FailureMode cases.

Wraps the Anthropic API to ask Claude for ISO 14224 candidates for an Orien
FailureMode. The full ISO catalog goes in a cached system prompt (it's the
same on every call); the per-call user message is just the failure-mode text
plus any rule-proposer context. Output uses ``messages.parse()`` against a
Pydantic schema so the response is validated structurally, not string-matched.

The proposer is **advisory** — its outputs are
:class:`Iso14224Mapping` rows tagged ``Proposer.LLM``, queued for SME review
just like rule-proposer multi-candidates.

Wire-level details follow the patterns in the Claude API skill:

* ``claude-opus-4-7`` default (latest, most capable)
* ``cache_control: {"type": "ephemeral"}`` on the ISO-catalog block
* ``client.messages.parse(..., output_format=Pydantic)`` for validated output
* Sync API; outputs are short (~hundreds of tokens), no streaming needed
* No real API in tests — the constructor accepts an injected client
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from orien_import_tool.iso14224 import Iso14224ReferenceSet
from orien_import_tool.llm.protocols import ProposerClient
from orien_import_tool.mapping.models import (
    Iso14224Mapping,
    MappingDimension,
    Proposer,
)

if TYPE_CHECKING:
    from orien_import_tool.domain.fmea import FailureMode


DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 4096


# --- Pydantic response schema -------------------------------------------------------


class B15Suggestion(BaseModel):
    """One B15 (failure-mode) candidate from the LLM."""

    code: str = Field(description="A B15 failure_mode code drawn verbatim from the catalog.")
    confidence: float = Field(ge=0, le=1)
    rationale: str


class B2Suggestion(BaseModel):
    """One B2 (mechanism) candidate from the LLM."""

    sub_code: str = Field(description="A B2 sub_code (e.g. '1.1', '2.4') from the catalog.")
    confidence: float = Field(ge=0, le=1)
    rationale: str


class B3Suggestion(BaseModel):
    """One B3 (cause) candidate from the LLM."""

    sub_code: str = Field(description="A B3 sub_code (e.g. '1.1', '2.3') from the catalog.")
    confidence: float = Field(ge=0, le=1)
    priority: int = Field(ge=0, description="0 = primary candidate; higher = alternate.")
    rationale: str


class FailureModeProposal(BaseModel):
    """Top-level LLM response for a single FailureMode."""

    mode: B15Suggestion | None = None
    mechanisms: list[B2Suggestion] = Field(default_factory=list)
    causes: list[B3Suggestion] = Field(default_factory=list)


# --- Proposer -----------------------------------------------------------------------


class LLMProposer:
    """Sends FailureModes to Claude and returns ``Iso14224Mapping`` rows."""

    def __init__(
        self,
        ref: Iso14224ReferenceSet,
        client: ProposerClient | None = None,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._ref = ref
        self._model = model
        self._max_tokens = max_tokens
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self._b15_codes = set(ref.failure_modes)
        self._b2_subcodes = set(ref.failure_mechanisms)
        self._b3_subcodes = set(ref.failure_causes)
        self._system_prompt = self._build_system_prompt()

    # --- Public API -------------------------------------------------------------------

    def propose_for_failure_mode(
        self,
        fm: FailureMode,
        rule_proposals: list[Iso14224Mapping] | None = None,
    ) -> list[Iso14224Mapping]:
        """Ask Claude for B15 / B2 / B3 candidates for one FailureMode.

        ``rule_proposals`` is shown to the model as context (the rule-based
        suggestion). The LLM may agree, refine, or override.
        """
        user_text = self._build_user_message(fm, rule_proposals or [])
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_text}],
            output_format=FailureModeProposal,
        )
        proposal = response.parsed_output
        return self._convert(proposal, fm)

    # --- Prompt construction ----------------------------------------------------------

    def _build_system_prompt(self) -> list[dict[str, Any]]:
        """Cached system prompt with the full ISO 14224 catalog.

        Returned as a list with a single text block carrying
        ``cache_control={"type": "ephemeral"}`` so the bytes are cached after
        the first call. The catalog is large and identical on every call, so
        this is the highest-leverage place to cache.
        """
        lines = [
            "You are an ISO 14224 reliability-engineering expert.",
            "Your job: map an Orien Tactics failure-mode description to ISO 14224 codes.",
            "",
            "Output one B15 (mode), one or more B2 (mechanism), and one or more B3 (cause) candidates.",
            "Use codes verbatim from the catalog below — do NOT invent codes or paraphrase names.",
            "",
            "## ISO 14224 — B.15 Failure Mode Descriptions",
            "(failure_mode → description)",
        ]
        for code, m in self._ref.failure_modes.items():
            lines.append(f"- {code}: {m.description}")
        lines += [
            "",
            "## ISO 14224 — B.2 Failure Mechanisms",
            "(sub_code → category — sub_name: description)",
        ]
        for c, mech in self._ref.failure_mechanisms.items():
            lines.append(f"- {c}: {mech.main_category} — {mech.sub_name}: {mech.description}")
        lines += [
            "",
            "## ISO 14224 — B.3 Failure Causes",
            "(sub_code → category — sub_name: description)",
        ]
        for c, cause in self._ref.failure_causes.items():
            lines.append(f"- {c}: {cause.main_category} — {cause.sub_name}: {cause.description}")
        lines += [
            "",
            "## Mapping rules",
            "",
            "- MODE (B.15): exactly one observable failure-mode code. Always provide one when possible.",
            "- MECHANISM (B.2): one or more sub_codes. Multi-tag when the failure has both an X-side mechanism (from the verb) and a Y-side mechanism (from the cause text).",
            "- CAUSE (B.3): one or more sub_codes ordered most-likely first via `priority` (0 = primary, 1 = first alternate, 2 = second alternate, etc.).",
            "- Confidence is your own self-rated certainty 0.0-1.0. Use 0.9+ only when the mapping is unambiguous.",
            "- Rationale: one sentence per candidate, referencing the ISO description or example that justifies it.",
        ]
        return [
            {
                "type": "text",
                "text": "\n".join(lines),
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _build_user_message(
        self,
        fm: FailureMode,
        rule_proposals: list[Iso14224Mapping],
    ) -> str:
        parts = [
            "Orien failure mode:",
            f"- mechanism_and_cause: {fm.mechanism_and_cause!r}",
        ]
        if fm.what:
            parts.append(f"- what fails: {fm.what!r}")
        if fm.strategy_type:
            parts.append(f"- strategy_type: {fm.strategy_type!r}")

        if rule_proposals:
            parts += [
                "",
                "Rule-based suggestion (for context — you may agree, refine, or override):",
            ]
            mode = next(
                (m for m in rule_proposals if m.dimension == MappingDimension.MODE),
                None,
            )
            if mode:
                parts.append(f"- MODE (B15): {mode.iso_code}")
            mechs = [m for m in rule_proposals if m.dimension == MappingDimension.MECHANISM]
            if mechs:
                joined = ", ".join(m.iso_code for m in mechs)
                parts.append(f"- MECHANISM (B2): {joined}")
            causes = sorted(
                (m for m in rule_proposals if m.dimension == MappingDimension.CAUSE),
                key=lambda m: m.priority,
            )
            if causes:
                joined = ", ".join(f"{m.iso_code} (priority={m.priority})" for m in causes)
                parts.append(f"- CAUSE (B3) candidates: {joined}")

        parts += [
            "",
            "Provide your mapping using the structured-output schema.",
        ]
        return "\n".join(parts)

    # --- Response conversion ----------------------------------------------------------

    def _convert(
        self,
        proposal: FailureModeProposal,
        fm: FailureMode,
    ) -> list[Iso14224Mapping]:
        """Convert a validated Pydantic proposal into Iso14224Mapping rows.

        Codes the LLM hallucinates (i.e. not present in the loaded catalog)
        are filtered out — the LLM is advisory, not authoritative.
        """
        out: list[Iso14224Mapping] = []
        if proposal.mode and proposal.mode.code in self._b15_codes:
            out.append(
                Iso14224Mapping(
                    source_entity_type="FailureMode",
                    source_entity_id=fm.token,
                    dimension=MappingDimension.MODE,
                    iso_code=proposal.mode.code,
                    proposer=Proposer.LLM,
                    confidence=proposal.mode.confidence,
                    rationale=proposal.mode.rationale,
                    priority=0,
                )
            )
        for m in proposal.mechanisms:
            if m.sub_code not in self._b2_subcodes:
                continue
            out.append(
                Iso14224Mapping(
                    source_entity_type="FailureMode",
                    source_entity_id=fm.token,
                    dimension=MappingDimension.MECHANISM,
                    iso_code=m.sub_code,
                    proposer=Proposer.LLM,
                    confidence=m.confidence,
                    rationale=m.rationale,
                    priority=0,
                )
            )
        for c in proposal.causes:
            if c.sub_code not in self._b3_subcodes:
                continue
            out.append(
                Iso14224Mapping(
                    source_entity_type="FailureMode",
                    source_entity_id=fm.token,
                    dimension=MappingDimension.CAUSE,
                    iso_code=c.sub_code,
                    proposer=Proposer.LLM,
                    confidence=c.confidence,
                    rationale=c.rationale,
                    priority=c.priority,
                )
            )
        return out
