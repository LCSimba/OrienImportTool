"""The dialogue manager — a deterministic slot-filling state machine.

This is the bot's brain and it is intentionally free of any audio concern: it
consumes plain-text utterances (whatever the speech-to-text produced) and emits
plain-text prompts (whatever the text-to-speech will read). That makes the
whole conversation unit-testable and lets the same logic sit behind a phone
line, a web chat, or the console.

The conversation walks a fixed slot order — machine type, asset reference,
component, position, failure mode, root cause — and only then reads the record
back for a final confirmation. Each slot runs a small ASK → (DISAMBIGUATE |
CONFIRM) → commit cycle:

* **ASK** — open question; the technician answers naturally.
* **DISAMBIGUATE** — when several options are plausible, read a short numbered
  list and take an ordinal pick or a clearer name.
* **CONFIRM** — read a single best guess back for a yes/no, because a misheard
  component or failure mode poisons the reliability data downstream.

Required slots (machine type, component, position, failure mode) must end with a
value; optional slots (asset reference, root cause) accept "don't know" / "skip".
The machine type is special: it scopes every later option list, so it is the one
slot that must resolve to a known equipment tree when an FMEA is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from orien_import_tool.downtime_bot.matching import (
    ACCEPT,
    MatchCandidate,
    Option,
    is_dont_know,
    match_options,
    parse_ordinal,
    parse_yes_no,
)
from orien_import_tool.downtime_bot.slots import (
    OPTIONAL_SLOTS,
    CapturedDowntime,
    Slot,
)
from orien_import_tool.downtime_bot.taxonomy import CaptureTaxonomy

# Order in which slots are filled. CONFIRM (final read-back) and DONE are
# handled outside this tuple.
_SLOT_ORDER: tuple[Slot, ...] = (
    Slot.MACHINE_TYPE,
    Slot.ASSET_REF,
    Slot.COMPONENT,
    Slot.POSITION,
    Slot.FAILURE_MODE,
    Slot.ROOT_CAUSE,
)

# Keywords that let the technician name a field to correct after the read-back.
_CORRECTION_TARGETS: tuple[tuple[Slot, tuple[str, ...]], ...] = (
    (Slot.MACHINE_TYPE, ("machine", "equipment", "asset type")),
    (Slot.ASSET_REF, ("asset", "tag", "number", "reference")),
    (Slot.COMPONENT, ("component", "part")),
    (Slot.POSITION, ("position", "location", "where")),
    (Slot.FAILURE_MODE, ("failure", "fault", "mode", "problem")),
    (Slot.ROOT_CAUSE, ("cause", "root", "reason")),
)


class _Phase:
    ASK = "ask"
    DISAMBIGUATE = "disambiguate"
    CONFIRM = "confirm"
    FINAL_CONFIRM = "final_confirm"
    CORRECTION = "correction"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class BotPrompt:
    """One thing for the bot to say, plus enough state to drive a UI / TTS.

    ``is_final`` is set on the closing message; when it is true the caller
    should stop the loop and read :attr:`captured`.
    """

    speech: str
    slot: Slot
    is_final: bool
    captured: CapturedDowntime


@dataclass
class DialogueManager:
    """Drives one downtime-capture conversation.

    Usage is a simple loop: call :meth:`start` for the opening line, then feed
    every recognised utterance to :meth:`handle` until a returned
    :class:`BotPrompt` has ``is_final``.
    """

    taxonomy: CaptureTaxonomy
    technician: str = ""
    captured: CapturedDowntime = field(init=False)

    _slot: Slot = field(init=False, default=Slot.GREETING)
    _phase: str = field(init=False, default=_Phase.ASK)
    _candidates: list[MatchCandidate] = field(init=False, default_factory=list)
    _pending: Option | None = field(init=False, default=None)
    _last_speech: str = field(init=False, default="")
    _correcting: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.captured = CapturedDowntime(technician=self.technician)

    # --- public API -------------------------------------------------------------

    def start(self) -> BotPrompt:
        """Greet and ask the first slot."""
        greeting = (
            "Hello, this is the reliability downtime line. "
            "I'll capture a few details about the breakdown. "
        )
        self._slot = _SLOT_ORDER[0]
        self._phase = _Phase.ASK
        return self._emit(greeting + self._ask_text(self._slot))

    def handle(self, utterance: str) -> BotPrompt:
        """Advance the conversation by one technician turn."""
        self.captured.transcript.append(("technician", utterance))

        # Global commands work in any phase.
        normalized = utterance.strip().casefold()
        if normalized in {"repeat", "say again", "pardon", "what"}:
            return self._emit(self._last_speech)
        if normalized in {"start over", "restart", "start again"}:
            return self._restart()

        dispatch = {
            _Phase.ASK: self._on_ask,
            _Phase.DISAMBIGUATE: self._on_disambiguate,
            _Phase.CONFIRM: self._on_confirm,
            _Phase.FINAL_CONFIRM: self._on_final_confirm,
            _Phase.CORRECTION: self._on_correction,
        }
        handler = dispatch.get(self._phase)
        if handler is None:  # already DONE — echo the closing line.
            return self._emit(self._last_speech, is_final=True)
        return handler(utterance)

    # --- phase handlers ---------------------------------------------------------

    def _on_ask(self, utterance: str) -> BotPrompt:
        slot = self._slot
        options = self._options(slot)

        if slot in OPTIONAL_SLOTS and is_dont_know(utterance):
            return self._commit(slot, Option(value=""))

        if options:
            candidates = match_options(utterance, options)
            if candidates and candidates[0].score >= 0.99:
                # Exact text or an ordinal pick — no need to confirm.
                return self._commit(slot, candidates[0].option)
            if candidates and candidates[0].score >= ACCEPT and (
                len(candidates) == 1 or candidates[0].score - candidates[1].score >= 0.15
            ):
                return self._begin_confirm(candidates[0].option)
            if candidates:
                return self._begin_disambiguate(candidates)
            # Nothing matched the controlled vocabulary.
            if self._allow_free_text(slot):
                return self._begin_confirm(Option(value=utterance.strip()))
            return self._reprompt_with_options(slot)

        # Free-text slot (no taxonomy options, e.g. asset reference).
        text = utterance.strip()
        if not text:
            return self._emit(self._ask_text(slot))
        return self._begin_confirm(Option(value=text))

    def _on_disambiguate(self, utterance: str) -> BotPrompt:
        pick = parse_ordinal(utterance, len(self._candidates))
        if pick is not None:
            return self._commit(self._slot, self._candidates[pick - 1].option)

        options = [c.option for c in self._candidates]
        rematch = match_options(utterance, options)
        if rematch and rematch[0].score >= ACCEPT:
            return self._commit(self._slot, rematch[0].option)

        if self._allow_free_text(self._slot) and not is_dont_know(utterance) and utterance.strip():
            # They named something not on the shortlist — keep it as free text.
            return self._begin_confirm(Option(value=utterance.strip()))

        return self._emit(
            "Sorry, I didn't catch which one. " + self._list_candidates(self._candidates)
        )

    def _on_confirm(self, utterance: str) -> BotPrompt:
        decision = parse_yes_no(utterance)
        if decision is True and self._pending is not None:
            return self._commit(self._slot, self._pending)
        if decision is False:
            self._pending = None
            self._phase = _Phase.ASK
            return self._emit("No problem. " + self._ask_text(self._slot))
        value = self._pending.value if self._pending else ""
        return self._emit(f"Sorry, was that a yes or a no? I heard '{value}'.")

    def _on_final_confirm(self, utterance: str) -> BotPrompt:
        decision = parse_yes_no(utterance)
        if decision is True:
            return self._finish()
        if decision is False:
            self._phase = _Phase.CORRECTION
            return self._emit(
                "Okay. Which detail should we fix — the machine, asset, "
                "component, position, failure mode, or cause?"
            )
        return self._emit("Is the record correct? Please say yes or no.")

    def _on_correction(self, utterance: str) -> BotPrompt:
        target = self._match_correction_target(utterance)
        if target is None:
            return self._emit(
                "Which detail should we fix — the machine, asset, component, "
                "position, failure mode, or cause?"
            )
        self._correcting = True
        self._slot = target
        self._phase = _Phase.ASK
        return self._emit(self._ask_text(target))

    # --- transitions ------------------------------------------------------------

    def _begin_confirm(self, option: Option) -> BotPrompt:
        self._pending = option
        self._phase = _Phase.CONFIRM
        return self._emit(f"I have '{option.value}'. Is that correct?")

    def _begin_disambiguate(self, candidates: list[MatchCandidate]) -> BotPrompt:
        self._candidates = candidates
        self._phase = _Phase.DISAMBIGUATE
        return self._emit("I have a few close matches. " + self._list_candidates(candidates))

    def _reprompt_with_options(self, slot: Slot) -> BotPrompt:
        shortlist = [MatchCandidate(o, 0.0) for o in self._options(slot)[:5]]
        self._candidates = shortlist
        self._phase = _Phase.DISAMBIGUATE
        return self._emit(
            "I didn't catch a known value. " + self._list_candidates(shortlist)
        )

    def _commit(self, slot: Slot, option: Option) -> BotPrompt:
        """Write the answer for ``slot`` and move to the next state."""
        self._write(slot, option)
        self._pending = None
        self._candidates = []

        if self._correcting:
            self._correcting = False
            return self._begin_final_confirm()

        next_slot = self._next_slot(slot)
        if next_slot is None:
            return self._begin_final_confirm()
        self._slot = next_slot
        self._phase = _Phase.ASK
        return self._emit(self._ask_text(next_slot))

    def _begin_final_confirm(self) -> BotPrompt:
        self._slot = Slot.CONFIRM
        self._phase = _Phase.FINAL_CONFIRM
        recap = " ".join(self.captured.summary_lines())
        return self._emit(
            "Let me read that back. " + recap + " Is that all correct?"
        )

    def _finish(self) -> BotPrompt:
        self.captured.completed_at = datetime.utcnow()
        self._slot = Slot.DONE
        self._phase = _Phase.DONE
        return self._emit("Thank you, the downtime has been logged. Goodbye.", is_final=True)

    def _restart(self) -> BotPrompt:
        tech = self.captured.technician
        self.captured = CapturedDowntime(technician=tech)
        self._correcting = False
        self._pending = None
        self._candidates = []
        return self.start()

    # --- slot helpers -----------------------------------------------------------

    def _write(self, slot: Slot, option: Option) -> None:
        value = option.value.strip()
        token = option.token
        if slot is Slot.MACHINE_TYPE:
            self.captured.machine_type = value
            self.captured.equipment_token = token
        elif slot is Slot.ASSET_REF:
            self.captured.asset_ref = value
        elif slot is Slot.COMPONENT:
            self.captured.component = value
            self.captured.component_token = token
        elif slot is Slot.POSITION:
            self.captured.position = value
        elif slot is Slot.FAILURE_MODE:
            self.captured.failure_mode = value
            self.captured.failure_mode_token = token
        elif slot is Slot.ROOT_CAUSE:
            self.captured.root_cause = value
            self.captured.root_cause_known = bool(value)

    def _options(self, slot: Slot) -> list[Option]:
        if slot is Slot.MACHINE_TYPE:
            return self.taxonomy.machine_types()
        if slot is Slot.COMPONENT:
            return self.taxonomy.components(self.captured.equipment_token)
        if slot is Slot.FAILURE_MODE:
            return self.taxonomy.failure_modes(self.captured.component_token)
        if slot is Slot.ROOT_CAUSE:
            return self.taxonomy.root_causes(self.captured.component_token)
        return []  # ASSET_REF and POSITION are free-text

    def _allow_free_text(self, slot: Slot) -> bool:
        # The machine type may be free-text only when no FMEA is loaded.
        if slot is Slot.MACHINE_TYPE:
            return not self.taxonomy.machine_types()
        return True

    def _next_slot(self, slot: Slot) -> Slot | None:
        idx = _SLOT_ORDER.index(slot)
        return _SLOT_ORDER[idx + 1] if idx + 1 < len(_SLOT_ORDER) else None

    def _ask_text(self, slot: Slot) -> str:
        if slot is Slot.MACHINE_TYPE:
            options = self.taxonomy.machine_types()
            base = "What type of machine is reporting downtime?"
            if 0 < len(options) <= 5:
                names = ", ".join(o.value for o in options)
                return f"{base} I have: {names}."
            return base
        if slot is Slot.ASSET_REF:
            return "What is the asset number or tag? You can say skip if you don't have one."
        if slot is Slot.COMPONENT:
            return "Which component failed?"
        if slot is Slot.POSITION:
            hints = self.taxonomy.position_hints(self.captured.component_token)
            if hints:
                return (
                    "What is the position or location of that component? "
                    f"For example: {', '.join(hints[:4])}."
                )
            return "What is the position or location of that component?"
        if slot is Slot.FAILURE_MODE:
            return "What was the failure mode — what went wrong with it?"
        if slot is Slot.ROOT_CAUSE:
            return "Do you know the root cause? If not, just say you don't know."
        return ""

    def _list_candidates(self, candidates: list[MatchCandidate]) -> str:
        parts = [f"{i}, {c.value}." for i, c in enumerate(candidates, start=1)]
        return "Say the number or the name. " + " ".join(parts)

    def _match_correction_target(self, utterance: str) -> Slot | None:
        text = utterance.strip().casefold()
        for slot, keywords in _CORRECTION_TARGETS:
            if any(keyword in text for keyword in keywords):
                return slot
        return None

    # --- emission ---------------------------------------------------------------

    def _emit(self, speech: str, *, is_final: bool = False) -> BotPrompt:
        self._last_speech = speech
        self.captured.transcript.append(("bot", speech))
        return BotPrompt(speech=speech, slot=self._slot, is_final=is_final, captured=self.captured)
