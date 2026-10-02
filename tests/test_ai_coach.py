from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.ai.feedback import CoachFeedback, Exercise
from vocal_ai_studio.ai.providers import LocalRulesProvider, OllamaProvider
from vocal_ai_studio.ai.rules import build_feedback
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.core.interfaces import PitchTrack
from vocal_ai_studio.voice_analysis.metrics import VocalAnalysis
from vocal_ai_studio.voice_analysis.notes import NoteSegment
from vocal_ai_studio.voice_analysis.song import SongAnalysis


def _track():
    return PitchTrack(np.linspace(0, 1, 10), np.full(10, 440.0), np.ones(10))


def _analysis(**overrides) -> VocalAnalysis:
    base = dict(pitch=_track(), duration=5.0, notes=[], avg_cents_deviation=5.0,
                stability_cents=5.0, vocal_range=("A3", "A4"), pauses=[],
                vibrato_rate_hz=None, vibrato_extent_cents=None, voiced_fraction=0.9)
    base.update(overrides)
    return VocalAnalysis(**base)


# --- feedback / exercise dataclasses ---

def test_exercise_dict_roundtrip():
    e = Exercise("Título", "Descripción")
    assert Exercise.from_dict(e.to_dict()) == e


def test_coach_feedback_dict_roundtrip():
    fb = CoachFeedback("resumen", ["fuerte"], ["mejorar"], [Exercise("T", "D")], "Ollama (x)")
    restored = CoachFeedback.from_dict(fb.to_dict())
    assert restored == fb


# --- reglas ---

def test_good_pitch_is_praised_and_no_forced_issues():
    fb = build_feedback(_analysis(avg_cents_deviation=5.0, stability_cents=5.0))
    assert any("precisa" in s for s in fb.strengths)
    assert fb.generated_by == "Reglas locales"


def test_bad_pitch_flagged_with_exercise():
    fb = build_feedback(_analysis(avg_cents_deviation=40.0))
    assert any("desvía" in i for i in fb.issues)
    assert fb.exercises


def test_unstable_pitch_flagged():
    fb = build_feedback(_analysis(stability_cents=50.0))
    assert any("tiembla" in i for i in fb.issues)


def test_worst_note_reported_with_direction():
    notes = [NoteSegment(start=1.0, end=1.5, midi=69, name="A4", avg_freq=460.0,
                         avg_cents=35.0, max_abs_cents=35.0)]
    fb = build_feedback(_analysis(notes=notes))
    assert any("A4" in i and "por encima" in i for i in fb.issues)


def test_wide_vibrato_flagged():
    fb = build_feedback(_analysis(vibrato_rate_hz=5.0, vibrato_extent_cents=200.0))
    assert any("vibrato" in i.lower() for i in fb.issues)


def test_natural_vibrato_praised():
    fb = build_feedback(_analysis(vibrato_rate_hz=5.5, vibrato_extent_cents=50.0))
    assert any("vibrato" in s.lower() for s in fb.strengths)


def test_song_analysis_adds_tempo_and_key_to_summary():
    song = SongAnalysis(bpm=120.0, key_root="C", key_is_major=True, key_confidence=0.8, duration=10.0)
    fb = build_feedback(_analysis(), song)
    assert "BPM" in fb.summary


def test_always_has_at_least_one_exercise():
    fb = build_feedback(_analysis())
    assert len(fb.exercises) >= 1


# --- proveedores ---

def test_local_provider_always_available():
    p = LocalRulesProvider()
    assert p.is_available() is True
    assert p.complete("hola") == "hola"


def test_ollama_unavailable_without_model():
    p = OllamaProvider("http://localhost:11434", "")
    assert p.is_available() is False


def test_ollama_unavailable_when_unreachable():
    p = OllamaProvider("http://localhost:1", "llama3")
    assert p.is_available() is False


# --- integración con Session ---

def test_session_generate_coach_feedback_requires_analysis(backend, tmp_path):
    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")), SettingsStore(tmp_path / "settings.json"))
    s.new_project("Coach")
    with pytest.raises(AppError):
        s.generate_coach_feedback()
    s.close()


def test_session_generate_and_load_coach_feedback(backend, tmp_path):
    import soundfile as sf

    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    sr = 44100
    wav = tmp_path / "voz.wav"
    t = np.arange(int(1.0 * sr)) / sr
    sf.write(str(wav), (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr)

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")), SettingsStore(tmp_path / "settings.json"))
    s.new_project("Coach")
    s.import_vocal_as_take(wav)
    s.analyze_vocal()
    feedback = s.generate_coach_feedback()
    assert feedback.summary
    loaded = s.load_coach_feedback()
    assert loaded == feedback
    s.close()
