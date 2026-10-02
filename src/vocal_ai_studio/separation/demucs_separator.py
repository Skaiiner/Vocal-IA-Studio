from __future__ import annotations

import logging
from typing import Callable

import numpy as np

from vocal_ai_studio.core.errors import AppError

log = logging.getLogger(__name__)

Progress = Callable[[float], None]
Cancelled = Callable[[], bool]

VOCAL_STEMS = ("vocals",)


class SeparationCancelled(Exception):
    pass


def _require_demucs():
    try:
        import torch
        from demucs.api import Separator
    except ImportError as exc:
        raise AppError(
            "Falta el separador de voz/instrumental (Demucs).",
            "El paquete 'demucs' (y PyTorch) no está instalado en el entorno de la aplicación.",
            "Ejecuta: .\\.venv\\Scripts\\python.exe -m pip install torch demucs --index-url "
            "https://download.pytorch.org/whl/cu128",
            cause=exc,
        ) from exc
    return torch, Separator


class DemucsSeparator:
    name = "Demucs (htdemucs)"

    def __init__(self, model: str = "htdemucs", device: str | None = None):
        self.model = model
        self.device = device
        self._separator = None

    def _load(self):
        if self._separator is not None:
            return self._separator
        torch, Separator = _require_demucs()
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        try:
            self._separator = Separator(model=self.model, device=device, progress=False)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                "No se pudo cargar el modelo de separación Demucs.",
                f"{type(exc).__name__}: {exc}",
                "Comprueba la conexión a Internet (la primera vez descarga el modelo) y el espacio en disco.",
                cause=exc,
            ) from exc
        return self._separator

    def separate(
        self,
        samples: np.ndarray,
        samplerate: int,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> dict[str, np.ndarray]:
        torch, _ = _require_demucs()
        separator = self._load()
        if cancelled and cancelled():
            raise SeparationCancelled
        if progress:
            progress(0.05)

        mono = np.asarray(samples, dtype=np.float32)
        if mono.ndim == 1:
            stereo = np.stack([mono, mono], axis=0)
        else:
            stereo = mono.T if mono.shape[0] != 2 else mono
        wav = torch.from_numpy(np.ascontiguousarray(stereo, dtype=np.float32))

        try:
            _, stems = separator.separate_tensor(wav, sr=samplerate)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                "Falló la separación de voz/instrumental.",
                f"{type(exc).__name__}: {exc}",
                "Prueba con un archivo más corto o comprueba la memoria de la GPU/CPU disponible.",
                cause=exc,
            ) from exc
        if cancelled and cancelled():
            raise SeparationCancelled
        if progress:
            progress(0.9)

        vocals = None
        instrumental = None
        for stem_name, tensor in stems.items():
            arr = tensor.cpu().numpy().mean(axis=0)  # mezcla a mono
            if stem_name in VOCAL_STEMS:
                vocals = arr if vocals is None else vocals + arr
            else:
                instrumental = arr if instrumental is None else instrumental + arr

        if progress:
            progress(1.0)
        return {
            "vocals": vocals.astype(np.float32),
            "instrumental": instrumental.astype(np.float32),
        }
