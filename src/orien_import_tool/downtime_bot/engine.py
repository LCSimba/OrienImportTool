"""Run loop that ties the dialogue manager to a voice channel.

:class:`VoiceBotSession` is the thin orchestrator a deployment instantiates per
call: it speaks each :class:`~orien_import_tool.downtime_bot.dialogue.BotPrompt`,
listens for the reply, and feeds it back in until the dialogue reports it is
final. It is deliberately small — all the conversation intelligence lives in
:class:`DialogueManager`; all the audio lives behind the voice protocols — so
this loop stays the same whether the channel is a console, a phone line, or a
test script.
"""

from __future__ import annotations

from orien_import_tool.downtime_bot.dialogue import DialogueManager
from orien_import_tool.downtime_bot.slots import CapturedDowntime
from orien_import_tool.downtime_bot.taxonomy import CaptureTaxonomy
from orien_import_tool.downtime_bot.voice import SpeechInput, SpeechOutput


class VoiceBotSession:
    """One downtime-capture call: greet, fill every slot, return the record."""

    def __init__(
        self,
        taxonomy: CaptureTaxonomy,
        output: SpeechOutput,
        input_: SpeechInput,
        *,
        technician: str = "",
        max_turns: int = 60,
        max_silent: int = 3,
    ) -> None:
        self._dialogue = DialogueManager(taxonomy=taxonomy, technician=technician)
        self._output = output
        self._input = input_
        self._max_turns = max_turns
        self._max_silent = max_silent

    def run(self) -> CapturedDowntime:
        """Drive the conversation to completion and return what was captured.

        Two guards stop a runaway loop: ``max_turns`` caps the whole call, and
        ``max_silent`` ends it after that many consecutive blank utterances —
        i.e. the caller has gone quiet or the channel has hung up. Both leave
        the partial :class:`CapturedDowntime` intact for follow-up.
        """
        prompt = self._dialogue.start()
        self._output.speak(prompt.speech)

        turns = 0
        silent = 0
        while not prompt.is_final and turns < self._max_turns:
            utterance = self._input.listen()
            silent = silent + 1 if not utterance.strip() else 0
            if silent >= self._max_silent:
                break
            prompt = self._dialogue.handle(utterance)
            self._output.speak(prompt.speech)
            turns += 1

        return prompt.captured
