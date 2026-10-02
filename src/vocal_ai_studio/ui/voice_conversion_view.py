from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.background import BackgroundTask
from vocal_ai_studio.ui.widgets import hint, panel, show_error

log = logging.getLogger(__name__)

AVISO_LEGAL_CONVERSION = (
    "La conversión de voz solo debe usarse con voces propias o con autorización explícita de la "
    "persona cuya voz quieras imitar. No la emplees para suplantar a terceros ni para contenido "
    "engañoso. El procesamiento es local: el modelo y el audio no salen de este equipo."
)


def _path_row(label: str, placeholder: str) -> tuple[QHBoxLayout, QLineEdit, QPushButton]:
    row = QHBoxLayout()
    row.addWidget(QLabel(label))
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    btn = QPushButton("Examinar…")
    row.addWidget(field, 1)
    row.addWidget(btn)
    return row, field, btn


class VoiceConversionView(QWidget):
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

        legal_panel, legal_box = panel("Aviso legal")
        legal_box.addWidget(hint(AVISO_LEGAL_CONVERSION))
        root.addWidget(legal_panel)

        model_panel, model_box = panel("Modelo")
        model_row, self.model_path, self.btn_model = _path_row(
            "Modelo (.pth):", "Ruta al checkpoint entrenado")
        self.btn_model.clicked.connect(lambda: self._browse(self.model_path, "Modelo RVC", "Modelos (*.pth)"))
        model_box.addLayout(model_row)
        index_row, self.index_path, self.btn_index = _path_row(
            "Índice (opcional):", "Índice .index para mayor fidelidad")
        self.btn_index.clicked.connect(lambda: self._browse(self.index_path, "Índice de retrieval", "Índices (*.index)"))
        model_box.addLayout(index_row)
        root.addWidget(model_panel)

        params_panel, params_box = panel("Parámetros")
        transpose_row = QHBoxLayout()
        transpose_row.addWidget(QLabel("Transposición (semitonos):"))
        self.spin_transpose = QSpinBox()
        self.spin_transpose.setRange(-24, 24)
        self.spin_transpose.setValue(0)
        transpose_row.addWidget(self.spin_transpose)
        transpose_row.addStretch(1)
        params_box.addLayout(transpose_row)

        def spin_row(label, lo, hi, default, step=0.05):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setDecimals(2)
            spin.setValue(default)
            row.addWidget(spin)
            row.addStretch(1)
            params_box.addLayout(row)
            return spin

        self.spin_protect = spin_row("Protección de consonantes (protect):", 0.0, 0.5, 0.33)
        self.spin_index_rate = spin_row("Peso del índice (index rate):", 0.0, 1.0, 0.0)
        self.spin_rms_mix = spin_row("Mezcla de volumen (rms mix rate):", 0.0, 1.0, 1.0)
        root.addWidget(params_panel)

        toolbar_panel, toolbar_box = panel()
        toolbar_row = QHBoxLayout()
        self.btn_convert = QPushButton("Convertir voz")
        self.btn_convert.setObjectName("Primary")
        self.btn_convert.clicked.connect(self._convert)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._task.cancel)
        toolbar_row.addWidget(self.btn_convert)
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

        root.addStretch(1)

    def _browse(self, field: QLineEdit, title: str, filter_: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, "", filter_)
        if path:
            field.setText(path)

    def _convert(self) -> None:
        if self._task.running:
            return
        model_path = self.model_path.text().strip()
        if not model_path:
            show_error(self, AppError(
                "Falta el modelo de voz.", "No se eligió ningún archivo .pth.",
                "Pulsa Examinar y selecciona un modelo RVC entrenado.",
            ), "Conversión de voz")
            return
        index_path = self.index_path.text().strip() or None
        transpose = float(self.spin_transpose.value())
        protect = self.spin_protect.value()
        index_rate = self.spin_index_rate.value()
        rms_mix_rate = self.spin_rms_mix.value()

        def job(progress, cancelled):
            return self.session.convert_voice(
                model_path=model_path, index_path=index_path, transpose=transpose,
                protect=protect, index_rate=index_rate, rms_mix_rate=rms_mix_rate,
                progress=progress, cancelled=cancelled,
            )

        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_cancel.setVisible(True)
        self.btn_convert.setEnabled(False)
        self.lbl_status.setText("Convirtiendo…")
        self._task.start(
            job, on_progress=self._on_progress, on_success=self._on_success,
            on_failure=self._on_failure, on_cancelled=self._on_cancelled,
            on_finished=self._on_finished,
        )

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(fraction * 100))
        if message:
            self.lbl_status.setText(message)

    def _on_success(self, take) -> None:
        self.status.emit(f"Conversión de voz completada → '{take.name}'")
        self.lbl_status.setText(f"Listo: {take.name}")

    def _on_failure(self, exc: Exception) -> None:
        log.exception("Fallo en conversión de voz")
        show_error(self, exc, "Conversión de voz")

    def _on_cancelled(self) -> None:
        self.lbl_status.setText("Cancelado.")

    def _on_finished(self) -> None:
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_convert.setEnabled(True)

    def refresh(self) -> None:
        if self.session.project is None:
            self.btn_convert.setEnabled(False)
            return
        has_vocal = self.session.project.active_vocal() is not None
        self.btn_convert.setEnabled(has_vocal and not self._task.running)
