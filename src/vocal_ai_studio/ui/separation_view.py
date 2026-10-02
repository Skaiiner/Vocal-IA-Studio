from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.background import BackgroundTask
from vocal_ai_studio.ui.widgets import hint, panel, show_error

log = logging.getLogger(__name__)


class SeparationView(QWidget):
    status = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._task = BackgroundTask()
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        intro_panel, intro_box = panel("Separar voz / instrumental")
        intro_box.addWidget(hint(
            "Separa la canción importada en pista vocal e instrumental usando Demucs. "
            "El primer uso descarga el modelo (se queda en el disco D:)."
        ))
        root.addWidget(intro_panel)

        toolbar_panel, toolbar_box = panel()
        toolbar_row = QHBoxLayout()
        self.btn_separate = QPushButton("Separar canción")
        self.btn_separate.setObjectName("Primary")
        self.btn_separate.clicked.connect(self._separate)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._task.cancel)
        toolbar_row.addWidget(self.btn_separate)
        toolbar_row.addWidget(self.btn_cancel)
        toolbar_row.addStretch(1)
        toolbar_box.addLayout(toolbar_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        toolbar_box.addWidget(self.progress)
        self.lbl_status = hint("")
        toolbar_box.addWidget(self.lbl_status)
        root.addWidget(toolbar_panel)

        use_panel, use_box = panel("Usar resultado")
        use_row = QHBoxLayout()
        self.btn_use_vocals = QPushButton("Usar voz separada como toma")
        self.btn_use_vocals.clicked.connect(self._use_vocals)
        self.btn_use_instrumental = QPushButton("Usar instrumental como canción")
        self.btn_use_instrumental.clicked.connect(self._use_instrumental)
        use_row.addWidget(self.btn_use_vocals)
        use_row.addWidget(self.btn_use_instrumental)
        use_row.addStretch(1)
        use_box.addLayout(use_row)
        use_box.addWidget(hint("Disponible después de separar la canción."))
        root.addWidget(use_panel)

        root.addStretch(1)

    def _separate(self) -> None:
        if self._task.running:
            return

        def job(progress, cancelled):
            return self.session.separate_song(progress=progress, cancelled=cancelled)

        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_cancel.setVisible(True)
        self.btn_separate.setEnabled(False)
        self.lbl_status.setText("Separando…")
        self._task.start(
            job, on_progress=self._on_progress, on_success=self._on_success,
            on_failure=self._on_failure, on_cancelled=self._on_cancelled,
            on_finished=self._on_finished,
        )

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(fraction * 100))
        if message:
            self.lbl_status.setText(message)

    def _on_success(self, stems: dict) -> None:
        self.status.emit("Separación completada.")
        self.lbl_status.setText("Listo: voz e instrumental separados.")
        self._update_use_buttons()

    def _on_failure(self, exc: Exception) -> None:
        log.exception("Fallo en separación de voz/instrumental")
        show_error(self, exc, "Separación voz/instrumental")

    def _on_cancelled(self) -> None:
        self.lbl_status.setText("Cancelado.")

    def _on_finished(self) -> None:
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_separate.setEnabled(True)

    def _use_vocals(self) -> None:
        try:
            take = self.session.use_separated_vocals_as_take()
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Al usar la voz separada")
            return
        self.status.emit(f"Voz separada añadida como toma → '{take.name}'")

    def _use_instrumental(self) -> None:
        try:
            self.session.use_separated_instrumental_as_song()
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Al usar el instrumental separado")
            return
        self.status.emit("Instrumental separado usado como canción.")

    def _update_use_buttons(self) -> None:
        has_separation = self.session.project is not None and self.session.load_separation() is not None
        self.btn_use_vocals.setEnabled(has_separation)
        self.btn_use_instrumental.setEnabled(has_separation)

    def refresh(self) -> None:
        if self.session.project is None:
            self.btn_separate.setEnabled(False)
            self.btn_use_vocals.setEnabled(False)
            self.btn_use_instrumental.setEnabled(False)
            return
        has_song = self.session.project.load_song() is not None
        self.btn_separate.setEnabled(has_song and not self._task.running)
        self._update_use_buttons()
