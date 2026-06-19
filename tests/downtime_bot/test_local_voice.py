"""Tests for the local voice backend's testable core.

The hardware/model wrappers (sounddevice, faster-whisper, Piper) are excluded
from coverage and exercised manually; here we test the pure endpointing logic
and the LocalVoice orchestration with fakes — no audio libraries required.
"""

from __future__ import annotations

import array

from orien_import_tool.downtime_bot.local_voice import Endpointer, LocalVoice

_SR = 16_000
_FRAME_MS = 30
_FRAME_SAMPLES = int(_SR * _FRAME_MS / 1000)


def _silence() -> bytes:
    return array.array("h", [0] * _FRAME_SAMPLES).tobytes()


def _speech(amplitude: int = 5000) -> bytes:
    return array.array("h", [amplitude] * _FRAME_SAMPLES).tobytes()


def _endpointer() -> Endpointer:
    # Short, test-friendly windows: 90 ms trailing silence ends an utterance.
    return Endpointer(
        sample_rate=_SR,
        frame_ms=_FRAME_MS,
        energy_threshold=500.0,
        start_timeout_ms=150,
        silence_ms=90,
        max_utterance_ms=600,
    )


def _feed(ep: Endpointer, frames: list[bytes]) -> int:
    for i, frame in enumerate(frames):
        if ep.update(frame):
            return i
    return -1


def test_endpointer_ends_after_trailing_silence() -> None:
    ep = _endpointer()
    # Two speech frames, then three silence frames (90 ms) should end it.
    frames = [_speech(), _speech(), _silence(), _silence(), _silence()]
    done_at = _feed(ep, frames)
    assert done_at == 4
    assert ep.started
    # Captured audio = the speech + the trailing silence that was buffered.
    assert len(ep.audio()) == 5 * _FRAME_SAMPLES * 2


def test_endpointer_times_out_on_silent_caller() -> None:
    ep = _endpointer()
    # Never any speech: after start_timeout_ms (150 ms = 5 frames) it gives up.
    done_at = _feed(ep, [_silence()] * 10)
    assert done_at == 4
    assert not ep.started
    assert ep.audio() == b""


def test_endpointer_caps_long_utterance() -> None:
    ep = _endpointer()
    # Continuous speech never goes silent; max_utterance_ms (600/30 = 20) caps it.
    done_at = _feed(ep, [_speech()] * 50)
    assert done_at == 19


def test_endpointer_reset_clears_state() -> None:
    ep = _endpointer()
    _feed(ep, [_speech(), _silence(), _silence(), _silence()])
    ep.reset()
    assert not ep.started
    assert ep.audio() == b""


class _FakeRecorder:
    def __init__(self, audio: bytes) -> None:
        self._audio = audio

    def record(self) -> bytes:
        return self._audio


class _FakeTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[int] = []

    def transcribe(self, audio: bytes, sample_rate: int) -> str:
        self.calls.append(len(audio))
        return self.text


class _FakeSynth:
    def synthesize(self, text: str) -> tuple[bytes, int]:
        return (text.encode(), 22_050)


class _FakePlayer:
    def __init__(self) -> None:
        self.played: list[tuple[bytes, int]] = []

    def play(self, audio: bytes, sample_rate: int) -> None:
        self.played.append((audio, sample_rate))


def test_local_voice_listen_transcribes_recorded_audio() -> None:
    transcriber = _FakeTranscriber("  drive motor ")
    voice = LocalVoice(_FakeRecorder(b"\x01\x02"), transcriber, _FakeSynth(), _FakePlayer())
    assert voice.listen() == "drive motor"  # stripped
    assert transcriber.calls == [2]


def test_local_voice_listen_skips_transcription_on_silence() -> None:
    transcriber = _FakeTranscriber("should not be used")
    voice = LocalVoice(_FakeRecorder(b""), transcriber, _FakeSynth(), _FakePlayer())
    assert voice.listen() == ""
    assert transcriber.calls == []  # empty audio short-circuits


def test_local_voice_speak_synthesizes_then_plays() -> None:
    player = _FakePlayer()
    voice = LocalVoice(_FakeRecorder(b""), _FakeTranscriber(""), _FakeSynth(), player)
    voice.speak("hello")
    assert player.played == [(b"hello", 22_050)]
