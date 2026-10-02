from __future__ import annotations

import shutil
from functools import lru_cache

from vocal_ai_studio.core.errors import AppError


@lru_cache(maxsize=1)
def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            "No se encontró FFmpeg, necesario para MP3, M4A y otros formatos.",
            "No está en el PATH y el paquete 'imageio-ffmpeg' no está instalado o no pudo localizar su binario.",
            "Ejecuta: pip install imageio-ffmpeg   (o instala FFmpeg con: winget install Gyan.FFmpeg)",
            cause=exc,
        ) from exc
