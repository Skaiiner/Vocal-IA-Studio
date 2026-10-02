from __future__ import annotations

import logging
from dataclasses import dataclass
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from vocal_ai_studio.audio.convert import decode_with_ffmpeg, encode_with_ffmpeg
from vocal_ai_studio.core.errors import AppError

log = logging.getLogger(__name__)

SF_READ_EXT = {".wav", ".flac", ".ogg", ".aif", ".aiff"}
IMPORT_EXTENSIONS = (".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aif", ".aiff", ".mp4", ".webm", ".mkv")
EXPORT_FORMATS = ("wav", "flac", "mp3")


@dataclass
class AudioData:
    samples: np.ndarray  # (frames, channels) float32
    samplerate: int

    def __post_init__(self) -> None:
        s = np.asarray(self.samples, dtype=np.float32)
        if s.ndim == 1:
            s = s[:, None]
        self.samples = s

    @property
    def frames(self) -> int:
        return self.samples.shape[0]

    @property
    def channels(self) -> int:
        return self.samples.shape[1]

    @property
    def duration(self) -> float:
        return self.frames / self.samplerate if self.samplerate else 0.0

    def to_mono(self) -> np.ndarray:
        return self.samples.mean(axis=1) if self.channels > 1 else self.samples[:, 0]

    def conform(self, channels: int) -> "AudioData":
        return AudioData(conform_channels(self.samples, channels), self.samplerate)


def conform_channels(samples: np.ndarray, channels: int) -> np.ndarray:
    cur = samples.shape[1]
    if cur == channels:
        return samples
    if channels == 1:
        return samples.mean(axis=1, keepdims=True).astype(np.float32)
    if cur == 1:
        return np.repeat(samples, channels, axis=1)
    if cur > channels:
        return samples[:, :channels].copy()
    pad = np.repeat(samples[:, -1:], channels - cur, axis=1)
    return np.concatenate([samples, pad], axis=1)


def resample(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or samples.shape[0] == 0:
        return samples
    g = gcd(src_sr, dst_sr)
    out = resample_poly(samples, dst_sr // g, src_sr // g, axis=0)
    return out.astype(np.float32)


def load_audio(path: str | Path, samplerate: int | None = None, channels: int | None = None) -> AudioData:
    path = Path(path)
    if not path.exists():
        raise AppError(
            f"No existe el archivo '{path}'.",
            "Fue movido o borrado.",
            "Selecciona el archivo de nuevo.",
        )
    data: AudioData | None = None
    if path.suffix.lower() in SF_READ_EXT:
        try:
            x, sr = sf.read(str(path), dtype="float32", always_2d=True)
            data = AudioData(x, sr)
        except Exception as exc:  # noqa: BLE001
            log.info("soundfile no pudo leer %s (%s); se usa FFmpeg.", path, exc)
    if data is None:
        sr = samplerate or 44100
        ch = channels or 2
        return AudioData(decode_with_ffmpeg(path, sr, ch), sr)
    if channels is not None:
        data = data.conform(channels)
    if samplerate is not None and data.samplerate != samplerate:
        data = AudioData(resample(data.samples, data.samplerate, samplerate), samplerate)
    return data


def save_audio(path: str | Path, audio: AudioData, fmt: str | None = None) -> Path:
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt not in EXPORT_FORMATS + ("ogg",):
        raise AppError(
            f"Formato de exportación no soportado: '{fmt}'.",
            "Solo se admiten WAV, FLAC y MP3.",
            "Elige uno de esos formatos.",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.clip(audio.samples, -1.0, 1.0)
    try:
        if fmt == "mp3":
            encode_with_ffmpeg(samples, audio.samplerate, path, ["-c:a", "libmp3lame", "-q:a", "2"])
        elif fmt == "ogg":
            sf.write(str(path), samples, audio.samplerate, format="OGG", subtype="VORBIS")
        else:
            sf.write(str(path), samples, audio.samplerate, format=fmt.upper(), subtype="PCM_24")
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            f"No se pudo guardar '{path.name}'.",
            f"{type(exc).__name__}: {exc}",
            "Comprueba que la carpeta existe, tienes permiso de escritura y hay espacio en disco.",
            cause=exc,
        ) from exc
    return path
