# La aplicación nunca busca letras en Internet; el contenido lo aporta siempre el usuario.

from __future__ import annotations

import logging

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from vocal_ai_studio.lyrics.model import LYRICS_EXTENSIONS, read_lyrics_file
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui import theme
from vocal_ai_studio.ui.widgets import hint, show_error

log = logging.getLogger(__name__)
_FILTER = "Letras (" + " ".join(f"*{e}" for e in LYRICS_EXTENSIONS) + ");;Todos los archivos (*.*)"


class LyricsDialog(QDialog):
    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Editar letra")
        self.resize(560, 520)
        self.setStyleSheet(theme.STYLESHEET)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel("Letra de la canción")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        layout.addWidget(hint(
            "Pega aquí tu propia letra (una línea por frase), o impórtala de un archivo .txt o .lrc "
            "que ya tengas. Si el archivo trae marcas de tiempo tipo [00:12.50] se sincronizará sola; "
            "si no, podrás sincronizarla a mano después pulsando Marcar mientras suena la canción."
        ))

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Pega aquí la letra…")
        lyrics = self.session.load_lyrics()
        if lyrics and lyrics.lines:
            self.editor.setPlainText(lyrics.to_plain_text())
        layout.addWidget(self.editor, 1)

        buttons = QHBoxLayout()
        btn_import = QPushButton("Importar archivo…")
        btn_import.clicked.connect(self._import_file)
        buttons.addWidget(btn_import)
        buttons.addStretch(1)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Guardar")
        btn_save.setObjectName("Primary")
        btn_save.clicked.connect(self._save)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_save)
        layout.addLayout(buttons)

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar letra", "", _FILTER)
        if not path:
            return
        try:
            text = read_lyrics_file(path)
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo al importar la letra")
            show_error(self, exc, "Al importar la letra")
            return
        self.editor.setPlainText(text)

    def _save(self) -> None:
        try:
            self.session.set_lyrics_text(self.editor.toPlainText())
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo al guardar la letra")
            show_error(self, exc, "Al guardar la letra")
            return
        self.accept()
