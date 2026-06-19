"""Local, turn-based voice channel: faster-whisper (STT) + Piper (TTS).

This is the recommended proof-of-concept backend — it runs entirely on the
local machine with no telephony or cloud service, so the conversation (the
risky part) can be validated with a real microphone in an afternoon. It
implements the same :class:`SpeechInput` / :class:`SpeechOutput` protocols the
console backend does, so the dialogue manager is completely unaware of it.

The design separates the *testable logic* from the *hardware/model glue*:

* :class:`Endpointer` — pure, dependency-light voice-activity endpointing
  (energy + trailing-silence). Decides when the technician has stopped talking.
  Fully unit tested with synthetic frames.
* :class:`LocalVoice` — orchestrates ``record → transcribe`` and
  ``synthesize → play`` against four small injected protocols. Tested with
  fakes; no audio libraries required.
* :class:`SoundDeviceRecorder`, :class:`FasterWhisperTranscriber`,
  :class:`PiperSynthesizer`, :class:`SoundDevicePlayer` — thin wrappers around
  ``sounddevice`` / ``faster-whisper`` / ``piper-tts``. Every heavy import is
  lazy, so importing this module (and the package) stays cheap and these are
  only required when you actually run the local backend (``pip install
  '.[voice]'``).
"""

from __future__ import annotations

import array
import math
from typing import Protocol, runtime_checkable

# 16 kHz mono int16 is what faster-whisper wants and what the mic records.
SAMPLE_RATE = 16_000
FRAME_MS = 30
_BYTES_PER_SAMPLE = 2


# --- endpointing (pure, testable) --------------------------------------------


def _rms(frame: bytes) -> float:
    """Root-mean-square amplitude of an int16 PCM frame (0 for silence)."""
    if len(frame) < _BYTES_PER_SAMPLE:
        return 0.0
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - len(frame) % _BYTES_PER_SAMPLE])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class Endpointer:
    """Detect one spoken utterance from a stream of fixed-size PCM frames.

    Feed frames in order via :meth:`update`; it returns ``True`` once the
    utterance is complete — either trailing silence exceeded ``silence_ms``
    after speech began, the utterance hit ``max_utterance_ms``, or no speech
    arrived within ``start_timeout_ms`` (an empty turn / silent caller).
    Collected speech is then available from :meth:`audio`.
    """

    def __init__(
        self,
        *,
        sample_rate: int = SAMPLE_RATE,
        frame_ms: int = FRAME_MS,
        energy_threshold: float = 500.0,
        start_timeout_ms: int = 8_000,
        silence_ms: int = 800,
        max_utterance_ms: int = 20_000,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.energy_threshold = energy_threshold
        self.start_timeout_ms = start_timeout_ms
        self.silence_ms = silence_ms
        self.max_utterance_ms = max_utterance_ms
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self.reset()

    def reset(self) -> None:
        self._started = False
        self._done = False
        self._frames: list[bytes] = []
        self._silence = 0
        self._waited = 0

    def update(self, frame: bytes) -> bool:
        """Consume one frame; return ``True`` when the utterance is finished."""
        if self._done:
            return True
        is_speech = _rms(frame) >= self.energy_threshold

        if not self._started:
            if is_speech:
                self._started = True
                self._frames.append(frame)
            else:
                self._waited += self.frame_ms
                if self._waited >= self.start_timeout_ms:
                    self._done = True
            return self._done

        self._frames.append(frame)
        if is_speech:
            self._silence = 0
        else:
            self._silence += self.frame_ms
            if self._silence >= self.silence_ms:
                self._done = True
        if len(self._frames) * self.frame_ms >= self.max_utterance_ms:
            self._done = True
        return self._done

    @property
    def started(self) -> bool:
        return self._started

    def audio(self) -> bytes:
        """The captured speech as raw int16 PCM (empty if nothing was said)."""
        return b"".join(self._frames)


# --- injected protocols ------------------------------------------------------


@runtime_checkable
class Recorder(Protocol):
    """Capture one utterance from the microphone, returning int16 PCM."""

    def record(self) -> bytes: ...


@runtime_checkable
class Transcriber(Protocol):
    """Turn int16 PCM into text (speech-to-text)."""

    def transcribe(self, audio: bytes, sample_rate: int) -> str: ...


@runtime_checkable
class Synthesizer(Protocol):
    """Turn text into int16 PCM plus its sample rate (text-to-speech)."""

    def synthesize(self, text: str) -> tuple[bytes, int]: ...


@runtime_checkable
class Player(Protocol):
    """Play int16 PCM out of the speaker."""

    def play(self, audio: bytes, sample_rate: int) -> None: ...


# --- the channel -------------------------------------------------------------


class LocalVoice:
    """A :class:`SpeechInput` + :class:`SpeechOutput` backed by local engines.

    Pure orchestration: ``listen`` records then transcribes; ``speak``
    synthesises then plays. The four collaborators are injected, which is what
    makes this testable without any audio stack — see
    :func:`build_local_voice` for the wired-up production instance.
    """

    def __init__(
        self,
        recorder: Recorder,
        transcriber: Transcriber,
        synthesizer: Synthesizer,
        player: Player,
        *,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self._recorder = recorder
        self._transcriber = transcriber
        self._synthesizer = synthesizer
        self._player = player
        self._sample_rate = sample_rate

    def listen(self) -> str:
        audio = self._recorder.record()
        if not audio:
            return ""
        return self._transcriber.transcribe(audio, self._sample_rate).strip()

    def speak(self, text: str) -> None:
        audio, sample_rate = self._synthesizer.synthesize(text)
        if audio:
            self._player.play(audio, sample_rate)


# --- concrete engines (lazy heavy imports; not unit-tested) ------------------


class SoundDeviceRecorder:
    """Microphone recorder that endpoints with :class:`Endpointer`."""

    def __init__(self, endpointer: Endpointer | None = None) -> None:
        self._endpointer = endpointer or Endpointer()

    def record(self) -> bytes:  # pragma: no cover - needs a microphone
        import sounddevice as sd

        ep = self._endpointer
        ep.reset()
        frames = ep.frame_samples
        with sd.RawInputStream(
            samplerate=ep.sample_rate, channels=1, dtype="int16", blocksize=frames
        ) as stream:
            while True:
                data, _overflow = stream.read(frames)
                if ep.update(bytes(data)):
                    break
        return ep.audio()


class FasterWhisperTranscriber:
    """faster-whisper STT. Multilingual; good default for accented speech."""

    def __init__(
        self,
        model_size: str = "small",
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None

    def _load(self):  # pragma: no cover - downloads/loads a model
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_size, device=self.device, compute_type=self.compute_type
            )
        return self._model

    def transcribe(self, audio: bytes, sample_rate: int) -> str:  # pragma: no cover
        import numpy as np

        pcm = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._load().transcribe(
            pcm, language=self.language, vad_filter=True
        )
        return " ".join(segment.text for segment in segments).strip()


class PiperSynthesizer:
    """Piper TTS. Fast and CPU-friendly; pass a ``.onnx`` voice model path."""

    def __init__(self, voice_path: str, *, config_path: str | None = None) -> None:
        self.voice_path = voice_path
        self.config_path = config_path
        self._voice = None

    def _load(self):  # pragma: no cover - loads a model
        if self._voice is None:
            from piper import PiperVoice

            self._voice = PiperVoice.load(self.voice_path, config_path=self.config_path)
        return self._voice

    def synthesize(self, text: str) -> tuple[bytes, int]:  # pragma: no cover
        voice = self._load()
        buffer = bytearray()
        for chunk in voice.synthesize_stream_raw(text):
            buffer.extend(chunk)
        return bytes(buffer), voice.config.sample_rate


class SoundDevicePlayer:
    """Blocking speaker playback via ``sounddevice``."""

    def play(self, audio: bytes, sample_rate: int) -> None:  # pragma: no cover
        import numpy as np
        import sounddevice as sd

        sd.play(np.frombuffer(audio, dtype=np.int16), samplerate=sample_rate)
        sd.wait()


def build_local_voice(
    *,
    piper_voice_path: str,
    stt_model: str = "small",
    language: str | None = None,
    stt_device: str = "cpu",
    stt_compute_type: str = "int8",
    silence_ms: int = 800,
) -> LocalVoice:
    """Wire up the production local backend (mic + faster-whisper + Piper)."""
    endpointer = Endpointer(silence_ms=silence_ms)
    return LocalVoice(
        SoundDeviceRecorder(endpointer),
        FasterWhisperTranscriber(
            stt_model, device=stt_device, compute_type=stt_compute_type, language=language
        ),
        PiperSynthesizer(piper_voice_path),
        SoundDevicePlayer(),
    )
