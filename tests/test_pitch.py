from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.core.interfaces import PitchTrack
from vocal_ai_studio.pitch.detector import YinPitchDetector
from vocal_ai_studio.pitch.notes import (
    cents_deviation,
    hz_to_midi,
    midi_to_hz,
    midi_to_note_name,
    note_name_to_hz,
    note_name_to_midi,
)
from vocal_ai_studio.pitch.yin import AnalysisCancelled, yin_pitch_track


def tone(freq=440.0, seconds=1.0, sr=44100, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# --- conversiones ---

def test_hz_to_midi_and_back_roundtrip():
    assert hz_to_midi(440.0) == pytest.approx(69.0, abs=1e-6)
    assert midi_to_hz(69.0) == pytest.approx(440.0, abs=1e-6)
    assert midi_to_hz(60.0) == pytest.approx(261.626, abs=0.01)


def test_hz_to_midi_vectorized():
    out = hz_to_midi(np.array([440.0, 220.0, -1.0]))
    assert out[0] == pytest.approx(69.0, abs=1e-6)
    assert out[1] == pytest.approx(57.0, abs=1e-6)
    assert np.isnan(out[2])


def test_midi_to_note_name():
    assert midi_to_note_name(69) == "A4"
    assert midi_to_note_name(60) == "C4"
    assert midi_to_note_name(61) == "C#4"


def test_note_name_to_midi_roundtrip():
    assert note_name_to_midi("A4") == 69
    assert note_name_to_midi("C4") == 60
    assert note_name_to_midi("C#4") == 61
    assert note_name_to_midi("Db4") == 61


def test_note_name_to_hz():
    assert note_name_to_hz("A4") == pytest.approx(440.0, abs=1e-6)


def test_cents_deviation_in_tune_and_sharp():
    assert cents_deviation(440.0) == pytest.approx(0.0, abs=0.01)
    sharp = 440.0 * 2 ** (20 / 1200)  # 20 cents agudo
    assert cents_deviation(sharp) == pytest.approx(20.0, abs=0.5)


# --- YIN ---

def test_yin_detects_steady_tone_frequency():
    x = tone(440.0, 1.0)
    track = yin_pitch_track(x, 44100)
    voiced = ~np.isnan(track.f0)
    assert voiced.mean() > 0.8
    assert np.nanmean(track.f0) == pytest.approx(440.0, rel=0.01)


@pytest.mark.parametrize("freq", [110.0, 220.0, 330.0, 523.25])
def test_yin_detects_various_frequencies(freq):
    track = yin_pitch_track(tone(freq, 0.6), 44100)
    assert np.nanmean(track.f0) == pytest.approx(freq, rel=0.02)


def test_yin_marks_silence_as_unvoiced():
    silence = np.zeros(44100, np.float32)
    track = yin_pitch_track(silence, 44100)
    assert np.all(np.isnan(track.f0))


def test_yin_times_match_hop_length():
    track = yin_pitch_track(tone(440.0, 0.5), 44100, hop_length=512)
    assert track.times[1] - track.times[0] == pytest.approx(512 / 44100)


def test_yin_too_short_signal_returns_empty():
    track = yin_pitch_track(np.zeros(100, np.float32), 44100)
    assert len(track.f0) == 0


def test_yin_respects_chunking_same_result():
    x = tone(440.0, 1.0)
    full = yin_pitch_track(x, 44100, chunk_frames=10_000)
    chunked = yin_pitch_track(x, 44100, chunk_frames=50)
    assert len(full.f0) == len(chunked.f0)
    np.testing.assert_allclose(np.nan_to_num(full.f0), np.nan_to_num(chunked.f0), rtol=1e-6)


def test_yin_can_be_cancelled():
    with pytest.raises(AnalysisCancelled):
        yin_pitch_track(tone(440.0, 2.0), 44100, chunk_frames=50, cancelled=lambda: True)


def test_yin_reports_progress():
    steps = []
    yin_pitch_track(tone(440.0, 1.0), 44100, chunk_frames=100, progress=steps.append)
    assert steps[-1] == pytest.approx(1.0)
    assert all(0 <= s <= 1 for s in steps)


def test_yin_pitch_detector_matches_function():
    x = tone(330.0, 0.5)
    direct = yin_pitch_track(x, 44100)
    via_detector = YinPitchDetector().detect(x, 44100)
    np.testing.assert_allclose(np.nan_to_num(direct.f0), np.nan_to_num(via_detector.f0))


def test_pitch_track_is_protocol_compatible():
    track = PitchTrack(np.array([0.0]), np.array([440.0]), np.array([1.0]))
    assert track.f0[0] == 440.0
