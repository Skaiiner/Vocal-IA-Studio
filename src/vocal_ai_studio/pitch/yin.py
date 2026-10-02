from __future__ import annotations

from typing import Callable

import numpy as np

from vocal_ai_studio.core.interfaces import PitchTrack

Progress = Callable[[float], None]
Cancelled = Callable[[], bool]


class AnalysisCancelled(Exception):
    pass


def _difference_function_batch(frames: np.ndarray, tau_max: int) -> np.ndarray:
    n_frames, w = frames.shape
    fft_size = 1 << int(np.ceil(np.log2(2 * w)))
    spectrum = np.fft.rfft(frames, fft_size, axis=1)
    acf = np.fft.irfft(spectrum * np.conj(spectrum), fft_size, axis=1)[:, :tau_max]
    sq = frames * frames
    cumsum = np.concatenate([np.zeros((n_frames, 1)), np.cumsum(sq, axis=1)], axis=1)
    total = cumsum[:, w:w + 1]
    taus = np.arange(tau_max)
    term1 = cumsum[:, w - taus]
    term2 = total - cumsum[:, taus]
    d = term1 + term2 - 2.0 * acf
    return np.maximum(d, 0.0)


def _cmnd_batch(d: np.ndarray) -> np.ndarray:
    n_frames, tau_max = d.shape
    cmnd = np.ones_like(d)
    if tau_max <= 1:
        return cmnd
    running = np.cumsum(d[:, 1:], axis=1)
    taus = np.arange(1, tau_max)
    means = running / taus
    with np.errstate(invalid="ignore", divide="ignore"):
        cmnd[:, 1:] = np.where(means > 1e-12, d[:, 1:] / means, 1.0)
    return cmnd


def _pick_tau_batch(cmnd: np.ndarray, tau_min: int, threshold: float) -> tuple[np.ndarray, np.ndarray]:
    n_frames, tau_max = cmnd.shape
    lo, hi = tau_min, tau_max - 1
    if hi <= lo:
        tau = np.full(n_frames, float(max(tau_min, 1)))
        return tau, np.zeros(n_frames)

    middle, left, right = cmnd[:, lo:hi], cmnd[:, lo - 1:hi - 1], cmnd[:, lo + 1:hi + 1]
    cond = (middle < threshold) & (middle <= left) & (middle <= right)
    has_candidate = cond.any(axis=1)
    first_idx = np.argmax(cond, axis=1)
    fallback_idx = np.argmin(cmnd[:, tau_min:], axis=1)
    found = np.where(has_candidate, lo + first_idx, tau_min + fallback_idx)
    found = np.clip(found, 1, tau_max - 2)

    rows = np.arange(n_frames)
    a, b, c = cmnd[rows, found - 1], cmnd[rows, found], cmnd[rows, found + 1]
    denom = a - 2 * b + c
    with np.errstate(invalid="ignore", divide="ignore"):
        shift = np.where(np.abs(denom) > 1e-12, 0.5 * (a - c) / denom, 0.0)
    shift = np.clip(shift, -1.0, 1.0)
    tau_refined = found.astype(np.float64) + shift
    confidence = 1.0 - np.minimum(b, 1.0)
    return tau_refined, confidence


def yin_pitch_track(
    samples: np.ndarray,
    sr: int,
    fmin: float = 65.0,
    fmax: float = 1046.5,
    frame_length: int = 2048,
    hop_length: int = 512,
    threshold: float = 0.1,
    silence_rms: float = 0.008,
    min_confidence: float = 0.35,
    chunk_frames: int = 1500,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> PitchTrack:
    # NumPy puro (sin Numba/librosa.pyin): evita el bloqueo de DLL de Control de aplicaciones
    # inteligente de Windows
    x = np.ascontiguousarray(samples, dtype=np.float64)
    n = len(x)
    tau_min = max(1, int(sr / fmax))
    tau_max = min(frame_length - 2, int(sr / fmin) + 1)
    if tau_max <= tau_min or n < frame_length:
        return PitchTrack(np.zeros(0), np.zeros(0), np.zeros(0))

    n_frames = 1 + (n - frame_length) // hop_length
    if n_frames <= 0:
        return PitchTrack(np.zeros(0), np.zeros(0), np.zeros(0))

    strides = (x.strides[0] * hop_length, x.strides[0])
    all_frames = np.lib.stride_tricks.as_strided(x, shape=(n_frames, frame_length), strides=strides)

    times = np.empty(n_frames)
    f0 = np.empty(n_frames)
    conf = np.empty(n_frames)

    done = 0
    while done < n_frames:
        if cancelled and cancelled():
            raise AnalysisCancelled
        end = min(done + chunk_frames, n_frames)
        chunk = all_frames[done:end].copy()

        d = _difference_function_batch(chunk, tau_max)
        cmnd = _cmnd_batch(d)
        tau, confidence = _pick_tau_batch(cmnd, tau_min, threshold)
        freq = np.where(tau > 0, sr / tau, 0.0)
        rms = np.sqrt(np.mean(chunk * chunk, axis=1))
        voiced = (confidence >= min_confidence) & (rms >= silence_rms) & (freq >= fmin) & (freq <= fmax)

        idx = np.arange(done, end)
        times[idx] = idx * hop_length / sr
        f0[idx] = np.where(voiced, freq, np.nan)
        conf[idx] = confidence

        done = end
        if progress:
            progress(done / n_frames)

    return PitchTrack(times, f0, conf)
