from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

from vocal_ai_studio.audio.ffmpeg_locator import find_ffmpeg
from vocal_ai_studio.core.errors import AppError

log = logging.getLogger(__name__)
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def decode_with_ffmpeg(path: Path, samplerate: int, channels: int) -> np.ndarray:
    cmd = [find_ffmpeg(), "-v", "error", "-nostdin", "-i", str(path), "-vn",
           "-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(samplerate), "-ac", str(channels), "-"]
    proc = subprocess.run(cmd, capture_output=True, creationflags=_NOWIN)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["sin detalle"]
        raise AppError(
            f"No se pudo leer el audio '{Path(path).name}'.",
            f"El archivo está dañado, protegido (DRM) o no es un formato de audio/vídeo válido. FFmpeg dijo: {detail[0]}",
            "Prueba con otro archivo o conviértelo a WAV/MP3. La app no puede abrir archivos con DRM.",
        )
    data = np.frombuffer(proc.stdout, dtype=np.float32)
    if data.size == 0:
        raise AppError(
            f"'{Path(path).name}' no contiene audio.",
            "El archivo no tiene pista de audio o está vacío.",
            "Comprueba que el archivo suena en otro reproductor.",
        )
    return data.reshape(-1, channels).copy()


def encode_with_ffmpeg(samples: np.ndarray, samplerate: int, dest: Path, codec_args: list[str]) -> None:
    channels = samples.shape[1]
    cmd = [find_ffmpeg(), "-v", "error", "-y", "-f", "f32le", "-ar", str(samplerate), "-ac", str(channels),
           "-i", "-", *codec_args, str(dest)]
    data = np.ascontiguousarray(samples, dtype=np.float32).tobytes()
    proc = subprocess.run(cmd, input=data, capture_output=True, creationflags=_NOWIN)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["sin detalle"]
        raise AppError(
            f"No se pudo exportar '{Path(dest).name}'.",
            f"FFmpeg falló al codificar: {detail[0]}",
            "Comprueba que puedes escribir en la carpeta de destino y que el archivo no está abierto en otro programa.",
        )
