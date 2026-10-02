from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.ai.feedback import CoachFeedback
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.background import BackgroundTask
from vocal_ai_studio.ui.widgets import hint, panel, show_error

log = logging.getLogger(__name__)


class AiCoachView(QWidget):
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

        toolbar_panel, toolbar_box = panel()
        toolbar_row = QHBoxLayout()
        self.btn_generate = QPushButton("Analizar mi interpretación")
        self.btn_generate.setObjectName("Primary")
        self.btn_generate.clicked.connect(self._generate)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._task.cancel)
        toolbar_row.addWidget(self.btn_generate)
        toolbar_row.addWidget(self.btn_cancel)
        toolbar_row.addStretch(1)
        toolbar_box.addLayout(toolbar_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        toolbar_box.addWidget(self.progress)
        self.lbl_status = hint("")
        toolbar_box.addWidget(self.lbl_status)
        root.addWidget(toolbar_panel)

        summary_panel, summary_box = panel("Resumen")
        self.lbl_summary = hint("Todavía no hay feedback. Analiza tu voz en Voice y pulsa el botón de arriba.")
        summary_box.addWidget(self.lbl_summary)
        root.addWidget(summary_panel)

        strengths_panel, strengths_box = panel("Puntos fuertes")
        self.lbl_strengths = hint("")
        strengths_box.addWidget(self.lbl_strengths)
        root.addWidget(strengths_panel)

        issues_panel, issues_box = panel("A mejorar")
        self.lbl_issues = hint("")
        issues_box.addWidget(self.lbl_issues)
        root.addWidget(issues_panel)

        exercises_panel, exercises_box = panel("Ejercicios sugeridos")
        self.lbl_exercises = hint("")
        exercises_box.addWidget(self.lbl_exercises)
        root.addWidget(exercises_panel)

        root.addStretch(1)

    def _generate(self) -> None:
        if self._task.running:
            return

        def job(progress, cancelled):
            return self.session.generate_coach_feedback()

        self.progress.setVisible(True)
        self.btn_cancel.setVisible(True)
        self.btn_generate.setEnabled(False)
        self.lbl_status.setText("Analizando…")
        self._task.start(
            job, on_success=self._on_success, on_failure=self._on_failure,
            on_cancelled=self._on_cancelled, on_finished=self._on_finished,
        )

    def _on_success(self, feedback: CoachFeedback) -> None:
        self._show_feedback(feedback)
        self.status.emit("Feedback del AI Coach generado.")
        self.lbl_status.setText(f"Generado con: {feedback.generated_by}")

    def _on_failure(self, exc: Exception) -> None:
        log.exception("Fallo en AI Coach")
        show_error(self, exc, "AI Coach")

    def _on_cancelled(self) -> None:
        self.lbl_status.setText("Cancelado.")

    def _on_finished(self) -> None:
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_generate.setEnabled(True)

    def _show_feedback(self, feedback: CoachFeedback) -> None:
        self.lbl_summary.setText(feedback.summary)
        self.lbl_strengths.setText(
            "\n".join(f"•  {s}" for s in feedback.strengths) or "Ninguno destacado todavía."
        )
        self.lbl_issues.setText(
            "\n".join(f"•  {s}" for s in feedback.issues) or "No se detectaron problemas."
        )
        self.lbl_exercises.setText(
            "\n\n".join(f"{e.title}\n{e.description}" for e in feedback.exercises) or "—"
        )

    def refresh(self) -> None:
        if self.session.project is None:
            self.btn_generate.setEnabled(False)
            return
        self.btn_generate.setEnabled(not self._task.running)
        feedback = self.session.load_coach_feedback()
        if feedback:
            self._show_feedback(feedback)
            self.lbl_status.setText(f"Generado con: {feedback.generated_by}")
