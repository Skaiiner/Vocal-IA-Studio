from __future__ import annotations

import logging
import time

import numpy as np

from vocal_ai_studio.core.errors import explain_exception
from vocal_ai_studio.core.interfaces import AudioBackend, AudioStream
from vocal_ai_studio.effects.chain import VoiceLabSettings
from vocal_ai_studio.realtime.streaming_effects import StreamingChain

log = logging.getLogger(__name__)

BLOCKSIZE = 512


def detect_virtual_devices(backend: AudioBackend) -> list[str]:
    keywords = ("cable", "voicemeeter")
    found = []
    for dev in backend.output_devices():
        low = dev.name.lower()
        if any(k in low for k in keywords):
            found.append(dev.label)
    return found


class LiveVoiceEngine:
    def __init__(self, backend: AudioBackend, samplerate: int = 44100,
                 input_device: str = "", output_device: str = ""):
        self.backend = backend
        self.samplerate = samplerate
        self.input_device = input_device
        self.output_device = output_device
        self.settings = VoiceLabSettings()
        self.bypass = False
        self.dry_wet = 1.0  # 0 = solo voz seca, 1 = solo procesada
        self._stream: AudioStream | None = None
        self._chain = StreamingChain(samplerate)
        self._input_level = 0.0
        self._output_level = 0.0
        self._cpu_usage = 0.0
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def input_level(self) -> float:
        return self._input_level

    @property
    def output_level(self) -> float:
        return self._output_level

    @property
    def cpu_usage(self) -> float:
        return self._cpu_usage

    @property
    def latency(self) -> float:
        return self._stream.latency if self._stream is not None else 0.0

    def set_devices(self, input_device: str, output_device: str) -> None:
        if (input_device, output_device) == (self.input_device, self.output_device):
            return
        self.input_device = input_device
        self.output_device = output_device
        if self._running:
            self.stop()
            self.start()

    def update_settings(self, settings: VoiceLabSettings) -> None:
        self.settings = settings

    def set_bypass(self, bypass: bool) -> None:
        self.bypass = bool(bypass)

    def set_dry_wet(self, wet: float) -> None:
        self.dry_wet = float(np.clip(wet, 0.0, 1.0))

    # --- ciclo de vida ---
    def start(self) -> None:
        if self._running:
            return
        self._chain = StreamingChain(self.samplerate)
        try:
            stream = self.backend.open_duplex(
                self.input_device, self.output_device, self.samplerate,
                1, 1, BLOCKSIZE, self._callback,
            )
        except Exception as exc:  # noqa: BLE001
            raise explain_exception(exc, "No se pudo iniciar la voz en vivo") from exc
        stream.start()
        self._stream = stream
        self._running = True

    def stop(self) -> None:
        self._running = False
        stream, self._stream = self._stream, None
        self._input_level = 0.0
        self._output_level = 0.0
        self._cpu_usage = 0.0
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("Error al cerrar el motor de voz en vivo: %s", exc)

    def close(self) -> None:
        self.stop()

    # --- callback de audio (hilo de PortAudio) ---
    def _callback(self, indata: np.ndarray, outdata: np.ndarray) -> None:
        start = time.perf_counter()
        mono_in = indata[:, 0] if indata.ndim > 1 else indata
        self._input_level = float(np.max(np.abs(mono_in))) if mono_in.size else 0.0

        if self.bypass:
            mix = mono_in
        else:
            wet = self._chain.process(mono_in, self.settings)
            mix = mono_in * (1.0 - self.dry_wet) + wet * self.dry_wet

        mix = np.clip(mix, -1.0, 1.0).astype(np.float32)
        self._output_level = float(np.max(np.abs(mix))) if mix.size else 0.0
        for ch in range(outdata.shape[1]):
            outdata[:, ch] = mix

        block_duration = len(mono_in) / self.samplerate if len(mono_in) else 0.0
        if block_duration > 0:
            self._cpu_usage = float(np.clip((time.perf_counter() - start) / block_duration, 0.0, 1.0))
