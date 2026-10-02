from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.playback.player import Player
from tests.conftest import tone


def test_player_outputs_audio_and_advances_position(backend):
    p = Player(backend, 44100)
    p.set_track("song", tone(1.0, 440, channels=2, amp=0.5))
    p.play()
    out = backend.output_stream.pump(4)
    assert float(np.max(np.abs(out))) > 0.1
    assert p.position == pytest.approx(4 * 256 / 44100, abs=1e-6)
    p.close()


def test_player_silent_when_paused(backend):
    p = Player(backend, 44100)
    p.set_track("song", tone(1.0, 440, channels=2))
    p.play()
    backend.output_stream.pump(1)
    pos = p.position
    p.pause()
    out = backend.output_stream.pump(2)
    assert float(np.max(np.abs(out))) == 0.0
    assert p.position == pytest.approx(pos)
    p.close()


def test_player_stop_rewinds_and_seek_works(backend):
    p = Player(backend, 44100)
    p.set_track("song", tone(2.0, 440, channels=2))
    p.play()
    backend.output_stream.pump(2)
    p.stop()
    assert p.position == 0.0
    p.seek(1.0)
    assert p.position == pytest.approx(1.0)
    p.seek(99.0)
    assert p.position == pytest.approx(p.duration)
    p.close()


def test_player_mutes_and_gains_tracks(backend):
    p = Player(backend, 44100)
    p.set_track("song", tone(1.0, 440, channels=2, amp=0.5))
    p.set_track("vocal", tone(1.0, 440, channels=1, amp=0.5))
    p.set_muted("song", True)
    p.set_gain("vocal", 0.0)
    p.play()
    out = backend.output_stream.pump(2)
    assert float(np.max(np.abs(out))) == 0.0
    p.close()


def test_player_reports_finish_once(backend):
    p = Player(backend, 44100)
    p.set_track("song", tone(256 * 2 / 44100, 440, channels=2))
    p.play()
    backend.output_stream.pump(4)
    assert p.pop_finished() is True
    assert p.pop_finished() is False
    assert p.is_playing is False
    p.close()


def test_player_duration_uses_offsets(backend):
    p = Player(backend, 44100)
    p.set_track("vocal", tone(1.0, 440, channels=1), offset_sec=2.0)
    assert p.duration == pytest.approx(3.0, abs=0.01)
    p.set_track("vocal", None)
    assert p.duration == 0.0
    p.close()


def test_player_extra_source_is_mixed(backend):
    p = Player(backend, 44100)

    def source(frames):
        return np.full((frames, 1), 0.3, np.float32)

    p.add_source(source)
    p.set_track("song", tone(1.0, 440, channels=2, amp=0.1))
    p.play()
    out = backend.output_stream.pump(1)
    assert float(np.max(np.abs(out))) > 0.25
    p.remove_source(source)
    p.close()


def test_player_changing_output_device_reopens_stream(backend):
    p = Player(backend, 44100, output_device="A")
    p.set_track("song", tone(0.5, 440, channels=2))
    p.play()
    first = backend.output_stream
    p.set_output_device("B")
    assert first.closed is True
    p.play()
    assert backend.output_stream is not first
    assert ("output", "B") in backend.opened_devices
    p.close()
