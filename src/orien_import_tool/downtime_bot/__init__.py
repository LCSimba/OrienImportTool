"""Interactive voice bot that captures plant-floor downtime from a technician.

A call-centre agent (or an automated phone line) walks the artisan through a
short, guided conversation that captures the reliability fields the platform
needs — **machine type, component, position, failure mode, and root cause** —
validating each answer against the FMEA taxonomy for the chosen machine so the
captured record links cleanly into the existing classification pipeline.

Layers (each independently testable):

* :mod:`slots` — the captured fields and the :class:`CapturedDowntime` result.
* :mod:`taxonomy` — FMEA-derived option sets per slot.
* :mod:`matching` — forgiving interpretation of noisy speech-to-text.
* :mod:`dialogue` — the channel-agnostic slot-filling state machine.
* :mod:`voice` — the speech-in / speech-out protocols and a console backend.
* :mod:`engine` — the per-call run loop.
* :mod:`persistence` — bridge to ``DowntimeEvent`` / ``DowntimeClassification``.
"""

from orien_import_tool.downtime_bot.dialogue import BotPrompt, DialogueManager
from orien_import_tool.downtime_bot.engine import VoiceBotSession
from orien_import_tool.downtime_bot.local_voice import (
    Endpointer,
    LocalVoice,
    build_local_voice,
)
from orien_import_tool.downtime_bot.slots import CapturedDowntime, Slot
from orien_import_tool.downtime_bot.taxonomy import CaptureTaxonomy
from orien_import_tool.downtime_bot.voice import (
    ConsoleVoice,
    ScriptedVoice,
    SpeechInput,
    SpeechOutput,
)

__all__ = [
    "BotPrompt",
    "CaptureTaxonomy",
    "CapturedDowntime",
    "ConsoleVoice",
    "DialogueManager",
    "Endpointer",
    "LocalVoice",
    "ScriptedVoice",
    "Slot",
    "SpeechInput",
    "SpeechOutput",
    "VoiceBotSession",
    "build_local_voice",
]
