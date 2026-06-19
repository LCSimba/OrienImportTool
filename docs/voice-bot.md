# Downtime Voice Bot

An interactive, voice-driven bot that captures plant-floor downtime from an
artisan or technician — typically through a call centre — and guarantees the
reliability fields the platform needs are captured **and validated against the
FMEA taxonomy for the machine being reported**.

It lives in `src/orien_import_tool/downtime_bot/` and reuses the canonical
`Equipment → Component → FailureMode` hierarchy, the ISO 14224 reference
tables, and the existing downtime persistence layer.

## What it captures

For the machine type the technician names, the bot fills these slots in order:

| Slot | Required | Source of valid values |
|---|---|---|
| **Machine type** | yes | one per loaded FMEA `Equipment` tree |
| Asset reference | no | free text (tag / number), "skip" to omit |
| **Component** | yes | `Component`s of the chosen machine |
| **Position** | yes | free text, with hints mined from component descriptions |
| **Failure mode** | yes | `FailureMode`s of the chosen component (ISO 14224 B.15 fallback) |
| **Root cause** | if known | causes parsed from Orien `mechanism_and_cause` + ISO 14224 B.3 |

Machine type is special: it scopes every later option list, so when an FMEA is
loaded it must resolve to a known equipment tree. With no FMEA loaded the bot
degrades gracefully to free-text capture.

## Design

The bot is layered so the conversation logic is testable without any audio,
and the speech provider is swappable:

```
 caller ⇄ [STT/TTS adapter] ⇄ VoiceBotSession ⇄ DialogueManager ⇄ CaptureTaxonomy
              (voice.py)          (engine.py)      (dialogue.py)     (taxonomy.py)
                                                        │
                                                   matching.py  ← noisy-speech interpretation
                                                        │
                                              CapturedDowntime (slots.py)
                                                        │
                                              persistence.py → DowntimeEvent + DowntimeClassification
```

* **`dialogue.py` — the brain.** A deterministic slot-filling state machine. It
  consumes plain-text utterances (whatever STT produced) and emits plain-text
  prompts (whatever TTS will read), so it is channel-agnostic and fully unit
  tested. Each slot runs an `ASK → (DISAMBIGUATE | CONFIRM) → commit` cycle;
  misheard answers get a yes/no read-back before they are committed, because a
  wrong component or failure mode corrupts the reliability data downstream.
* **`matching.py` — forgiving interpretation.** Handles ordinal picks ("number
  two"), fuzzy/alias phrase matching (reusing the platform's `normalise`), and
  the yes/no and "don't know" vocabularies. Confidence bands decide whether an
  answer is committed, confirmed, or disambiguated.
* **`taxonomy.py` — FMEA-derived options.** Turns equipment trees into the
  per-slot option sets and mines position hints; widens failure-mode and
  root-cause vocabularies with ISO 14224 when reference data is loaded.
* **`voice.py` — the audio seam.** `SpeechInput.listen()` and
  `SpeechOutput.speak()` structural protocols (same style as
  `llm/protocols.py`). `ConsoleVoice` is the batteries-included text backend;
  `ScriptedVoice` drives the tests. A production deployment supplies an adapter
  wrapping a telephony + STT + TTS provider (e.g. Twilio + Whisper/Azure).
* **`engine.py` — the run loop.** Speaks, listens, feeds the reply back until
  the dialogue is final. Guards against runaway calls (`max_turns`) and caller
  silence / hang-up (`max_silent` consecutive blank utterances).
* **`persistence.py` — the bridge.** A finished `CapturedDowntime` becomes a
  `DowntimeEvent` plus a pre-filled `DowntimeClassification` (the technician
  already told us the component and failure mode, so it does not need
  re-classifying), written via the existing repositories with an audit row.

## Running it

The CLI runs one capture on the console (no audio dependency required):

```bash
python -m orien_import_tool.downtime_bot \
    --orien tests/fixtures/orien/<export>.xlsx \
    --technician "J. Smith" \
    --json capture.json
```

Persist into the canonical store as well:

```bash
python -m orien_import_tool.downtime_bot \
    --db-url sqlite:///downtime.db --persist \
    --technician "J. Smith"
```

`--db-url` (without `--persist`) also loads the FMEA taxonomy from a database
that already holds imported equipment, instead of (or in addition to)
`--orien`.

## Adding a real voice channel

Implement the two protocols against your provider and pass them to
`VoiceBotSession`:

```python
class TwilioVoice:
    def speak(self, text: str) -> None:
        ...  # text-to-speech out to the call

    def listen(self) -> str:
        ...  # speech-to-text of the caller's next utterance

session = VoiceBotSession(taxonomy, TwilioVoice(), TwilioVoice(), technician=name)
captured = session.run()
```

Everything else — the questions, the validation against the FMEA, the
confirmations, the persistence — stays exactly the same.
