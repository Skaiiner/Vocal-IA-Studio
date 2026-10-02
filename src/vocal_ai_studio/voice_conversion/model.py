from __future__ import annotations

import logging
from typing import Callable

import numpy as np
from scipy.signal import butter, filtfilt

from vocal_ai_studio.audio.io import resample
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.voice_conversion import pitch_adapter
from vocal_ai_studio.voice_conversion.checkpoint import VCCheckpoint, load_checkpoint
from vocal_ai_studio.voice_conversion.content_encoder import ContentEncoder

log = logging.getLogger(__name__)

Progress = Callable[[float], None]
Cancelled = Callable[[], bool]


class VoiceConversionCancelled(Exception):
    pass


def _require_torch():
    try:
        import torch
    except ImportError as exc:
        raise AppError(
            "Falta PyTorch para la conversión de voz.",
            "El paquete 'torch' no está instalado en el entorno de la aplicación.",
            "Ejecuta: .\\.venv\\Scripts\\python.exe -m pip install torch --index-url "
            "https://download.pytorch.org/whl/cu128",
            cause=exc,
        ) from exc
    return torch


def _highpass(samples: np.ndarray, sr: int, cutoff: float = 48.0) -> np.ndarray:
    if len(samples) <= 15:
        return samples
    b, a = butter(5, cutoff / (sr / 2), btype="high")
    pad = min(len(samples) - 1, 3 * max(len(a), len(b)))
    if pad <= 0:
        return filtfilt(b, a, samples).astype(np.float32)
    padded = np.pad(samples, pad, mode="reflect")
    filtered = filtfilt(b, a, padded)
    return filtered[pad:-pad].astype(np.float32)


def _window_rms(x: np.ndarray, frame_len: int) -> np.ndarray:
    frame_len = max(1, frame_len)
    n_frames = max(1, len(x) // frame_len)
    trimmed = x[: n_frames * frame_len]
    frames = trimmed.reshape(n_frames, frame_len)
    return np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-9)


def _interp_to_length(values: np.ndarray, length: int) -> np.ndarray:
    if len(values) <= 1:
        return np.full(length, values[0] if len(values) else 0.0)
    xp = np.linspace(0.0, 1.0, len(values))
    x = np.linspace(0.0, 1.0, length)
    return np.interp(x, xp, values)


def _match_rms(source: np.ndarray, source_sr: int, target: np.ndarray, target_sr: int, rate: float) -> np.ndarray:
    # rate=1.0 -> se queda con el volumen del propio resultado (sin cambios).
    if rate >= 1.0 or len(target) == 0:
        return target
    rms_src = _interp_to_length(_window_rms(source, max(1, source_sr // 20)), len(target))
    rms_tgt = _interp_to_length(_window_rms(target, max(1, target_sr // 20)), len(target))
    rms_tgt = np.maximum(rms_tgt, 1e-6)
    gain = (rms_src ** (1.0 - rate)) * (rms_tgt ** (rate - 1.0))
    return (target * gain).astype(np.float32)


def _retrieve(feats: np.ndarray, index_path: str | None, index_rate: float) -> np.ndarray:
    if not index_path or index_rate <= 0:
        return feats
    try:
        import faiss
    except ImportError:
        log.warning("faiss no está instalado: se omite el índice de retrieval '%s'.", index_path)
        return feats
    try:
        index = faiss.read_index(index_path)
        big_npy = index.reconstruct_n(0, index.ntotal)
        _, ix = index.search(feats.astype(np.float32), 8)
    except Exception:  # noqa: BLE001
        log.warning("No se pudo usar el índice de retrieval '%s'.", index_path)
        return feats
    weight = np.square(1.0 / np.arange(1, 9))
    weight /= weight.sum()
    retrieved = np.sum(big_npy[ix] * weight[None, :, None], axis=1)
    return (feats * (1 - index_rate) + retrieved * index_rate).astype(np.float32)


class RVCVoiceConversionModel:
    # Conversión de voz (arquitectura RVC v2, MIT): contenido HuBERT + pitch propio + sintetizador NSF.
    name = "RVC v2 (768-dim, NSF)"
    license = "MIT"
    requires_gpu = False

    def __init__(self):
        self.device = "cpu"
        self._content_encoder = ContentEncoder()
        self._checkpoints: dict[str, VCCheckpoint] = {}

    def load(self, device: str) -> None:
        self.device = device
        self._content_encoder.device = device

    def _get_checkpoint(self, model_path: str) -> VCCheckpoint:
        cpt = self._checkpoints.get(model_path)
        if cpt is None:
            cpt = load_checkpoint(model_path, self.device)
            self._checkpoints[model_path] = cpt
        return cpt

    def convert(
        self,
        samples: np.ndarray,
        samplerate: int,
        *,
        model_path: str = "",
        transpose: float = 0.0,
        protect: float = 0.33,
        rms_mix_rate: float = 1.0,
        index_path: str | None = None,
        index_rate: float = 0.0,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
        **_ignored,
    ) -> np.ndarray:
        torch = _require_torch()
        if not model_path:
            raise AppError(
                "Falta el modelo de conversión de voz.",
                "No se indicó ningún archivo .pth.",
                "Selecciona un modelo RVC (v2, con pitch) antes de convertir.",
            )
        cpt = self._get_checkpoint(model_path)
        if cancelled and cancelled():
            raise VoiceConversionCancelled
        if progress:
            progress(0.05)

        mono = np.asarray(samples, dtype=np.float32)
        samples_16k = resample(mono, samplerate, 16000)
        samples_16k = _highpass(samples_16k, 16000)

        f0_hz = pitch_adapter.compute_f0(samples_16k, f0_up_key=transpose)
        f0_coarse = pitch_adapter.f0_to_coarse(f0_hz.copy())
        if cancelled and cancelled():
            raise VoiceConversionCancelled
        if progress:
            progress(0.3)

        feats0 = self._content_encoder.extract(samples_16k)
        feats0 = np.repeat(feats0, 2, axis=0)  # ~50Hz -> ~100Hz, igual que el F0

        n = min(len(feats0), len(f0_hz))
        feats0 = feats0[:n]
        f0_hz = f0_hz[:n]
        f0_coarse = f0_coarse[:n]
        if progress:
            progress(0.5)
        if cancelled and cancelled():
            raise VoiceConversionCancelled

        feats = _retrieve(feats0, index_path, index_rate)
        if protect < 1.0:
            blend = np.where(f0_hz > 0, 1.0, protect)[:, None]
            feats = feats * blend + feats0 * (1.0 - blend)

        device = self.device
        phone = torch.from_numpy(feats.astype(np.float32)).unsqueeze(0).to(device)
        phone_lengths = torch.tensor([feats.shape[0]], dtype=torch.long, device=device)
        pitch = torch.from_numpy(f0_coarse.astype(np.int64)).unsqueeze(0).to(device)
        nsff0 = torch.from_numpy(f0_hz.astype(np.float32)).unsqueeze(0).to(device)
        sid = torch.zeros(1, dtype=torch.long, device=device)

        try:
            out, *_rest = cpt.synthesizer.infer(phone, phone_lengths, pitch, nsff0, sid)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                "Falló la conversión de voz.",
                f"{type(exc).__name__}: {exc}",
                "Comprueba que el modelo sea compatible (RVC v2, 768-dim, con pitch) y la memoria disponible.",
                cause=exc,
            ) from exc
        if progress:
            progress(0.9)

        audio_out = out[0, 0].detach().cpu().numpy().astype(np.float32)
        audio_out = _match_rms(samples_16k, 16000, audio_out, cpt.target_sr, rms_mix_rate)
        result = resample(audio_out, cpt.target_sr, samplerate)
        if progress:
            progress(1.0)
        return result
