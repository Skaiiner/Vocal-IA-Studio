from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from vocal_ai_studio.session import Session
from vocal_ai_studio.song_import.sources import SearchResult, SongSource
from vocal_ai_studio.ui import theme
from vocal_ai_studio.ui.background import BackgroundTask
from vocal_ai_studio.ui.widgets import hint, show_error
from vocal_ai_studio.youtube.source import AVISO_LEGAL

log = logging.getLogger(__name__)


class SearchDialog(QDialog):
    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Buscar canción")
        self.resize(720, 540)
        self.setStyleSheet(theme.STYLESHEET)
        self._task = BackgroundTask()
        self._pending_error: Exception | None = None
        self._results: list[SearchResult] = []
        self.imported_title: str | None = None
        self._build()
        self._update_source_hint()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("¿Qué canción quieres cantar?")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        row = QHBoxLayout()
        self.cmb_source = QComboBox()
        for source in self.session.sources():
            self.cmb_source.addItem(source.name, source)
        self.cmb_source.currentIndexChanged.connect(self._update_source_hint)
        self.field = QLineEdit()
        self.field.setPlaceholderText("Título, artista… o pega una URL de YouTube")
        self.field.returnPressed.connect(self._search)
        self.btn_search = QPushButton("Buscar")
        self.btn_search.setObjectName("Primary")
        self.btn_search.clicked.connect(self._search)
        row.addWidget(self.cmb_source)
        row.addWidget(self.field, 1)
        row.addWidget(self.btn_search)
        layout.addLayout(row)

        self.lbl_source = hint("")
        layout.addWidget(self.lbl_source)

        self.results = QListWidget()
        self.results.itemSelectionChanged.connect(self._update_buttons)
        self.results.itemDoubleClicked.connect(lambda _: self._import())
        layout.addWidget(self.results, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("Hint")
        buttons.addWidget(self.lbl_status, 1)
        self.btn_cancel_task = QPushButton("Cancelar")
        self.btn_cancel_task.setVisible(False)
        self.btn_cancel_task.clicked.connect(self._cancel_task)
        self.btn_import = QPushButton("Usar esta canción")
        self.btn_import.setObjectName("Primary")
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self._import)
        self.btn_close = QPushButton("Cerrar")
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_cancel_task, self.btn_import, self.btn_close):
            buttons.addWidget(b)
        layout.addLayout(buttons)

    # --- fuente seleccionada ---
    def _source(self) -> SongSource:
        return self.cmb_source.currentData()

    def _update_source_hint(self) -> None:
        source = self._source()
        available, reason = source.is_available()
        if source.name == "YouTube" and available:
            self.lbl_source.setText(AVISO_LEGAL)
        elif available:
            folders = ", ".join(p.name for p in self.session.settings.music_paths())
            self.lbl_source.setText(f"Buscando en: {folders}")
        else:
            self.lbl_source.setText(reason)
        self.btn_search.setEnabled(available)
        self.field.setEnabled(available)

    # --- búsqueda ---
    def _search(self) -> None:
        query = self.field.text().strip()
        if not query or self._task.running:
            return
        source = self._source()
        self.results.clear()
        self._results = []
        self._start(
            lambda progress, cancelled: source.search(query, 25, cancelled),
            busy_text=f"Buscando «{query}»…",
            on_success=self._show_results,
            indeterminate=True,
        )

    def _show_results(self, results: list[SearchResult]) -> None:
        self._results = results
        for r in results:
            item = QListWidgetItem(f"{r.title}\n{r.subtitle}")
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.results.addItem(item)
        if not results:
            self.lbl_status.setText("Sin resultados. Prueba con otras palabras.")
        else:
            self.lbl_status.setText(f"{len(results)} resultados. Doble clic para usar uno.")
            self.results.setCurrentRow(0)

    # --- importación ---
    def _import(self) -> None:
        item = self.results.currentItem()
        if item is None or self._task.running:
            return
        result: SearchResult = item.data(Qt.ItemDataRole.UserRole)
        source = self._source()
        self._start(
            lambda progress, cancelled: self.session.import_search_result(result, source, progress, cancelled),
            busy_text=f"Preparando «{result.title}»…",
            on_success=lambda _audio: self._finish_import(result),
            indeterminate=False,
        )

    def _finish_import(self, result: SearchResult) -> None:
        # Se guarda el título; el diálogo se cierra al terminar el hilo, no antes.
        self.imported_title = result.title

    # --- tarea en segundo plano ---
    def _start(self, job, busy_text: str, on_success, indeterminate: bool) -> None:
        self.lbl_status.setText(busy_text)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0 if indeterminate else 100)
        self.progress.setValue(0)
        self.btn_cancel_task.setVisible(True)
        self._set_busy(True)
        self._pending_error = None
        self._task.start(
            job, on_progress=self._on_progress, on_success=on_success,
            on_failure=self._on_failed, on_cancelled=self._on_cancelled, on_finished=self._on_thread_finished,
        )

    def _on_thread_finished(self) -> None:
        self.progress.setVisible(False)
        self.btn_cancel_task.setVisible(False)
        self._set_busy(False)
        error, self._pending_error = self._pending_error, None
        if error is not None:
            self.lbl_status.setText("No se pudo completar.")
            show_error(self, error, "Al buscar la canción")
        elif self.imported_title is not None:
            self.accept()

    def _on_progress(self, fraction: float, message: str) -> None:
        if self.progress.maximum() != 0:
            self.progress.setValue(int(fraction * 100))
        self.lbl_status.setText(message)

    def _on_failed(self, exc: Exception) -> None:
        # El diálogo de error se muestra cuando el hilo ya ha terminado, no desde el callback.
        self._pending_error = exc

    def _on_cancelled(self) -> None:
        self.lbl_status.setText("Cancelado.")

    def _cancel_task(self) -> None:
        self._task.cancel()
        self.lbl_status.setText("Cancelando…")

    def _set_busy(self, busy: bool) -> None:
        self.btn_search.setEnabled(not busy)
        self.cmb_source.setEnabled(not busy)
        self.field.setEnabled(not busy)
        self.btn_close.setEnabled(not busy)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.btn_import.setEnabled(not self._task.running and self.results.currentItem() is not None)

    def closeEvent(self, event) -> None:
        self._cancel_task()
        self._task.wait()
        super().closeEvent(event)
