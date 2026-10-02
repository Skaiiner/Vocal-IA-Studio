from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.effects.chain import (
    CompressorSettings,
    DeEsserSettings,
    DelaySettings,
    ReverbSettings,
    VoiceLabSettings,
    apply_chain,
)
from vocal_ai_studio.effects.dynamics import apply_compressor, apply_deesser
from vocal_ai_studio.effects.eq import apply_eq
from vocal_ai_studio.effects.formants import shift_formants
from vocal_ai_studio.effects.presets import PRESET_NAMES, PRESETS
from vocal_ai_studio.effects.reverb import apply_delay, apply_reverb


SR = 44100


def sine(freq=440.0, seconds=0.5, sr=SR, amp=0.4):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


# --- EQ ---

def test_eq_flat_passthrough():
    x = sine()
    bands = [{"type": "low_shelf", "freq": 100, "gain_db": 0.0, "q": 0.7}]
    y = apply_eq(x, SR, bands)
    assert np.allclose(x, y, atol=1e-4)


def test_eq_peak_boost_increases_rms():
    x = sine(freq=1000.0)
    bands = [{"type": "peak", "freq": 1000, "gain_db": 12.0, "q": 1.0}]
    y = apply_eq(x, SR, bands)
    assert rms(y) > rms(x) * 1.5


def test_eq_peak_cut_decreases_rms():
    x = sine(freq=1000.0)
    bands = [{"type": "peak", "freq": 1000, "gain_db": -12.0, "q": 1.0}]
    y = apply_eq(x, SR, bands)
    assert rms(y) < rms(x) * 0.5


def test_eq_preserves_length():
    x = sine()
    bands = [{"type": "low_shelf", "freq": 200, "gain_db": 3.0, "q": 0.7},
             {"type": "high_shelf", "freq": 8000, "gain_db": -3.0, "q": 0.7}]
    y = apply_eq(x, SR, bands)
    assert len(y) == len(x)


def test_eq_empty_bands_passthrough():
    x = sine()
    y = apply_eq(x, SR, [])
    assert np.array_equal(x, y)


# --- Compresor ---

def test_compressor_reduces_peaks():
    x = sine(amp=0.9)
    y = apply_compressor(x, SR, threshold_db=-20, ratio=10.0, attack_ms=1, release_ms=10)
    assert np.max(np.abs(y)) < np.max(np.abs(x))


def test_compressor_silence_passthrough():
    x = np.zeros(SR, dtype=np.float32)
    y = apply_compressor(x, SR)
    assert np.allclose(y, 0, atol=1e-6)


def test_compressor_length_preserved():
    x = sine()
    y = apply_compressor(x, SR)
    assert len(y) == len(x)


# --- De-esser ---

def test_deesser_reduces_sibilants():
    sr = 22050
    t = np.arange(int(0.5 * sr)) / sr
    sibilant = (0.6 * np.sin(2 * np.pi * 7000 * t)).astype(np.float32)
    y = apply_deesser(sibilant, sr, threshold_db=-25, freq_hz=7000, bandwidth=2000)
    assert rms(y) < rms(sibilant)


def test_deesser_preserves_length():
    x = sine()
    y = apply_deesser(x, SR)
    assert len(y) == len(x)


# --- Reverb ---

def test_reverb_adds_tail():
    x = sine(seconds=0.3)
    y = apply_reverb(x, SR, room_size=0.5, wet=0.4)
    assert len(y) == len(x)
    # La señal procesada debe diferir de la original
    assert not np.allclose(x, y, atol=1e-3)


def test_reverb_wet_zero_passthrough():
    x = sine()
    y = apply_reverb(x, SR, wet=0.0)
    assert np.allclose(x, y, atol=1e-4)


def test_delay_creates_echo():
    x = sine(seconds=0.5)
    y = apply_delay(x, SR, time_ms=100, feedback=0.3, wet=0.5)
    assert len(y) == len(x)
    assert not np.allclose(x, y, atol=1e-3)


def test_delay_wet_zero_passthrough():
    x = sine()
    y = apply_delay(x, SR, wet=0.0)
    assert np.allclose(x, y, atol=1e-4)


# --- Formant shift ---

def test_formant_shift_zero_is_identity():
    x = sine()
    y = shift_formants(x, SR, semitones=0.0)
    assert np.allclose(x, y, atol=1e-4)


def test_formant_shift_changes_signal():
    x = sine(seconds=0.5)
    y = shift_formants(x, SR, semitones=3.0)
    assert len(y) == len(x)
    assert not np.allclose(x, y, atol=1e-3)


def test_formant_shift_preserves_rms():
    x = sine(seconds=0.5)
    y = shift_formants(x, SR, semitones=-2.0)
    assert abs(rms(y) - rms(x)) / (rms(x) + 1e-9) < 0.2


# --- VoiceLabSettings serialization ---

def test_settings_roundtrip():
    s = VoiceLabSettings(formant_shift=1.5, preset_name="Pop")
    s.compressor.enabled = True
    s.compressor.ratio = 6.0
    s.reverb.enabled = True
    s.reverb.wet = 0.25
    d = s.to_dict()
    s2 = VoiceLabSettings.from_dict(d)
    assert s2.formant_shift == pytest.approx(1.5)
    assert s2.preset_name == "Pop"
    assert s2.compressor.enabled is True
    assert s2.compressor.ratio == pytest.approx(6.0)
    assert s2.reverb.enabled is True
    assert s2.reverb.wet == pytest.approx(0.25)


def test_from_preset_loads_known_preset():
    s = VoiceLabSettings.from_preset("Rock")
    assert s.preset_name == "Rock"
    assert s.compressor.enabled is True


def test_all_presets_are_valid():
    for name in PRESET_NAMES[1:]:  # skip "Custom"
        s = VoiceLabSettings.from_preset(name)
        assert s.preset_name == name
        assert len(s.eq_bands) == 5


# --- apply_chain ---

def test_chain_clean_preset_passthrough_like():
    x = sine(seconds=0.3)
    s = VoiceLabSettings()  # todos desactivados, EQ plana
    y = apply_chain(x, SR, s)
    assert len(y) == len(x)
    assert np.allclose(x, y, atol=1e-3)


def test_chain_pop_preset_changes_signal():
    x = sine(seconds=0.5)
    s = VoiceLabSettings.from_preset("Pop")
    y = apply_chain(x, SR, s)
    assert len(y) == len(x)
    assert not np.allclose(x, y, atol=1e-3)


def test_chain_cancellation_returns_partial():
    x = sine(seconds=0.5)
    s = VoiceLabSettings.from_preset("Studio")
    calls = [0]

    def progress(f, msg):
        calls[0] += 1

    cancelled = [False]

    def cancel():
        cancelled[0] = True
        return True

    y = apply_chain(x, SR, s, progress=progress, cancelled=cancel)
    assert y is not None
    assert len(y) > 0


# --- session integration ---

def test_session_apply_voice_lab_creates_take(backend, tmp_path):
    import soundfile as sf

    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    wav = tmp_path / "voz.wav"
    t = np.arange(int(0.5 * SR)) / SR
    sf.write(str(wav), (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), SR)

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")),
                SettingsStore(tmp_path / "settings.json"))
    s.new_project("VoiceLab")
    s.import_vocal_as_take(wav)
    before = len(s.project.data.takes)
    settings = VoiceLabSettings.from_preset("Radio")
    take = s.apply_voice_lab(settings)
    assert "Radio" in take.name
    assert len(s.project.data.takes) == before + 1
    s.close()


def test_session_original_take_untouched_after_voice_lab(backend, tmp_path):
    import soundfile as sf

    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    wav = tmp_path / "voz.wav"
    t = np.arange(int(0.5 * SR)) / SR
    samples = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sf.write(str(wav), samples, SR)

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")),
                SettingsStore(tmp_path / "settings.json"))
    s.new_project("VoiceLab2")
    s.import_vocal_as_take(wav)
    orig_take_id = s.project.data.active_take
    settings = VoiceLabSettings.from_preset("Deep")
    s.apply_voice_lab(settings)
    orig_audio = s.project.load_take(orig_take_id)
    assert np.allclose(orig_audio.samples.flatten()[:len(samples)], samples, atol=1e-4)
    s.close()
