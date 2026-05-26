"""Stage-2 entity extraction for Pipeline B (before any FMEA matching).

Per event: clean the operator narrative (TextLine3) — spelling + abbreviations
via the :class:`TextNormalizer`, then alias mapping — and from the cleaned text
extract what it mentions:

* **failure modes** — deterministic tag against the generic failure vocabulary
  (:mod:`extraction.failure_terms`),
* **components** — open LLM extraction (:class:`LLMComponentExtractor`).

The result (:class:`ExtractedEntities`) is *not* matched to the equipment FMEA;
that linking is a later stage. The component extractor is optional so the
deterministic half runs (and is testable) with no LLM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from orien_import_tool.classification.preprocessor import tokenise
from orien_import_tool.domain.downtime import DowntimeEvent, ExtractedEntities
from orien_import_tool.extraction.failure_terms import tag_failure_modes

if TYPE_CHECKING:
    from orien_import_tool.aliases.store import AliasStore
    from orien_import_tool.extraction.components import LLMComponentExtractor
    from orien_import_tool.textnorm.normalizer import TextNormalizer


class EntityExtractor:
    """Clean operator text and extract components + failure modes from it."""

    def __init__(
        self,
        failure_vocabulary: frozenset[str],
        *,
        normalizer: TextNormalizer | None = None,
        alias_store: AliasStore | None = None,
        component_extractor: LLMComponentExtractor | None = None,
    ) -> None:
        self._vocab = failure_vocabulary
        self._normalizer = normalizer
        self._alias_store = alias_store
        self._component_extractor = component_extractor

    def clean(self, event: DowntimeEvent) -> str:
        """Cleaned operator text — TextLine3 preferred, falling back to free/full text."""
        source = event.text_line3 or event.free_text or event.text
        if self._normalizer is None:
            return source
        return self._normalizer.normalize(source).cleaned_text

    def extract(self, events: list[DowntimeEvent]) -> list[ExtractedEntities]:
        cleaned = [self.clean(event) for event in events]

        failure_modes: list[tuple[str, ...]] = []
        for text in cleaned:
            tokens = set(tokenise(text))
            if self._alias_store is not None:
                tokens |= self._alias_store.expand_tokens(tokens)
            failure_modes.append(tag_failure_modes(tokens, self._vocab))

        if self._component_extractor is not None:
            components = self._component_extractor.extract(cleaned)
        else:
            components = [[] for _ in cleaned]

        return [
            ExtractedEntities(
                event_external_id=event.external_id,
                cleaned_text=text,
                components=tuple(comps),
                failure_modes=fms,
            )
            for event, text, fms, comps in zip(
                events, cleaned, failure_modes, components, strict=True
            )
        ]
