from __future__ import annotations

import numpy as np
import pytest
import torch

from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.separation.demucs_separator import DemucsSeparator

SR = 44100


def sine(freq=440.0, seconds=0.5, sr=SR, amp=0.4):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class FakeSeparatorBackend:
    def __init__(self, model, device, progress):
        self.model = model
        self.device = device

    def separate_tensor(self, wav, sr):
        vocals = wav * 0.6
        instrumental = wav * 0.4
        return None, {"vocals": vocals, "bass": instrumental * 0.5, "drums": instrumental * 0.5}


def _fake_require_demucs():
    return torch, FakeSeparatorBackend


def test_separate_mono_input_sums_stems(monkeypatch):
    import vocal_ai_studio.separation.demucs_separator as mod

    monkeypatch.setattr(mod, "_require_demucs", _fake_require_demucs)

    sep = DemucsSeparator()
    x = sine(seconds=0.2)
    calls = []
    result = sep.separate(x, SR, progress=calls.append)
    assert set(result.keys()) == {"vocals", "instrumental"}
    assert result["vocals"].dtype == np.float32
    assert len(result["vocals"]) == len(x)
    assert calls[0] == pytest.approx(0.05)
    assert calls[-1] == pytest.approx(1.0)


def test_separate_cancelled_before_start_raises(monkeypatch):
    import vocal_ai_studio.separation.demucs_separator as mod

    monkeypatch.setattr(mod, "_require_demucs", _fake_require_demucs)

    sep = DemucsSeparator()
    x = sine(seconds=0.1)
    with pytest.raises(mod.SeparationCancelled):
        sep.separate(x, SR, cancelled=lambda: True)


def test_separate_missing_demucs_raises_app_error(monkeypatch):
    import vocal_ai_studio.separation.demucs_separator as mod

    def boom():
        raise AppError("Falta Demucs.", "", "")

    monkeypatch.setattr(mod, "_require_demucs", boom)
    sep = DemucsSeparator()
    with pytest.raises(AppError):
        sep.separate(sine(seconds=0.1), SR)


# --- session integration ---

def test_session_separate_song_persists_stems(backend, tmp_path, monkeypatch):
    import soundfile as sf

    import vocal_ai_studio.session as session_mod
    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    def fake_separate(self, samples, samplerate, progress=None, cancelled=None):
        if progress:
            progress(1.0)
        return {
            "vocals": (samples * 0.5).astype(np.float32),
            "instrumental": (samples * 0.5).astype(np.float32),
        }

    monkeypatch.setattr(session_mod.DemucsSeparator, "separate", fake_separate)

    wav = tmp_path / "song.wav"
    sf.write(str(wav), sine(seconds=0.3), SR)

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")),
                SettingsStore(tmp_path / "settings.json"))
    s.new_project("Separation")
    s.import_song_file(wav)

    result = s.separate_song()
    assert "vocals" in result and "instrumental" in result
    assert s.project.path("separated", "vocals.wav").exists()
    assert s.project.path("separated", "instrumental.wav").exists()

    loaded = s.load_separation()
    assert loaded is not None
    assert len(loaded["vocals"].to_mono()) > 0
    s.close()


def test_session_separate_song_without_song_raises(backend, tmp_path):
    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")),
                SettingsStore(tmp_path / "settings.json"))
    s.new_project("NoSong")
    with pytest.raises(AppError):
        s.separate_song()
    s.close()


def test_session_separate_song_loads_original_vocal_track_muted(backend, tmp_path, monkeypatch):
    import soundfile as sf

    import vocal_ai_studio.session as session_mod
    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    def fake_separate(self, samples, samplerate, progress=None, cancelled=None):
        return {
            "vocals": (samples * 0.5).astype(np.float32),
            "instrumental": (samples * 0.5).astype(np.float32),
        }

    monkeypatch.setattr(session_mod.DemucsSeparator, "separate", fake_separate)

    wav = tmp_path / "song.wav"
    sf.write(str(wav), sine(seconds=0.3), SR)

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")),
                SettingsStore(tmp_path / "settings.json"))
    s.new_project("OriginalVocalTrack")
    s.import_song_file(wav)
    assert not s.has_separation()

    s.separate_song()

    assert s.has_separation()
    assert s.player.duration > 0
    # recién descubierta: no debe oírse hasta que el usuario la active a mano
    assert s.player.is_muted("original_vocal") is True

    s.player.set_muted("original_vocal", False)
    s.set_original_vocal_gain(0.7)
    assert s.project.data.original_vocal_gain == pytest.approx(0.7)

    # un refresh posterior (p. ej. al seleccionar otra toma) no debe volver a silenciarla sola
    s.refresh_tracks()
    assert s.player.is_muted("original_vocal") is False
    s.close()


def test_session_use_separated_vocals_as_take(backend, tmp_path, monkeypatch):
    import soundfile as sf

    import vocal_ai_studio.session as session_mod
    from vocal_ai_studio.core.config import Settings, SettingsStore
    from vocal_ai_studio.session import Session

    def fake_separate(self, samples, samplerate, progress=None, cancelled=None):
        return {
            "vocals": (samples * 0.5).astype(np.float32),
            "instrumental": (samples * 0.5).astype(np.float32),
        }

    monkeypatch.setattr(session_mod.DemucsSeparator, "separate", fake_separate)

    wav = tmp_path / "song.wav"
    sf.write(str(wav), sine(seconds=0.3), SR)

    s = Session(backend, Settings(projects_dir=str(tmp_path / "P")),
                SettingsStore(tmp_path / "settings.json"))
    s.new_project("UseSeparated")
    s.import_song_file(wav)
    s.separate_song()

    before = len(s.project.data.takes)
    take = s.use_separated_vocals_as_take()
    assert "voz separada" in take.name
    assert len(s.project.data.takes) == before + 1

    s.use_separated_instrumental_as_song()
    assert "instrumental" in s.project.data.song_title
    s.close()
