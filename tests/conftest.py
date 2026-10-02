from __future__ import annotations

import os
import threading
from pathlib import Path

# Qt sin ventanas reales: debe fijarse antes de crear cualquier QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from vocal_ai_studio.audio.io import AudioData
from vocal_ai_studio.core.interfaces import DeviceInfo
from vocal_ai_studio.storage.project import Project


def tone(seconds: float = 1.0, freq: float = 440.0, sr: int = 44100, channels: int = 2, amp: float = 0.5) -> AudioData:
    t = np.arange(int(seconds * sr)) / sr
    x = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return AudioData(np.repeat(x[:, None], channels, axis=1), sr)


class FakeStream:
    def __init__(self, backend: "FakeBackend", callback, frames: int, channels: int, is_input: bool):
        self.backend = backend
        self.callback = callback
        self.frames = frames
        self.channels = channels
        self.is_input = is_input
        self.running = False
        self.closed = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def close(self) -> None:
        self.running = False
        self.closed = True

    def pump(self, blocks: int = 1, indata: np.ndarray | None = None) -> np.ndarray:
        out_blocks = []
        for _ in range(blocks):
            if self.is_input:
                block = indata if indata is not None else np.full((self.frames, self.channels), 0.25, np.float32)
                self.callback(block.astype(np.float32))
            else:
                buf = np.zeros((self.frames, self.channels), np.float32)
                self.callback(buf)
                out_blocks.append(buf.copy())
        return np.concatenate(out_blocks, axis=0) if out_blocks else np.zeros((0, self.channels), np.float32)


class FakeBackend:
    def __init__(self, block_frames: int = 256, fail_input_channels: set[int] | None = None):
        self.block_frames = block_frames
        self.fail_input_channels = fail_input_channels or set()
        self.output_stream: FakeStream | None = None
        self.input_stream: FakeStream | None = None
        self.opened_devices: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def input_devices(self):
        return [DeviceInfo(0, "Fake Mic", "FakeAPI", 2, 0, 44100.0)]

    def output_devices(self):
        return [DeviceInfo(1, "Fake Speakers", "FakeAPI", 0, 2, 44100.0)]

    def open_output(self, device, samplerate, channels, callback):
        self.opened_devices.append(("output", device))
        self.output_stream = FakeStream(self, callback, self.block_frames, channels, is_input=False)
        return self.output_stream

    def open_input(self, device, samplerate, channels, callback):
        if channels in self.fail_input_channels:
            raise RuntimeError(f"fake: {channels} canales no soportados")
        self.opened_devices.append(("input", device))
        self.input_stream = FakeStream(self, callback, self.block_frames, channels, is_input=True)
        return self.input_stream


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return Project.create(tmp_path / "Test Project", "Test Project")
