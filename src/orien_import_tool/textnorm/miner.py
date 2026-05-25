# ruff: noqa: E501
"""LLM-based abbreviation miner.

Normalisation surfaces *unknown tokens* — operator shorthand and jargon that's
neither valid English nor a domain term (``splc``, ``instr``, ``simocode``,
``peflo``). This miner asks an LLM to expand the genuine abbreviations
(``instr`` -> ``instrument``) and flag the rest (product names, equipment
codes) as not expandable. Output is :class:`Abbreviation` proposals tagged
``proposer="llm"`` for SME review — never auto-applied.

Same architectural shape as the alias miner and ISO proposer:

* ``claude-opus-4-7`` default; any :class:`ProposerClient` (Anthropic or the
  OpenAI-compatible local adapter)
* cached system prompt with domain context so expansions are domain-flavoured
* ``client.messages.parse()`` with a Pydantic schema
* mocked client in tests; never hits a real API there

This is the generalisation engine for the cleanup layer: each dataset
auto-discovers its own shorthand instead of relying on a hand-curated seed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from orien_import_tool.textnorm.abbreviations import (
    Abbreviation,
    AbbreviationStore,
    AbbrevProposer,
)


@dataclass(frozen=True, slots=True)
class TokenContext:
    """Disambiguation evidence for one unknown token, gathered from the data.

    ``examples`` are short free-text snippets where the token appears.
    ``cooccurring`` are the validated/coded labels (category, component, table
    descriptions) the token shows up next to. Both let the LLM decide what a
    token means from context instead of guessing the bare string — the reason
    ``bmak`` was mis-read as "brake" when sent alone, while the data labels it
    "boiler making".
    """

    examples: tuple[str, ...] = ()
    cooccurring: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.examples or self.cooccurring)


if TYPE_CHECKING:
    from orien_import_tool.domain.fmea import Equipment
    from orien_import_tool.iso14224 import Iso14224ReferenceSet
    from orien_import_tool.llm.protocols import ProposerClient


DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 16384
DEFAULT_BATCH_SIZE = 40


class AbbreviationProposal(BaseModel):
    """One proposed shorthand expansion."""

    short: str = Field(description="The unknown operator token, lowercase.")
    expansion: str = Field(
        description="The expanded form (e.g. 'instrument' for 'instr'). Empty if not expandable."
    )
    is_expandable: bool = Field(
        description="True if `short` is an abbreviation/typo with a meaningful expansion; "
        "False for product names, equipment codes, or unrecognisable tokens."
    )
    confidence: float = Field(ge=0, le=1)
    rationale: str
    group: str = Field(
        default="",
        description="Short family label clustering related tokens — use the SAME label for "
        "related tokens (e.g. 'comms', 'safety-device', 'plc-variant', 'sensor', 'typo'). "
        "One family per token.",
    )


class AbbreviationProposalBatch(BaseModel):
    """Top-level LLM response."""

    proposals: list[AbbreviationProposal] = Field(default_factory=list)


class LLMAbbreviationMiner:
    """Mines abbreviation expansions from unknown operator tokens."""

    def __init__(
        self,
        equipment: Equipment | None = None,
        iso_ref: Iso14224ReferenceSet | None = None,
        client: ProposerClient | None = None,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._equipment = equipment
        self._iso_ref = iso_ref
        self._model = model
        self._max_tokens = max_tokens
        self._batch_size = batch_size
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self._system_prompt = self._build_system_prompt()

    # --- Public API -------------------------------------------------------------------

    def mine(
        self,
        unknown_tokens: Iterable[str] | Counter[str],
        *,
        skip_known: AbbreviationStore | None = None,
        context: Mapping[str, TokenContext] | None = None,
    ) -> list[Abbreviation]:
        """Return :class:`Abbreviation` rows (proposer=LLM) for expandable tokens.

        ``unknown_tokens`` may be a plain iterable or a Counter (frequency is
        used only to order the batch — most-frequent first). Tokens already in
        ``skip_known`` are filtered out so re-runs don't re-propose settled
        shorthand. Non-expandable proposals (product codes, proper nouns) are
        dropped from the result — they're noise for the abbreviation store.

        ``context`` optionally supplies per-token :class:`TokenContext`
        (example usages + co-occurring validated labels). When present it's
        folded into the prompt so the model disambiguates from real context
        rather than the bare token.
        """
        ordered = self._order_tokens(unknown_tokens, skip_known)
        out: list[Abbreviation] = []
        for batch in self._batches(ordered):
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system_prompt,
                messages=[{"role": "user", "content": self._build_user_message(batch, context)}],
                output_format=AbbreviationProposalBatch,
            )
            for proposal in response.parsed_output.proposals:
                if proposal.is_expandable and proposal.expansion.strip():
                    out.append(
                        Abbreviation(
                            short=proposal.short,
                            expansion=proposal.expansion.strip(),
                            proposer=AbbrevProposer.LLM,
                            confidence=proposal.confidence,
                            rationale=proposal.rationale,
                            group=proposal.group.strip(),
                        )
                    )
        return out

    # --- Internals --------------------------------------------------------------------

    def _order_tokens(
        self,
        unknown_tokens: Iterable[str] | Counter[str],
        skip_known: AbbreviationStore | None,
    ) -> list[str]:
        if isinstance(unknown_tokens, Counter):
            ordered = [tok for tok, _ in unknown_tokens.most_common()]
        else:
            # Preserve first-seen order, dedupe.
            seen: set[str] = set()
            ordered = []
            for tok in unknown_tokens:
                if tok not in seen:
                    seen.add(tok)
                    ordered.append(tok)
        if skip_known is not None:
            ordered = [t for t in ordered if t not in skip_known]
        return ordered

    def _build_system_prompt(self) -> list[dict[str, Any]]:
        lines = [
            "You expand maintenance-operator shorthand into plain technical English.",
            "",
            "For each token you are given, decide:",
            "- If it is an abbreviation, contraction, or obvious typo of a maintenance term, set is_expandable=true and give the expansion (e.g. 'instr' -> 'instrument', 'gbx' -> 'gearbox', 'temp' -> 'temperature').",
            "- If it is a product name, manufacturer code, equipment tag, or unrecognisable, set is_expandable=false and leave expansion empty (e.g. 'simocode' is a Siemens product, 'esrl'/'mwtu' look like equipment codes).",
            "",
            "Expand toward the equipment's domain vocabulary below when ambiguous.",
            "Some tokens include context lines: 'appears alongside' lists the validated category/component labels the token co-occurs with, and 'e.g.' lines show real usage. Use that context to disambiguate — e.g. a token on rows labelled 'BOILER MAKING' is a boiler-making term, not a brake.",
            "Lowercase expansions. Keep them short — the expansion replaces the token inline in operator text.",
        ]
        if self._equipment is not None:
            lines += ["", "## Equipment context (component descriptions)"]
            for component in self._equipment.components:
                lines.append(f"- {component.description}")
            # A sample of failure-mode vocabulary helps domain-flavoured expansion.
            verbs: set[str] = set()
            for component in self._equipment.components:
                for function in component.functions:
                    for failure in function.failures:
                        for fm in failure.failure_modes:
                            verbs.update(fm.mechanism_and_cause.split())
            if verbs:
                sample = ", ".join(sorted(v.lower() for v in verbs if v.isalpha())[:40])
                lines += ["", "## Failure-mode vocabulary (sample)", sample]
        lines += [
            "",
            "## Output rules",
            "- One proposal per input token; preserve the token verbatim in `short`.",
            "- confidence 0.0-1.0; 0.9+ only for unambiguous expansions.",
            "- rationale: one short sentence.",
            "- group: a short family label; give related tokens the SAME label so a reviewer "
            "sees them clustered (e.g. PLC variants together, comms terms together, typos together).",
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
        tokens: list[str],
        context: Mapping[str, TokenContext] | None = None,
    ) -> str:
        lines = ["Expand these operator tokens (or mark them not expandable):", ""]
        for token in tokens:
            lines.append(f"- {token}")
            ctx = context.get(token) if context else None
            if ctx and ctx.cooccurring:
                lines.append(f"    appears alongside: {'; '.join(ctx.cooccurring)}")
            if ctx:
                for example in ctx.examples:
                    lines.append(f"    e.g. {example!r}")
        return "\n".join(lines)

    def _batches(self, tokens: list[str]) -> list[list[str]]:
        return [tokens[i : i + self._batch_size] for i in range(0, len(tokens), self._batch_size)]
