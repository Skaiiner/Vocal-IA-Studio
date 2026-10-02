from __future__ import annotations

import numpy as np

from vocal_ai_studio.core.errors import AppError

MODEL_NAME = "lengyue233/content-vec-best"
OUTPUT_LAYER = 12  # capa de HuBERT que usa RVC v2 (sin final_proj)


def _require_transformers():
    try:
        import torch
        from transformers import HubertModel
    except ImportError as exc:
        raise AppError(
            "Falta el extractor de contenido vocal (transformers/content-vec).",
            "El paquete 'transformers' no está instalado en el entorno de la aplicación.",
            "Ejecuta: .\\.venv\\Scripts\\python.exe -m pip install transformers",
            cause=exc,
        ) from exc
    return torch, HubertModel


class ContentEncoder:
    # Extrae las características lingüísticas (768-dim) que alimentan al sintetizador RVC.
    def __init__(self, device: str | None = None):
        self.device = device
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        torch, HubertModel = _require_transformers()
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        try:
            model = HubertModel.from_pretrained(MODEL_NAME)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                "No se pudo descargar/cargar el modelo de contenido vocal.",
                f"{type(exc).__name__}: {exc}",
                "Comprueba la conexión a Internet (la primera vez descarga el modelo) y el espacio en disco.",
                cause=exc,
            ) from exc
        model.eval()
        model.to(device)
        self._model = model
        self.device = device
        return model

    def extract(self, samples_16k: np.ndarray) -> np.ndarray:
        """samples_16k: mono float32 a 16kHz. Devuelve (T, 768) a ~50Hz."""
        torch, _ = _require_transformers()
        model = self._load()
        with torch.no_grad():
            wav = torch.from_numpy(np.asarray(samples_16k, dtype=np.float32))
            wav = wav.unsqueeze(0).to(self.device)
            out = model(wav, output_hidden_states=True)
            feats = out.hidden_states[OUTPUT_LAYER][0]
        return feats.cpu().numpy().astype(np.float32)
