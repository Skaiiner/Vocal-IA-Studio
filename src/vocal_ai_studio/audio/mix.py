from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vocal_ai_studio.audio.io import AudioData, conform_channels


@dataclass
class MixTrack:
    audio: AudioData
    gain: float = 1.0
    offset_sec: float = 0.0


def mix_tracks(tracks: list[MixTrack], samplerate: int, channels: int = 2, normalize_if_clipping: bool = True) -> AudioData:
    tracks = [t for t in tracks if t.audio is not None]
    if not tracks:
        return AudioData(np.zeros((0, channels), np.float32), samplerate)
    for t in tracks:
        if t.audio.samplerate != samplerate:
            raise ValueError("Las pistas deben tener la misma frecuencia de muestreo antes de mezclar.")
    ends = [int(round(t.offset_sec * samplerate)) + t.audio.frames for t in tracks]
    out = np.zeros((max(ends), channels), np.float32)
    for t in tracks:
        start = max(0, int(round(t.offset_sec * samplerate)))
        x = conform_channels(t.audio.samples, channels) * np.float32(t.gain)
        out[start:start + x.shape[0]] += x[: out.shape[0] - start]
    if normalize_if_clipping:
        peak = float(np.max(np.abs(out))) if out.size else 0.0
        if peak > 1.0:
            out /= peak
    return AudioData(out, samplerate)
