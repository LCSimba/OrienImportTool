# ruff: noqa: E501
"""LLM-based alias miner.

Walks a batch of unmatched / low-confidence downtime events, asks Claude to
propose operator->canonical-token mappings, and returns the proposals for
SME review (never auto-accepted).

Same architectural shape as
:class:`~orien_import_tool.mapping.LLMProposer`:

* ``claude-opus-4-7`` default
* Cached system prompt with the FMEA + ISO 14224 vocabulary
* ``client.messages.parse()`` with a Pydantic schema
* Mocked client in tests; never hits the real API there
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from orien_import_tool.aliases.models import Alias, AliasProposer
from orien_import_tool.iso14224 import Iso14224ReferenceSet

if TYPE_CHECKING:
    import anthropic

    from orien_import_tool.domain.downtime import DowntimeEvent
    from orien_import_tool.domain.fmea import Equipment


DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_BATCH_SIZE = 50


class AliasProposal(BaseModel):
    """One proposed operator-vocabulary -> canonical-token mapping."""

    alias_text: str = Field(description="Operator-vocabulary token, lowercase, single word.")
    canonical_tokens: list[str] = Field(
        description="One or more tokens that already appear in the FMEA vocabulary."
    )
    iso_hint: str = Field(default="", description="Optional ISO 14224 reference (e.g. 'B15:Worn').")
    confidence: float = Field(ge=0, le=1)
    rationale: str


class AliasProposalBatch(BaseModel):
    """Top-level LLM response."""

    proposals: list[AliasProposal] = Field(default_factory=list)


class LLMAliasMiner:
    """Mines operator-vocabulary alias candidates from downtime events.

    The system prompt embeds the canonical FMEA vocabulary (verbs from the
    mechanism+cause dropdown plus a compact ISO 14224 catalog) so the LLM
    only proposes mappings to tokens that the classifier can actually use.
    """

    def __init__(
        self,
        ref: Iso14224ReferenceSet,
        equipment: Equipment | None = None,
        client: anthropic.Anthropic | None = None,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._ref = ref
        self._equipment = equipment
        self._model = model
        self._max_tokens = max_tokens
        self._batch_size = batch_size
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self._system_prompt = self._build_system_prompt()

    # --- Public API -------------------------------------------------------------

    def mine(self, events: list[DowntimeEvent]) -> list[Alias]:
        """Return :class:`Alias` rows tagged ``Proposer.LLM`` for SME review.

        Splits the input into batches of ``batch_size`` to keep prompts
        bounded. Hallucinated canonical tokens (those that don't appear in
        the FMEA's verb/term vocabulary) are not filtered here — the alias
        store can hold them, and the classifier ignores any expansion that
        doesn't match the seed index.
        """
        out: list[Alias] = []
        for batch in self._batches(events):
            user_text = self._build_user_message(batch)
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system_prompt,
                messages=[{"role": "user", "content": user_text}],
                output_format=AliasProposalBatch,
            )
            for proposal in response.parsed_output.proposals:
                out.append(
                    Alias(
                        alias_text=proposal.alias_text,
                        canonical_tokens=tuple(proposal.canonical_tokens),
                        proposer=AliasProposer.LLM,
                        confidence=proposal.confidence,
                        iso_hint=proposal.iso_hint,
                        rationale=proposal.rationale,
                    )
                )
        return out

    # --- Prompt construction ----------------------------------------------------

    def _build_system_prompt(self) -> list[dict[str, Any]]:
        lines = [
            "You map operator-entered downtime vocabulary to canonical FMEA tokens.",
            "",
            "Only propose ``canonical_tokens`` from the FMEA vocabulary catalog below — the classifier will only use tokens it already knows.",
            "If an operator term has no clear FMEA equivalent, omit it.",
            "Lowercase the operator term. Strip punctuation. Single-word terms preferred; multi-word phrases acceptable when the meaning is collocated.",
            "",
            "## Canonical FMEA verb vocabulary (use these as canonical_tokens)",
            "(from Orien mechanismAndCause verbs)",
            "- arcs, blocks, breaks, fracture, separates, corrodes, cracks, degrades, distorts, drifts, expires, immobilised, binds, jams, loses, preload, melts, overheats, burns, severs, washes, wears, thermally, overloads",
            "- stoppage, stop, failure, failed, blockage, looseness, vibration, lubrication, lubricant, rubbing, fretting, abrasion, fatigue, breakage, deformation, sticking, erosion, cavitation, corrosion",
            "",
            "## ISO 14224 — B.15 Failure Mode Descriptions",
        ]
        for code in self._ref.failure_modes:
            lines.append(f"- B15: {code}")
        lines += ["", "## ISO 14224 — B.2 Failure Mechanisms (sub_code: sub_name)"]
        for c, mech in self._ref.failure_mechanisms.items():
            lines.append(f"- B2: {c} {mech.sub_name}")
        lines += ["", "## ISO 14224 — B.3 Failure Causes (sub_code: sub_name)"]
        for c, cause in self._ref.failure_causes.items():
            lines.append(f"- B3: {c} {cause.sub_name}")

        if self._equipment is not None:
            lines += ["", "## Equipment context (component descriptions)"]
            for component in self._equipment.components:
                lines.append(f"- {component.description}")

        lines += [
            "",
            "## Output rules",
            "- canonical_tokens: list of words that appear verbatim in the verb vocabulary above.",
            "- iso_hint: optional ('B15:<code>' or 'B2:<sub_code>' or 'B3:<sub_code>') for SME readability.",
            "- confidence: 0.0-1.0; use 0.9+ only for unambiguous direct synonyms.",
            "- rationale: one sentence per proposal.",
        ]
        return [
            {
                "type": "text",
                "text": "\n".join(lines),
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _build_user_message(self, events: list[DowntimeEvent]) -> str:
        lines = [
            "Below are downtime descriptions that did not match the FMEA. Propose alias",
            "mappings for operator-specific terms that recur and have a clear FMEA equivalent.",
            "Skip terms that already match (no need to propose 'belt' -> 'belt').",
            "",
            "Events:",
        ]
        for event in events:
            lines.append(f"- [{event.external_id}] asset={event.asset_ref!r} text={event.text!r}")
        return "\n".join(lines)

    # --- Batching ---------------------------------------------------------------

    def _batches(self, events: list[DowntimeEvent]) -> list[list[DowntimeEvent]]:
        return [events[i : i + self._batch_size] for i in range(0, len(events), self._batch_size)]
