from __future__ import annotations

import numpy as np

from vocal_ai_studio.core.interfaces import DeviceInfo
from vocal_ai_studio.effects.chain import VoiceLabSettings
from vocal_ai_studio.realtime.engine import LiveVoiceEngine, detect_virtual_devices


def test_detect_virtual_devices_matches_cable_and_voicemeeter(backend):
    backend.output_devices = lambda: [
        DeviceInfo(0, "VB-Audio Virtual Cable", "MME", 0, 2, 44100.0),
        DeviceInfo(1, "Altavoces normales", "MME", 0, 2, 44100.0),
    ]
    found = detect_virtual_devices(backend)
    assert any("cable" in f.lower() for f in found)
    assert len(found) == 1


def test_detect_virtual_devices_empty_when_no_match(backend):
    found = detect_virtual_devices(backend)
    assert found == []


def test_engine_start_opens_duplex_stream(backend):
    engine = LiveVoiceEngine(backend, 44100, "Fake Mic", "Fake Speakers")
    engine.start()
    assert engine.is_running
    assert backend.duplex_stream is not None
    assert backend.duplex_stream.running
    engine.stop()
    assert not engine.is_running
    assert backend.duplex_stream.closed


def test_engine_passthrough_bypass(backend):
    engine = LiveVoiceEngine(backend, 44100, "Fake Mic", "Fake Speakers")
    engine.set_bypass(True)
    engine.start()
    indata = np.full((backend.duplex_stream.frames, 1), 0.3, np.float32)
    out = backend.duplex_stream.pump(1, indata)
    assert np.allclose(out, 0.3, atol=1e-5)
    engine.stop()


def test_engine_dry_wet_zero_is_passthrough(backend):
    engine = LiveVoiceEngine(backend, 44100, "Fake Mic", "Fake Speakers")
    engine.update_settings(VoiceLabSettings.from_preset("Pop"))
    engine.set_dry_wet(0.0)
    engine.start()
    indata = np.full((backend.duplex_stream.frames, 1), 0.2, np.float32)
    out = backend.duplex_stream.pump(1, indata)
    assert np.allclose(out, 0.2, atol=1e-5)
    engine.stop()


def test_engine_updates_levels_and_cpu(backend):
    engine = LiveVoiceEngine(backend, 44100, "Fake Mic", "Fake Speakers")
    engine.start()
    indata = np.full((backend.duplex_stream.frames, 1), 0.5, np.float32)
    backend.duplex_stream.pump(1, indata)
    assert engine.input_level > 0
    assert engine.output_level >= 0
    assert engine.cpu_usage >= 0
    engine.stop()
    assert engine.input_level == 0
    assert engine.output_level == 0


def test_engine_set_devices_restarts_when_running(backend):
    engine = LiveVoiceEngine(backend, 44100, "Fake Mic", "Fake Speakers")
    engine.start()
    first_stream = backend.duplex_stream
    engine.set_devices("Otro Mic", "Fake Speakers")
    assert backend.duplex_stream is not first_stream
    assert engine.is_running
    engine.stop()


def test_engine_set_devices_noop_when_same(backend):
    engine = LiveVoiceEngine(backend, 44100, "Fake Mic", "Fake Speakers")
    engine.start()
    first_stream = backend.duplex_stream
    engine.set_devices("Fake Mic", "Fake Speakers")
    assert backend.duplex_stream is first_stream
    engine.stop()
