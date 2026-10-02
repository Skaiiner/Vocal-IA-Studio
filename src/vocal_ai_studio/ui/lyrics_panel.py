from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from vocal_ai_studio.lyrics.model import Lyrics
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.widgets import hint, panel, show_error

log = logging.getLogger(__name__)
_PLACEHOLDER = "Sin letra todavía.\nPulsa “Editar letra” para pegarla o importarla."


class LyricsPanel(QWidget):
    status = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._lyrics: Lyrics | None = None
        self._syncing = False
        self._sync_index = 0
        self._last_highlight: int | None = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        frame, box = panel("Letra")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        box.addWidget(self.list, 1)

        self.lbl_hint = hint("")
        box.addWidget(self.lbl_hint)

        self.row_normal = QHBoxLayout()
        self.btn_edit = QPushButton("Editar letra")
        self.btn_edit.clicked.connect(self._edit)
        self.btn_sync = QPushButton("Sincronizar")
        self.btn_sync.clicked.connect(self._start_sync)
        self.btn_unsync = QPushButton("Quitar sincronización")
        self.btn_unsync.clicked.connect(self._clear_sync)
        for b in (self.btn_edit, self.btn_sync, self.btn_unsync):
            self.row_normal.addWidget(b)
        box.addLayout(self.row_normal)

        self.row_sync = QHBoxLayout()
        self.btn_mark = QPushButton("Marcar (↵)")
        self.btn_mark.setObjectName("Primary")
        self.btn_mark.clicked.connect(self._mark)
        self.btn_undo = QPushButton("Deshacer")
        self.btn_undo.clicked.connect(self._undo_mark)
        self.btn_finish = QPushButton("Terminar")
        self.btn_finish.clicked.connect(self._finish_sync)
        for b in (self.btn_mark, self.btn_undo, self.btn_finish):
            self.row_sync.addWidget(b)
            b.setVisible(False)
        box.addLayout(self.row_sync)

    # --- datos ---
    def refresh(self) -> None:
        self._lyrics = self.session.load_lyrics()
        self._last_highlight = None
        self.list.clear()
        has_lines = bool(self._lyrics and self._lyrics.lines)
        if not has_lines:
            self.list.addItem(_PLACEHOLDER)
        else:
            for line in self._lyrics.lines:
                self.list.addItem(QListWidgetItem(line.text or " "))
        self._update_hint()
        self._update_buttons()

    def _update_hint(self) -> None:
        if not self._lyrics or not self._lyrics.lines:
            self.lbl_hint.setText("")
        elif self._syncing:
            self.lbl_hint.setText(f"Sincronizando… línea {self._sync_index + 1} de {len(self._lyrics.lines)}")
        elif self._lyrics.synced:
            self.lbl_hint.setText(f"Sincronizada: {self._lyrics.synced_count} de {len(self._lyrics.lines)} líneas.")
        else:
            self.lbl_hint.setText("Sin sincronizar: se mostrará entera, sin resaltar la línea actual.")

    def _update_buttons(self) -> None:
        has_lines = bool(self._lyrics and self._lyrics.lines)
        for b in (self.btn_edit, self.btn_sync):
            b.setVisible(not self._syncing)
            b.setEnabled(not self._syncing)
        self.btn_sync.setEnabled(not self._syncing and has_lines)
        self.btn_unsync.setVisible(bool(self._lyrics and self._lyrics.synced) and not self._syncing)
        for b in (self.btn_mark, self.btn_undo, self.btn_finish):
            b.setVisible(self._syncing)
        self.btn_undo.setEnabled(self._sync_index > 0)

    # --- edición ---
    def _edit(self) -> None:
        from vocal_ai_studio.ui.lyrics_dialog import LyricsDialog
        from PySide6.QtWidgets import QDialog

        dialog = LyricsDialog(self.session, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.status.emit("Letra guardada.")

    # --- sincronización ---
    def _start_sync(self) -> None:
        if not self._lyrics or not self._lyrics.lines:
            return
        self._syncing = True
        self._sync_index = 0
        try:
            self.session.clear_lyrics_sync()
            self.session.seek(0.0)
            self.session.play()
        except Exception as exc:  # noqa: BLE001
            self._syncing = False
            show_error(self, exc, "Al iniciar la sincronización")
            return
        self.refresh()
        self._syncing = True  # refresh() no lo toca, pero se reafirma por claridad
        self.list.setCurrentRow(0)
        self._update_hint()
        self._update_buttons()
        self.status.emit("Pulsa Marcar (o Enter) justo cuando empiece cada línea.")
        self.setFocus()

    def _mark(self) -> None:
        if not self._syncing or self._lyrics is None or self._sync_index >= len(self._lyrics.lines):
            return
        self._lyrics = self.session.set_lyric_time(self._sync_index, self.session.player.position)
        self._sync_index += 1
        if self._sync_index >= len(self._lyrics.lines):
            self._finish_sync()
        else:
            self.list.setCurrentRow(self._sync_index)
            self._update_hint()
            self._update_buttons()

    def _undo_mark(self) -> None:
        if self._sync_index <= 0 or self._lyrics is None:
            return
        self._sync_index -= 1
        self._lyrics = self.session.set_lyric_time(self._sync_index, None)
        self.list.setCurrentRow(self._sync_index)
        self._update_hint()
        self._update_buttons()

    def _finish_sync(self) -> None:
        self._syncing = False
        self.session.pause()
        self.refresh()
        self.status.emit("Sincronización terminada.")

    def _clear_sync(self) -> None:
        self._lyrics = self.session.clear_lyrics_sync()
        self.refresh()
        self.status.emit("Sincronización eliminada: la letra se mostrará entera.")

    # --- reproducción ---
    def tick(self, position: float) -> None:
        if self._syncing or not self._lyrics or not self._lyrics.synced:
            return
        idx = self._lyrics.current_index(position)
        if idx is not None and idx != self._last_highlight:
            self.list.setCurrentRow(idx)
            self._last_highlight = idx

    def keyPressEvent(self, event) -> None:
        if self._syncing and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._mark()
            event.accept()
            return
        super().keyPressEvent(event)
