"""Heuristic: does a component span actually name an equipment/section ID?

The component extractor sometimes returns conveyor-section identifiers
(``e1``, ``4a``, ``vuma-1 conveyor``, ``b-conv``) rather than physical
components. Those belong on the asset/location axis, not the component list, so
the linker filters them out before matching to the FMEA.

Deliberately conservative and domain-general: a span reads as an asset ID when,
after dropping the generic words ``conveyor`` / ``conv`` / ``section``, every
remaining token either carries a digit (``e1``, ``4a``, ``vuma2``) or is a
1-2 character stub (``b`` from ``b-conv``).
"""

from __future__ import annotations

from orien_import_tool.classification.preprocessor import tokenise

_GENERIC = frozenset({"conveyor", "conv", "section"})


def looks_like_asset_id(span: str) -> bool:
    core = [t for t in tokenise(span) if t not in _GENERIC]
    if not core:
        return False
    if any(any(ch.isdigit() for ch in token) for token in core):
        return True
    return all(len(token) <= 2 for token in core)
