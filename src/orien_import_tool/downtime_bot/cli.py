"""Command-line driver for the downtime voice bot.

Runs one capture conversation on the console (the default voice backend, so it
needs no audio dependency) and optionally persists the result. The taxonomy
that scopes the questions comes from an Orien export and/or a database that
already holds imported FMEA equipment.

    python -m orien_import_tool.downtime_bot \
        --orien tests/fixtures/orien/<export>.xlsx \
        --technician "J. Smith"

Add ``--db-url sqlite:///downtime.db --persist`` to write the captured event
and classification into the canonical store.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from orien_import_tool.domain.fmea import Equipment
from orien_import_tool.downtime_bot.engine import VoiceBotSession
from orien_import_tool.downtime_bot.slots import CapturedDowntime
from orien_import_tool.downtime_bot.taxonomy import CaptureTaxonomy
from orien_import_tool.downtime_bot.voice import ConsoleVoice
from orien_import_tool.iso14224 import load_all


def _load_equipment(orien: Path | None, db_url: str) -> list[Equipment]:
    equipment: list[Equipment] = []
    if orien is not None:
        from orien_import_tool.importers.orien import normalize, parse_workbook

        equipment.append(normalize(parse_workbook(orien)))
    if db_url:
        from orien_import_tool.persistence.repositories import EquipmentRepository
        from orien_import_tool.persistence.session import (
            init_db,
            make_engine,
            make_session_factory,
        )

        engine = make_engine(db_url)
        init_db(engine)
        with make_session_factory(engine)() as session:
            equipment.extend(EquipmentRepository(session).list())
    return equipment


def _build_taxonomy(orien: Path | None, db_url: str, iso_dir: Path) -> CaptureTaxonomy:
    equipment = _load_equipment(orien, db_url)
    iso = None
    if iso_dir.exists():
        try:
            iso = load_all(iso_dir)
        except Exception:
            iso = None
    return CaptureTaxonomy(equipment=equipment, iso=iso)


def _build_voice(args):
    """Return the configured voice backend (console or local mic)."""
    if args.voice == "local":
        from orien_import_tool.downtime_bot.local_voice import build_local_voice

        return build_local_voice(
            piper_voice_path=args.piper_voice,
            stt_model=args.stt_model,
            language=args.language,
        )
    return ConsoleVoice()


def _dump_json(captured: CapturedDowntime, path: Path) -> None:
    record = dataclasses.asdict(captured)
    record["started_at"] = captured.started_at.isoformat()
    record["completed_at"] = (
        captured.completed_at.isoformat() if captured.completed_at else None
    )
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orien-downtime-bot", description=__doc__)
    parser.add_argument("--orien", type=Path, help="Orien Tactics .xlsx to scope the taxonomy.")
    parser.add_argument(
        "--db-url",
        default="",
        help="SQLAlchemy URL to load FMEA equipment from and/or persist the capture.",
    )
    parser.add_argument("--iso-dir", type=Path, default=Path("data/iso14224"))
    parser.add_argument("--technician", default="", help="Reporting artisan/technician name.")
    parser.add_argument("--persist", action="store_true", help="Write the capture to --db-url.")
    parser.add_argument("--json", type=Path, help="Write the captured record as JSON.")
    parser.add_argument(
        "--voice",
        choices=["console", "local"],
        default="console",
        help="Voice backend: 'console' (typed, default) or 'local' (mic + "
        "faster-whisper + Piper; needs the 'voice' extra).",
    )
    parser.add_argument("--piper-voice", help="Path to a Piper .onnx voice (local backend).")
    parser.add_argument("--stt-model", default="small", help="faster-whisper model size.")
    parser.add_argument(
        "--language",
        default=None,
        help="Force an STT language code (e.g. 'en'); default auto-detect.",
    )
    args = parser.parse_args(argv)

    if args.persist and not args.db_url:
        parser.error("--persist requires --db-url")
    if args.voice == "local" and not args.piper_voice:
        parser.error("--voice local requires --piper-voice (a Piper .onnx model path)")

    taxonomy = _build_taxonomy(args.orien, args.db_url, args.iso_dir)
    if not taxonomy.machine_types():
        print(
            "Warning: no FMEA equipment loaded — the bot will run in free-text "
            "mode without taxonomy validation.",
            file=sys.stderr,
        )

    voice = _build_voice(args)
    session = VoiceBotSession(taxonomy, voice, voice, technician=args.technician)
    captured = session.run()

    if args.json:
        _dump_json(captured, args.json)

    if args.persist:
        from orien_import_tool.downtime_bot.persistence import persist
        from orien_import_tool.persistence.session import (
            init_db,
            make_engine,
            make_session_factory,
        )

        engine = make_engine(args.db_url)
        init_db(engine)
        with make_session_factory(engine)() as db:
            external_id = persist(db, captured)
            db.commit()
        print(f"Persisted downtime event {external_id}", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
