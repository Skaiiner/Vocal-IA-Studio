from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

from vocal_ai_studio.audio.io import AudioData, conform_channels
from vocal_ai_studio.core.interfaces import AudioBackend, AudioStream

log = logging.getLogger(__name__)

CHANNELS = 2


@dataclass
class _Track:
    samples: np.ndarray       # (frames, 2) float32
    offset_frames: int = 0
    gain: float = 1.0
    muted: bool = False

    @property
    def end(self) -> int:
        return self.offset_frames + self.samples.shape[0]


class Player:
    def __init__(self, backend: AudioBackend, samplerate: int = 44100, output_device: str = ""):
        self.backend = backend
        self.samplerate = samplerate
        self.output_device = output_device
        self._tracks: dict[str, _Track] = {}
        self._pos = 0
        self._playing = False
        self._finished = False
        self._stream: AudioStream | None = None
        self._sources: list[Callable[[int], np.ndarray | None]] = []
        self._lock = threading.Lock()

    # --- pistas ---
    def set_track(self, name: str, audio: AudioData | None, offset_sec: float = 0.0, gain: float | None = None) -> None:
        tracks = dict(self._tracks)
        if audio is None:
            tracks.pop(name, None)
        else:
            if audio.samplerate != self.samplerate:
                raise ValueError("La pista debe tener la frecuencia de muestreo del reproductor.")
            old = tracks.get(name)
            tracks[name] = _Track(
                conform_channels(audio.samples, CHANNELS),
                int(round(offset_sec * self.samplerate)),
                gain if gain is not None else (old.gain if old else 1.0),
                old.muted if old else False,
            )
        self._tracks = tracks  # reemplazo atómico: el callback nunca ve un dict a medio modificar

    def set_gain(self, name: str, gain: float) -> None:
        if name in self._tracks:
            self._tracks[name].gain = float(gain)

    def set_muted(self, name: str, muted: bool) -> None:
        if name in self._tracks:
            self._tracks[name].muted = bool(muted)

    def add_source(self, source: Callable[[int], np.ndarray | None]) -> None:
        self._sources = [*self._sources, source]

    def remove_source(self, source: Callable[[int], np.ndarray | None]) -> None:
        self._sources = [s for s in self._sources if s is not source]

    # --- estado ---
    @property
    def duration(self) -> float:
        end = max((t.end for t in self._tracks.values()), default=0)
        return end / self.samplerate

    @property
    def position(self) -> float:
        return self._pos / self.samplerate

    @property
    def is_playing(self) -> bool:
        return self._playing

    def pop_finished(self) -> bool:
        if self._finished:
            self._finished = False
            return True
        return False

    # --- control ---
    def ensure_stream(self) -> None:
        if self._stream is None:
            stream = self.backend.open_output(self.output_device, self.samplerate, CHANNELS, self._callback)
            stream.start()
            self._stream = stream

    def set_output_device(self, device: str) -> None:
        if device != self.output_device:
            self.output_device = device
            self.close_stream()

    def play(self) -> None:
        if self.duration == 0:
            return
        if self._pos >= int(self.duration * self.samplerate):
            self._pos = 0
        self.ensure_stream()
        self._finished = False
        self._playing = True

    def pause(self) -> None:
        self._playing = False

    def stop(self) -> None:
        self._playing = False
        self._pos = 0

    def seek(self, seconds: float) -> None:
        total = int(self.duration * self.samplerate)
        self._pos = int(min(max(0, round(seconds * self.samplerate)), total))

    def close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("Error al cerrar la salida de audio: %s", exc)

    def close(self) -> None:
        self._playing = False
        self.close_stream()

    # --- callback de audio (hilo de PortAudio) ---
    def _callback(self, out: np.ndarray) -> None:
        frames = out.shape[0]
        out[:] = 0
        if self._playing:
            pos = self._pos
            end_all = 0
            for t in self._tracks.values():
                end_all = max(end_all, t.end)
                if t.muted or t.gain == 0:
                    continue
                a = max(pos, t.offset_frames)
                b = min(pos + frames, t.end)
                if b > a:
                    out[a - pos:b - pos] += t.samples[a - t.offset_frames:b - t.offset_frames] * np.float32(t.gain)
            self._pos = pos + frames
            if self._pos >= end_all:
                self._pos = end_all
                self._playing = False
                self._finished = True
        for src in self._sources:
            extra = src(frames)
            if extra is not None and extra.shape[0] == frames:
                out += conform_channels(extra, out.shape[1])
        np.clip(out, -1.0, 1.0, out=out)
