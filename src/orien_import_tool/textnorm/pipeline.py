"""Event-level normalisation helpers.

Where the classifiers take a ``normalizer`` and clean text *internally* (the
ergonomic path), these helpers produce a cleaned :class:`DowntimeEvent` plus
the :class:`NormalizationResult` *explicitly* — for callers that want to
persist the corrections (audit) or harvest the unknown tokens (the
abbreviation-mining queue).

The cleaned event keeps the same ``external_id`` so downstream
classifications still link back to it; ``asset_ref`` is left untouched
(it's a tag/code, not prose). The original text isn't lost — it's carried on
the returned :class:`NormalizationResult.original_text`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable

from orien_import_tool.domain.downtime import DowntimeEvent
from orien_import_tool.textnorm.normalizer import NormalizationResult, TextNormalizer


def normalize_event(
    event: DowntimeEvent,
    normalizer: TextNormalizer,
) -> tuple[DowntimeEvent, NormalizationResult]:
    """Return a cleaned copy of ``event`` plus the normalisation result."""
    result = normalizer.normalize(event.text)
    cleaned = dataclasses.replace(event, text=result.cleaned_text)
    return cleaned, result


def normalize_events(
    events: Iterable[DowntimeEvent],
    normalizer: TextNormalizer,
) -> tuple[list[DowntimeEvent], list[NormalizationResult]]:
    """Normalise a batch; return (cleaned_events, results) in input order."""
    cleaned: list[DowntimeEvent] = []
    results: list[NormalizationResult] = []
    for event in events:
        c, r = normalize_event(event, normalizer)
        cleaned.append(c)
        results.append(r)
    return cleaned, results
