from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.core.interfaces import PitchTrack
from vocal_ai_studio.voice_analysis import metrics, song
from vocal_ai_studio.voice_analysis.notes import segment_notes


def steady_tone(freq=440.0, seconds=1.0, sr=44100, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def vibrato_tone(freq=440.0, seconds=1.0, sr=44100, rate=5.5, extent_cents=40, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    inst_freq = freq * (2 ** ((extent_cents * np.sin(2 * np.pi * rate * t)) / 1200))
    phase = 2 * np.pi * np.cumsum(inst_freq) / sr
    return (amp * np.sin(phase)).astype(np.float32)


def click_track(bpm=120.0, seconds=8.0, sr=44100):
    period = 60.0 / bpm
    x = np.zeros(int(seconds * sr), np.float32)
    t = 0.0
    while t < seconds:
        i = int(t * sr)
        click = (0.9 * np.exp(-np.arange(200) / 15.0)).astype(np.float32)
        x[i:i + len(click)] += click[: len(x) - i]
        t += period
    return x


def c_major_scale(sr=44100, note_sec=0.3):
    freqs = [261.63, 293.66, 329.63, 349.23, 392.00, 440.00, 493.88, 523.25]  # Do mayor (C4..C5)
    return np.concatenate([steady_tone(f, note_sec, sr, 0.4) for f in freqs]).astype(np.float32)


# --- notas ---

def test_segment_notes_on_steady_tone():
    track = PitchTrack(np.linspace(0, 1, 100), np.full(100, 440.0), np.ones(100))
    notes = segment_notes(track)
    assert len(notes) == 1
    assert notes[0].name == "A4"
    assert notes[0].duration == pytest.approx(1.0, abs=0.05)


def test_segment_notes_splits_different_pitches():
    f0 = np.concatenate([np.full(50, 440.0), np.full(50, 523.25)])
    track = PitchTrack(np.linspace(0, 1, 100), f0, np.ones(100))
    notes = segment_notes(track)
    assert [n.name for n in notes] == ["A4", "C5"]


def test_segment_notes_ignores_short_blips():
    f0 = np.full(100, 440.0)
    track = PitchTrack(np.linspace(0, 0.02, 100), f0, np.ones(100))  # muy corto: 20ms
    assert segment_notes(track, min_note_duration=0.08) == []


def test_segment_notes_merges_short_gap_same_note():
    times = np.linspace(0, 1, 100)
    f0 = np.full(100, 440.0)
    f0[48:52] = np.nan  # hueco corto en medio
    track = PitchTrack(times, f0, np.ones(100))
    notes = segment_notes(track, merge_gap=0.1)
    assert len(notes) == 1


def test_segment_notes_empty_track():
    assert segment_notes(PitchTrack(np.array([]), np.array([]), np.array([]))) == []
    assert segment_notes(PitchTrack(np.linspace(0, 1, 10), np.full(10, np.nan), np.zeros(10))) == []


# --- análisis vocal completo ---

def test_analyze_vocal_in_tune_steady_note():
    analysis = metrics.analyze_vocal(steady_tone(440.0, 1.0), 44100)
    assert analysis.avg_cents_deviation < 5.0
    assert analysis.vocal_range == ("A4", "A4")
    assert len(analysis.notes) == 1
    assert analysis.voiced_fraction > 0.8


def test_analyze_vocal_detects_pause():
    silence = np.zeros(int(0.5 * 44100), np.float32)
    x = np.concatenate([steady_tone(440, 0.5), silence, steady_tone(440, 0.5)])
    analysis = metrics.analyze_vocal(x, 44100)
    assert len(analysis.pauses) == 1
    start, end = analysis.pauses[0]
    assert end - start == pytest.approx(0.5, abs=0.1)


def test_analyze_vocal_detects_vibrato():
    analysis = metrics.analyze_vocal(vibrato_tone(440.0, 1.2, rate=5.5, extent_cents=35), 44100)
    assert analysis.vibrato_rate_hz is not None
    assert analysis.vibrato_rate_hz == pytest.approx(5.5, abs=1.5)
    assert analysis.vibrato_extent_cents > 10


def test_analyze_vocal_no_vibrato_on_flat_tone():
    analysis = metrics.analyze_vocal(steady_tone(440.0, 1.0), 44100)
    assert analysis.vibrato_rate_hz is None


def test_analyze_vocal_silence_gives_empty_result():
    analysis = metrics.analyze_vocal(np.zeros(44100, np.float32), 44100)
    assert analysis.notes == []
    assert analysis.vocal_range is None
    assert analysis.avg_cents_deviation == 0.0


def test_analyze_vocal_reports_progress_to_completion():
    steps = []
    metrics.analyze_vocal(steady_tone(440, 0.5), 44100, progress=lambda f, m: steps.append((f, m)))
    assert steps[-1][0] == pytest.approx(1.0)


def test_vocal_analysis_dict_roundtrip():
    analysis = metrics.analyze_vocal(steady_tone(440, 0.5), 44100)
    data = metrics.to_dict(analysis)
    restored = metrics.from_dict(data, analysis.pitch)
    assert restored.avg_cents_deviation == pytest.approx(analysis.avg_cents_deviation)
    assert [n.name for n in restored.notes] == [n.name for n in analysis.notes]
    assert restored.vocal_range == analysis.vocal_range


# --- canción: BPM y tonalidad ---

def test_estimate_bpm_on_click_track():
    bpm = song.estimate_bpm(click_track(120.0, 8.0), 44100)
    assert bpm is not None
    # tolera errores de octava (60/120/240) ademas del valor exacto
    assert any(abs(bpm - target) < 4 for target in (60.0, 120.0, 240.0))


def test_estimate_bpm_silence_returns_none():
    assert song.estimate_bpm(np.zeros(44100 * 4, np.float32), 44100) is None


def test_estimate_bpm_too_short_returns_none():
    assert song.estimate_bpm(np.zeros(1000, np.float32), 44100) is None


def test_estimate_key_detects_c_major():
    root, is_major, confidence = song.estimate_key(c_major_scale(), 44100)
    assert root == "C"
    assert is_major is True
    assert confidence > 0.3


def test_estimate_key_silence_returns_default_with_zero_confidence():
    root, is_major, confidence = song.estimate_key(np.zeros(44100, np.float32), 44100)
    assert confidence == 0.0


def test_analyze_song_combines_bpm_and_key():
    analysis = song.analyze_song(c_major_scale(note_sec=0.4), 44100)
    assert analysis.key_root == "C"
    assert analysis.key_label == "Do mayor"
    assert analysis.duration > 0


def test_song_analysis_labels():
    a = song.SongAnalysis(bpm=128.4, key_root="A", key_is_major=False, key_confidence=0.7, duration=180.0)
    assert a.bpm_label == "128 BPM"
    assert a.key_label == "La menor"
    assert song.SongAnalysis(None, "C", True, 0.0, 0.0).bpm_label == "No detectado"


def test_song_analysis_dict_roundtrip():
    a = song.SongAnalysis(bpm=100.0, key_root="G", key_is_major=True, key_confidence=0.5, duration=200.0)
    assert song.from_dict(song.to_dict(a)) == a
