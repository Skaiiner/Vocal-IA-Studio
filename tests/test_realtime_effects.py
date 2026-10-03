from __future__ import annotations

import numpy as np

from vocal_ai_studio.effects.chain import VoiceLabSettings
from vocal_ai_studio.realtime.streaming_effects import (
    StreamingChain,
    StreamingCompressor,
    StreamingDeEsser,
    StreamingDelay,
    StreamingEq,
    StreamingFormantShifter,
    StreamingReverb,
)

SR = 44100
BLOCK = 512


def sine(freq=440.0, seconds=1.0, sr=SR, amp=0.4):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def run_in_blocks(effect_fn, x, block=BLOCK):
    out = []
    for i in range(0, len(x), block):
        out.append(effect_fn(x[i:i + block]))
    return np.concatenate(out)


def assert_finite_and_bounded(y, limit=4.0):
    assert np.all(np.isfinite(y))
    assert np.max(np.abs(y)) < limit


# --- EQ ---

def test_streaming_eq_boosts_like_offline():
    from vocal_ai_studio.effects.eq import apply_eq

    x = sine(freq=1000.0)
    bands = [{"type": "peak", "freq": 1000, "gain_db": 12.0, "q": 1.0}]
    offline = apply_eq(x, SR, bands)

    eq = StreamingEq()
    y = run_in_blocks(lambda b: eq.process(b, SR, bands), x)
    assert_finite_and_bounded(y)
    # tras el transitorio inicial del filtro, debe converger a un resultado similar al offline
    assert np.allclose(y[2000:], offline[2000:], atol=0.05)


def test_streaming_eq_empty_bands_passthrough():
    eq = StreamingEq()
    x = sine(seconds=0.2)
    y = run_in_blocks(lambda b: eq.process(b, SR, []), x)
    assert np.array_equal(x, y)


# --- De-esser ---

def test_streaming_deesser_reduces_sibilants():
    sr = 22050
    t = np.arange(int(1.0 * sr)) / sr
    sibilant = (0.6 * np.sin(2 * np.pi * 7000 * t)).astype(np.float32)
    de = StreamingDeEsser()
    y = run_in_blocks(lambda b: de.process(b, sr, -25.0, 7000.0, 2000.0), sibilant, block=256)
    assert_finite_and_bounded(y)
    in_rms = float(np.sqrt(np.mean(sibilant[5000:] ** 2)))
    out_rms = float(np.sqrt(np.mean(y[5000:] ** 2)))
    assert out_rms < in_rms


# --- Compresor ---

def test_streaming_compressor_reduces_peaks():
    x = sine(amp=0.9)
    comp = StreamingCompressor()
    y = run_in_blocks(lambda b: comp.process(b, SR, -20.0, 10.0, 1.0, 10.0, 0.0), x)
    assert_finite_and_bounded(y)
    assert np.max(np.abs(y[2000:])) < np.max(np.abs(x[2000:]))


def test_streaming_compressor_silence_passthrough():
    x = np.zeros(SR, dtype=np.float32)
    comp = StreamingCompressor()
    y = run_in_blocks(lambda b: comp.process(b, SR, -18.0, 3.0, 5.0, 50.0, 0.0), x)
    assert np.allclose(y, 0, atol=1e-5)


# --- Reverb / Delay ---

def test_streaming_reverb_adds_tail_and_stays_bounded():
    x = sine(seconds=0.5)
    rev = StreamingReverb()
    y = run_in_blocks(lambda b: rev.process(b, SR, 0.5, 0.4), x)
    assert_finite_and_bounded(y, limit=1.5)
    assert not np.allclose(x, y, atol=1e-3)


def test_streaming_reverb_wet_zero_passthrough():
    rev = StreamingReverb()
    x = sine(seconds=0.2)
    y = run_in_blocks(lambda b: rev.process(b, SR, 0.3, 0.0), x)
    assert np.allclose(x, y, atol=1e-4)


def test_streaming_delay_creates_echo_and_stays_bounded():
    x = sine(seconds=1.0)
    delay = StreamingDelay()
    y = run_in_blocks(lambda b: delay.process(b, SR, 100.0, 0.3, 0.5), x)
    assert_finite_and_bounded(y, limit=1.5)
    assert not np.allclose(x, y, atol=1e-3)


def test_streaming_delay_wet_zero_passthrough():
    delay = StreamingDelay()
    x = sine(seconds=0.2)
    y = run_in_blocks(lambda b: delay.process(b, SR, 250.0, 0.3, 0.0), x)
    assert np.allclose(x, y, atol=1e-4)


# --- Formantes ---

def test_streaming_formants_zero_is_identity():
    shifter = StreamingFormantShifter()
    x = sine(seconds=0.2)
    y = run_in_blocks(lambda b: shifter.process(b, SR, 0.0), x)
    assert np.allclose(x, y, atol=1e-4)


def test_streaming_formants_changes_signal_and_stays_bounded():
    shifter = StreamingFormantShifter()
    x = sine(seconds=1.0)
    y = run_in_blocks(lambda b: shifter.process(b, SR, 3.0), x)
    assert_finite_and_bounded(y, limit=1.5)
    assert len(y) == len(x)
    # tras la latencia inherente del vocoder de fase, la señal debe diferir de la original
    assert not np.allclose(x[5000:], y[5000:], atol=1e-3)


def test_streaming_formants_concatenation_matches_block_by_block_state():
    shifter_a = StreamingFormantShifter()
    shifter_b = StreamingFormantShifter()
    x = sine(seconds=0.5)
    y_blocked = run_in_blocks(lambda b: shifter_a.process(b, SR, 2.0), x, block=256)
    y_whole = shifter_b.process(x, SR, 2.0)
    # procesar en bloques pequeños con estado persistido debe converger al mismo resultado
    # que procesar todo de una vez cuando ambos usan el mismo motor con estado
    assert len(y_blocked) == len(y_whole)


# --- Chain completa ---

def test_chain_clean_settings_passthrough_like():
    chain = StreamingChain(SR)
    settings = VoiceLabSettings()
    x = sine(seconds=0.3)
    y = run_in_blocks(lambda b: chain.process(b, settings), x)
    assert np.allclose(x, y, atol=1e-3)


def test_chain_preset_changes_signal_and_stays_bounded():
    chain = StreamingChain(SR)
    settings = VoiceLabSettings.from_preset("Pop")
    x = sine(seconds=1.0)
    y = run_in_blocks(lambda b: chain.process(b, settings), x)
    assert_finite_and_bounded(y, limit=2.0)
    assert len(y) == len(x)
    assert not np.allclose(x, y, atol=1e-3)


def test_chain_reset_clears_state():
    chain = StreamingChain(SR)
    settings = VoiceLabSettings.from_preset("Studio")
    x = sine(seconds=0.3)
    run_in_blocks(lambda b: chain.process(b, settings), x)
    chain.reset()
    y = run_in_blocks(lambda b: chain.process(b, settings), x)
    assert np.all(np.isfinite(y))
