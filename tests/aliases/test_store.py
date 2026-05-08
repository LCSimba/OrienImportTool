"""Tests for AliasStore CRUD + expand semantics."""

from __future__ import annotations

from orien_import_tool.aliases import Alias, AliasProposer, AliasStore


def _alias(text: str, *canonical: str, scope: str | None = None) -> Alias:
    return Alias(
        alias_text=text,
        canonical_tokens=tuple(canonical),
        proposer=AliasProposer.RULE,
        scope_equipment_token=scope,
    )


def test_add_and_get() -> None:
    store = AliasStore()
    store.add(_alias("tripped", "stoppage", "stop"))
    matches = store.get("tripped")
    assert len(matches) == 1
    assert matches[0].canonical_tokens == ("stoppage", "stop")


def test_add_normalises_text() -> None:
    store = AliasStore()
    store.add(_alias("Tripped!", "stoppage"))
    assert "tripped" in store
    assert store.get("TRIPPED")


def test_duplicate_aliases_collapsed() -> None:
    store = AliasStore()
    store.add(_alias("tripped", "stoppage", "stop"))
    store.add(_alias("tripped", "stoppage", "stop"))  # exact duplicate
    assert len(store.get("tripped")) == 1


def test_different_proposer_kept_separately() -> None:
    store = AliasStore()
    store.add(_alias("tripped", "stoppage"))
    sme_variant = Alias(
        alias_text="tripped",
        canonical_tokens=("stoppage",),
        proposer=AliasProposer.SME,
    )
    store.add(sme_variant)
    assert len(store.get("tripped")) == 2


def test_expand_token_unions_all_matches() -> None:
    store = AliasStore()
    store.add(_alias("tripped", "stoppage"))
    store.add(_alias("tripped", "stop", "shutdown"))
    expanded = store.expand_token("tripped")
    assert expanded == {"stoppage", "stop", "shutdown"}


def test_expand_tokens_handles_unknown() -> None:
    store = AliasStore()
    store.add(_alias("tripped", "stoppage"))
    expanded = store.expand_tokens({"tripped", "unknown_word"})
    assert expanded == {"stoppage"}


def test_scoped_alias_only_expands_in_scope() -> None:
    store = AliasStore()
    store.add(_alias("trunk", "trunk", scope="eq-conveyor-A"))

    assert store.expand_token("trunk", equipment_token="eq-conveyor-A") == {"trunk"}
    # Different equipment, scoped alias does not contribute.
    assert store.expand_token("trunk", equipment_token="eq-conveyor-B") == set()
    # Global call also excluded for scoped aliases.
    assert store.expand_token("trunk") == set()


def test_global_alias_active_regardless_of_scope() -> None:
    store = AliasStore()
    store.add(_alias("tripped", "stoppage"))
    assert store.expand_token("tripped", equipment_token="eq-1") == {"stoppage"}
    assert store.expand_token("tripped") == {"stoppage"}


def test_iter_yields_all_aliases() -> None:
    store = AliasStore()
    store.add(_alias("tripped", "stoppage"))
    store.add(_alias("faulty", "failure"))
    assert {a.alias_text for a in store} == {"tripped", "faulty"}
    assert len(store) == 2


def test_empty_alias_text_ignored() -> None:
    store = AliasStore()
    store.add(_alias("", "stoppage"))
    assert len(store) == 0
