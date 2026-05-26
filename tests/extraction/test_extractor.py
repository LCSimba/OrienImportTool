"""Pipeline B stage-2 extraction: failure vocab, deterministic tagging,
LLM component extraction (mocked), and the orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orien_import_tool.aliases import Alias, AliasProposer
from orien_import_tool.aliases.store import AliasStore
from orien_import_tool.domain.downtime import DowntimeEvent
from orien_import_tool.extraction import (
    ComponentExtractionBatch,
    EntityExtractor,
    LLMComponentExtractor,
    RowComponents,
    build_failure_vocabulary,
    tag_failure_modes,
)
from orien_import_tool.iso14224 import load_all


def _event(text_line3: str, eid: str = "e-1") -> DowntimeEvent:
    return DowntimeEvent(external_id=eid, asset_ref="conveyor", text="x", text_line3=text_line3)


# --- failure vocabulary -------------------------------------------------------------


def test_build_vocabulary_from_curated_and_iso(iso_dir: Path) -> None:
    ref = load_all(iso_dir)
    vocab = build_failure_vocabulary(ref)

    assert "fracture" in vocab  # curated generic term
    assert "erratic" in vocab  # derived from ISO B.15 'Erratic output'
    assert "output" not in vocab  # B.15 plumbing word filtered out
    # Component words must NOT leak into the failure vocabulary.
    assert "belt" not in vocab
    assert "conveyor" not in vocab


def test_tag_failure_modes_intersects_vocabulary() -> None:
    vocab = frozenset({"fracture", "blockage"})
    assert tag_failure_modes(["belt", "fracture", "noise"], vocab) == ("fracture",)
    assert tag_failure_modes(["clean"], vocab) == ()


# --- deterministic extraction (no LLM) ----------------------------------------------


def test_extractor_tags_failure_modes_without_llm() -> None:
    extractor = EntityExtractor(build_failure_vocabulary())
    [res] = extractor.extract([_event("SEQUENCE ROLLER BRACKET BROKEN")])
    assert "broken" in res.failure_modes
    assert res.components == ()  # no component extractor wired
    assert res.cleaned_text == "SEQUENCE ROLLER BRACKET BROKEN"  # no normalizer


def test_extractor_uses_alias_expansion_for_failure_modes() -> None:
    store = AliasStore()
    store.add(Alias("snapped", ("fracture",), proposer=AliasProposer.SME))
    extractor = EntityExtractor(build_failure_vocabulary(), alias_store=store)
    [res] = extractor.extract([_event("main shaft snapped")])
    assert "fracture" in res.failure_modes  # reached only via alias expansion


def test_extractor_prefers_text_line3_then_falls_back() -> None:
    extractor = EntityExtractor(build_failure_vocabulary())
    ev = DowntimeEvent(external_id="1", asset_ref="c", text="full", free_text="free broken")
    [res] = extractor.extract([ev])  # no text_line3 -> falls back to free_text
    assert res.cleaned_text == "free broken"
    assert "broken" in res.failure_modes


# --- LLM component extraction (mocked) ----------------------------------------------


@dataclass
class _Resp:
    parsed_output: ComponentExtractionBatch


class _Msgs:
    def __init__(self, responses: list[ComponentExtractionBatch]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> _Resp:
        self.calls.append(kwargs)
        return _Resp(self._responses.pop(0) if self._responses else ComponentExtractionBatch())


class _Client:
    def __init__(self, *responses: ComponentExtractionBatch) -> None:
        self.messages = _Msgs(list(responses))


def test_component_extractor_aligns_by_index_and_fills_gaps() -> None:
    canned = ComponentExtractionBatch(
        rows=[
            RowComponents(index=0, components=["sequence roller", "bracket"]),
            RowComponents(index=2, components=["chute detector"]),  # index 1 omitted
        ]
    )
    extractor = LLMComponentExtractor(client=_Client(canned))
    out = extractor.extract(
        ["sequence roller bracket broken", "no comms", "blocked chute detector faulty"]
    )
    assert out == [["sequence roller", "bracket"], [], ["chute detector"]]


def test_entity_extractor_attaches_components() -> None:
    canned = ComponentExtractionBatch(rows=[RowComponents(index=0, components=["roller"])])
    extractor = EntityExtractor(
        build_failure_vocabulary(),
        component_extractor=LLMComponentExtractor(client=_Client(canned)),
    )
    [res] = extractor.extract([_event("roller broken")])
    assert res.components == ("roller",)
    assert "broken" in res.failure_modes
