"""Argparse-based CLI for SME review tooling.

Subcommands:

* ``export`` — given an Orien fixture path and (optionally) a downtime
  XLSX path, build a unified review queue and write it to CSV / Markdown.
* ``apply`` — re-import an SME-edited CSV and apply alias decisions.

Designed to be invokable as ``python -m orien_import_tool.review`` (see
``__main__.py``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orien_import_tool.aliases import build_initial_alias_store
from orien_import_tool.classification import AliasClassifier, build_seed_index
from orien_import_tool.importers.downtime import parse_xlsx
from orien_import_tool.importers.orien import normalize, parse_workbook
from orien_import_tool.iso14224 import load_all
from orien_import_tool.mapping import propose_mappings
from orien_import_tool.review.applier import apply_decisions
from orien_import_tool.review.builders import build_unified_queue
from orien_import_tool.review.exporters import (
    decisions_from_csv,
    queue_to_csv,
    queue_to_markdown,
)


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

    args = parser.parse_args(argv)

    if args.command == "export":
        return _export(args)
    if args.command == "apply":
        return _apply(args)
    return 1


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
    queue = _build_queue(args)
    decisions = decisions_from_csv(args.decisions_csv.read_text(encoding="utf-8"))

    if args.db_url:
        from orien_import_tool.persistence import (
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
                audit_log_repository=AuditLogRepository(session),
                sme_user=args.sme_user,
            )
            session.commit()
    else:
        alias_store = build_initial_alias_store()
        result = apply_decisions(decisions, queue, alias_store=alias_store, sme_user=args.sme_user)

    print(
        f"Applied {len(decisions)} decisions: "
        f"+{result.aliases_added} aliases, "
        f"-{result.aliases_rejected} rejected, "
        f"{result.mappings_recorded} mappings, "
        f"{result.classifications_recorded} classifications, "
        f"{result.audit_entries} audit entries, "
        f"{len(result.skipped)} skipped",
        file=sys.stderr,
    )
    return 0


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
