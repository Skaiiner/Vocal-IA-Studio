from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.core.config import Settings, SettingsStore
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.session import Session
from vocal_ai_studio.audio.io import AudioData


def steady_tone(freq=440.0, seconds=0.8, sr=44100, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    return AudioData((amp * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)


@pytest.fixture
def session(backend, tmp_path):
    settings = Settings(projects_dir=str(tmp_path / "Projects"))
    s = Session(backend, settings, SettingsStore(tmp_path / "settings.json"))
    s.new_project("Analisis")
    yield s
    s.close()


def test_analyze_vocal_requires_voice(session):
    with pytest.raises(AppError):
        session.analyze_vocal()


def test_analyze_vocal_on_take_and_cache_roundtrip(session):
    session.project.add_take(steady_tone())
    session.refresh_tracks()
    analysis = session.analyze_vocal()
    assert analysis.vocal_range == ("A4", "A4")

    cached = session.load_vocal_analysis()
    assert cached is not None
    assert cached.vocal_range == analysis.vocal_range
    assert cached.notes[0].name == "A4"
    np.testing.assert_allclose(cached.pitch.times, analysis.pitch.times)


def test_analyze_vocal_key_follows_active_take(session):
    t1 = session.project.add_take(steady_tone(440.0))
    session.analyze_vocal()
    t2 = session.project.add_take(steady_tone(523.25))
    session.analyze_vocal()
    session.select_take(t1.id)
    assert session.load_vocal_analysis().vocal_range == ("A4", "A4")
    session.select_take(t2.id)
    assert session.load_vocal_analysis().vocal_range == ("C5", "C5")


def test_load_vocal_analysis_without_prior_analysis_is_none(session):
    session.project.add_take(steady_tone())
    session.refresh_tracks()
    assert session.load_vocal_analysis() is None


def test_analyze_vocal_progress_and_cancel(session, backend):
    session.project.add_take(steady_tone(440.0, 1.0))
    session.refresh_tracks()
    steps = []
    session.analyze_vocal(progress=lambda f, m: steps.append(f))
    assert steps[-1] == pytest.approx(1.0)

    from vocal_ai_studio.pitch.yin import AnalysisCancelled

    with pytest.raises(AnalysisCancelled):
        session.analyze_vocal(cancelled=lambda: True)


def test_analyze_song_requires_song(session):
    with pytest.raises(AppError):
        session.analyze_song()


def test_analyze_song_and_cache_roundtrip(session, tmp_path):
    from vocal_ai_studio.audio.io import save_audio

    save_audio(tmp_path / "s.wav", steady_tone(440.0, 2.0, amp=0.6), "wav")
    session.import_song_file(tmp_path / "s.wav")
    analysis = session.analyze_song()
    assert analysis.duration > 1.0

    cached = session.load_song_analysis()
    assert cached is not None
    assert cached.key_root == analysis.key_root
    assert cached.bpm == analysis.bpm


def test_load_song_analysis_without_prior_is_none(session, tmp_path):
    from vocal_ai_studio.audio.io import save_audio

    save_audio(tmp_path / "s.wav", steady_tone(440.0, 1.0), "wav")
    session.import_song_file(tmp_path / "s.wav")
    assert session.load_song_analysis() is None


def test_reimporting_song_invalidates_cached_analysis(session, tmp_path):
    from vocal_ai_studio.audio.io import save_audio

    save_audio(tmp_path / "s1.wav", steady_tone(440.0, 1.0), "wav")
    session.import_song_file(tmp_path / "s1.wav")
    session.analyze_song()
    assert session.load_song_analysis() is not None

    save_audio(tmp_path / "s2.wav", steady_tone(220.0, 1.0), "wav")
    session.import_song_file(tmp_path / "s2.wav")
    assert session.load_song_analysis() is None
