from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.recording.recorder import Recorder, RecState
from tests.conftest import FakeBackend


def test_recorder_captures_audio(backend):
    r = Recorder(backend, 44100)
    r.start()
    backend.input_stream.pump(4)
    take = r.stop()
    assert take.frames == 4 * 256 and take.channels == 1
    assert float(np.max(np.abs(take.to_mono()))) == pytest.approx(0.25, abs=0.01)
    assert r.state is RecState.ARMED
    r.close()


def test_recorder_armed_does_not_capture_but_meters(backend):
    r = Recorder(backend, 44100)
    r.arm()
    backend.input_stream.pump(2)
    assert r.level == pytest.approx(0.25, abs=0.01)
    assert r.elapsed == 0.0
    r.close()


def test_recorder_pause_and_resume_skips_audio(backend):
    r = Recorder(backend, 44100)
    r.start()
    backend.input_stream.pump(2)
    r.pause()
    backend.input_stream.pump(5)
    r.resume()
    backend.input_stream.pump(1)
    take = r.stop()
    assert take.frames == 3 * 256
    r.close()


def test_recorder_gain_is_applied_and_clipped(backend):
    r = Recorder(backend, 44100)
    r.gain = 8.0
    r.start()
    backend.input_stream.pump(1)
    take = r.stop()
    assert float(np.max(take.to_mono())) == pytest.approx(1.0)
    r.close()


def test_recorder_downmixes_stereo_input(backend):
    r = Recorder(backend, 44100)
    r.start()
    stereo = np.stack([np.ones(256), np.zeros(256)], axis=1).astype(np.float32)
    backend.input_stream.pump(1, indata=stereo)
    take = r.stop()
    assert take.channels == 1
    assert float(take.to_mono()[0]) == pytest.approx(0.5)
    r.close()


def test_recorder_stop_without_start_raises(backend):
    r = Recorder(backend, 44100)
    with pytest.raises(AppError):
        r.stop()


def test_recorder_cancel_discards_take(backend):
    r = Recorder(backend, 44100)
    r.start()
    backend.input_stream.pump(2)
    r.cancel()
    assert r.state is RecState.ARMED and r.elapsed == 0.0
    r.start()
    backend.input_stream.pump(1)
    assert r.stop().frames == 256
    r.close()


def test_recorder_monitor_source_returns_input(backend):
    r = Recorder(backend, 44100)
    r.monitor = True
    r.arm()
    backend.input_stream.pump(2)
    block = r.monitor_source(256)
    assert block is not None and block.shape == (256, 1)
    assert float(np.max(np.abs(block))) == pytest.approx(0.25, abs=0.01)
    r.monitor = False
    assert r.monitor_source(256) is None
    r.close()


def test_recorder_falls_back_when_mono_unsupported():
    backend = FakeBackend(fail_input_channels={1})
    r = Recorder(backend, 44100)
    r.arm()
    assert r.state is RecState.ARMED
    assert backend.input_stream.channels == 2
    r.close()


def test_recorder_reports_error_when_device_unavailable():
    backend = FakeBackend(fail_input_channels={1, 2})
    r = Recorder(backend, 44100)
    with pytest.raises(AppError) as err:
        r.arm()
    assert "Cómo solucionarlo" in err.value.user_message()
