from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from vocal_ai_studio.core.config import SettingsStore, data_dir, load_dotenv
from vocal_ai_studio.core.hardware import detect_hardware
from vocal_ai_studio.core.logging_setup import setup_logging

log = logging.getLogger(__name__)


def _install_excepthook(log_file: Path) -> None:
    # un error inesperado no debe cerrar la app en silencio
    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Error no controlado:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        try:
            from PySide6.QtWidgets import QApplication

            from vocal_ai_studio.ui.widgets import show_error

            if QApplication.instance() is not None:
                show_error(None, exc, "Error inesperado")
        except Exception:  # noqa: BLE001
            print(f"Error inesperado: {exc}\nDetalles en {log_file}", file=sys.stderr)

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    home = data_dir()
    log_file = setup_logging(home / "logs")
    load_dotenv(home / ".env")
    log.info("--- Vocal AI Studio ---")
    log.info("%s", detect_hardware().summary().replace("\n", " | "))

    from PySide6.QtWidgets import QApplication

    from vocal_ai_studio.audio.backends import SoundDeviceBackend
    from vocal_ai_studio.session import Session
    from vocal_ai_studio.ui import theme
    from vocal_ai_studio.ui.main_window import MainWindow
    from vocal_ai_studio.ui.widgets import show_error

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Vocal AI Studio")
    app.setStyleSheet(theme.STYLESHEET)
    _install_excepthook(log_file)

    store = SettingsStore(home / "settings.json")
    settings = store.load()
    session = Session(SoundDeviceBackend(), settings, store)

    window = MainWindow(session, log_file)
    window.show()

    # Reabrir el último proyecto; si no existe, crear uno para poder empezar a trabajar ya.
    try:
        last = Path(settings.last_project) if settings.last_project else None
        if last and (last / "project.json").exists():
            session.open_project(last)
            window.show_status(f"Proyecto reabierto: {session.project.name}")  # type: ignore[union-attr]
        else:
            session.new_project("My Song Project")
            window.show_status(f"Proyecto nuevo creado en {session.project.root}")  # type: ignore[union-attr]
        window.song_view.refresh()
        window.voice_view.refresh()
        window.pitch_editor_view.refresh()
        window._update_project_label()
    except Exception as exc:  # noqa: BLE001
        log.exception("No se pudo preparar el proyecto inicial")
        show_error(window, exc, "Al preparar el proyecto inicial")

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
