from __future__ import annotations

import numpy as np
from scipy.signal import windows


def shift_formants(
    samples: np.ndarray,
    sr: int,
    semitones: float,
    hop_ms: float = 5.0,
    win_ms: float = 25.0,
) -> np.ndarray:
    # rango útil: -6..+6 semitonos, más allá se nota el artefacto
    if abs(semitones) < 0.01:
        return samples

    factor = 2.0 ** (semitones / 12.0)
    hop = max(1, int(hop_ms * sr / 1000.0))
    win_size = max(hop * 2, int(win_ms * sr / 1000.0))
    n_fft = 1
    while n_fft < win_size:
        n_fft <<= 1

    window = windows.hann(n_fft, sym=False).astype(np.float64)
    x = samples.astype(np.float64)
    pad = n_fft
    x = np.concatenate([np.zeros(pad), x, np.zeros(pad)])
    n = len(x)
    out = np.zeros(n)
    norm = np.zeros(n)

    freqs = np.arange(n_fft // 2 + 1, dtype=np.float64)
    src_freqs = np.clip(freqs * factor, 0, n_fft // 2)

    positions = np.arange(0, n - n_fft + 1, hop)
    for pos in positions:
        frame = x[pos:pos + n_fft] * window
        spec = np.fft.rfft(frame)
        mag = np.abs(spec)
        phase = np.angle(spec)

        mag_new = np.interp(freqs, src_freqs, mag)
        spec_new = mag_new * np.exp(1j * phase)

        frame_out = np.fft.irfft(spec_new)
        out[pos:pos + n_fft] += frame_out * window
        norm[pos:pos + n_fft] += window ** 2

    norm = np.maximum(norm, 1e-8)
    out /= norm
    out = out[pad:pad + len(samples)]
    in_rms = np.sqrt(np.mean(samples ** 2) + 1e-12)
    out_rms = np.sqrt(np.mean(out ** 2) + 1e-12)
    if out_rms > 1e-8:
        out *= in_rms / out_rms
    return out.astype(np.float32)
