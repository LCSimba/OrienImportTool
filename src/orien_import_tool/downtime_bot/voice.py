"""Voice I/O seam for the downtime bot.

The dialogue manager speaks and listens in plain text; this module is where
that text meets an actual voice channel. Following the same structural-protocol
style as :mod:`orien_import_tool.llm.protocols`, the bot depends only on two
tiny interfaces:

* :class:`SpeechOutput` — ``speak(text)`` renders a bot line (text-to-speech).
* :class:`SpeechInput` — ``listen()`` returns the technician's next utterance
  as text (speech-to-text).

A real deployment supplies an adapter wrapping a telephony / STT / TTS provider
(Twilio, Whisper, Azure Speech, …). :class:`ConsoleVoice` is the batteries-
included implementation: it prints and reads stdin, so the whole bot runs and
is demoable without any audio dependency. :class:`ScriptedVoice` feeds a fixed
list of utterances, which is what the tests drive the engine with.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class SpeechOutput(Protocol):
    """Render one line of bot speech (text-to-speech)."""

    def speak(self, text: str) -> None: ...


@runtime_checkable
class SpeechInput(Protocol):
    """Capture the next technician utterance as text (speech-to-text)."""

    def listen(self) -> str: ...


class ConsoleVoice:
    """Console implementation of both halves of the voice channel.

    Prints bot lines and reads typed replies from stdin. Useful for local
    demos, manual QA, and as the default CLI backend when no speech provider is
    configured. A real STT/TTS adapter implements the same two methods.
    """

    def __init__(self, *, prompt: str = "you> ", bot_label: str = "bot> ") -> None:
        self._prompt = prompt
        self._bot_label = bot_label

    def speak(self, text: str) -> None:
        print(f"{self._bot_label}{text}")

    def listen(self) -> str:
        try:
            return input(self._prompt)
        except EOFError:
            return ""


class ScriptedVoice:
    """Replays a fixed sequence of utterances; records everything spoken.

    The engine treats it like any other voice channel, which makes a full
    conversation testable end-to-end without a human or a microphone.
    """

    def __init__(self, utterances: Iterable[str]) -> None:
        self._utterances: Iterator[str] = iter(utterances)
        self.spoken: list[str] = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def listen(self) -> str:
        try:
            return next(self._utterances)
        except StopIteration:
            return ""
