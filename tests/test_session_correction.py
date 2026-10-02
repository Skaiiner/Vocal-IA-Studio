from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.audio.io import AudioData
from vocal_ai_studio.core.config import Settings, SettingsStore
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.pitch.correction import CorrectionSettings, NoteOverride
from vocal_ai_studio.pitch.notes import hz_to_midi, note_name_to_hz
from vocal_ai_studio.session import Session


def flat_tone(target_name="A4", cents_off=35.0, seconds=1.0, sr=44100, amp=0.5):
    freq = note_name_to_hz(target_name) * 2 ** (cents_off / 1200)
    t = np.arange(int(seconds * sr)) / sr
    return AudioData((amp * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)


@pytest.fixture
def session(backend, tmp_path):
    settings = Settings(projects_dir=str(tmp_path / "Projects"))
    s = Session(backend, settings, SettingsStore(tmp_path / "settings.json"))
    s.new_project("Correccion")
    yield s
    s.close()


def test_load_correction_defaults_without_project(backend, tmp_path):
    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")))
    settings, overrides = s.load_correction()
    assert settings == CorrectionSettings()
    assert overrides == []
    s.close()


def test_save_and_load_correction_roundtrip(session):
    session.project.add_take(flat_tone())
    session.refresh_tracks()
    settings = CorrectionSettings.from_mode("Hard Autotune", key="G", scale="Menor natural")
    overrides = [NoteOverride(0.0, 0.5, semitone_offset=1, bypass=False)]
    session.save_correction(settings, overrides)

    loaded_settings, loaded_overrides = session.load_correction()
    assert loaded_settings == settings
    assert loaded_overrides == overrides


def test_correction_follows_active_take(session):
    t1 = session.project.add_take(flat_tone())
    session.save_correction(CorrectionSettings(key="C"), [])
    t2 = session.project.add_take(flat_tone())
    session.save_correction(CorrectionSettings(key="D"), [])

    session.select_take(t1.id)
    assert session.load_correction()[0].key == "C"
    session.select_take(t2.id)
    assert session.load_correction()[0].key == "D"


def test_seed_overrides_requires_prior_analysis(session):
    session.project.add_take(flat_tone())
    session.refresh_tracks()
    assert session.seed_overrides_from_analysis() == []  # sin analizar, no hay notas
    session.analyze_vocal()
    overrides = session.seed_overrides_from_analysis()
    assert len(overrides) == 1
    assert overrides[0].semitone_offset == 0 and not overrides[0].bypass


def test_preview_correction_curve_requires_analysis(session):
    session.project.add_take(flat_tone())
    session.refresh_tracks()
    with pytest.raises(AppError):
        session.preview_correction_curve(CorrectionSettings(), [])


def test_preview_correction_curve_matches_build_target(session):
    session.project.add_take(flat_tone(cents_off=40))
    session.refresh_tracks()
    session.analyze_vocal()
    settings = CorrectionSettings.from_mode("Hard Autotune", key="C", scale="Mayor")
    curve = session.preview_correction_curve(settings, [])
    voiced = ~np.isnan(curve)
    assert voiced.any()
    assert np.nanmean(curve) == pytest.approx(note_name_to_hz("A4"), rel=0.01)


def test_apply_correction_requires_voice(session):
    with pytest.raises(AppError):
        session.apply_correction(CorrectionSettings(), [])


def test_apply_correction_requires_analysis_first(session):
    session.project.add_take(flat_tone())
    session.refresh_tracks()
    with pytest.raises(AppError):
        session.apply_correction(CorrectionSettings(), [])


def test_apply_correction_creates_new_take_and_corrects_pitch(session):
    session.project.add_take(flat_tone(cents_off=45), offset_sec=0.3)
    session.refresh_tracks()
    session.analyze_vocal()
    before = len(session.project.data.takes)

    settings = CorrectionSettings.from_mode("Hard Autotune", key="C", scale="Mayor")
    steps = []
    new_take = session.apply_correction(settings, [], progress=lambda f, m: steps.append((f, m)))

    assert len(session.project.data.takes) == before + 1
    assert "corregida" in new_take.name
    assert new_take.offset_sec == pytest.approx(0.3)  # conserva el mismo punto de entrada
    assert steps and steps[-1][0] == pytest.approx(1.0)

    corrected_audio = session.project.load_take(new_take.id)
    from vocal_ai_studio.pitch.yin import yin_pitch_track

    verified = yin_pitch_track(corrected_audio.to_mono(), corrected_audio.samplerate)
    assert np.nanmean(verified.f0) == pytest.approx(note_name_to_hz("A4"), rel=0.01)


def test_apply_correction_original_take_untouched(session):
    original = session.project.add_take(flat_tone(cents_off=45))
    session.refresh_tracks()
    session.analyze_vocal()
    before_audio = session.project.load_take(original.id)

    session.apply_correction(CorrectionSettings.from_mode("Hard Autotune"), [])

    after_audio = session.project.load_take(original.id)
    np.testing.assert_allclose(before_audio.samples, after_audio.samples)


def test_apply_correction_saves_settings_used(session):
    session.project.add_take(flat_tone())
    session.refresh_tracks()
    session.analyze_vocal()
    settings = CorrectionSettings(key="F", scale="Pentatónica mayor", amount=60, speed_ms=15, humanize=20)
    session.apply_correction(settings, [])
    saved_settings, _ = session.load_correction()
    assert saved_settings == settings


def test_apply_correction_amount_zero_barely_changes_pitch(session):
    session.project.add_take(flat_tone(cents_off=45))
    session.refresh_tracks()
    analysis = session.analyze_vocal()
    original_midi = hz_to_midi(np.nanmean(analysis.pitch.f0))

    settings = CorrectionSettings(amount=0, speed_ms=10, humanize=0)
    new_take = session.apply_correction(settings, [])
    corrected_audio = session.project.load_take(new_take.id)

    from vocal_ai_studio.pitch.yin import yin_pitch_track

    verified = yin_pitch_track(corrected_audio.to_mono(), corrected_audio.samplerate)
    assert hz_to_midi(np.nanmean(verified.f0)) == pytest.approx(original_midi, abs=0.1)
