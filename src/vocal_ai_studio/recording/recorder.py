from __future__ import annotations

import logging
import threading
from collections import deque
from enum import Enum

import numpy as np

from vocal_ai_studio.audio.io import AudioData
from vocal_ai_studio.core.errors import AppError, explain_exception
from vocal_ai_studio.core.interfaces import AudioBackend, AudioStream

log = logging.getLogger(__name__)


class RecState(str, Enum):
    CLOSED = "closed"
    ARMED = "armed"          # micrófono abierto, solo medidor/monitor
    RECORDING = "recording"
    PAUSED = "paused"


LIVE_BUFFER_SAMPLES = 4096  # ~93ms a 44.1kHz: suficiente para detectar hasta notas graves (~C2)


class Recorder:
    def __init__(self, backend: AudioBackend, samplerate: int = 44100, input_device: str = ""):
        self.backend = backend
        self.samplerate = samplerate
        self.input_device = input_device
        self.gain = 1.0
        self.monitor = False
        self._state = RecState.CLOSED
        self._stream: AudioStream | None = None
        self._chunks: list[np.ndarray] = []
        self._frames = 0
        self._level = 0.0
        self._monitor_buf: deque[np.ndarray] = deque(maxlen=64)
        self._live_buffer = np.zeros(LIVE_BUFFER_SAMPLES, np.float32)
        self._lock = threading.Lock()

    @property
    def state(self) -> RecState:
        return self._state

    @property
    def is_recording(self) -> bool:
        return self._state == RecState.RECORDING

    @property
    def elapsed(self) -> float:
        return self._frames / self.samplerate

    @property
    def level(self) -> float:
        return self._level

    def set_device(self, device: str) -> None:
        if device != self.input_device:
            self.input_device = device
            if self._state in (RecState.ARMED,):
                self.close()
                self.arm()

    # --- ciclo de vida ---
    def arm(self) -> None:
        if self._state != RecState.CLOSED:
            return
        last: BaseException | None = None
        for channels in (1, 2):
            try:
                stream = self.backend.open_input(self.input_device, self.samplerate, channels, self._callback)
            except Exception as exc:  # noqa: BLE001
                last = exc
                continue
            stream.start()
            self._stream = stream
            self._state = RecState.ARMED
            return
        raise explain_exception(last, "No se pudo abrir el micrófono") from last

    def close(self) -> None:
        self._state = RecState.CLOSED
        stream, self._stream = self._stream, None
        self._level = 0.0
        self._monitor_buf.clear()
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("Error al cerrar el micrófono: %s", exc)

    # --- grabación ---
    def start(self) -> None:
        self.arm()
        with self._lock:
            self._chunks = []
            self._frames = 0
        self._state = RecState.RECORDING

    def pause(self) -> None:
        if self._state == RecState.RECORDING:
            self._state = RecState.PAUSED

    def resume(self) -> None:
        if self._state == RecState.PAUSED:
            self._state = RecState.RECORDING

    def stop(self) -> AudioData:
        if self._state not in (RecState.RECORDING, RecState.PAUSED):
            raise AppError("No hay ninguna grabación en curso.", "", "Pulsa Grabar primero.")
        self._state = RecState.ARMED
        with self._lock:
            chunks, self._chunks = self._chunks, []
            self._frames = 0
        if not chunks:
            return AudioData(np.zeros((0, 1), np.float32), self.samplerate)
        return AudioData(np.concatenate(chunks, axis=0), self.samplerate)

    def cancel(self) -> None:
        if self._state in (RecState.RECORDING, RecState.PAUSED):
            self._state = RecState.ARMED
        with self._lock:
            self._chunks = []
            self._frames = 0

    def recent_samples(self, n: int = LIVE_BUFFER_SAMPLES) -> np.ndarray:
        buf = self._live_buffer  # reasignado como objeto nuevo en el callback: lectura segura
        return buf[-n:] if n < len(buf) else buf

    def live_pitch(self) -> tuple[float, float]:
        if self._state == RecState.CLOSED:
            return float("nan"), 0.0
        from vocal_ai_studio.pitch.yin import yin_pitch_track

        buf = self._live_buffer
        if float(np.sqrt(np.mean(buf.astype(np.float64) ** 2))) < 0.008:
            return float("nan"), 0.0
        track = yin_pitch_track(buf, self.samplerate, frame_length=len(buf), hop_length=len(buf))
        if len(track.f0) == 0:
            return float("nan"), 0.0
        return float(track.f0[0]), float(track.confidence[0])

    # --- monitor: fuente para Player.add_source ---
    def monitor_source(self, frames: int) -> np.ndarray | None:
        if not self.monitor or not self._monitor_buf:
            return None
        out = np.zeros((frames, 1), np.float32)
        filled = 0
        while filled < frames and self._monitor_buf:
            chunk = self._monitor_buf.popleft()
            take = min(frames - filled, chunk.shape[0])
            out[filled:filled + take] = chunk[:take]
            filled += take
            if take < chunk.shape[0]:
                self._monitor_buf.appendleft(chunk[take:])
        return out

    # --- callback de audio (hilo de PortAudio) ---
    def _callback(self, indata: np.ndarray) -> None:
        mono = (indata.mean(axis=1, keepdims=True) if indata.shape[1] > 1 else indata) * np.float32(self.gain)
        mono = np.clip(mono, -1.0, 1.0).astype(np.float32, copy=True)
        self._level = float(np.max(np.abs(mono))) if mono.size else 0.0
        # Se reasigna a un array NUEVO (no se modifica in-place): así una lectura concurrente
        # desde recent_samples() siempre ve un buffer completo y consistente, nunca a medio escribir.
        flat = mono[:, 0] if mono.ndim > 1 else mono
        self._live_buffer = np.concatenate([self._live_buffer, flat])[-LIVE_BUFFER_SAMPLES:]
        if self.monitor:
            self._monitor_buf.append(mono)
        if self._state == RecState.RECORDING:
            with self._lock:
                self._chunks.append(mono)
                self._frames += mono.shape[0]
