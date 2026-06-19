"""End-to-end tests: voice channel + engine + persistence bridge."""

from __future__ import annotations

from orien_import_tool.downtime_bot.engine import VoiceBotSession
from orien_import_tool.downtime_bot.taxonomy import CaptureTaxonomy
from orien_import_tool.downtime_bot.voice import ScriptedVoice

_SCRIPT = [
    "Conveyor",       # machine type (exact -> committed)
    "CV-200-A",       # asset reference (free text -> confirm)
    "yes",
    "Drive motor",    # component (exact)
    "drive end",      # position (free text -> confirm)
    "yes",
    "Motor overheats",  # failure mode (exact)
    "overload",         # root cause (exact)
    "yes",              # final confirmation
]


def test_session_runs_to_completion(taxonomy: CaptureTaxonomy) -> None:
    voice = ScriptedVoice(_SCRIPT)
    session = VoiceBotSession(taxonomy, voice, voice, technician="A. Artisan")
    captured = session.run()

    assert captured.is_complete()
    assert captured.technician == "A. Artisan"
    assert captured.asset_ref == "CV-200-A"
    assert captured.component_token == "C-MOTOR"
    # The bot spoke a greeting and a closing line at minimum.
    assert any("downtime line" in line.lower() for line in voice.spoken)
    assert "logged" in voice.spoken[-1].lower()
    assert captured.transcript[0][0] == "bot"


def test_session_guards_against_silent_caller(taxonomy: CaptureTaxonomy) -> None:
    voice = ScriptedVoice([])  # caller never says anything
    session = VoiceBotSession(taxonomy, voice, voice, max_turns=5)
    captured = session.run()
    assert not captured.is_complete()  # bailed out instead of looping forever


def test_persistence_bridge_roundtrip(taxonomy: CaptureTaxonomy) -> None:
    from orien_import_tool.downtime_bot.persistence import persist
    from orien_import_tool.persistence.repositories import DowntimeRepository
    from orien_import_tool.persistence.session import (
        init_db,
        make_engine,
        make_session_factory,
    )

    voice = ScriptedVoice(_SCRIPT)
    captured = VoiceBotSession(taxonomy, voice, voice).run()

    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        external_id = persist(session, captured)
        session.commit()

    with factory() as session:
        repo = DowntimeRepository(session)
        events = repo.list_events(source_system="voicebot")
        assert len(events) == 1
        assert events[0].external_id == external_id
        classifications = repo.latest_classifications(external_id)
        assert classifications[0].component_match.component_token == "C-MOTOR"
        assert classifications[0].best_failure_mode.failure_mode_token == "FM-MOT-1"
