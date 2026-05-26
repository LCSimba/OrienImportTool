"""Pipeline B stage 3 — asset-ID filtering, component linking (FMEA seed
index), failure-mode linking (ISO B.15 + VERB_TO_B15), and the orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from orien_import_tool.classification.seeds import build_seed_index
from orien_import_tool.domain.downtime import ExtractedEntities
from orien_import_tool.domain.fmea import Component, Equipment
from orien_import_tool.iso14224 import load_all
from orien_import_tool.linking import (
    ComponentLinker,
    EntityLinker,
    FailureModeLinker,
    looks_like_asset_id,
)


@pytest.fixture
def index():
    equipment = Equipment(
        token="eq-1",
        description="Conveyor",
        components=[
            Component(token="c-belt", description="Belt"),
            Component(token="c-roller", description="Sequence Roller"),
            Component(token="c-brg", description="Drive Motor Bearing"),
        ],
    )
    return build_seed_index(equipment)


@pytest.fixture(scope="module")
def ref(iso_dir: Path):
    return load_all(iso_dir)


# --- asset-ID heuristic -------------------------------------------------------------


def test_asset_id_detection() -> None:
    for span in ["e1", "e2", "4a", "vuma-1 conveyor", "thusa-2", "b-conv", "ucv4e1 conveyor"]:
        assert looks_like_asset_id(span), span
    for span in ["belt", "end unit", "pull key", "sequence roller bracket", "chute detector"]:
        assert not looks_like_asset_id(span), span


# --- component linking --------------------------------------------------------------


def test_component_linker_matches_and_contains(index) -> None:
    assert ComponentLinker(index).link("belt").component_token == "c-belt"
    # span carries extra words but still links to the component's key tokens
    assert ComponentLinker(index).link("sequence roller bracket").component_token == "c-roller"
    # a single key token links to a longer component description (containment)
    assert ComponentLinker(index).link("bearing").component_token == "c-brg"


def test_component_linker_unmatched_below_threshold(index) -> None:
    link = ComponentLinker(index).link("gremlin widget")
    assert link.component_token == ""
    assert not link.matched


# --- failure-mode linking -----------------------------------------------------------


def test_failure_linker_exact_and_stem(ref) -> None:
    linker = FailureModeLinker(ref)
    assert "broken" in linker.link("broken").iso_b15.lower()  # exact B.15 word
    assert linker.link("fracture").matched  # stem match -> fractured
    assert linker.link("blockage").matched  # stem match -> blocked


def test_failure_linker_verb_table_fallback(ref) -> None:
    # 'wears' is not a literal B.15 word; VERB_TO_B15 maps it to 'Worn'.
    assert FailureModeLinker(ref).link("wears").iso_b15 == "Worn"


def test_failure_linker_unmatched(ref) -> None:
    assert not FailureModeLinker(ref).link("zzz").matched


# --- orchestrator -------------------------------------------------------------------


def test_entity_linker_end_to_end(index, ref) -> None:
    extracted = ExtractedEntities(
        event_external_id="e-1",
        cleaned_text="belt broken on e1 conveyor",
        components=("belt", "e1 conveyor"),
        failure_modes=("broken", "fracture"),
    )
    linked = EntityLinker(index, ref).link(extracted)

    assert linked.asset_ids == ("e1 conveyor",)  # section id filtered out
    assert [c.component_token for c in linked.components] == ["c-belt"]
    assert all(fm.matched for fm in linked.failure_modes)
