from __future__ import annotations

import numpy as np
import pytest

from vocal_ai_studio.audio.io import save_audio
from vocal_ai_studio.core.config import Settings, SettingsStore
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.recording.recorder import RecState
from vocal_ai_studio.session import Session
from tests.conftest import tone


@pytest.fixture
def session(backend, tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    settings = Settings(projects_dir=str(tmp_path / "Projects"))
    s = Session(backend, settings, store)
    yield s
    s.close()


def test_new_project_and_reopen(session, tmp_path):
    project = session.new_project("My Song Project")
    assert project.root.parent == tmp_path / "Projects"
    assert session.settings.last_project == str(project.root)
    again = session.new_project("My Song Project")
    assert again.root.name == "My Song Project 2"
    assert session.open_project(project.root).name == "My Song Project"


def test_actions_without_project_explain(session, tmp_path):
    with pytest.raises(AppError):
        session.import_song_file(tmp_path / "x.wav")
    with pytest.raises(AppError):
        session.export("mix", tmp_path / "o.wav")
    with pytest.raises(AppError):
        session.start_recording()


def test_import_loads_tracks_into_player(session, tmp_path):
    session.new_project("P")
    save_audio(tmp_path / "s.wav", tone(1.0, 440, channels=2), "wav")
    session.import_song_file(tmp_path / "s.wav")
    assert session.player.duration == pytest.approx(1.0, abs=0.02)
    session.play()
    out = backend_out(session, 3)
    assert float(np.max(np.abs(out))) > 0.1


def test_recording_creates_take_and_reloads_player(session, backend):
    session.new_project("P")
    session.start_recording()
    assert session.recorder.state is RecState.RECORDING
    backend.input_stream.pump(8)
    take = session.finish_recording()
    assert take is not None and take.name == "Take 1"
    assert session.project.data.active_take == take.id
    assert session.player.duration > 0


def test_recording_mutes_vocal_while_recording(session, backend, tmp_path):
    session.new_project("P")
    session.project.add_take(tone(1.0, 440, channels=1, amp=0.8))
    session.refresh_tracks()
    session.start_recording()
    out = backend.output_stream.pump(2)
    assert float(np.max(np.abs(out))) == 0.0  # la toma anterior no suena durante la grabación
    backend.input_stream.pump(2)
    session.finish_recording()
    session.play()
    assert float(np.max(np.abs(backend.output_stream.pump(2)))) > 0.1


def test_empty_recording_creates_no_take(session, backend):
    session.new_project("P")
    session.start_recording()
    assert session.finish_recording() is None
    assert session.project.data.takes == []


def test_cancel_recording_discards(session, backend):
    session.new_project("P")
    session.start_recording()
    backend.input_stream.pump(3)
    session.cancel_recording()
    assert session.project.data.takes == []
    assert session.recorder.state is RecState.ARMED


def test_recording_offset_follows_playhead_and_latency(session, backend, tmp_path):
    session.new_project("P")
    save_audio(tmp_path / "s.wav", tone(4.0, 440, channels=2), "wav")
    session.import_song_file(tmp_path / "s.wav")
    session.settings.latency_compensation_ms = 100.0
    session.seek(2.0)
    session.start_recording()
    backend.input_stream.pump(4)
    take = session.finish_recording()
    assert take.offset_sec == pytest.approx(1.9, abs=0.01)


def test_stop_during_recording_saves_take(session, backend):
    session.new_project("P")
    session.start_recording()
    backend.input_stream.pump(4)
    session.stop()
    assert len(session.project.data.takes) == 1
    assert session.player.position == 0.0


def test_select_and_delete_take_updates_player(session, backend):
    session.new_project("P")
    session.project.add_take(tone(1.0, 440, channels=1))
    t2 = session.project.add_take(tone(0.3, 440, channels=1))
    session.refresh_tracks()
    assert session.player.duration == pytest.approx(0.3, abs=0.02)
    session.delete_take(t2.id)
    assert session.player.duration == pytest.approx(1.0, abs=0.02)


def test_gains_persist_in_project(session):
    session.new_project("P")
    session.set_song_gain(0.5)
    session.set_vocal_gain(1.2)
    reopened = session.open_project(session.project.root)
    assert reopened.data.song_gain == pytest.approx(0.5)
    assert reopened.data.vocal_gain == pytest.approx(1.2)


def test_apply_devices_persists_and_reopens_output(session, backend):
    session.new_project("P")
    session.apply_devices(input_device="Mic [X]", output_device="Out [X]")
    assert session.settings.input_device == "Mic [X]"
    assert SettingsStore(session.store.path).load().output_device == "Out [X]"


def test_monitor_source_is_mixed_into_output(session, backend):
    session.new_project("P")
    session.recorder.monitor = True
    session.recorder.arm()
    backend.input_stream.pump(2)
    session.player.ensure_stream()
    out = backend.output_stream.pump(1)
    assert float(np.max(np.abs(out))) > 0.1


def test_export_uses_session_project(session, tmp_path):
    session.new_project("P")
    session.project.add_take(tone(0.4, 440, channels=1))
    session.refresh_tracks()
    out = session.export("vocal", tmp_path / "v.wav")
    assert out.exists()
    assert "vocal" in session.default_export_name("vocal", "wav")


def test_save_project_as_switches_to_copy(session, tmp_path):
    session.new_project("P")
    session.project.add_take(tone(0.2, 440, channels=1))
    copy = session.save_project_as(tmp_path / "Copias", "P copia")
    assert session.project is copy
    assert (copy.root / "takes" / "take_01.wav").exists()


def backend_out(session: Session, blocks: int):
    return session.backend.output_stream.pump(blocks)
