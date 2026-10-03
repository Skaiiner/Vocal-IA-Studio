from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float

    @property
    def label(self) -> str:
        return f"{self.name} [{self.hostapi}]"


@runtime_checkable
class AudioStream(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...

    @property
    def latency(self) -> float: ...


class AudioBackend(Protocol):
    def input_devices(self) -> list[DeviceInfo]: ...
    def output_devices(self) -> list[DeviceInfo]: ...

    def open_output(
        self, device: str, samplerate: int, channels: int, callback: Callable[[np.ndarray], None]
    ) -> AudioStream:
        ...

    def open_input(
        self, device: str, samplerate: int, channels: int, callback: Callable[[np.ndarray], None]
    ) -> AudioStream:
        ...

    def open_duplex(
        self, input_device: str, output_device: str, samplerate: int,
        input_channels: int, output_channels: int, blocksize: int,
        callback: Callable[[np.ndarray, np.ndarray], None],
    ) -> AudioStream:
        ...


# --- Ganchos para fases futuras (solo contratos; sin implementación en la Fase 1) ---

@dataclass
class PitchTrack:
    times: np.ndarray        # segundos
    f0: np.ndarray           # Hz (nan = sin voz)
    confidence: np.ndarray


class PitchDetector(Protocol):
    name: str

    def detect(self, samples: np.ndarray, samplerate: int) -> PitchTrack: ...


class SourceSeparator(Protocol):
    name: str

    def separate(
        self, samples: np.ndarray, samplerate: int,
        progress: Callable[[float], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, np.ndarray]: ...


class VoiceConversionModel(Protocol):
    name: str
    license: str
    requires_gpu: bool

    def load(self, device: str) -> None: ...
    def convert(self, samples: np.ndarray, samplerate: int, **params) -> np.ndarray: ...


class EffectProcessor(Protocol):
    name: str

    def process(self, samples: np.ndarray, samplerate: int) -> np.ndarray: ...


class AIProvider(Protocol):
    name: str
    is_local: bool

    def is_available(self) -> bool: ...
    def complete(self, prompt: str, **options) -> str: ...
