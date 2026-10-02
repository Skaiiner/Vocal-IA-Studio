# NumPy puro: nada de librosa.beat/chroma, dependen de Numba (bloqueado en algunos Windows).

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vocal_ai_studio.pitch.notes import NOTE_NAMES, hz_to_midi

# Perfiles de Krumhansl-Kessler (Krumhansl & Kessler, 1982): pesos numéricos de estabilidad tonal
# percibida para cada uno de los 12 semitonos relativos a la tónica. Son datos publicados en
# investigación académica de teoría musical, de uso estándar en el análisis de audio (los usan,
# por ejemplo, librosa y music21); no son una obra con derechos de autor, son una tabla de números.
_KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

_SOLFEGE = {"C": "Do", "C#": "Do#", "D": "Re", "D#": "Re#", "E": "Mi", "F": "Fa", "F#": "Fa#",
            "G": "Sol", "G#": "Sol#", "A": "La", "A#": "La#", "B": "Si"}


@dataclass
class SongAnalysis:
    bpm: float | None
    key_root: str
    key_is_major: bool
    key_confidence: float
    duration: float

    @property
    def key_label(self) -> str:
        return f"{_SOLFEGE.get(self.key_root, self.key_root)} {'mayor' if self.key_is_major else 'menor'}"

    @property
    def bpm_label(self) -> str:
        return f"{self.bpm:.0f} BPM" if self.bpm else "No detectado"


def _frame_view(x: np.ndarray, frame_length: int, hop_length: int) -> np.ndarray:
    n = len(x)
    n_frames = 1 + (n - frame_length) // hop_length
    if n_frames <= 0:
        return np.zeros((0, frame_length))
    strides = (x.strides[0] * hop_length, x.strides[0])
    return np.lib.stride_tricks.as_strided(x, shape=(n_frames, frame_length), strides=strides)


def _autocorrelate_fft(x: np.ndarray) -> np.ndarray:
    n = len(x)
    size = 1 << int(np.ceil(np.log2(2 * n))) if n > 0 else 1
    spectrum = np.fft.rfft(x, size)
    return np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]


def estimate_bpm(samples: np.ndarray, sr: int) -> float | None:
    # envolvente de energía -> onsets -> periodo dominante por autocorrelación
    x = np.ascontiguousarray(samples, dtype=np.float64)
    hop, frame = 512, 1024
    if len(x) < frame * 8:
        return None
    frames = _frame_view(x, frame, hop)
    if frames.shape[0] < 8:
        return None
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    onset = np.maximum(np.diff(rms, prepend=rms[0]), 0.0)
    onset = onset - onset.mean()
    if np.allclose(onset, 0.0):
        return None

    fps = sr / hop
    min_lag = max(1, int(fps * 60 / 200))   # 200 BPM
    max_lag = min(len(onset) - 1, int(fps * 60 / 50))  # 50 BPM
    if max_lag <= min_lag:
        return None
    ac = _autocorrelate_fft(onset)
    segment = ac[min_lag:max_lag]
    if segment.size == 0 or not np.any(segment > 0):
        return None
    best_lag = min_lag + int(np.argmax(segment))
    return float(60.0 * fps / best_lag)


def estimate_key(samples: np.ndarray, sr: int) -> tuple[str, bool, float]:
    # cromagrama medio correlacionado con los 24 perfiles Krumhansl-Kessler
    x = np.ascontiguousarray(samples, dtype=np.float64)
    frame_length, hop_length = 4096, 1024
    frames = _frame_view(x, frame_length, hop_length)
    if frames.shape[0] == 0:
        return "C", True, 0.0

    window = np.hanning(frame_length)
    spec = np.abs(np.fft.rfft(frames * window, axis=1))
    freqs = np.fft.rfftfreq(frame_length, 1 / sr)
    valid = freqs > 20.0
    pitch_class = np.full(freqs.shape, -1, dtype=int)
    pitch_class[valid] = np.mod(np.round(hz_to_midi(freqs[valid])), 12).astype(int)

    mean_spec = spec.mean(axis=0)
    chroma = np.array([mean_spec[pitch_class == pc].sum() for pc in range(12)])
    if chroma.sum() <= 0:
        return "C", True, 0.0
    chroma = chroma / chroma.sum()

    best_corr, best_root, best_major = -2.0, "C", True
    for root in range(12):
        corr_major = np.corrcoef(chroma, np.roll(_KK_MAJOR, root))[0, 1]
        corr_minor = np.corrcoef(chroma, np.roll(_KK_MINOR, root))[0, 1]
        if corr_major > best_corr:
            best_corr, best_root, best_major = corr_major, NOTE_NAMES[root], True
        if corr_minor > best_corr:
            best_corr, best_root, best_major = corr_minor, NOTE_NAMES[root], False
    confidence = float(np.clip((best_corr + 1) / 2, 0.0, 1.0))
    return best_root, best_major, confidence


def analyze_song(samples: np.ndarray, sr: int) -> SongAnalysis:
    bpm = estimate_bpm(samples, sr)
    root, is_major, confidence = estimate_key(samples, sr)
    return SongAnalysis(bpm, root, is_major, confidence, duration=len(samples) / sr if sr else 0.0)


def to_dict(analysis: SongAnalysis) -> dict:
    return {
        "bpm": analysis.bpm, "key_root": analysis.key_root, "key_is_major": analysis.key_is_major,
        "key_confidence": analysis.key_confidence, "duration": analysis.duration,
    }


def from_dict(data: dict) -> SongAnalysis:
    return SongAnalysis(**data)
