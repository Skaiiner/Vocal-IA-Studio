from __future__ import annotations

import numpy as np

from vocal_ai_studio.pitch.yin import yin_pitch_track

HOP_LENGTH = 160  # 10 ms a 16kHz -> 100Hz, igual que el frame rate de F0 de RVC
F0_MIN = 50.0
F0_MAX = 1100.0
_F0_MEL_MIN = 1127.0 * np.log(1.0 + F0_MIN / 700.0)
_F0_MEL_MAX = 1127.0 * np.log(1.0 + F0_MAX / 700.0)


def compute_f0(samples_16k: np.ndarray, f0_up_key: float = 0.0) -> np.ndarray:
    """F0 en Hz a 100Hz (hop=160 @ 16kHz), 0.0 en tramos sin voz."""
    track = yin_pitch_track(
        samples_16k, 16000,
        fmin=F0_MIN, fmax=F0_MAX,
        frame_length=2048, hop_length=HOP_LENGTH,
    )
    f0 = np.nan_to_num(track.f0, nan=0.0).astype(np.float64)
    if f0_up_key:
        f0 *= 2.0 ** (f0_up_key / 12.0)
    return f0


def f0_to_coarse(f0: np.ndarray) -> np.ndarray:
    """Cuantiza F0 (Hz) a bins [1, 255] en escala mel, igual que el encoder de pitch de RVC."""
    f0_mel = 1127.0 * np.log(1.0 + f0 / 700.0)
    voiced = f0_mel > 0
    f0_mel[voiced] = (f0_mel[voiced] - _F0_MEL_MIN) * 254.0 / (_F0_MEL_MAX - _F0_MEL_MIN) + 1.0
    f0_mel[f0_mel <= 1] = 1
    f0_mel[f0_mel > 255] = 255
    return np.rint(f0_mel).astype(np.int64)
