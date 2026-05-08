"""Build a seed index from a canonical Equipment tree.

The classifier's vocabulary comes from the FMEA itself — every Component
description and every FailureMode's mechanism+cause + what text becomes a
seed. This file is the data prep step; the classifier does the matching.

The index uses inverse-document-frequency (IDF) weighting so that rare
domain tokens (``thermography``, ``cavitation``) outweigh common ones
(``system``, ``conveyor``). Without IDF, every event would match the asset
name with a high score regardless of fault content.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from orien_import_tool.classification.preprocessor import tokenise
from orien_import_tool.domain.fmea import Component, Equipment, FailureMode


@dataclass
class _Doc:
    token_set: frozenset[str]
    source_text: str


@dataclass
class SeedIndex:
    """Token-level seed index for downtime classification.

    Build via :func:`build_seed_index`.
    """

    component_docs: dict[str, _Doc] = field(default_factory=dict)
    failure_mode_docs: dict[str, _Doc] = field(default_factory=dict)
    failure_modes_by_component: dict[str, set[str]] = field(default_factory=dict)
    component_descriptions: dict[str, str] = field(default_factory=dict)
    token_idf: dict[str, float] = field(default_factory=dict)

    def component_tokens(self, component_token: str) -> frozenset[str]:
        doc = self.component_docs.get(component_token)
        return doc.token_set if doc else frozenset()

    def failure_mode_tokens(self, failure_mode_token: str) -> frozenset[str]:
        doc = self.failure_mode_docs.get(failure_mode_token)
        return doc.token_set if doc else frozenset()

    def all_failure_modes(self) -> list[str]:
        return list(self.failure_mode_docs)

    def failure_modes_under(self, component_token: str) -> set[str]:
        return self.failure_modes_by_component.get(component_token, set())

    def idf(self, token: str) -> float:
        """IDF weight for a token; unknown tokens get weight ``0`` (no signal)."""
        return self.token_idf.get(token, 0.0)


def build_seed_index(equipment: Equipment) -> SeedIndex:
    """Build a :class:`SeedIndex` from an :class:`Equipment` tree."""

    component_docs: dict[str, _Doc] = {}
    component_descriptions: dict[str, str] = {}
    failure_mode_docs: dict[str, _Doc] = {}
    failure_modes_by_component: dict[str, set[str]] = defaultdict(set)

    for component in equipment.components:
        component_text = _component_text(component)
        component_docs[component.token] = _Doc(
            token_set=frozenset(tokenise(component_text)),
            source_text=component_text,
        )
        component_descriptions[component.token] = component.description

        for function in component.functions:
            for failure in function.failures:
                for fm in failure.failure_modes:
                    fm_text = _failure_mode_text(fm, function.description, failure.description)
                    failure_mode_docs[fm.token] = _Doc(
                        token_set=frozenset(tokenise(fm_text)),
                        source_text=fm_text,
                    )
                    failure_modes_by_component[component.token].add(fm.token)

    token_idf = _compute_idf(component_docs, failure_mode_docs)

    return SeedIndex(
        component_docs=component_docs,
        failure_mode_docs=failure_mode_docs,
        failure_modes_by_component=dict(failure_modes_by_component),
        component_descriptions=component_descriptions,
        token_idf=token_idf,
    )


def _component_text(component: Component) -> str:
    """Concatenate description + parent_description + make/model for matching."""
    parts = [component.description]
    if component.parent_description:
        parts.append(component.parent_description)
    if component.make:
        parts.append(component.make)
    if component.model:
        parts.append(component.model)
    return " ".join(parts)


def _failure_mode_text(
    fm: FailureMode,
    function_description: str,
    failure_description: str,
) -> str:
    """Concatenate everything that should match against the event text."""
    parts: list[str] = []
    if fm.what:
        parts.append(fm.what)
    if fm.mechanism_and_cause:
        parts.append(fm.mechanism_and_cause)
    if function_description:
        parts.append(function_description)
    if failure_description:
        parts.append(failure_description)
    return " ".join(parts)


def _compute_idf(
    component_docs: dict[str, _Doc],
    failure_mode_docs: dict[str, _Doc],
) -> dict[str, float]:
    """Standard IDF: ``log((N + 1) / (df + 1)) + 1``.

    Combines components and failure modes into a single document set so a
    token that's globally common across the FMEA (e.g. ``conveyor``) gets a
    low weight even if it appears in every component.
    """
    docs = list(component_docs.values()) + list(failure_mode_docs.values())
    if not docs:
        return {}
    n = len(docs)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(doc.token_set)
    return {token: math.log((n + 1) / (count + 1)) + 1.0 for token, count in df.items()}
