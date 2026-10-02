from __future__ import annotations

import pytest

from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.lyrics.model import Lyrics, LyricLine, parse_text, read_lyrics_file
from vocal_ai_studio.session import Session
from vocal_ai_studio.core.config import Settings, SettingsStore


# --- modelo ---

def test_parse_plain_text_has_no_times():
    lyrics = parse_text("Primera linea\nSegunda linea\n\nTercera")
    assert [l.text for l in lyrics.lines] == ["Primera linea", "Segunda linea", "", "Tercera"]
    assert lyrics.synced is False
    assert all(l.time is None for l in lyrics.lines)


def test_parse_plain_text_trims_blank_edges():
    lyrics = parse_text("\n\nHola\nMundo\n\n\n")
    assert [l.text for l in lyrics.lines] == ["Hola", "Mundo"]


def test_parse_lrc_extracts_timestamps():
    raw = "[00:01.00]Primera linea\n[00:05.50]Segunda linea\n[01:02]Tercera"
    lyrics = parse_text(raw)
    assert [l.text for l in lyrics.lines] == ["Primera linea", "Segunda linea", "Tercera"]
    assert [l.time for l in lyrics.lines] == [1.0, 5.5, 62.0]
    assert lyrics.synced is True
    assert lyrics.synced_count == 3


def test_parse_lrc_sorts_by_time():
    raw = "[00:10.00]Segunda\n[00:01.00]Primera"
    lyrics = parse_text(raw)
    assert [l.text for l in lyrics.lines] == ["Primera", "Segunda"]


def test_current_index_follows_position():
    lyrics = Lyrics([LyricLine("A", 1.0), LyricLine("B", 5.0), LyricLine("C", 10.0)])
    assert lyrics.current_index(0.5) is None
    assert lyrics.current_index(1.0) == 0
    assert lyrics.current_index(4.9) == 0
    assert lyrics.current_index(5.0) == 1
    assert lyrics.current_index(99) == 2


def test_current_index_skips_unsynced_lines():
    lyrics = Lyrics([LyricLine("A", 1.0), LyricLine("B", None), LyricLine("C", 10.0)])
    assert lyrics.current_index(2.0) == 0
    assert lyrics.current_index(10.0) == 2


def test_lyrics_json_roundtrip():
    original = Lyrics([LyricLine("Hola", 1.5), LyricLine("Mundo", None)])
    restored = Lyrics.from_json(original.to_json())
    assert restored == original


def test_lyrics_to_plain_text():
    assert Lyrics([LyricLine("Uno"), LyricLine("Dos")]).to_plain_text() == "Uno\nDos"


def test_read_lyrics_file_missing(tmp_path):
    with pytest.raises(AppError):
        read_lyrics_file(tmp_path / "no.txt")


def test_read_lyrics_file_utf8(tmp_path):
    path = tmp_path / "letra.txt"
    path.write_text("Canción con ñ y acentós", encoding="utf-8")
    assert "ñ" in read_lyrics_file(path)


def test_read_lyrics_file_latin1_fallback(tmp_path):
    path = tmp_path / "letra.txt"
    path.write_bytes("Canción".encode("latin-1"))
    assert "Canci" in read_lyrics_file(path)


# --- proyecto ---

def test_project_set_and_load_lyrics(project):
    lyrics = Lyrics([LyricLine("Primera", 0.0), LyricLine("Segunda", 2.0)])
    project.set_lyrics(lyrics)
    assert project.data.lyrics_file == "lyrics.json"
    reopened_lyrics = project.load_lyrics()
    assert reopened_lyrics == lyrics


def test_project_load_lyrics_without_any_returns_none(project):
    assert project.load_lyrics() is None


def test_project_set_empty_lyrics_clears(project):
    project.set_lyrics(Lyrics([LyricLine("X", 0.0)]))
    project.set_lyrics(Lyrics([]))
    assert project.data.lyrics_file == ""
    assert project.load_lyrics() is None


def test_project_clear_lyrics_removes_file(project):
    project.set_lyrics(Lyrics([LyricLine("X")]))
    path = project.path("lyrics.json")
    assert path.exists()
    project.clear_lyrics()
    assert not path.exists()
    assert project.data.lyrics_file == ""


def test_project_lyrics_persist_across_reopen(project):
    project.set_lyrics(Lyrics([LyricLine("Hola", 1.0)]))
    from vocal_ai_studio.storage.project import Project

    reopened = Project.open(project.root)
    assert reopened.load_lyrics() == Lyrics([LyricLine("Hola", 1.0)])


# --- sesión ---

@pytest.fixture
def session(backend, tmp_path):
    settings = Settings(projects_dir=str(tmp_path / "Projects"))
    s = Session(backend, settings, SettingsStore(tmp_path / "settings.json"))
    s.new_project("Letra")
    yield s
    s.close()


def test_session_set_lyrics_text_plain(session):
    lyrics = session.set_lyrics_text("Linea uno\nLinea dos")
    assert [l.text for l in lyrics.lines] == ["Linea uno", "Linea dos"]
    assert session.load_lyrics() == lyrics


def test_session_set_lyrics_text_lrc(session):
    lyrics = session.set_lyrics_text("[00:00.00]Hola\n[00:03.00]Mundo")
    assert lyrics.synced is True
    assert session.load_lyrics().synced is True


def test_session_set_lyric_time_marks_single_line(session):
    session.set_lyrics_text("Uno\nDos\nTres")
    lyrics = session.set_lyric_time(1, 4.2)
    assert lyrics.lines[1].time == pytest.approx(4.2)
    assert lyrics.lines[0].time is None and lyrics.lines[2].time is None


def test_session_clear_lyrics_sync(session):
    session.set_lyrics_text("[00:01.00]Uno\n[00:02.00]Dos")
    lyrics = session.clear_lyrics_sync()
    assert lyrics.synced is False
    assert all(l.time is None for l in lyrics.lines)


def test_session_requires_project_for_lyrics(backend, tmp_path):
    settings = Settings(projects_dir=str(tmp_path / "P"))
    s = Session(backend, settings)
    with pytest.raises(AppError):
        s.set_lyrics_text("algo")
    s.close()
