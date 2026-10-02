from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import sounddevice as sd

from vocal_ai_studio.core.errors import AppError, explain_exception
from vocal_ai_studio.core.interfaces import AudioStream, DeviceInfo

log = logging.getLogger(__name__)

# WDM-KS es inestable para aplicaciones normales; se oculta.
_HIDDEN_HOSTAPIS = {"Windows WDM-KS"}


class _SdStream:
    def __init__(self, stream: sd.RawStream | sd.OutputStream | sd.InputStream):
        self._s = stream

    def start(self) -> None:
        self._s.start()

    def stop(self) -> None:
        self._s.stop()

    def close(self) -> None:
        self._s.close()

    @property
    def latency(self) -> float:
        lat = self._s.latency
        return float(lat[0] if isinstance(lat, (tuple, list)) else lat)


class SoundDeviceBackend:
    def _devices(self) -> list[DeviceInfo]:
        hostapis = sd.query_hostapis()
        out = []
        for i, d in enumerate(sd.query_devices()):
            api = hostapis[d["hostapi"]]["name"]
            if api in _HIDDEN_HOSTAPIS:
                continue
            out.append(DeviceInfo(i, d["name"], api, d["max_input_channels"], d["max_output_channels"],
                                  d["default_samplerate"]))
        return out

    def input_devices(self) -> list[DeviceInfo]:
        return [d for d in self._devices() if d.max_input_channels > 0]

    def output_devices(self) -> list[DeviceInfo]:
        return [d for d in self._devices() if d.max_output_channels > 0]

    def _resolve(self, label: str, kind: str) -> DeviceInfo | None:
        if not label:
            return None
        devices = self.input_devices() if kind == "input" else self.output_devices()
        for d in devices:
            if d.label == label:
                return d
        log.warning("Dispositivo '%s' no encontrado; se usa el predeterminado.", label)
        return None

    @staticmethod
    def _extra(dev: DeviceInfo | None):
        if dev is not None and "WASAPI" in dev.hostapi:
            return sd.WasapiSettings(auto_convert=True)
        return None

    def open_output(self, device: str, samplerate: int, channels: int,
                    callback: Callable[[np.ndarray], None]) -> AudioStream:
        dev = self._resolve(device, "output")

        def cb(outdata, frames, time, status):  # noqa: ARG001
            if status:
                log.debug("Estado salida: %s", status)
            callback(outdata)

        try:
            stream = sd.OutputStream(samplerate=samplerate, channels=channels, dtype="float32",
                                     device=dev.index if dev else None, callback=cb,
                                     extra_settings=self._extra(dev))
        except Exception as exc:  # noqa: BLE001
            raise explain_exception(exc, "No se pudo abrir la salida de audio") from exc
        return _SdStream(stream)

    def open_input(self, device: str, samplerate: int, channels: int,
                   callback: Callable[[np.ndarray], None]) -> AudioStream:
        dev = self._resolve(device, "input")

        def cb(indata, frames, time, status):  # noqa: ARG001
            if status:
                log.debug("Estado entrada: %s", status)
            callback(indata)

        try:
            stream = sd.InputStream(samplerate=samplerate, channels=channels, dtype="float32",
                                    device=dev.index if dev else None, callback=cb,
                                    extra_settings=self._extra(dev))
        except Exception as exc:  # noqa: BLE001
            raise explain_exception(exc, "No se pudo abrir el micrófono") from exc
        return _SdStream(stream)

    def max_input_channels(self, device: str) -> int:
        dev = self._resolve(device, "input")
        if dev is not None:
            return dev.max_input_channels
        try:
            return int(sd.query_devices(kind="input")["max_input_channels"]) or 1
        except Exception:  # noqa: BLE001
            return 1
