from __future__ import annotations

import importlib.util
import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class HardwareInfo:
    os: str = ""
    cpu: str = ""
    cpu_cores: int = 0
    ram_gb: float = 0.0
    gpu_name: str = ""
    gpu_vram_gb: float = 0.0
    has_nvidia: bool = False
    torch_installed: bool = False
    cuda_available: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def recommended_device(self) -> str:
        return "cuda" if (self.has_nvidia and self.cuda_available) else "cpu"

    def summary(self) -> str:
        gpu = f"{self.gpu_name} ({self.gpu_vram_gb:.0f} GB VRAM)" if self.has_nvidia else "Sin GPU NVIDIA (se usará CPU)"
        return (
            f"Sistema: {self.os}\nCPU: {self.cpu} ({self.cpu_cores} núcleos)\nRAM: {self.ram_gb:.1f} GB\n"
            f"GPU: {gpu}\nDispositivo de IA recomendado: {self.recommended_device}"
        )


def detect_hardware() -> HardwareInfo:
    info = HardwareInfo(os=f"{platform.system()} {platform.release()}", cpu=platform.processor() or platform.machine())
    try:
        import psutil

        info.cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 0
        info.ram_gb = psutil.virtual_memory().total / 1024**3
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo leer CPU/RAM: %s", exc)

    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip().splitlines()
            if out:
                name, _, mem = out[0].partition(",")
                info.gpu_name = name.strip()
                info.gpu_vram_gb = float(mem.strip()) / 1024
                info.has_nvidia = True
        except Exception as exc:  # noqa: BLE001
            info.notes.append(f"nvidia-smi falló: {exc}")

    info.torch_installed = importlib.util.find_spec("torch") is not None
    if info.torch_installed:
        try:
            import torch

            info.cuda_available = bool(torch.cuda.is_available())
        except Exception as exc:  # noqa: BLE001
            info.notes.append(f"No se pudo consultar CUDA en torch: {exc}")
    return info
