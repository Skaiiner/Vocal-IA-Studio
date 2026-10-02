from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vocal_ai_studio.core.errors import AppError


@dataclass
class VCCheckpoint:
    synthesizer: object
    target_sr: int
    speaker_dim: int


def load_checkpoint(path: str | Path, device: str) -> VCCheckpoint:
    import torch

    from vocal_ai_studio.voice_conversion.synthesizer import Synthesizer

    path = Path(path)
    try:
        cpt = torch.load(path, map_location="cpu", weights_only=False)
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            "No se pudo leer el modelo de conversión de voz (.pth).",
            f"{type(exc).__name__}: {exc}",
            "Comprueba que el archivo no esté dañado y que sea un modelo RVC compatible.",
            cause=exc,
        ) from exc

    version = cpt.get("version", "v1")
    has_f0 = bool(cpt.get("f0", 1))
    if version != "v2" or not has_f0:
        raise AppError(
            "Este modelo de conversión de voz no es compatible.",
            f"version={version!r}, f0={has_f0!r}: solo se admiten modelos RVC v2 con detección de tono (f0=1).",
            "Usa un modelo entrenado como RVC v2 con pitch activado.",
        )

    weight = cpt["weight"]
    config = list(cpt["config"])
    speaker_dim = weight["emb_g.weight"].shape[0]
    config[-3] = speaker_dim

    synth = Synthesizer(*config, is_half=False)
    synth.load_state_dict(weight, strict=False)
    synth.eval()
    synth.to(device)

    return VCCheckpoint(synthesizer=synth, target_sr=int(config[-1]), speaker_dim=speaker_dim)
