from __future__ import annotations

from pathlib import Path

import pytest

from vocal_ai_studio.audio.io import save_audio
from vocal_ai_studio.core.config import Settings, SettingsStore
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.session import Session
from vocal_ai_studio.song_import.sources import LocalLibrarySource, SearchCancelled, SearchResult
from vocal_ai_studio.youtube.source import YouTubeSource
from tests.conftest import tone


@pytest.fixture
def library(tmp_path) -> Path:
    root = tmp_path / "Music"
    for artist, titles in {"Queen": ["Bohemian Rhapsody", "Somebody To Love"],
                           "Adele": ["Hello", "Someone Like You"]}.items():
        (root / artist).mkdir(parents=True)
        for title in titles:
            save_audio(root / artist / f"{title}.mp3", tone(0.2, 440, channels=2), "mp3")
    (root / "notas.txt").write_text("no es audio", encoding="utf-8")
    return root


def test_local_search_finds_by_title(library):
    results = LocalLibrarySource([library]).search("hello")
    assert len(results) == 1
    assert results[0].title == "Hello" and results[0].artist == "Adele"


def test_local_search_matches_all_words_in_any_order(library):
    source = LocalLibrarySource([library])
    assert len(source.search("queen love")) == 1
    assert len(source.search("love queen")) == 1
    assert source.search("queen hello") == []


def test_local_search_ignores_non_audio_files(library):
    assert all(not r.title.startswith("notas") for r in LocalLibrarySource([library]).search(""))


def test_local_search_empty_query_lists_everything(library):
    assert len(LocalLibrarySource([library]).search("")) == 4


def test_local_search_respects_limit(library):
    assert len(LocalLibrarySource([library]).search("", limit=2)) == 2


def test_local_search_can_be_cancelled(library):
    with pytest.raises(SearchCancelled):
        LocalLibrarySource([library]).search("", cancelled=lambda: True)


def test_local_source_unavailable_without_folders(tmp_path):
    ok, reason = LocalLibrarySource([tmp_path / "no-existe"]).is_available()
    assert ok is False and "Ajustes" in reason


def test_local_fetch_returns_original_path(library, tmp_path):
    source = LocalLibrarySource([library])
    result = source.search("hello")[0]
    assert source.fetch(result, tmp_path / "dl") == Path(result.ref)


def test_local_fetch_explains_missing_file(library, tmp_path):
    source = LocalLibrarySource([library])
    result = source.search("hello")[0]
    Path(result.ref).unlink()
    with pytest.raises(AppError):
        source.fetch(result, tmp_path / "dl")


def test_youtube_disabled_by_default():
    ok, reason = YouTubeSource(enabled=False).is_available()
    assert ok is False and "Privacidad" in reason


def test_youtube_refuses_to_search_when_disabled():
    with pytest.raises(AppError) as err:
        YouTubeSource(enabled=False).search("algo")
    assert "Ajustes" in err.value.user_message()


def test_youtube_available_when_enabled():
    ok, _ = YouTubeSource(enabled=True).is_available()
    assert ok is True  # yt-dlp está instalado


@pytest.mark.parametrize("message,expected", [
    ("Sign in to confirm your age", "restricciones de acceso"),
    ("Video unavailable", "ya no está disponible"),
    ("[Errno 11001] getaddrinfo failed", "sin conexión"),
    ("Something odd happened", "No se pudo"),
])
def test_youtube_errors_are_explained(message, expected):
    from vocal_ai_studio.youtube.source import _explain_ydl

    err = _explain_ydl(Exception(message), "descargar el audio")
    assert expected in err.user_message()
    assert err.fix


class _FakeYdl:
    def __init__(self, dest: Path, written: int, reported: int, attempts: list):
        self.dest, self.written, self.reported, self.attempts = dest, written, reported, attempts

    def __call__(self, opts):
        self.opts = opts
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=True):
        self.attempts.append(url)
        path = self.dest / "vid.webm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * self.written)
        self._path = path
        return {"id": "vid", "ext": "webm", "filesize": self.reported}

    def prepare_filename(self, info):
        return str(self._path)


def _patch_ydl(monkeypatch, fake):
    import types

    import vocal_ai_studio.youtube.source as mod

    monkeypatch.setattr(mod, "_ydl", lambda: types.SimpleNamespace(YoutubeDL=fake))


def test_download_accepts_complete_file(tmp_path, monkeypatch):
    attempts: list = []
    _patch_ydl(monkeypatch, _FakeYdl(tmp_path / "dl", written=1000, reported=1000, attempts=attempts))
    source = YouTubeSource(enabled=True)
    result = SearchResult("Canción", "YouTube", "http://x", duration=100)
    path = source.fetch(result, tmp_path / "dl")
    assert path.stat().st_size == 1000
    assert len(attempts) == 1


def test_download_retries_once_then_reports_truncation(tmp_path, monkeypatch):
    attempts: list = []
    _patch_ydl(monkeypatch, _FakeYdl(tmp_path / "dl", written=100, reported=10_000, attempts=attempts))
    source = YouTubeSource(enabled=True)
    result = SearchResult("Canción", "YouTube", "http://x", duration=600)
    with pytest.raises(AppError) as err:
        source.fetch(result, tmp_path / "dl")
    assert len(attempts) == 2                       # reintentó una vez
    message = err.value.user_message()
    assert "incompleta" in message and "cortada" in message
    assert err.value.fix


def test_download_accepts_small_difference(tmp_path, monkeypatch):
    attempts: list = []
    _patch_ydl(monkeypatch, _FakeYdl(tmp_path / "dl", written=900, reported=1000, attempts=attempts))
    path = YouTubeSource(enabled=True).fetch(SearchResult("C", "YouTube", "http://x"), tmp_path / "dl")
    assert path.exists() and len(attempts) == 1


def test_download_reports_progress(tmp_path, monkeypatch):
    _patch_ydl(monkeypatch, _FakeYdl(tmp_path / "dl", written=1000, reported=1000, attempts=[]))
    steps: list = []
    YouTubeSource(enabled=True).fetch(SearchResult("C", "YouTube", "http://x"), tmp_path / "dl",
                                      progress=lambda f, m: steps.append((f, m)))
    assert steps[0][0] < 0.1 and steps[-1][0] == 1.0


def test_search_result_subtitle():
    r = SearchResult("Hello", "YouTube", "http://x", artist="Adele", duration=295)
    assert r.duration_text == "4:55"
    assert "Adele" in r.subtitle and "YouTube" in r.subtitle
    assert SearchResult("X", "Y", "z").duration_text == "—"


def test_session_sources_reflect_privacy_setting(backend, tmp_path):
    settings = Settings(projects_dir=str(tmp_path / "P"), music_folders=[str(tmp_path)])
    session = Session(backend, settings, SettingsStore(tmp_path / "s.json"))
    names = [s.name for s in session.sources()]
    assert names == ["Mi música", "YouTube"]
    assert session.sources()[1].is_available()[0] is False
    settings.allow_youtube = True
    assert session.sources()[1].is_available()[0] is True
    session.close()


def test_session_imports_search_result(backend, tmp_path, library):
    settings = Settings(projects_dir=str(tmp_path / "P"), music_folders=[str(library)])
    session = Session(backend, settings, SettingsStore(tmp_path / "s.json"))
    session.new_project("Busqueda")
    source = session.sources()[0]
    result = source.search("bohemian")[0]
    steps: list[tuple[float, str]] = []
    audio = session.import_search_result(result, source, progress=lambda f, m: steps.append((f, m)))
    assert audio.duration > 0.1
    assert session.project.data.song_title == "Bohemian Rhapsody"
    assert session.player.duration > 0.1
    assert steps and steps[-1][0] == 1.0
    assert not session.project.path(".download").exists()
    session.close()


def test_session_import_requires_project(backend, tmp_path, library):
    settings = Settings(projects_dir=str(tmp_path / "P"), music_folders=[str(library)])
    session = Session(backend, settings, SettingsStore(tmp_path / "s.json"))
    source = session.sources()[0]
    with pytest.raises(AppError):
        session.import_search_result(source.search("hello")[0], source)
    session.close()


def test_music_paths_default_and_configured(tmp_path):
    assert Settings(music_folders=[str(tmp_path)]).music_paths() == [tmp_path]
    for path in Settings().music_paths():
        assert path.exists()
