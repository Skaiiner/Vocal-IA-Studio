from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.ai_coach_view import AiCoachView
from vocal_ai_studio.ui.pitch_editor_view import PitchEditorView
from vocal_ai_studio.ui.settings_view import SettingsView
from vocal_ai_studio.ui.song_view import SongView
from vocal_ai_studio.ui.voice_lab_view import VoiceLabView
from vocal_ai_studio.ui.voice_view import VoiceView
from vocal_ai_studio.ui.widgets import placeholder_tab, show_error

log = logging.getLogger(__name__)

FUTURE_TABS = [
    ("Live Voice", "Voz procesada en tiempo real hacia OBS y Discord. (Fase 7)",
     ["Entrada, salida, monitorización y latencia", "Bypass y mezcla Dry/Wet",
      "Micrófono virtual mediante VB-CABLE o VoiceMeeter", "Medidores de nivel y uso de CPU"]),
]


class MainWindow(QMainWindow):
    def __init__(self, session: Session, log_file: Path):
        super().__init__()
        self.session = session
        self.setWindowTitle("Vocal AI Studio")
        self.resize(1180, 760)
        self.setMinimumSize(900, 620)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("VOCAL AI STUDIO")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addSpacing(14)
        self.lbl_project = QLabel("")
        self.lbl_project.setObjectName("Subtitle")
        header.addWidget(self.lbl_project)
        header.addStretch(1)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.song_view = SongView(session)
        self.song_view.status.connect(self.show_status)
        self.song_view.project_changed.connect(self._update_project_label)
        self.song_view.project_changed.connect(self._on_project_data_changed)
        self.tabs.addTab(self.song_view, "Song")
        self.voice_view = VoiceView(session)
        self.voice_view.status.connect(self.show_status)
        self.tabs.addTab(self.voice_view, "Voice")
        self.pitch_editor_view = PitchEditorView(session)
        self.pitch_editor_view.status.connect(self.show_status)
        self.tabs.addTab(self.pitch_editor_view, "Pitch Editor")
        self.voice_lab_view = VoiceLabView(session)
        self.voice_lab_view.status.connect(self.show_status)
        self.tabs.addTab(self.voice_lab_view, "Voice Lab")
        self.ai_coach_view = AiCoachView(session)
        self.ai_coach_view.status.connect(self.show_status)
        self.tabs.addTab(self.ai_coach_view, "AI Coach")
        for name, desc, bullets in FUTURE_TABS:
            index = self.tabs.addTab(placeholder_tab(name, desc, bullets), name)
            self.tabs.setTabToolTip(index, "Llegará en una fase posterior")
        self.settings_view = SettingsView(session, log_file)
        self.settings_view.status.connect(self.show_status)
        self.tabs.addTab(self.settings_view, "Settings")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)

        self._build_menu()
        self.statusBar().showMessage("Listo.")
        self._update_project_label()

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self.settings_view.tick)
        self._timer.start()

    # --- menú ---
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Proyecto")
        for text, shortcut, slot in (
            ("Nuevo proyecto", QKeySequence.StandardKey.New, self.new_project),
            ("Abrir proyecto…", QKeySequence.StandardKey.Open, self.open_project),
            ("Guardar", QKeySequence.StandardKey.Save, self.save_project),
            ("Guardar como…", QKeySequence.StandardKey.SaveAs, self.save_project_as),
        ):
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("Salir", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        play_action = QAction("Reproducir / Pausa", self)
        play_action.setShortcut(Qt.Key.Key_Space)
        play_action.triggered.connect(self.song_view._toggle_play)
        self.addAction(play_action)

    # --- proyecto ---
    def new_project(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuevo proyecto", "Nombre del proyecto:", text="My Song Project")
        if not ok or not name.strip():
            return
        try:
            project = self.session.new_project(name.strip())
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo al crear el proyecto")
            show_error(self, exc, "Al crear el proyecto")
            return
        self.song_view.refresh()
        self.voice_view.refresh()
        self.pitch_editor_view.refresh()
        self.voice_lab_view.refresh()
        self.ai_coach_view.refresh()
        self._update_project_label()
        self.show_status(f"Proyecto creado en {project.root}")

    def open_project(self) -> None:
        start = str(self.session.settings.projects_path())
        path = QFileDialog.getExistingDirectory(self, "Abrir proyecto (carpeta con project.json)", start)
        if not path:
            return
        try:
            self.session.open_project(path)
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo al abrir el proyecto")
            show_error(self, exc, "Al abrir el proyecto")
            return
        self.song_view.refresh()
        self.voice_view.refresh()
        self.pitch_editor_view.refresh()
        self.voice_lab_view.refresh()
        self.ai_coach_view.refresh()
        self._update_project_label()
        self.show_status(f"Proyecto abierto: {path}")

    def save_project(self) -> None:
        if self.session.project is None:
            return
        try:
            self.session.project.save()
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Al guardar el proyecto")
            return
        self.show_status("Proyecto guardado.")

    def save_project_as(self) -> None:
        if self.session.project is None:
            return
        name, ok = QInputDialog.getText(self, "Guardar como", "Nombre del nuevo proyecto:",
                                        text=f"{self.session.project.name} copia")
        if not ok or not name.strip():
            return
        try:
            project = self.session.save_project_as(self.session.settings.projects_path(), name.strip())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Al guardar como")
            return
        self.song_view.refresh()
        self.voice_view.refresh()
        self.pitch_editor_view.refresh()
        self.voice_lab_view.refresh()
        self.ai_coach_view.refresh()
        self._update_project_label()
        self.show_status(f"Guardado como {project.root}")

    def _on_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.song_view:
            self.song_view.sync_devices()
        elif widget is self.voice_view:
            self.voice_view.refresh()
        elif widget is self.pitch_editor_view:
            self.pitch_editor_view.refresh()
        elif widget is self.voice_lab_view:
            self.voice_lab_view.refresh()
        elif widget is self.ai_coach_view:
            self.ai_coach_view.refresh()

    def _on_project_data_changed(self) -> None:
        self.voice_view.refresh()
        self.pitch_editor_view.refresh()
        self.voice_lab_view.refresh()
        self.ai_coach_view.refresh()

    def _update_project_label(self) -> None:
        project = self.session.project
        if project is None:
            self.lbl_project.setText("Sin proyecto — usa Proyecto ▸ Nuevo proyecto")
            return
        song = project.data.song_title or "sin canción"
        self.lbl_project.setText(f"{project.name}  ·  {song}  ·  {len(project.data.takes)} tomas")

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)
        log.info("%s", message)

    def closeEvent(self, event) -> None:
        try:
            if self.session.project is not None:
                self.session.project.save()
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo guardar al cerrar: %s", exc)
        self.session.close()
        super().closeEvent(event)
