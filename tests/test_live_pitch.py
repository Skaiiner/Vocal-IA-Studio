from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.recording.recorder import RecState, Recorder


def tone_block(freq=440.0, seconds=0.1, sr=44100, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_recent_samples_accumulates_across_blocks(backend):
    r = Recorder(backend, 44100)
    r.arm()
    backend.input_stream.pump(1)  # bloques de 256 muestras del backend falso (silencio/valor fijo)
    buf = r.recent_samples(100)
    assert len(buf) == 100
    r.close()


def test_recent_samples_default_length_matches_buffer(backend):
    from vocal_ai_studio.recording.recorder import LIVE_BUFFER_SAMPLES

    r = Recorder(backend, 44100)
    r.arm()
    backend.input_stream.pump(1)
    assert len(r.recent_samples()) == LIVE_BUFFER_SAMPLES
    r.close()


def _pump_continuous_tone(backend, freq: float, sr: int = 44100, block_size: int = 256, n_blocks: int = 20) -> None:
    # fase coherente entre bloques; repetir un bloque crearía un artefacto periódico a sr/block_size Hz
    full = tone_block(freq, seconds=block_size * n_blocks / sr, sr=sr)
    for i in range(n_blocks):
        chunk = full[i * block_size:(i + 1) * block_size]
        backend.input_stream.pump(1, indata=chunk[:, None])


def test_live_pitch_detects_tone_from_real_stream(backend):
    r = Recorder(backend, 44100)
    r.arm()
    _pump_continuous_tone(backend, 440.0)
    freq, confidence = r.live_pitch()
    assert confidence > 0.3
    assert freq == pytest.approx(440.0, rel=0.03)
    r.close()


def test_live_pitch_silence_gives_no_confidence(backend):
    r = Recorder(backend, 44100)
    r.arm()
    silence = np.zeros((256, 1), np.float32)
    for _ in range(20):
        backend.input_stream.pump(1, indata=silence)
    freq, confidence = r.live_pitch()
    assert confidence == 0.0
    assert freq != freq  # NaN
    r.close()


def test_live_pitch_closed_recorder_returns_nan(backend):
    r = Recorder(backend, 44100)
    freq, confidence = r.live_pitch()
    assert confidence == 0.0 and freq != freq


def test_live_pitch_works_while_recording_too(backend):
    r = Recorder(backend, 44100)
    r.start()
    assert r.state is RecState.RECORDING
    _pump_continuous_tone(backend, 330.0)
    freq, confidence = r.live_pitch()
    assert confidence > 0.3
    assert freq == pytest.approx(330.0, rel=0.03)
    r.close()


def test_pitch_view_live_marker_extends_duration_when_needed():
    from vocal_ai_studio.ui.pitch_view import PitchView

    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    w = PitchView()
    w.set_live_pitch(2.0, 440.0)
    assert w._duration >= 2.0
    w.set_live_pitch(None, None)
    assert w._live_time is None and w._live_freq is None
