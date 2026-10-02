from __future__ import annotations

import logging
from pathlib import Path

import pytest

from vocal_ai_studio.audio.ffmpeg_locator import find_ffmpeg
from vocal_ai_studio.core.config import Settings, SettingsStore, load_dotenv
from vocal_ai_studio.core.errors import AppError, explain_exception
from vocal_ai_studio.core.hardware import detect_hardware
from vocal_ai_studio.core.logging_setup import setup_logging


def test_settings_roundtrip(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    s = store.load()
    assert s.allow_external_services is False  # privacidad: local por defecto
    s.input_device = "Mic [WASAPI]"
    s.input_gain = 1.5
    store.save(s)
    assert store.load().input_device == "Mic [WASAPI]"
    assert store.load().input_gain == pytest.approx(1.5)


def test_settings_tolerates_corrupt_file(tmp_path, caplog):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        s = SettingsStore(path).load()
    assert s.sample_rate == 44100


def test_settings_ignores_unknown_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"input_device": "X", "obsolete": 1}', encoding="utf-8")
    assert SettingsStore(path).load().input_device == "X"


def test_settings_projects_path_default():
    assert Settings().projects_path().name == "Projects"
    assert Settings(projects_dir="D:/Proyectos").projects_path() == Path("D:/Proyectos")


def test_load_dotenv_does_not_override_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('A_KEY="from-file"\nB_KEY=other\n# comment\n', encoding="utf-8")
    monkeypatch.setenv("A_KEY", "from-env")
    load_dotenv(env)
    import os

    assert os.environ["A_KEY"] == "from-env"
    assert os.environ["B_KEY"] == "other"


def test_logging_writes_file(tmp_path):
    log_file = setup_logging(tmp_path / "logs", console=False)
    logging.getLogger("test").info("hola mundo")
    logging.shutdown()
    assert "hola mundo" in log_file.read_text(encoding="utf-8")


def test_app_error_message_has_three_parts():
    err = AppError("Falló X.", "Porque Y.", "Haz Z.")
    msg = err.user_message()
    assert "Falló X." in msg and "Posible causa" in msg and "Cómo solucionarlo" in msg


@pytest.mark.parametrize("exc", [FileNotFoundError("x"), PermissionError("x"), ValueError("x"), MemoryError()])
def test_explain_exception_always_actionable(exc):
    err = explain_exception(exc, "Al importar")
    assert err.fix and err.what


def test_explain_exception_passes_through_app_error():
    original = AppError("a", "b", "c")
    assert explain_exception(original) is original


def test_detect_hardware_never_raises():
    info = detect_hardware()
    assert info.os and info.recommended_device in ("cpu", "cuda")
    assert "Dispositivo de IA recomendado" in info.summary()


def test_ffmpeg_is_available():
    assert Path(find_ffmpeg()).exists()
