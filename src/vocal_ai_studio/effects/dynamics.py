from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt


def _db(x: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(x, 1e-9))


def _linear(db: np.ndarray) -> np.ndarray:
    return 10.0 ** (db / 20.0)


def apply_compressor(
    samples: np.ndarray,
    sr: int,
    threshold_db: float = -18.0,
    ratio: float = 3.0,
    attack_ms: float = 5.0,
    release_ms: float = 50.0,
    makeup_db: float = 0.0,
) -> np.ndarray:
    frame = max(1, int(sr * 0.001))
    n_frames = max(1, len(samples) // frame)
    rms = np.zeros(n_frames)
    for i in range(n_frames):
        chunk = samples[i * frame:(i + 1) * frame]
        rms[i] = np.sqrt(np.mean(chunk ** 2) + 1e-12)

    rms_db = _db(rms)
    gr_db = np.where(
        rms_db > threshold_db,
        (rms_db - threshold_db) * (1.0 - 1.0 / max(1.0, ratio)),
        0.0,
    )

    attack_frames = max(1, int(attack_ms * sr / (1000 * frame)))
    release_frames = max(1, int(release_ms * sr / (1000 * frame)))
    smoothed = np.zeros_like(gr_db)
    prev = 0.0
    for i in range(n_frames):
        target = gr_db[i]
        alpha = 1.0 - np.exp(-1.0 / (attack_frames if target > prev else release_frames))
        prev = prev + alpha * (target - prev)
        smoothed[i] = prev

    gain = np.repeat(_linear(-smoothed), frame)[:len(samples)]
    if len(gain) < len(samples):
        gain = np.concatenate([gain, np.ones(len(samples) - len(gain))])
    return (samples * gain * _linear(np.array([makeup_db]))[0]).astype(np.float32)


def apply_deesser(
    samples: np.ndarray,
    sr: int,
    threshold_db: float = -20.0,
    freq_hz: float = 7000.0,
    bandwidth: float = 3000.0,
) -> np.ndarray:
    low = max(20.0, freq_hz - bandwidth / 2.0)
    high = min(sr / 2.0 - 1.0, freq_hz + bandwidth / 2.0)
    if low >= high:
        return samples

    sos_bp = butter(2, [low / (sr / 2.0), high / (sr / 2.0)], btype="band", output="sos")
    detect = sosfilt(sos_bp, samples.astype(np.float64))

    frame = max(1, int(sr * 0.005))
    n_frames = max(1, len(samples) // frame)
    gain = np.ones(len(samples), dtype=np.float64)
    for i in range(n_frames):
        sl = slice(i * frame, (i + 1) * frame)
        rms_db = float(_db(np.sqrt(np.mean(detect[sl] ** 2) + 1e-12)))
        if rms_db > threshold_db:
            gain[sl] = _linear(np.array([-(rms_db - threshold_db) * 0.5]))[0]

    sos_hp = butter(1, low / (sr / 2.0), btype="high", output="sos")
    sos_lp = butter(1, high / (sr / 2.0), btype="low", output="sos")
    return (sosfilt(sos_lp, samples.astype(np.float64)) +
            sosfilt(sos_hp, samples.astype(np.float64)) * gain).astype(np.float32)
