from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from vocal_ai_studio.audio.io import AudioData
from vocal_ai_studio.core.config import Settings, SettingsStore
from vocal_ai_studio.session import Session
from vocal_ai_studio.song_import.importer import import_vocal_as_take


def _write_wav(path, seconds=1.0, sr=44100, freq=440.0):
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    samples = (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), samples, sr)
    return path


@pytest.fixture
def session(backend, tmp_path):
    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")),
                SettingsStore(tmp_path / "settings.json"))
    s.new_project("ImportToma")
    yield s
    s.close()


def test_import_as_take_adds_new_take(session, tmp_path):
    wav = _write_wav(tmp_path / "canto.wav")
    before = len(session.project.data.takes)
    session.import_vocal_as_take(wav)
    assert len(session.project.data.takes) == before + 1


def test_import_as_take_uses_filename_as_name(session, tmp_path):
    wav = _write_wav(tmp_path / "mi_voz.wav")
    session.import_vocal_as_take(wav)
    names = [t.name for t in session.project.data.takes]
    assert "mi_voz" in names


def test_import_as_take_becomes_active_take(session, tmp_path):
    wav = _write_wav(tmp_path / "voz2.wav")
    session.import_vocal_as_take(wav)
    active = session.project.data.active_take
    last_id = session.project.data.takes[-1].id
    assert active == last_id


def test_import_multiple_as_takes(session, tmp_path):
    paths = [_write_wav(tmp_path / f"take{i}.wav", freq=220 * i + 220) for i in range(3)]
    results = session.import_vocal_files_as_takes(paths)
    assert len(results) == 3
    assert len(session.project.data.takes) == 3


def test_import_as_take_does_not_overwrite_existing_takes(session, tmp_path):
    w1 = _write_wav(tmp_path / "primera.wav")
    w2 = _write_wav(tmp_path / "segunda.wav")
    session.import_vocal_as_take(w1)
    session.import_vocal_as_take(w2)
    names = [t.name for t in session.project.data.takes]
    assert "primera" in names and "segunda" in names


def test_import_as_take_low_level_function(tmp_path):
    from vocal_ai_studio.storage.project import Project

    root = tmp_path / "proj"
    root.mkdir()
    project = Project.create(root, "Test")
    wav = _write_wav(tmp_path / "audio.wav", freq=330.0)
    import_vocal_as_take(project, wav)
    assert len(project.data.takes) == 1
    assert project.data.takes[0].name == "audio"
