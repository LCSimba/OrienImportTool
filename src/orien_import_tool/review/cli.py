"""Argparse-based CLI for SME review tooling.

Subcommands:

* ``export`` — given an Orien fixture path and (optionally) a downtime
  XLSX path, build a unified review queue and write it to CSV / Markdown.
* ``apply`` — re-import an SME-edited CSV and apply alias decisions.
* ``mine-aliases`` — drive :class:`LLMAliasMiner` against low-confidence
  events using a local (or hosted) OpenAI-compatible endpoint, and write
  the proposed aliases as a review CSV ready for ``apply``.

Designed to be invokable as ``python -m orien_import_tool.review`` (see
``__main__.py``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from orien_import_tool.aliases import build_initial_alias_store
from orien_import_tool.classification import AliasClassifier, build_seed_index
from orien_import_tool.importers.downtime import parse_xlsx
from orien_import_tool.importers.orien import normalize, parse_workbook
from orien_import_tool.iso14224 import load_all
from orien_import_tool.mapping import propose_mappings
from orien_import_tool.review.applier import apply_decisions
from orien_import_tool.review.builders import (
    build_abbreviation_review,
    build_alias_review,
    build_unified_queue,
)
from orien_import_tool.review.exporters import (
    decisions_from_csv,
    queue_from_csv,
    queue_to_csv,
    queue_to_markdown,
)

if TYPE_CHECKING:
    from orien_import_tool.llm.protocols import ProposerClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orien-review", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="Build the review queue and write CSV/Markdown.")
    export.add_argument("--orien", type=Path, required=True, help="Orien Tactics .xlsx fixture.")
    export.add_argument("--iso-dir", type=Path, default=Path("data/iso14224"))
    export.add_argument(
        "--downtime",
        type=Path,
        help="Optional downtime .xlsx (CMMS export).",
    )
    export.add_argument(
        "--downtime-sheet",
        default="Conveyor",
        help="Sheet name within the downtime workbook (default: Conveyor).",
    )
    export.add_argument("--csv", type=Path, help="Write CSV here.")
    export.add_argument("--markdown", type=Path, help="Write Markdown here.")

    apply = sub.add_parser("apply", help="Apply SME decisions from an edited CSV.")
    apply.add_argument("--orien", type=Path, required=True)
    apply.add_argument("--iso-dir", type=Path, default=Path("data/iso14224"))
    apply.add_argument("--downtime", type=Path)
    apply.add_argument("--downtime-sheet", default="Conveyor")
    apply.add_argument("--decisions-csv", type=Path, required=True)
    apply.add_argument(
        "--db-url",
        default="",
        help=(
            "Optional SQLAlchemy URL (e.g. 'sqlite:///review.db' or "
            "'postgresql+psycopg://user:pass@host/db'). When set, "
            "alias/mapping/classification decisions and the audit log "
            "persist to the database."
        ),
    )
    apply.add_argument(
        "--sme-user",
        default="",
        help="Reviewer name to record on audit-log entries.",
    )

    mine = sub.add_parser(
        "mine-aliases",
        help="Drive the LLM alias miner against low-confidence events.",
    )
    mine.add_argument("--orien", type=Path, required=True)
    mine.add_argument("--iso-dir", type=Path, default=Path("data/iso14224"))
    mine.add_argument("--downtime", type=Path, required=True)
    mine.add_argument("--downtime-sheet", default="Conveyor")
    mine.add_argument("--csv", type=Path, help="Write proposed aliases here (else stdout).")
    mine.add_argument(
        "--score-threshold",
        type=float,
        default=0.3,
        help=(
            "Mine events whose top-FM score is below this. Defaults to 0.3 — "
            "events the alias-rule classifier already handles confidently are "
            "skipped, saving LLM calls."
        ),
    )
    mine.add_argument(
        "--max-events",
        type=int,
        default=200,
        help="Cap on events sent to the LLM in one run.",
    )
    mine.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help=(
            "Events per LLM call. Smaller batches = shorter prompts and "
            "shorter generations per call (each call stays well under "
            "the timeout); larger batches = fewer calls. Default 25."
        ),
    )
    mine.add_argument(
        "--max-tokens",
        type=int,
        default=16384,
        help=(
            "Per-call generation cap. Thinking models (DeepSeek-R1, QwQ, "
            "Qwen3-*) burn roughly half their token budget on chain-of-"
            "thought before producing JSON, so a generous default keeps "
            "the answer from being cut off."
        ),
    )
    mine.add_argument(
        "--db-url",
        default="",
        help=(
            "Optional SQLAlchemy URL. When set, SME-confirmed aliases and "
            "abbreviations from prior runs are loaded so classification and "
            "normalisation benefit from accumulated knowledge."
        ),
    )
    mine.add_argument(
        "--no-normalize",
        action="store_true",
        help=(
            "Skip text normalisation before classification. Normalisation "
            "needs the [textnorm] extra (pyspellchecker)."
        ),
    )
    _add_llm_args(mine)

    abbr = sub.add_parser(
        "mine-abbreviations",
        help="Expand unknown operator shorthand via the LLM (cleanup layer).",
    )
    abbr.add_argument("--orien", type=Path, required=True)
    abbr.add_argument("--iso-dir", type=Path, default=Path("data/iso14224"))
    abbr.add_argument("--downtime", type=Path, required=True)
    abbr.add_argument("--downtime-sheet", default="Conveyor")
    abbr.add_argument("--csv", type=Path, help="Write proposed abbreviations here (else stdout).")
    abbr.add_argument(
        "--max-unknowns",
        type=int,
        default=150,
        help="Cap on distinct unknown tokens sent to the LLM (most-frequent first).",
    )
    abbr.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="Cap events scanned for unknown tokens (0 = all). Lower for a quick sample.",
    )
    abbr.add_argument("--max-tokens", type=int, default=16384)
    abbr.add_argument(
        "--db-url",
        default="",
        help=(
            "Optional SQLAlchemy URL. When set, SME-confirmed abbreviations "
            "from prior runs are loaded so the normaliser expands them and "
            "they no longer surface as unknown — the store self-improves."
        ),
    )
    _add_llm_args(abbr)

    args = parser.parse_args(argv)

    if args.command == "export":
        return _export(args)
    if args.command == "apply":
        return _apply(args)
    if args.command == "mine-aliases":
        return _mine_aliases(args)
    if args.command == "mine-abbreviations":
        return _mine_abbreviations(args)
    return 1


# --- LLM helpers --------------------------------------------------------------------


def _add_llm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--llm-url",
        default="",
        help=(
            "OpenAI-compatible endpoint base URL. Examples: "
            "vLLM 'http://host:8000/v1', Ollama 'http://host:11434/v1', "
            "LM Studio 'http://localhost:1234/v1'."
        ),
    )
    parser.add_argument(
        "--llm-model",
        default="",
        help="Model name your server serves (e.g. 'qwen2.5-32b-instruct').",
    )
    parser.add_argument(
        "--llm-api-key",
        default="sk-local",
        help="API key; most local runtimes ignore this.",
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=600.0,
        help=(
            "Per-request timeout in seconds. Cold-start a 27B+ model and "
            "the first call can be very slow (model load + 4k-token gen); "
            "default 600 covers that. Drop to 60 once the server is warm "
            "if you want fast-fail."
        ),
    )
    parser.add_argument(
        "--no-thinking",
        action="store_true",
        help=(
            "For thinking models served via vLLM (Qwen3-*, QwQ), send "
            "chat_template_kwargs={'enable_thinking': False} to skip the "
            "chain-of-thought phase. Alias mining and ISO mapping are "
            "retrieval/classification tasks where deliberation buys "
            "little — disabling thinking typically halves per-call latency."
        ),
    )


def _make_llm_client(args) -> ProposerClient:
    """Build an OpenAI-compatible client from CLI flags."""
    if not args.llm_url or not args.llm_model:
        raise SystemExit("--llm-url and --llm-model are required for this subcommand")
    from orien_import_tool.llm import OpenAIProposerClient

    extra_body: dict = {}
    if getattr(args, "no_thinking", False):
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    return OpenAIProposerClient(
        base_url=args.llm_url,
        api_key=args.llm_api_key,
        model_name=args.llm_model,
        timeout=args.llm_timeout,
        extra_body=extra_body or None,
    )


# --- Subcommand handlers ------------------------------------------------------------


def _export(args) -> int:
    queue = _build_queue(args)
    if args.csv:
        args.csv.write_text(queue_to_csv(queue), encoding="utf-8")
        print(f"Wrote {len(queue)} review items to {args.csv}", file=sys.stderr)
    if args.markdown:
        args.markdown.write_text(queue_to_markdown(queue), encoding="utf-8")
        print(f"Wrote review queue Markdown to {args.markdown}", file=sys.stderr)
    if not args.csv and not args.markdown:
        # No output target — print CSV to stdout.
        sys.stdout.write(queue_to_csv(queue))
    return 0


def _apply(args) -> int:
    csv_text = args.decisions_csv.read_text(encoding="utf-8")
    decisions = decisions_from_csv(csv_text)
    # Reconstruct the queue from the CSV itself (payload_json carries each
    # item's context), so LLM-derived items (aliases, abbreviations) round-trip
    # without re-running the proposer that produced them.
    queue = queue_from_csv(csv_text)

    if args.db_url:
        from orien_import_tool.persistence import (
            AbbreviationRepository,
            AliasRepository,
            AuditLogRepository,
            DowntimeRepository,
            MappingRepository,
            init_db,
            make_engine,
            make_session_factory,
        )

        engine = make_engine(args.db_url)
        init_db(engine)
        factory = make_session_factory(engine)
        with factory() as session:
            result = apply_decisions(
                decisions,
                queue,
                alias_repository=AliasRepository(session),
                mapping_repository=MappingRepository(session),
                downtime_repository=DowntimeRepository(session),
                abbreviation_repository=AbbreviationRepository(session),
                audit_log_repository=AuditLogRepository(session),
                sme_user=args.sme_user,
            )
            session.commit()
    else:
        from orien_import_tool.textnorm import AbbreviationStore

        result = apply_decisions(
            decisions,
            queue,
            alias_store=build_initial_alias_store(),
            abbreviation_store=AbbreviationStore(),
            sme_user=args.sme_user,
        )

    print(
        f"Applied {len(decisions)} decisions: "
        f"+{result.aliases_added} aliases (-{result.aliases_rejected}), "
        f"+{result.abbreviations_added} abbreviations (-{result.abbreviations_rejected}), "
        f"{result.mappings_recorded} mappings, "
        f"{result.classifications_recorded} classifications, "
        f"{result.audit_entries} audit entries, "
        f"{len(result.skipped)} skipped",
        file=sys.stderr,
    )
    return 0


def _mine_aliases(args) -> int:
    from orien_import_tool.aliases import LLMAliasMiner
    from orien_import_tool.textnorm import normalize_events

    equipment = normalize(parse_workbook(args.orien))
    iso_ref = load_all(args.iso_dir)
    alias_store, abbrev_store = _knowledge_stores(args, equipment, iso_ref)

    normalizer = None
    if not getattr(args, "no_normalize", False):
        normalizer = _build_normalizer(equipment, iso_ref, abbrev_store)

    classifier = AliasClassifier(
        build_seed_index(equipment),
        alias_store=alias_store,
        normalizer=normalizer,
    )

    events = parse_xlsx(args.downtime, args.downtime_sheet)
    low_conf = _select_low_confidence_events(
        events,
        classifier,
        threshold=args.score_threshold,
        cap=args.max_events,
    )
    # Send the LLM cleaned text — normalisation already fixed typos/abbreviations.
    if normalizer is not None and low_conf:
        low_conf, _ = normalize_events(low_conf, normalizer)
    print(
        f"Selected {len(low_conf)}/{len(events)} events below score {args.score_threshold} "
        f"(capped at {args.max_events}). Sending to {args.llm_url} / {args.llm_model}...",
        file=sys.stderr,
    )

    client = _make_llm_client(args)
    miner = LLMAliasMiner(
        iso_ref,
        equipment=equipment,
        client=client,
        model=args.llm_model,
        max_tokens=args.max_tokens,
        batch_size=args.batch_size,
    )
    proposed = miner.mine(low_conf)
    print(f"Got {len(proposed)} alias proposals back.", file=sys.stderr)

    queue = build_alias_review(proposed)
    if args.csv:
        args.csv.write_text(queue_to_csv(queue), encoding="utf-8")
        print(f"Wrote {len(queue)} alias review items to {args.csv}", file=sys.stderr)
    else:
        sys.stdout.write(queue_to_csv(queue))
    return 0


def _knowledge_stores(args, equipment, iso_ref):
    """Build (alias_store, abbreviation_store) = rule seed + DB-persisted rows.

    Without ``--db-url`` returns just the seeded stores. With it, layers the
    SME/LLM-confirmed rows from prior ``apply`` runs on top — so every run of
    the pipeline benefits from accumulated, reviewed knowledge.
    """
    from orien_import_tool.textnorm import build_initial_abbreviations

    alias_store = build_initial_alias_store(equipment, iso_ref)
    abbrev_store = build_initial_abbreviations()

    db_url = getattr(args, "db_url", "")
    if db_url:
        from orien_import_tool.persistence import (
            AbbreviationRepository,
            AliasRepository,
            init_db,
            make_engine,
            make_session_factory,
        )

        engine = make_engine(db_url)
        init_db(engine)
        with make_session_factory(engine)() as session:
            alias_store.add_many(AliasRepository(session).all())
            abbrev_store.add_many(AbbreviationRepository(session).all())
    return alias_store, abbrev_store


def _build_normalizer(equipment, iso_ref, abbrev_store):
    """Construct a TextNormalizer over the domain dictionary + abbreviation store."""
    from orien_import_tool.textnorm import (
        PySpellEngine,
        TextNormalizer,
        build_domain_dictionary,
    )

    dictionary = build_domain_dictionary(equipment, iso_ref)
    return TextNormalizer(dictionary, PySpellEngine(dictionary), abbrev_store)


def _mine_abbreviations(args) -> int:
    import dataclasses
    from collections import Counter

    from orien_import_tool.textnorm import LLMAbbreviationMiner

    equipment = normalize(parse_workbook(args.orien))
    iso_ref = load_all(args.iso_dir)
    abbrev_store = _build_abbreviation_store(args)  # seed + any persisted (feedback loop)
    normalizer = _build_normalizer(equipment, iso_ref, abbrev_store)

    events = parse_xlsx(args.downtime, args.downtime_sheet)
    if args.max_events:
        events = events[: args.max_events]
    unknown_freq: Counter[str] = Counter()
    for event in events:
        for token in normalizer.normalize(event.text).unknown_tokens:
            unknown_freq[token] += 1

    top_unknowns = Counter(dict(unknown_freq.most_common(args.max_unknowns)))
    print(
        f"Found {len(unknown_freq)} distinct unknown tokens; "
        f"sending top {len(top_unknowns)} to {args.llm_url} / {args.llm_model}...",
        file=sys.stderr,
    )

    client = _make_llm_client(args)
    miner = LLMAbbreviationMiner(
        equipment=equipment,
        iso_ref=iso_ref,
        client=client,
        model=args.llm_model,
        max_tokens=args.max_tokens,
    )
    # Don't re-propose shorthand already in the store (seed or confirmed).
    proposed = miner.mine(top_unknowns, skip_known=abbrev_store)
    print(f"Got {len(proposed)} expandable abbreviation proposals.", file=sys.stderr)

    # Stash observed frequency into the rationale so the SME can prioritise.
    enriched = [
        dataclasses.replace(
            a, rationale=f"(seen {unknown_freq.get(a.short, 0)}x) {a.rationale}".strip()
        )
        for a in proposed
    ]
    queue = build_abbreviation_review(enriched)
    if args.csv:
        args.csv.write_text(queue_to_csv(queue), encoding="utf-8")
        print(f"Wrote {len(queue)} abbreviation review items to {args.csv}", file=sys.stderr)
    else:
        sys.stdout.write(queue_to_csv(queue))
    return 0


def _build_abbreviation_store(args):
    """Seed abbreviations + any SME/LLM rows persisted in the DB (feedback loop).

    When ``--db-url`` is set, confirmed abbreviations from a prior ``apply``
    run are layered on top of the rule seed, so the normaliser expands them
    and they no longer surface as unknown tokens — the store self-improves
    across runs.
    """
    from orien_import_tool.textnorm import build_initial_abbreviations

    db_url = getattr(args, "db_url", "")
    if not db_url:
        return build_initial_abbreviations()

    from orien_import_tool.persistence import (
        AbbreviationRepository,
        init_db,
        make_engine,
        make_session_factory,
    )

    engine = make_engine(db_url)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        return AbbreviationRepository(session).to_store(seeded=True)


def _select_low_confidence_events(
    events,
    classifier: AliasClassifier,
    *,
    threshold: float,
    cap: int,
) -> list:
    """Run the classifier and keep events whose primary FM score is below threshold."""
    selected = []
    for event in events:
        result = classifier.classify(event)
        top = result.failure_mode_candidates[0].score if result.failure_mode_candidates else 0.0
        if top < threshold:
            selected.append(event)
            if len(selected) >= cap:
                break
    return selected


def _build_queue(args):
    equipment = normalize(parse_workbook(args.orien))
    iso_ref = load_all(args.iso_dir)
    mapping_result = propose_mappings(equipment, iso_ref)

    classifications = None
    events_index = None
    if args.downtime is not None:
        events = parse_xlsx(args.downtime, args.downtime_sheet)
        classifier = AliasClassifier(
            build_seed_index(equipment),
            alias_store=build_initial_alias_store(equipment, iso_ref),
        )
        classifications = [classifier.classify(e) for e in events]
        events_index = {e.external_id: e for e in events}

    return build_unified_queue(
        mapping_result=mapping_result,
        classifications=classifications,
        events=events_index,
    )


if __name__ == "__main__":
    raise SystemExit(main())
