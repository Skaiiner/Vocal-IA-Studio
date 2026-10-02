from __future__ import annotations

import numpy as np

_COMB_DELAYS_44 = [1557, 1617, 1491, 1422]
_ALLPASS_DELAYS_44 = [225, 341]
_COMB_DECAYS = [0.805, 0.827, 0.783, 0.764]
_ALLPASS_GAIN = 0.7


def _comb_filter(x: np.ndarray, delay: int, decay: float) -> np.ndarray:
    out = np.zeros_like(x)
    buf = np.zeros(delay)
    for i in range(len(x)):
        idx = i % delay
        out[i] = x[i] + buf[idx] * decay
        buf[idx] = out[i]
    return out


def _comb_filter_fast(x: np.ndarray, delay: int, decay: float) -> np.ndarray:
    n = len(x)
    out = np.zeros(n)
    buf = np.zeros(delay, dtype=np.float64)
    pos = 0
    i = 0
    while i < n:
        end = min(i + delay, n)
        chunk_len = end - i
        chunk = x[i:end].astype(np.float64)
        fb = np.concatenate([buf[pos:], buf[:pos]])[:chunk_len]
        out_chunk = chunk + fb * decay
        for j in range(chunk_len):
            buf[(pos + j) % delay] = out_chunk[j]
        out[i:end] = out_chunk
        pos = (pos + chunk_len) % delay
        i = end
    return out


def _allpass_filter(x: np.ndarray, delay: int, gain: float) -> np.ndarray:
    out = np.zeros(len(x))
    buf = np.zeros(delay)
    pos = 0
    for i in range(len(x)):
        delayed = buf[pos]
        v = x[i] + gain * delayed
        out[i] = -gain * v + delayed
        buf[pos] = v
        pos = (pos + 1) % delay
    return out


def apply_reverb(
    samples: np.ndarray,
    sr: int,
    room_size: float = 0.3,
    wet: float = 0.15,
) -> np.ndarray:
    if wet <= 0.001:
        return samples
    wet = float(np.clip(wet, 0.0, 1.0))
    room = float(np.clip(room_size, 0.0, 1.0))
    scale = sr / 44100.0
    comb_delays = [max(2, int(d * scale)) for d in _COMB_DELAYS_44]
    allpass_delays = [max(2, int(d * scale)) for d in _ALLPASS_DELAYS_44]
    decays = [d * (0.6 + 0.35 * room) for d in _COMB_DECAYS]

    x = samples.astype(np.float64)
    wet_sig = np.zeros_like(x)
    for delay, decay in zip(comb_delays, decays):
        wet_sig += _comb_filter_fast(x, delay, decay)
    wet_sig /= len(comb_delays)
    for delay in allpass_delays:
        wet_sig = _allpass_filter(wet_sig, delay, _ALLPASS_GAIN)

    peak = np.max(np.abs(wet_sig)) + 1e-9
    if peak > 1.0:
        wet_sig /= peak
    return (x * (1 - wet) + wet_sig * wet).astype(np.float32)


def apply_delay(
    samples: np.ndarray,
    sr: int,
    time_ms: float = 250.0,
    feedback: float = 0.3,
    wet: float = 0.2,
) -> np.ndarray:
    if wet <= 0.001:
        return samples
    delay_samples = int(time_ms * sr / 1000.0)
    if delay_samples <= 0:
        return samples
    wet = float(np.clip(wet, 0.0, 1.0))
    feedback = float(np.clip(feedback, 0.0, 0.95))
    x = samples.astype(np.float64)
    out = np.zeros(len(x) + delay_samples)
    out[:len(x)] += x
    echo = x.copy()
    while np.max(np.abs(echo)) > 1e-6:
        echo = echo * feedback
        tmp = np.zeros(len(x) + delay_samples)
        tmp[delay_samples:delay_samples + len(x)] += echo
        out += tmp
        if len(out) < len(tmp):
            break
    out = out[:len(x)]
    peak = np.max(np.abs(out)) + 1e-9
    if peak > 1.0:
        out /= peak
    return (x * (1 - wet) + out * wet).astype(np.float32)
