from __future__ import annotations

import json

import numpy as np
import pytest

from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.song_import.importer import import_song, import_vocal
from vocal_ai_studio.storage import exporter
from vocal_ai_studio.storage.project import PROJECT_FILE, SUBDIRS, Project, safe_name
from vocal_ai_studio.audio.io import save_audio
from tests.conftest import tone


def test_create_project_makes_structure(tmp_path):
    p = Project.create(tmp_path / "My Song Project")
    assert (p.root / PROJECT_FILE).exists()
    for sub in SUBDIRS:
        assert (p.root / sub).is_dir()
    assert p.name == "My Song Project"


def test_create_twice_raises(tmp_path):
    Project.create(tmp_path / "P")
    with pytest.raises(AppError):
        Project.create(tmp_path / "P")


def test_open_roundtrip_keeps_data(project):
    import_song(project, _write(project.root / "src.wav", 1.0))
    project.set_gains(song=0.8, vocal=0.6)
    reopened = Project.open(project.root)
    assert reopened.data.song_file == "song.wav"
    assert reopened.data.song_gain == pytest.approx(0.8)
    assert reopened.load_song().duration == pytest.approx(1.0, abs=0.02)


def test_open_invalid_folder_raises(tmp_path):
    with pytest.raises(AppError):
        Project.open(tmp_path / "not a project")


def test_open_corrupt_project_file_explains(tmp_path):
    p = Project.create(tmp_path / "P")
    (p.root / PROJECT_FILE).write_text("{ broken", encoding="utf-8")
    with pytest.raises(AppError) as err:
        Project.open(p.root)
    assert "Cómo solucionarlo" in err.value.user_message()


def test_unknown_fields_in_project_file_are_ignored(tmp_path):
    p = Project.create(tmp_path / "P")
    raw = json.loads((p.root / PROJECT_FILE).read_text(encoding="utf-8"))
    raw["future_option"] = True
    (p.root / PROJECT_FILE).write_text(json.dumps(raw), encoding="utf-8")
    assert Project.open(p.root).name == "P"


def test_takes_lifecycle(project):
    t1 = project.add_take(tone(0.5, 440, channels=1))
    t2 = project.add_take(tone(0.4, 440, channels=1), offset_sec=1.5)
    assert [t.name for t in project.data.takes] == ["Take 1", "Take 2"]
    assert project.data.active_take == t2.id
    project.set_active_take(t1.id)
    assert project.active_vocal()[1] == 0.0
    project.set_active_take(t2.id)
    assert project.active_vocal()[1] == pytest.approx(1.5)
    project.rename_take(t1.id, "Mejor toma")
    assert project.get_take(t1.id).name == "Mejor toma"
    project.delete_take(t2.id)
    assert project.data.active_take == t1.id
    assert not (project.root / t2.file).exists()
    assert Project.open(project.root).data.active_take == t1.id


def test_set_active_take_validates(project):
    with pytest.raises(AppError):
        project.set_active_take(99)


def test_active_vocal_prefers_take_over_imported(project):
    import_vocal(project, _write(project.root / "v.wav", 0.5, channels=1))
    assert project.active_vocal()[0].duration == pytest.approx(0.5, abs=0.02)
    project.add_take(tone(0.2, 440, channels=1))
    assert project.active_vocal()[0].duration == pytest.approx(0.2, abs=0.02)


def test_save_as_copies_project(project, tmp_path):
    project.add_take(tone(0.2, 440, channels=1))
    copy = project.save_as(tmp_path / "Copia", "Copia")
    assert (copy.root / "takes" / "take_01.wav").exists()
    assert copy.name == "Copia"


def test_save_as_refuses_non_empty_folder(project, tmp_path):
    dest = tmp_path / "ocupada"
    dest.mkdir()
    (dest / "algo.txt").write_text("x", encoding="utf-8")
    with pytest.raises(AppError):
        project.save_as(dest)


def test_unique_root_avoids_collisions(tmp_path):
    (tmp_path / "Song").mkdir()
    assert Project.unique_root(tmp_path, "Song").name == "Song 2"


def test_safe_name_strips_invalid_characters():
    assert safe_name('a/b:c*?"<>|') == "a_b_c______"
    assert safe_name("   ") == "Untitled"


def test_import_song_normalizes_to_project_rate(project, tmp_path):
    src = _write(tmp_path / "s.wav", 0.5, sr=48000, channels=1)
    audio = import_song(project, src)
    assert audio.samplerate == project.samplerate and audio.channels == 2
    assert project.data.song_title == "s"


def test_import_vocal_resets_active_take(project, tmp_path):
    project.add_take(tone(0.2, 440, channels=1))
    import_vocal(project, _write(tmp_path / "v.wav", 0.3, channels=1))
    assert project.data.active_take == 0
    assert project.active_vocal()[0].duration == pytest.approx(0.3, abs=0.02)


@pytest.mark.parametrize("fmt", ["wav", "flac", "mp3"])
def test_export_mix_formats(project, tmp_path, fmt):
    import_song(project, _write(tmp_path / "s.wav", 0.5))
    project.add_take(tone(0.3, 660, channels=1))
    out = exporter.export_project(project, "mix", tmp_path / f"mix.{fmt}")
    assert out.exists() and out.stat().st_size > 0


def test_export_vocal_and_song(project, tmp_path):
    import_song(project, _write(tmp_path / "s.wav", 0.6))
    project.add_take(tone(0.3, 660, channels=1), offset_sec=0.2)
    vocal = exporter.render(project, "vocal")
    assert vocal.duration == pytest.approx(0.5, abs=0.02)
    assert exporter.render(project, "song").duration == pytest.approx(0.6, abs=0.02)
    assert exporter.render(project, "mix").duration == pytest.approx(0.6, abs=0.02)


def test_export_without_content_explains(project, tmp_path):
    with pytest.raises(AppError):
        exporter.render(project, "mix")
    with pytest.raises(AppError):
        exporter.render(project, "vocal")
    with pytest.raises(AppError):
        exporter.render(project, "song")


def test_export_unknown_kind(project):
    with pytest.raises(AppError):
        exporter.render(project, "karaoke")


def test_exported_mix_does_not_clip(project, tmp_path):
    import_song(project, _write(tmp_path / "s.wav", 0.4, amp=0.95))
    project.add_take(tone(0.4, 660, channels=1, amp=0.95))
    assert float(np.max(np.abs(exporter.render(project, "mix").samples))) <= 1.0


def _write(path, seconds, sr=44100, channels=2, amp=0.5):
    save_audio(path, tone(seconds, 440, sr=sr, channels=channels, amp=amp), "wav")
    return path


# --- caché de análisis ---

def test_analysis_json_roundtrip(project):
    project.save_analysis_json("song_tempo_key", {"bpm": 120.0, "key_root": "C"})
    assert project.load_analysis_json("song_tempo_key") == {"bpm": 120.0, "key_root": "C"}


def test_analysis_json_missing_returns_none(project):
    assert project.load_analysis_json("nope") is None


def test_analysis_arrays_roundtrip(project):
    import numpy as np

    project.save_analysis_arrays("vocal_take1", times=np.array([0.0, 0.1]), f0=np.array([440.0, 442.0]))
    arrays = project.load_analysis_arrays("vocal_take1")
    assert arrays is not None
    np.testing.assert_allclose(arrays["times"], [0.0, 0.1])
    np.testing.assert_allclose(arrays["f0"], [440.0, 442.0])


def test_analysis_arrays_missing_returns_none(project):
    assert project.load_analysis_arrays("nope") is None


def test_clear_analysis_removes_both_files(project):
    import numpy as np

    project.save_analysis_json("vocal_take1", {"x": 1})
    project.save_analysis_arrays("vocal_take1", f0=np.array([1.0]))
    project.clear_analysis("vocal_take1")
    assert project.load_analysis_json("vocal_take1") is None
    assert project.load_analysis_arrays("vocal_take1") is None


def test_analysis_key_is_sanitized_for_filesystem(project):
    project.save_analysis_json("weird/key:name", {"ok": True})
    assert project.load_analysis_json("weird/key:name") == {"ok": True}


def test_set_song_clears_stale_song_analysis(project, tmp_path):
    project.save_analysis_json("song_tempo_key", {"bpm": 999})
    import_song(project, _write(tmp_path / "s.wav", 0.5))
    assert project.load_analysis_json("song_tempo_key") is None


def test_set_vocal_clears_stale_vocal_analysis(project, tmp_path):
    project.save_analysis_json("vocal_imported", {"stale": True})
    import_vocal(project, _write(tmp_path / "v.wav", 0.5, channels=1))
    assert project.load_analysis_json("vocal_imported") is None


def test_delete_take_clears_its_analysis(project):
    take = project.add_take(tone(0.3, 440, channels=1))
    project.save_analysis_json(f"vocal_take{take.id}", {"x": 1})
    project.delete_take(take.id)
    assert project.load_analysis_json(f"vocal_take{take.id}") is None
