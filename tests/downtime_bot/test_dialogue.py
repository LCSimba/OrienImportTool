"""Tests for the slot-filling dialogue state machine."""

from __future__ import annotations

from orien_import_tool.downtime_bot.dialogue import DialogueManager
from orien_import_tool.downtime_bot.slots import Slot
from orien_import_tool.downtime_bot.taxonomy import CaptureTaxonomy


def _run(dm: DialogueManager, utterances: list[str]):
    prompt = dm.start()
    for u in utterances:
        prompt = dm.handle(u)
    return prompt


def test_happy_path_fills_every_slot(taxonomy: CaptureTaxonomy) -> None:
    dm = DialogueManager(taxonomy=taxonomy, technician="J. Smith")
    prompt = _run(
        dm,
        [
            "Conveyor",        # machine type (exact -> committed)
            "skip",            # asset reference (optional)
            "Drive motor",     # component (exact)
            "drive end",       # position (free text -> confirm)
            "yes",
            "Motor overheats",  # failure mode (exact)
            "overload",         # root cause (exact)
            "yes",              # final confirmation
        ],
    )
    assert prompt.is_final
    captured = prompt.captured
    assert captured.machine_type == "Conveyor"
    assert captured.equipment_token == "CONV1"
    assert captured.component == "Drive motor"
    assert captured.component_token == "C-MOTOR"
    assert captured.position == "drive end"
    assert captured.failure_mode == "Motor overheats"
    assert captured.failure_mode_token == "FM-MOT-1"
    assert captured.root_cause == "overload"
    assert captured.root_cause_known is True
    assert captured.completed_at is not None
    assert captured.is_complete()


def test_confirm_no_reasks_then_yes(taxonomy: CaptureTaxonomy) -> None:
    dm = DialogueManager(taxonomy=taxonomy)
    dm.start()
    dm.handle("Conveyor")
    dm.handle("skip")
    dm.handle("Drive motor")
    p = dm.handle("head end")  # free-text position -> confirm
    assert "correct" in p.speech.lower()
    p = dm.handle("no")  # reject -> re-ask
    assert p.slot is Slot.POSITION
    dm.handle("tail end")
    p = dm.handle("yes")
    assert dm.captured.position == "tail end"


def test_disambiguation_with_ordinal(taxonomy: CaptureTaxonomy) -> None:
    dm = DialogueManager(taxonomy=taxonomy)
    dm.start()
    dm.handle("Conveyor")
    dm.handle("skip")
    p = dm.handle("motor")  # partial -> single weak match -> disambiguate list
    assert p.slot is Slot.COMPONENT
    p = dm.handle("the first one")
    # Committed the motor and advanced to the position question.
    assert dm.captured.component == "Drive motor"
    assert p.slot is Slot.POSITION


def test_optional_root_cause_unknown(taxonomy: CaptureTaxonomy) -> None:
    dm = DialogueManager(taxonomy=taxonomy)
    dm.start()
    dm.handle("Conveyor")
    dm.handle("skip")
    dm.handle("Drive motor")
    dm.handle("drive end")
    dm.handle("yes")
    dm.handle("Motor overheats")
    p = dm.handle("I don't know")  # root cause unknown
    assert dm.captured.root_cause == ""
    assert dm.captured.root_cause_known is False
    assert p.slot is Slot.CONFIRM  # went straight to the final read-back


def test_correction_after_readback(taxonomy: CaptureTaxonomy) -> None:
    dm = DialogueManager(taxonomy=taxonomy)
    dm.start()
    dm.handle("Conveyor")
    dm.handle("skip")
    dm.handle("Drive motor")
    dm.handle("drive end")
    dm.handle("yes")
    dm.handle("Motor overheats")
    dm.handle("overload")
    p = dm.handle("no")  # final read-back wrong
    assert "fix" in p.speech.lower()
    dm.handle("component")  # name the field to fix
    dm.handle("Conveyor belt")  # new value (exact -> committed)
    p = dm.handle("yes")  # back to final confirm -> done
    assert p.is_final
    assert dm.captured.component == "Conveyor belt"
    assert dm.captured.component_token == "C-BELT"


def test_repeat_command(taxonomy: CaptureTaxonomy) -> None:
    dm = DialogueManager(taxonomy=taxonomy)
    first = dm.start()
    again = dm.handle("repeat")
    assert again.speech == first.speech
