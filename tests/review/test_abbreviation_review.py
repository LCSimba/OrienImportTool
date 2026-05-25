"""Abbreviation review + persistence + round-trip.

Covers the feedback loop: LLM proposes -> build review -> SME accepts ->
persist to AbbreviationRepository -> rehydrate into a store the normaliser
can use.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from orien_import_tool.persistence import AbbreviationRepository, AuditLogRepository
from orien_import_tool.review import (
    ReviewDecision,
    ReviewItemType,
    ReviewVerdict,
    apply_decisions,
    build_abbreviation_review,
    decisions_from_csv,
    queue_from_csv,
    queue_to_csv,
)
from orien_import_tool.textnorm.abbreviations import (
    Abbreviation,
    AbbreviationStore,
    AbbrevProposer,
)


def _llm_abbrev(short: str, expansion: str) -> Abbreviation:
    return Abbreviation(
        short=short,
        expansion=expansion,
        proposer=AbbrevProposer.LLM,
        confidence=0.8,
        rationale="mined",
    )


# --- builder ------------------------------------------------------------------------


def test_build_abbreviation_review_keeps_llm_only() -> None:
    abbrevs = [
        _llm_abbrev("instr", "instrument"),
        Abbreviation("mtr", "motor", AbbrevProposer.RULE),
        Abbreviation("brg", "bearing", AbbrevProposer.SME),
    ]
    queue = build_abbreviation_review(abbrevs)
    assert len(queue) == 1
    item = queue.items[0]
    assert item.item_type == ReviewItemType.ABBREVIATION
    assert item.payload == {
        "short": "instr",
        "expansion": "instrument",
        "rationale": "mined",
        "group": "",
    }


# --- CSV round-trip -----------------------------------------------------------------


def test_abbreviation_round_trips_through_csv() -> None:
    queue = build_abbreviation_review([_llm_abbrev("instr", "instrument")])
    csv_text = queue_to_csv(queue)
    rebuilt = queue_from_csv(csv_text)
    item = rebuilt.items[0]
    assert item.item_type == ReviewItemType.ABBREVIATION
    assert item.payload["short"] == "instr"
    assert item.payload["expansion"] == "instrument"


def test_group_lands_in_sortable_csv_column() -> None:
    """The family label surfaces as a dedicated column so the SME can cluster."""
    import csv as _csv
    import io

    abbrev = Abbreviation(
        "iplc", "input plc", AbbrevProposer.LLM, 0.7, "plc variant", group="plc-variant"
    )
    csv_text = queue_to_csv(build_abbreviation_review([abbrev]))
    rows = list(_csv.DictReader(io.StringIO(csv_text)))
    assert rows[0]["group"] == "plc-variant"
    # And it still round-trips via payload_json.
    assert queue_from_csv(csv_text).items[0].payload["group"] == "plc-variant"


# --- apply -> store -----------------------------------------------------------------


def test_accepted_abbreviation_lands_in_store() -> None:
    queue = build_abbreviation_review([_llm_abbrev("instr", "instrument")])
    store = AbbreviationStore()
    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.ACCEPTED)
    result = apply_decisions([decision], queue, abbreviation_store=store)
    assert result.abbreviations_added == 1
    assert store.expand("instr") == "instrument"


def test_corrected_abbreviation_uses_chosen_alternative() -> None:
    queue = build_abbreviation_review([_llm_abbrev("instr", "wrong")])
    store = AbbreviationStore()
    decision = ReviewDecision(
        item_id=queue.items[0].item_id,
        verdict=ReviewVerdict.CORRECTED,
        chosen_alternative="instrument",
    )
    apply_decisions([decision], queue, abbreviation_store=store)
    assert store.expand("instr") == "instrument"


def test_rejected_abbreviation_not_stored() -> None:
    queue = build_abbreviation_review([_llm_abbrev("xyz", "something")])
    store = AbbreviationStore()
    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.REJECTED)
    result = apply_decisions([decision], queue, abbreviation_store=store)
    assert result.abbreviations_rejected == 1
    assert store.expand("xyz") is None


# --- apply -> persistence (#1) ------------------------------------------------------


def test_accepted_abbreviation_persists_to_repository(session: Session) -> None:
    queue = build_abbreviation_review([_llm_abbrev("instr", "instrument")])
    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.ACCEPTED)
    repo = AbbreviationRepository(session)
    audit = AuditLogRepository(session)
    result = apply_decisions(
        [decision],
        queue,
        abbreviation_repository=repo,
        audit_log_repository=audit,
        sme_user="alice",
    )
    session.commit()

    assert result.abbreviations_added == 1
    persisted = repo.all()
    assert any(a.short == "instr" and a.proposer == AbbrevProposer.SME for a in persisted)
    assert audit.for_entity("abbreviation", queue.items[0].item_id)


# --- repository -> store feedback (#2) ----------------------------------------------


def test_repository_to_store_layers_persisted_over_seed(session: Session) -> None:
    repo = AbbreviationRepository(session)
    repo.add(Abbreviation("peflo", "perform flow check", AbbrevProposer.SME, rationale="confirmed"))
    session.commit()

    store = repo.to_store(seeded=True)
    # Seed shorthand still present...
    assert store.expand("mtr") == "motor"
    # ...plus the SME-confirmed one.
    assert store.expand("peflo") == "perform flow check"


def test_repository_to_store_unseeded_is_persisted_only(session: Session) -> None:
    repo = AbbreviationRepository(session)
    repo.add(Abbreviation("peflo", "perform flow check", AbbrevProposer.SME))
    session.commit()
    store = repo.to_store(seeded=False)
    assert store.expand("peflo") == "perform flow check"
    assert store.expand("mtr") is None  # no seed


# --- end-to-end CSV -> decisions -> persist -----------------------------------------


def test_end_to_end_csv_to_persist(session: Session) -> None:
    queue = build_abbreviation_review(
        [_llm_abbrev("instr", "instrument"), _llm_abbrev("gbx", "gearbox")]
    )
    csv_text = queue_to_csv(queue)

    # SME marks both accepted (simulate editing the verdict column).
    import csv as _csv
    import io

    rows = list(_csv.DictReader(io.StringIO(csv_text)))
    for r in rows:
        r["verdict"] = "accepted"
    out = io.StringIO()
    w = _csv.DictWriter(out, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
    edited = out.getvalue()

    # apply rebuilds the queue from the CSV payload — no source needed.
    rebuilt = queue_from_csv(edited)
    decisions = decisions_from_csv(edited)
    repo = AbbreviationRepository(session)
    result = apply_decisions(decisions, rebuilt, abbreviation_repository=repo)
    session.commit()

    assert result.abbreviations_added == 2
    store = repo.to_store(seeded=False)
    assert store.expand("instr") == "instrument"
    assert store.expand("gbx") == "gearbox"


# --- unexpandable-token review (the "what we didn't expand" category) ----------------


def test_build_unexpandable_review_surfaces_tokens() -> None:
    from orien_import_tool.review import build_unexpandable_review
    from orien_import_tool.textnorm import UnexpandableToken

    queue = build_unexpandable_review(
        [
            UnexpandableToken(
                "simocode", rationale="Siemens product", confidence=0.8, group="product"
            )
        ]
    )
    assert len(queue) == 1
    item = queue.items[0]
    assert item.item_type == ReviewItemType.UNKNOWN_TOKEN
    assert item.primary_proposal == ""
    assert item.payload == {"short": "simocode", "rationale": "Siemens product", "group": "product"}


def test_corrected_unknown_token_becomes_sme_abbreviation() -> None:
    from orien_import_tool.review import build_unexpandable_review
    from orien_import_tool.textnorm import UnexpandableToken

    queue = build_unexpandable_review([UnexpandableToken("splc", rationale="looks like a code")])
    store = AbbreviationStore()
    decision = ReviewDecision(
        item_id=queue.items[0].item_id,
        verdict=ReviewVerdict.CORRECTED,
        chosen_alternative="safety plc",
    )
    result = apply_decisions([decision], queue, abbreviation_store=store)
    assert result.abbreviations_added == 1
    assert store.expand("splc") == "safety plc"


def test_accepted_unknown_token_writes_nothing() -> None:
    from orien_import_tool.review import build_unexpandable_review
    from orien_import_tool.textnorm import UnexpandableToken

    queue = build_unexpandable_review([UnexpandableToken("vuma", rationale="conveyor name")])
    store = AbbreviationStore()
    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.ACCEPTED)
    result = apply_decisions([decision], queue, abbreviation_store=store)
    assert result.abbreviations_added == 0
    assert store.expand("vuma") is None


def test_accepted_unknown_token_persists_to_suppression_store(session: Session) -> None:
    """Accepting 'leave as-is' records the token so future mining skips it."""
    from orien_import_tool.persistence import NonExpandableTokenRepository
    from orien_import_tool.review import build_unexpandable_review
    from orien_import_tool.textnorm import UnexpandableToken

    queue = build_unexpandable_review([UnexpandableToken("vuma", rationale="conveyor name")])
    repo = NonExpandableTokenRepository(session)
    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.ACCEPTED)
    result = apply_decisions([decision], queue, non_expandable_repository=repo, sme_user="alice")
    session.commit()

    assert result.non_expandable_confirmed == 1
    assert "vuma" in repo.tokens()
