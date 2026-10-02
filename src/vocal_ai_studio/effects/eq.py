from __future__ import annotations

import numpy as np
from scipy.signal import sosfilt


def _low_shelf_sos(freq: float, gain_db: float, sr: int) -> np.ndarray:
    if abs(gain_db) < 0.01:
        return np.array([[1, 0, 0, 1, 0, 0]], dtype=np.float64)
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * freq / sr
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    alpha = sin_w0 / 2 * np.sqrt((A + 1 / A) * (1 / 0.707 - 1) + 2)
    b0 = A * ((A + 1) - (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha)
    b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
    b2 = A * ((A + 1) - (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha)
    a0 = (A + 1) + (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha
    a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
    a2 = (A + 1) + (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def _high_shelf_sos(freq: float, gain_db: float, sr: int) -> np.ndarray:
    if abs(gain_db) < 0.01:
        return np.array([[1, 0, 0, 1, 0, 0]], dtype=np.float64)
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * freq / sr
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    alpha = sin_w0 / 2 * np.sqrt((A + 1 / A) * (1 / 0.707 - 1) + 2)
    b0 = A * ((A + 1) + (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha)
    b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha
    a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def _peak_sos(freq: float, gain_db: float, q: float, sr: int) -> np.ndarray:
    if abs(gain_db) < 0.01:
        return np.array([[1, 0, 0, 1, 0, 0]], dtype=np.float64)
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * freq / sr
    alpha = np.sin(w0) / (2 * max(0.1, q))
    b0 = 1 + alpha * A
    b1 = -2 * np.cos(w0)
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha / A
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def apply_eq(samples: np.ndarray, sr: int, bands: list[dict]) -> np.ndarray:
    if not bands:
        return samples
    sos_list = []
    for band in bands:
        t = band.get("type", "peak")
        freq = float(np.clip(band.get("freq", 1000.0), 20.0, sr / 2.0 - 1))
        gain_db = float(band.get("gain_db", 0.0))
        q = float(band.get("q", 1.0))
        if t == "low_shelf":
            sos_list.append(_low_shelf_sos(freq, gain_db, sr))
        elif t == "high_shelf":
            sos_list.append(_high_shelf_sos(freq, gain_db, sr))
        else:
            sos_list.append(_peak_sos(freq, gain_db, q, sr))
    return sosfilt(np.vstack(sos_list), samples).astype(np.float32)
