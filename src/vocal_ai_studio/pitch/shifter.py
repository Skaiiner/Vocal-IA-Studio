from __future__ import annotations

from typing import Callable

import numpy as np

from vocal_ai_studio.pitch.notes import hz_to_midi, median_smooth, midi_to_hz

Progress = Callable[[float], None]
Cancelled = Callable[[], bool]

DEFAULT_UNVOICED_HZ = 100.0
MIN_HZ, MAX_HZ = 50.0, 1000.0


class ShiftCancelled(Exception):
    pass


def _lookup_freq(t: float, times: np.ndarray, f0: np.ndarray) -> float:
    if len(times) == 0:
        return float("nan")
    idx = int(np.searchsorted(times, t))
    idx = min(max(idx, 0), len(times) - 1)
    freq = f0[idx]
    if np.isnan(freq) and idx > 0 and not np.isnan(f0[idx - 1]):
        freq = f0[idx - 1]
    return float(freq)


def _instant_period(t: float, times: np.ndarray, f0: np.ndarray,
                     fallback_times: np.ndarray | None = None, fallback_f0: np.ndarray | None = None) -> float:
    freq = _lookup_freq(t, times, f0)
    if np.isnan(freq) and fallback_f0 is not None:
        freq = _lookup_freq(t, fallback_times, fallback_f0)
    if np.isnan(freq):
        freq = DEFAULT_UNVOICED_HZ
    freq = float(np.clip(freq, MIN_HZ, MAX_HZ))
    return 1.0 / freq


def _generate_marks(duration: float, times: np.ndarray, f0: np.ndarray,
                     fallback_times: np.ndarray | None = None, fallback_f0: np.ndarray | None = None) -> np.ndarray:
    marks = [0.0]
    t = 0.0
    while t < duration:
        t += _instant_period(t, times, f0, fallback_times, fallback_f0)
        marks.append(t)
    return np.asarray(marks)


def _resample_to_length(x: np.ndarray, new_len: int) -> np.ndarray:
    if len(x) == new_len or new_len <= 0:
        return x[:new_len] if new_len <= len(x) else np.pad(x, (0, new_len - len(x)))
    old_idx = np.linspace(0.0, 1.0, len(x))
    new_idx = np.linspace(0.0, 1.0, new_len)
    return np.interp(new_idx, old_idx, x)


def psola_resynthesize(
    samples: np.ndarray, sr: int,
    src_times: np.ndarray, src_f0: np.ndarray,
    target_times: np.ndarray, target_f0: np.ndarray,
    preserve_formants: bool = True,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> np.ndarray:
    # target_f0 con NaN = no tocar ese tramo, usa el periodo original ahí
    x = np.ascontiguousarray(samples, dtype=np.float64)
    n = len(x)
    duration = n / sr if sr else 0.0
    if duration <= 0 or n == 0:
        return x.astype(np.float32)

    src_f0_smooth = midi_to_hz(median_smooth(hz_to_midi(src_f0)))

    analysis_marks = _generate_marks(duration, src_times, src_f0_smooth)
    synth_marks = _generate_marks(duration, target_times, target_f0, src_times, src_f0_smooth)
    synth_marks = synth_marks[synth_marks < duration]

    out = np.zeros(n, dtype=np.float64)
    norm = np.zeros(n, dtype=np.float64)

    total = max(1, len(synth_marks))
    for i, t_s in enumerate(synth_marks):
        if cancelled and cancelled() and i % 256 == 0:
            raise ShiftCancelled
        j = int(np.argmin(np.abs(analysis_marks - t_s)))
        t_a = float(analysis_marks[j])
        src_period = _instant_period(t_a, src_times, src_f0_smooth)

        half_src = max(int(round(sr * src_period)), 16)
        a_center = int(round(t_a * sr))
        a0, a1 = a_center - half_src, a_center + half_src
        grain = np.zeros(2 * half_src)
        s0, s1 = max(0, a0), min(n, a1)
        if s1 > s0:
            grain[s0 - a0: s1 - a0] = x[s0:s1]

        if preserve_formants:
            half_out = half_src
            placed = grain
        else:
            tgt_period = _instant_period(float(t_s), target_times, target_f0, src_times, src_f0_smooth)
            half_out = max(int(round(sr * tgt_period)), 16)
            placed = _resample_to_length(grain, 2 * half_out)

        window = np.hanning(2 * half_out)
        placed = placed * window

        o_center = int(round(t_s * sr))
        o0, o1 = o_center - half_out, o_center + half_out
        d0, d1 = max(0, o0), min(n, o1)
        if d1 > d0:
            out[d0:d1] += placed[d0 - o0: d1 - o0]
            norm[d0:d1] += window[d0 - o0: d1 - o0]

        if progress and i % 500 == 0:
            progress(i / total)

    safe = norm > 1e-6
    out[safe] /= norm[safe]
    if progress:
        progress(1.0)
    return out.astype(np.float32)
