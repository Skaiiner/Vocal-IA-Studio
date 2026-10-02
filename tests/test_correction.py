from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.core.interfaces import PitchTrack
from vocal_ai_studio.pitch.correction import (
    CorrectionSettings,
    NoteOverride,
    build_target_curve,
    overrides_from_notes,
)
from vocal_ai_studio.pitch.notes import hz_to_midi, note_name_to_hz
from vocal_ai_studio.pitch.scales import KEYS, SCALES, nearest_scale_midi
from vocal_ai_studio.pitch.shifter import ShiftCancelled, psola_resynthesize
from vocal_ai_studio.pitch.yin import yin_pitch_track
from vocal_ai_studio.voice_analysis.notes import segment_notes


def tone(freq=440.0, seconds=1.0, sr=44100, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def slightly_flat_tone(target_hz, cents_off, seconds=1.0, sr=44100, amp=0.5):
    freq = target_hz * 2 ** (cents_off / 1200)
    return tone(freq, seconds, sr, amp)


# --- escalas ---

def test_nearest_scale_midi_snaps_to_major_scale():
    # Re# (63) no está en Do mayor; el más cercano es Re (62) o Mi (64)
    assert nearest_scale_midi(63.4, "C", "Mayor") == 64
    assert nearest_scale_midi(62.6, "C", "Mayor") == 62


def test_nearest_scale_midi_chromatic_is_identity():
    assert nearest_scale_midi(61.3, "C", "Cromática") == 61


def test_nearest_scale_midi_respects_key():
    # Fa# (66) está en Sol mayor pero no en Do mayor
    assert nearest_scale_midi(66.0, "G", "Mayor") == 66
    assert nearest_scale_midi(66.0, "C", "Mayor") in (65, 67)


def test_all_scales_and_keys_are_usable():
    for key in KEYS:
        for scale in SCALES:
            assert isinstance(nearest_scale_midi(69.3, key, scale), int)


# --- curva objetivo ---

def _track_from(freq, cents_off=0.0, seconds=1.0, sr=44100):
    f0 = np.full(100, freq * 2 ** (cents_off / 1200))
    return PitchTrack(np.linspace(0, seconds, 100), f0, np.ones(100))


def test_amount_zero_leaves_pitch_untouched():
    track = _track_from(440.0, cents_off=35)  # desafinado a propósito
    settings = CorrectionSettings(amount=0.0, speed_ms=1.0, humanize=0.0)
    target = build_target_curve(track, [], settings)
    np.testing.assert_allclose(target, track.f0, rtol=1e-6)


def test_amount_hundred_snaps_fully_with_fast_speed():
    track = _track_from(440.0, cents_off=35)  # A4 + 35 cents
    settings = CorrectionSettings(amount=100.0, speed_ms=0.5, humanize=0.0, key="C", scale="Mayor")
    target = build_target_curve(track, [], settings)
    # con velocidad casi instantánea, converge rápido a A4 exacto (440 Hz)
    assert target[-1] == pytest.approx(440.0, rel=0.002)


def test_partial_amount_blends_towards_target():
    track = _track_from(440.0, cents_off=100)  # a un semitono (A#4)
    full = build_target_curve(track, [], CorrectionSettings(amount=100.0, speed_ms=0.5, humanize=0))
    half = build_target_curve(track, [], CorrectionSettings(amount=50.0, speed_ms=0.5, humanize=0))
    # a medio camino en cents entre el original y la corrección completa
    orig_midi = hz_to_midi(track.f0[-1])
    assert hz_to_midi(half[-1]) == pytest.approx((orig_midi + hz_to_midi(full[-1])) / 2, abs=0.05)


def test_slow_speed_lags_behind_fast_speed():
    # Un salto real de nota a mitad de camino: sin un cambio de objetivo no hay nada que
    # "velocidad" pueda hacer notar (ambas convergerían igual de rápido al primer valor).
    times = np.linspace(0, 1.0, 100)
    f0 = np.concatenate([np.full(50, 440.0), np.full(50, 440.0 * 2 ** (1 / 12))])  # A4 -> A#4
    track = PitchTrack(times, f0, np.ones(100))
    settings_kwargs = dict(amount=100, humanize=0, key="C", scale="Cromática")
    slow = build_target_curve(track, [], CorrectionSettings(speed_ms=500, **settings_kwargs))
    fast = build_target_curve(track, [], CorrectionSettings(speed_ms=1, **settings_kwargs))
    just_after_jump = 55
    target_freq = f0[-1]
    assert abs(slow[just_after_jump] - target_freq) > abs(fast[just_after_jump] - target_freq)


def test_humanize_lets_pitch_drift_back_on_long_notes():
    track = _track_from(440.0, cents_off=35, seconds=1.0)
    notes = segment_notes(track)
    assert len(notes) == 1
    no_human = build_target_curve(track, notes, CorrectionSettings(amount=100, speed_ms=1, humanize=0))
    human = build_target_curve(track, notes, CorrectionSettings(amount=100, speed_ms=1, humanize=90))
    # al final de la nota sostenida, humanize deja volver más cerca del original desafinado
    assert abs(human[-1] - track.f0[-1]) < abs(no_human[-1] - track.f0[-1])


def test_bypass_override_restores_original():
    track = _track_from(440.0, cents_off=35)
    ov = [NoteOverride(0.0, 10.0, semitone_offset=0, bypass=True)]  # cubre todo el track con margen
    target = build_target_curve(track, [], CorrectionSettings(amount=100, speed_ms=0.5), overrides=ov)
    np.testing.assert_allclose(target, track.f0, rtol=1e-6)


def test_transpose_override_shifts_semitones():
    track = _track_from(440.0, cents_off=0)  # exactamente A4
    ov = [NoteOverride(0.0, 10.0, semitone_offset=2, bypass=False)]
    target = build_target_curve(track, [], CorrectionSettings(amount=100, speed_ms=0.5), overrides=ov)
    assert hz_to_midi(target[-1]) == pytest.approx(71.0, abs=0.05)  # A4 + 2 semitonos = B4


def test_overrides_from_notes_seeds_identity():
    track = _track_from(440.0, seconds=0.5)
    notes = segment_notes(track)
    overrides = overrides_from_notes(notes)
    assert len(overrides) == len(notes)
    assert all(o.semitone_offset == 0 and not o.bypass for o in overrides)


def test_build_target_curve_handles_silence():
    track = PitchTrack(np.linspace(0, 1, 50), np.full(50, np.nan), np.zeros(50))
    target = build_target_curve(track, [], CorrectionSettings())
    assert np.all(np.isnan(target))


def test_correction_settings_dict_roundtrip():
    s = CorrectionSettings(key="G", scale="Menor natural", amount=55, speed_ms=22, humanize=33,
                           preserve_formants=False, mode="Balanced")
    assert CorrectionSettings.from_dict(s.to_dict()) == s


def test_note_override_dict_roundtrip():
    ov = NoteOverride(1.0, 2.5, semitone_offset=-3, bypass=True)
    assert NoteOverride.from_dict(ov.to_dict()) == ov


def test_mode_presets_cover_spec_modes():
    from vocal_ai_studio.pitch.correction import MODE_NAMES
    assert set(MODE_NAMES) == {"Natural", "Balanced", "Hard Autotune", "Extreme"}
    hard = CorrectionSettings.from_mode("Hard Autotune")
    extreme = CorrectionSettings.from_mode("Extreme")
    assert hard.amount == 100 and extreme.amount == 100
    assert extreme.speed_ms < hard.speed_ms


# --- PSOLA: ¿de verdad cambia el tono? ---

def test_psola_shifts_pitch_up_two_semitones_preserving_formants():
    sr = 44100
    x = tone(440.0, 1.0, sr)
    times = np.linspace(0, 1.0, 50)
    src_f0 = np.full(50, 440.0)
    target_f0 = np.full(50, 440.0 * 2 ** (2 / 12))  # +2 semitonos ≈ 493.88 Hz (B4)
    out = psola_resynthesize(x, sr, times, src_f0, times, target_f0, preserve_formants=True)
    track = yin_pitch_track(out, sr)
    measured = np.nanmean(track.f0)
    assert measured == pytest.approx(493.88, rel=0.02)


def test_psola_shifts_pitch_down_preserving_formants():
    sr = 44100
    x = tone(440.0, 1.0, sr)
    times = np.linspace(0, 1.0, 50)
    target_f0 = np.full(50, 440.0 * 2 ** (-3 / 12))
    out = psola_resynthesize(x, sr, times, np.full(50, 440.0), times, target_f0, preserve_formants=True)
    track = yin_pitch_track(out, sr)
    assert np.nanmean(track.f0) == pytest.approx(target_f0[0], rel=0.02)


def test_psola_output_same_length_as_input():
    sr = 44100
    x = tone(440.0, 0.7, sr)
    times = np.linspace(0, 0.7, 30)
    out = psola_resynthesize(x, sr, times, np.full(30, 440.0), times, np.full(30, 523.25))
    assert len(out) == len(x)


def test_psola_nan_target_leaves_pitch_unchanged():
    sr = 44100
    x = tone(330.0, 0.8, sr)
    times = np.linspace(0, 0.8, 40)
    out = psola_resynthesize(x, sr, times, np.full(40, 330.0), times, np.full(40, np.nan))
    track = yin_pitch_track(out, sr)
    assert np.nanmean(track.f0) == pytest.approx(330.0, rel=0.02)


def test_psola_silence_in_silence_out():
    sr = 44100
    x = np.zeros(sr, np.float32)
    times = np.linspace(0, 1.0, 20)
    out = psola_resynthesize(x, sr, times, np.full(20, np.nan), times, np.full(20, np.nan))
    assert np.max(np.abs(out)) < 0.01


def test_psola_without_formant_preservation_still_shifts_pitch():
    sr = 44100
    x = tone(440.0, 0.8, sr)
    times = np.linspace(0, 0.8, 40)
    target_f0 = np.full(40, 440.0 * 2 ** (4 / 12))
    out = psola_resynthesize(x, sr, times, np.full(40, 440.0), times, target_f0, preserve_formants=False)
    track = yin_pitch_track(out, sr)
    assert np.nanmean(track.f0) == pytest.approx(target_f0[0], rel=0.03)


def test_psola_reports_progress_and_can_be_cancelled():
    sr = 44100
    x = tone(440.0, 1.5, sr)
    times = np.linspace(0, 1.5, 60)
    steps = []
    psola_resynthesize(x, sr, times, np.full(60, 440.0), times, np.full(60, 466.16), progress=steps.append)
    assert steps[-1] == pytest.approx(1.0)

    with pytest.raises(ShiftCancelled):
        psola_resynthesize(x, sr, times, np.full(60, 440.0), times, np.full(60, 466.16),
                           cancelled=lambda: True)


def test_full_pipeline_detect_correct_and_reverify():
    # extremo a extremo: tono desafinado -> curva objetivo (Hard Autotune) -> PSOLA -> re-detectar
    sr = 44100
    x = slightly_flat_tone(note_name_to_hz("A4"), cents_off=40, seconds=1.0, sr=sr)
    track = yin_pitch_track(x, sr)
    notes = segment_notes(track)
    settings = CorrectionSettings.from_mode("Hard Autotune", key="C", scale="Mayor")
    target = build_target_curve(track, notes, settings)
    corrected = psola_resynthesize(x, sr, track.times, track.f0, track.times, target,
                                   preserve_formants=settings.preserve_formants)
    verified = yin_pitch_track(corrected, sr)
    assert np.nanmean(verified.f0) == pytest.approx(note_name_to_hz("A4"), rel=0.01)
