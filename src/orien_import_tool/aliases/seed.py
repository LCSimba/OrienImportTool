"""Seed an :class:`AliasStore` from canonical sources.

This is the deterministic, rule-tagged starting set every system gets before
any LLM mining or SME curation. It contains:

* Identity aliases for FMEA verbs from the mechanism+cause vocabulary
  (e.g. "wears" -> ("wears",)) — the classifier already matches these
  directly, so the alias is mostly for SME inspectability.
* Common operator -> FMEA mappings curated empirically against the AI_Test
  CMMS fixture (e.g. "tripped" -> ("stoppage", "stop")).
* B15 / B2 / B3 names as identity aliases so the term store can introspect
  the canonical vocabulary.

The set is deliberately small and conservative — the LLM miner expands it.
"""

from __future__ import annotations

from orien_import_tool.aliases.models import Alias, AliasProposer
from orien_import_tool.aliases.store import AliasStore
from orien_import_tool.classification.preprocessor import tokenise
from orien_import_tool.domain.fmea import Equipment
from orien_import_tool.iso14224 import Iso14224ReferenceSet

# Operator vocabulary observed on the AI_Test fixture. Each entry pairs an
# operator term with one or more canonical tokens that the FMEA actually uses,
# so expanding via this alias gives the classifier a real match.
_CMMS_OPERATOR_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Stoppage / outage flavour
    ("tripped", ("stoppage", "stop")),
    ("trip", ("stoppage", "stop")),
    ("tripping", ("stoppage", "stop")),
    ("stopped", ("stoppage", "stop")),
    ("stop", ("stoppage", "stop")),
    ("stopping", ("stoppage", "stop")),
    ("shutdown", ("stoppage", "stop")),
    ("offline", ("stoppage", "stop")),
    # Failure flavour
    ("faulty", ("failure", "failed")),
    ("fault", ("failure", "failed")),
    ("failed", ("failure", "failed")),
    ("failing", ("failure", "failed")),
    ("broken", ("breaks", "broken", "fracture")),
    ("collapsed", ("breaks", "broken", "fracture")),
    ("collapsing", ("breaks", "broken", "fracture")),
    ("damaged", ("breaks", "broken", "wears")),
    ("worn", ("wears", "worn")),
    ("torn", ("severs", "broken")),
    # Blocking flavour
    ("blocked", ("blocks", "blockage")),
    ("blockage", ("blocks", "blockage")),
    ("plugged", ("blocks", "blockage")),
    ("clogged", ("blocks", "blockage")),
    ("stuck", ("immobilised", "binds", "jams")),
    ("jammed", ("immobilised", "binds", "jams")),
    # Loose / disconnected flavour
    ("loose", ("loses", "preload", "looseness")),
    ("disconnected", ("loses", "preload", "looseness")),
    ("dislodged", ("loses", "preload", "looseness")),
    # Heat flavour
    ("overheating", ("overheats", "melts")),
    ("overheated", ("overheats", "melts")),
    ("burned", ("burns", "overheats")),
    ("burnt", ("burns", "overheats")),
    ("melted", ("melts", "overheats")),
    # Wear flavour
    ("wear", ("wears", "wear")),
    ("worn-out", ("wears", "wear")),
    ("eroded", ("washes", "erosion")),
    # Vibration / noise
    ("vibrating", ("vibration",)),
    ("vibration", ("vibration",)),
    ("rattling", ("vibration",)),
    ("grinding", ("rubbing", "wears")),
    ("noisy", ("vibration",)),
    # Lubrication
    ("oil", ("lubrication", "lubricant")),
    ("oiled", ("lubrication", "lubricant")),
    ("grease", ("lubrication", "lubricant")),
    ("greased", ("lubrication", "lubricant")),
    ("dry", ("lack", "lubrication")),
    # Electrical
    ("short", ("short", "circuit", "circuiting")),
    ("shorted", ("short", "circuit", "circuiting")),
    ("arc", ("arcs", "arcing")),
    ("arcing", ("arcs", "arcing")),
    ("spark", ("arcs", "arcing")),
    ("sparking", ("arcs", "arcing")),
)


def build_initial_alias_store(
    equipment: Equipment | None = None,
    iso_ref: Iso14224ReferenceSet | None = None,
) -> AliasStore:
    """Construct a seed :class:`AliasStore`.

    Both arguments are optional — if absent, only the curated CMMS operator
    aliases are seeded. Passing ``equipment`` and ``iso_ref`` adds identity
    aliases for the catalog vocabulary so SMEs can browse what's recognised.
    """
    store = AliasStore()
    _seed_cmms_operator_aliases(store)
    if iso_ref is not None:
        _seed_iso_identity_aliases(store, iso_ref)
    if equipment is not None:
        _seed_equipment_identity_aliases(store, equipment)
    return store


def _seed_cmms_operator_aliases(store: AliasStore) -> None:
    for alias_text, canonical_tokens in _CMMS_OPERATOR_ALIASES:
        store.add(
            Alias(
                alias_text=alias_text,
                canonical_tokens=canonical_tokens,
                proposer=AliasProposer.RULE,
                confidence=0.9,
                rationale="Curated CMMS-vocabulary mapping",
            )
        )


def _seed_iso_identity_aliases(store: AliasStore, iso_ref: Iso14224ReferenceSet) -> None:
    """B15 / B2 / B3 names as identity aliases (token -> token)."""

    def _add_text(text: str, hint: str) -> None:
        for token in tokenise(text):
            store.add(
                Alias(
                    alias_text=token,
                    canonical_tokens=(token,),
                    proposer=AliasProposer.RULE,
                    confidence=1.0,
                    iso_hint=hint,
                    rationale="Identity alias for ISO 14224 vocabulary",
                )
            )

    for fm in iso_ref.failure_modes.values():
        _add_text(fm.code, f"B15:{fm.code}")
    for mech in iso_ref.failure_mechanisms.values():
        _add_text(mech.sub_name, f"B2:{mech.sub_code}")
    for cause in iso_ref.failure_causes.values():
        _add_text(cause.sub_name, f"B3:{cause.sub_code}")


def _seed_equipment_identity_aliases(store: AliasStore, equipment: Equipment) -> None:
    """Component-description tokens as identity aliases scoped to the equipment."""
    for component in equipment.components:
        for token in tokenise(component.description):
            store.add(
                Alias(
                    alias_text=token,
                    canonical_tokens=(token,),
                    proposer=AliasProposer.RULE,
                    confidence=1.0,
                    scope_equipment_token=equipment.token,
                    rationale="Identity alias for component vocabulary",
                )
            )
