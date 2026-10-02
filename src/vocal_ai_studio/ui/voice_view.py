from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.background import BackgroundTask
from vocal_ai_studio.ui.pitch_view import PitchView, legend_text
from vocal_ai_studio.ui.waveform_widget import format_time
from vocal_ai_studio.ui.widgets import hint, panel, show_error
from vocal_ai_studio.voice_analysis.metrics import VocalAnalysis
from vocal_ai_studio.voice_analysis.song import SongAnalysis

log = logging.getLogger(__name__)


class VoiceView(QWidget):
    status = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._task = BackgroundTask()
        self._analysis: VocalAnalysis | None = None
        self._song_analysis: SongAnalysis | None = None
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        top_panel, top_box = panel()
        row = QHBoxLayout()
        self.lbl_source = QLabel("")
        row.addWidget(QLabel("Analizando:"))
        row.addWidget(self.lbl_source)
        row.addStretch(1)
        self.btn_analyze = QPushButton("Analizar")
        self.btn_analyze.setObjectName("Primary")
        self.btn_analyze.clicked.connect(self._analyze)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._task.cancel)
        row.addWidget(self.btn_analyze)
        row.addWidget(self.btn_cancel)
        top_box.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        top_box.addWidget(self.progress)
        self.lbl_status = hint("")
        top_box.addWidget(self.lbl_status)
        root.addWidget(top_panel)

        # resumen: canción (BPM/tonalidad) + voz (rango, afinación, estabilidad, vibrato)
        summary_panel, summary_box = panel("Resumen")
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self._stat_labels: dict[str, QLabel] = {}
        stats = ["bpm", "key", "range", "deviation", "stability", "vibrato", "pauses"]
        titles = ["BPM", "Tonalidad", "Rango vocal", "Afinación media", "Estabilidad", "Vibrato", "Pausas"]
        for col, (key, title) in enumerate(zip(stats, titles)):
            name = QLabel(title)
            name.setObjectName("Hint")
            value = QLabel("—")
            value.setObjectName("SectionTitle")
            grid.addWidget(name, 0, col)
            grid.addWidget(value, 1, col)
            self._stat_labels[key] = value
        summary_box.addLayout(grid)
        root.addWidget(summary_panel)

        # curva de afinación
        wave_panel, wave_box = panel()
        self.pitch_view = PitchView()
        self.pitch_view.seeked.connect(self._on_seek)
        wave_box.addWidget(self.pitch_view, 1)
        bottom_row = QHBoxLayout()
        bottom_row.addWidget(hint(legend_text(), wrap=False))
        bottom_row.addStretch(1)
        self.btn_live_note = QPushButton("Nota en vivo")
        self.btn_live_note.setCheckable(True)
        self.btn_live_note.setToolTip("Muestra tu nota actual sobre la curva mientras cantas. Apagado "
                                      "por defecto para no gastar CPU de fondo; actívalo cuando quieras.")
        bottom_row.addWidget(self.btn_live_note)
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setFixedWidth(34)
        btn_zoom_out.clicked.connect(lambda: self.pitch_view.set_zoom(self.pitch_view.zoom / 1.5))
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedWidth(34)
        btn_zoom_in.clicked.connect(lambda: self.pitch_view.set_zoom(self.pitch_view.zoom * 1.5))
        btn_zoom_fit = QPushButton("Ajustar")
        btn_zoom_fit.clicked.connect(lambda: self.pitch_view.set_zoom(1.0))
        for b in (btn_zoom_out, btn_zoom_in, btn_zoom_fit):
            bottom_row.addWidget(b)
        wave_box.addLayout(bottom_row)
        root.addWidget(wave_panel, 1)

        # notas detectadas
        notes_panel, notes_box = panel("Notas")
        self.cmb_notes_info = QLabel("Analiza tu voz para ver aquí las notas detectadas.")
        self.cmb_notes_info.setObjectName("Hint")
        self.cmb_notes_info.setWordWrap(True)
        notes_box.addWidget(self.cmb_notes_info)
        root.addWidget(notes_panel)

    # --- acciones ---
    def _analyze(self) -> None:
        if self._task.running:
            return
        try:
            self.session._require_project()  # mensaje de error consistente si no hay proyecto
        except AppError as exc:
            show_error(self, exc, "Al analizar")
            return

        def job(progress, cancelled):
            song_analysis = None
            if self.session.project.data.song_file:
                try:
                    song_analysis = self.session.analyze_song()
                except AppError:
                    pass
            vocal_analysis = self.session.analyze_vocal(progress=progress, cancelled=cancelled)
            return vocal_analysis, song_analysis

        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.btn_cancel.setVisible(True)
        self.btn_analyze.setEnabled(False)
        self.lbl_status.setText("Analizando…")
        self._task.start(
            job, on_progress=self._on_progress, on_success=self._on_success,
            on_failure=self._on_failure, on_cancelled=self._on_cancelled, on_finished=self._on_finished,
        )

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(fraction * 100))
        self.lbl_status.setText(message)

    def _on_success(self, result) -> None:
        self._analysis, self._song_analysis = result
        self._refresh_summary()
        self.status.emit("Análisis completado.")

    def _on_failure(self, exc: Exception) -> None:
        log.exception("Fallo al analizar")
        show_error(self, exc, "Al analizar")

    def _on_cancelled(self) -> None:
        self.lbl_status.setText("Análisis cancelado.")

    def _on_finished(self) -> None:
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_analyze.setEnabled(True)
        if self.lbl_status.text() not in ("Análisis cancelado.",):
            self.lbl_status.setText("")

    def _on_seek(self, seconds: float) -> None:
        self.session.seek(seconds)

    # --- refresco ---
    def refresh(self) -> None:
        project = self.session.project
        if project is None:
            self.lbl_source.setText("Sin proyecto")
            self.btn_analyze.setEnabled(False)
            self._analysis = None
            self._song_analysis = None
            self.pitch_view.set_track(None)
            self._refresh_summary()
            return
        take = project.get_take(project.data.active_take) if project.data.active_take else None
        self.lbl_source.setText(take.name if take else ("Voz importada" if project.data.vocal_file else "—"))
        has_vocal = project.active_vocal() is not None
        self.btn_analyze.setEnabled(has_vocal and not self._task.running)
        self._analysis = self.session.load_vocal_analysis()
        self._song_analysis = self.session.load_song_analysis()
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        labels = self._stat_labels
        song = self._song_analysis
        labels["bpm"].setText(song.bpm_label if song else "—")
        labels["key"].setText(song.key_label if song else "—")

        a = self._analysis
        if a is None:
            for key in ("range", "deviation", "stability", "vibrato", "pauses"):
                labels[key].setText("—")
            self.pitch_view.set_track(None)
            self.cmb_notes_info.setText("Analiza tu voz para ver aquí las notas detectadas.")
            return

        labels["range"].setText(f"{a.vocal_range[0]} – {a.vocal_range[1]}" if a.vocal_range else "—")
        labels["deviation"].setText(f"{a.avg_cents_deviation:.0f} cents")
        labels["stability"].setText(_stability_label(a.stability_cents))
        if a.vibrato_rate_hz:
            labels["vibrato"].setText(f"{a.vibrato_rate_hz:.1f} Hz (±{a.vibrato_extent_cents:.0f} cents)")
        else:
            labels["vibrato"].setText("No detectado")
        total_pause = sum(end - start for start, end in a.pauses)
        labels["pauses"].setText(f"{len(a.pauses)} ({format_time(total_pause)})" if a.pauses else "Ninguna")

        self.pitch_view.set_track(a.pitch, a.duration)
        if a.notes:
            self.cmb_notes_info.setText(
                f"{len(a.notes)} notas detectadas, de {min(n.duration for n in a.notes):.2f}s a "
                f"{max(n.duration for n in a.notes):.2f}s. Nota más repetida: {_most_common_note(a)}."
            )
        else:
            self.cmb_notes_info.setText("No se detectaron notas con suficiente duración.")

    def _tick(self) -> None:
        self.pitch_view.set_position(self.session.player.position)
        self._update_live_pitch()

    def _update_live_pitch(self) -> None:
        rec = self.session.recorder
        if self.btn_live_note.isChecked() and rec.state.value in ("armed", "recording", "paused"):
            freq, confidence = rec.live_pitch()
            if confidence > 0.3 and not (freq != freq):  # freq != freq ⇔ NaN, sin importar el import
                self.pitch_view.set_live_pitch(rec.elapsed, freq)
                return
        self.pitch_view.set_live_pitch(None, None)


def _stability_label(stability_cents: float) -> str:
    if stability_cents <= 0:
        return "—"
    if stability_cents < 15:
        return f"Muy estable ({stability_cents:.0f}¢)"
    if stability_cents < 30:
        return f"Estable ({stability_cents:.0f}¢)"
    return f"Irregular ({stability_cents:.0f}¢)"


def _most_common_note(analysis: VocalAnalysis) -> str:
    totals: dict[str, float] = {}
    for note in analysis.notes:
        totals[note.name] = totals.get(note.name, 0.0) + note.duration
    return max(totals, key=totals.get) if totals else "—"
