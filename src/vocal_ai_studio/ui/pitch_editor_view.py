from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.pitch.correction import MODE_NAMES, CorrectionSettings
from vocal_ai_studio.pitch.scales import KEYS, SCALES
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.background import BackgroundTask
from vocal_ai_studio.ui.pitch_editor_widget import PitchEditorWidget
from vocal_ai_studio.ui.pitch_view import legend_text
from vocal_ai_studio.ui.widgets import hint, panel, show_error

log = logging.getLogger(__name__)


def _slider_row(label: str, lo: int, hi: int, value: int, suffix: str = "") -> tuple[QHBoxLayout, QSlider, QLabel]:
    row = QHBoxLayout()
    name = QLabel(label)
    name.setMinimumWidth(130)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(lo, hi)
    slider.setValue(value)
    value_lbl = QLabel(f"{value}{suffix}")
    value_lbl.setMinimumWidth(50)
    value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: value_lbl.setText(f"{v}{suffix}"))
    row.addWidget(name)
    row.addWidget(slider, 1)
    row.addWidget(value_lbl)
    return row, slider, value_lbl


class PitchEditorView(QWidget):
    status = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._task = BackgroundTask()
        self._loading = False  # evita guardar/recalcular mientras se cargan los controles
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
        row.addWidget(QLabel("Corrigiendo:"))
        row.addWidget(self.lbl_source)
        row.addStretch(1)
        self.btn_apply = QPushButton("Aplicar (crea una toma nueva)")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.clicked.connect(self._apply)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._task.cancel)
        row.addWidget(self.btn_apply)
        row.addWidget(self.btn_cancel)
        top_box.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        top_box.addWidget(self.progress)
        self.lbl_status = hint("")
        top_box.addWidget(self.lbl_status)
        root.addWidget(top_panel)

        controls_panel, controls_box = panel("Corrección automática")
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modo"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(MODE_NAMES)
        self.cmb_mode.currentTextChanged.connect(self._apply_mode_preset)
        mode_row.addWidget(self.cmb_mode)
        mode_row.addSpacing(16)
        mode_row.addWidget(QLabel("Tonalidad"))
        self.cmb_key = QComboBox()
        self.cmb_key.addItems(KEYS)
        self.cmb_key.currentTextChanged.connect(self._on_settings_changed)
        mode_row.addWidget(self.cmb_key)
        mode_row.addWidget(QLabel("Escala"))
        self.cmb_scale = QComboBox()
        self.cmb_scale.addItems(list(SCALES.keys()))
        self.cmb_scale.currentTextChanged.connect(self._on_settings_changed)
        mode_row.addWidget(self.cmb_scale)
        mode_row.addStretch(1)
        self.chk_formants = QCheckBox("Preservar formantes")
        self.chk_formants.setToolTip("Mantiene el timbre de tu voz al corregir. Si lo desactivas, "
                                     "saltos grandes de afinación suenan más \"ardilla/demonio\".")
        self.chk_formants.toggled.connect(self._on_settings_changed)
        mode_row.addWidget(self.chk_formants)
        controls_box.addLayout(mode_row)

        amount_row, self.sld_amount, _ = _slider_row("Amount", 0, 100, 70, "%")
        self.sld_amount.valueChanged.connect(self._on_settings_changed)
        controls_box.addLayout(amount_row)
        speed_row, self.sld_speed, _ = _slider_row("Speed (Retune)", 1, 500, 40, " ms")
        self.sld_speed.valueChanged.connect(self._on_settings_changed)
        controls_box.addLayout(speed_row)
        human_row, self.sld_humanize, _ = _slider_row("Humanize", 0, 100, 40, "%")
        self.sld_humanize.valueChanged.connect(self._on_settings_changed)
        controls_box.addLayout(human_row)
        controls_box.addWidget(hint("Amount=0 no cambia nada. Speed bajo = deslizamiento natural; "
                                    "alto = corrección robótica instantánea. La corrección nunca es "
                                    "obligatoria: pulsa Aplicar solo si te gusta el resultado."))
        root.addWidget(controls_panel)

        editor_panel, editor_box = panel()
        self.editor = PitchEditorWidget()
        self.editor.seeked.connect(self._on_seek)
        self.editor.selection_changed.connect(self._on_selection_changed)
        self.editor.changed.connect(self._on_overrides_changed)
        editor_box.addWidget(self.editor, 1)
        legend_row = QHBoxLayout()
        legend_row.addWidget(hint(legend_text() + " · Arrastra una nota verticalmente para transportarla",
                                  wrap=False))
        legend_row.addStretch(1)
        self.btn_live_note = QPushButton("Nota en vivo")
        self.btn_live_note.setCheckable(True)
        self.btn_live_note.setToolTip("Muestra tu nota actual sobre la curva mientras cantas. Apagado "
                                      "por defecto para no gastar CPU de fondo; actívalo cuando quieras.")
        legend_row.addWidget(self.btn_live_note)
        editor_box.addLayout(legend_row)
        root.addWidget(editor_panel, 1)

        note_panel, note_box = panel("Nota seleccionada")
        note_row = QHBoxLayout()
        self.lbl_note = QLabel("Ninguna — haz clic en una nota de la curva corregida.")
        self.lbl_note.setObjectName("Hint")
        note_row.addWidget(self.lbl_note, 1)
        self.btn_down = QPushButton("− semitono")
        self.btn_down.clicked.connect(lambda: self.editor.transpose_selected(-1))
        self.btn_up = QPushButton("+ semitono")
        self.btn_up.clicked.connect(lambda: self.editor.transpose_selected(1))
        self.btn_bypass = QPushButton("Excluir / incluir")
        self.btn_bypass.clicked.connect(self.editor.toggle_bypass_selected)
        self.btn_reset = QPushButton("Restablecer")
        self.btn_reset.clicked.connect(self.editor.reset_selected)
        self.btn_split = QPushButton("Dividir aquí")
        self.btn_split.setToolTip("Divide la nota seleccionada en el punto de reproducción actual.")
        self.btn_split.clicked.connect(lambda: self.editor.split_selected_at(self.session.player.position))
        self.btn_merge = QPushButton("Unir con la siguiente")
        self.btn_merge.clicked.connect(self.editor.merge_selected_with_next)
        for b in (self.btn_down, self.btn_up, self.btn_bypass, self.btn_reset, self.btn_split, self.btn_merge):
            note_row.addWidget(b)
        note_box.addLayout(note_row)
        root.addWidget(note_panel)

        self._update_note_buttons()

    # --- carga / guardado de ajustes ---
    def refresh(self) -> None:
        project = self.session.project
        if project is None:
            self.lbl_source.setText("Sin proyecto")
            self.btn_apply.setEnabled(False)
            self.editor.set_track(None)
            self.editor.set_target(None)
            self.editor.set_overrides([])
            return
        take = project.get_take(project.data.active_take) if project.data.active_take else None
        self.lbl_source.setText(take.name if take else ("Voz importada" if project.data.vocal_file else "—"))

        analysis = self.session.load_vocal_analysis()
        settings, overrides = self.session.load_correction()
        self._loading = True
        self.cmb_mode.setCurrentText(settings.mode if settings.mode in MODE_NAMES else "Balanced")
        self.cmb_key.setCurrentText(settings.key)
        self.cmb_scale.setCurrentText(settings.scale if settings.scale in SCALES else "Mayor")
        self.chk_formants.setChecked(settings.preserve_formants)
        self.sld_amount.setValue(int(settings.amount))
        self.sld_speed.setValue(max(1, int(settings.speed_ms)))
        self.sld_humanize.setValue(int(settings.humanize))
        self._loading = False

        if analysis is None:
            self.editor.set_track(None)
            self.editor.set_target(None)
            self.editor.set_overrides([])
            self.btn_apply.setEnabled(False)
            self.lbl_status.setText("Analiza tu voz primero en la pestaña Voice.")
        else:
            self.editor.set_track(analysis.pitch, analysis.duration)
            if not overrides:
                overrides = self.session.seed_overrides_from_analysis()
            self.editor.set_overrides(overrides)
            self.btn_apply.setEnabled(not self._task.running)
            self.lbl_status.setText("")
            self._recompute_preview()
        self._update_note_buttons()

    def _current_settings(self) -> CorrectionSettings:
        return CorrectionSettings(
            key=self.cmb_key.currentText(), scale=self.cmb_scale.currentText(),
            amount=float(self.sld_amount.value()), speed_ms=float(self.sld_speed.value()),
            humanize=float(self.sld_humanize.value()), preserve_formants=self.chk_formants.isChecked(),
            mode=self.cmb_mode.currentText(),
        )

    def _apply_mode_preset(self, mode: str) -> None:
        if self._loading:
            return
        preset = CorrectionSettings.from_mode(mode, key=self.cmb_key.currentText(),
                                              scale=self.cmb_scale.currentText(),
                                              preserve_formants=self.chk_formants.isChecked())
        self._loading = True
        self.sld_amount.setValue(int(preset.amount))
        self.sld_speed.setValue(max(1, int(preset.speed_ms)))
        self.sld_humanize.setValue(int(preset.humanize))
        self._loading = False
        self._on_settings_changed()

    def _on_settings_changed(self) -> None:
        if self._loading or self.session.project is None:
            return
        self._recompute_preview()
        self._save_state()

    def _on_overrides_changed(self) -> None:
        self._recompute_preview_curve_only()
        self._save_state()
        self._update_note_buttons()

    def _save_state(self) -> None:
        if self.session.project is None:
            return
        try:
            self.session.save_correction(self._current_settings(), self.editor.overrides())
        except AppError:
            pass  # sin análisis todavía; se guardará la próxima vez que haya overrides

    def _recompute_preview(self) -> None:
        if self.session.load_vocal_analysis() is None:
            return
        try:
            curve = self.session.preview_correction_curve(self._current_settings(), self.editor.overrides())
        except AppError:
            return
        self.editor.set_target(curve)

    def _recompute_preview_curve_only(self) -> None:
        self._recompute_preview()

    # --- selección / edición ---
    def _on_selection_changed(self, override) -> None:
        self._update_note_buttons(override)

    def _update_note_buttons(self, override=None) -> None:
        if override is None:
            override = self.editor.selected_override()
        has = override is not None
        for b in (self.btn_down, self.btn_up, self.btn_bypass, self.btn_reset, self.btn_split, self.btn_merge):
            b.setEnabled(has)
        if override is None:
            self.lbl_note.setText("Ninguna — haz clic en una nota de la curva corregida.")
        else:
            state = "excluida de la corrección" if override.bypass else f"{override.semitone_offset:+d} semitonos"
            self.lbl_note.setText(f"{override.start:.2f}s – {override.end:.2f}s · {state}")

    def _on_seek(self, seconds: float) -> None:
        self.session.seek(seconds)

    # --- aplicar ---
    def _apply(self) -> None:
        if self._task.running or self.session.project is None:
            return
        settings = self._current_settings()
        overrides = self.editor.overrides()
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.btn_cancel.setVisible(True)
        self.btn_apply.setEnabled(False)
        self.lbl_status.setText("Aplicando corrección…")
        self._task.start(
            lambda progress, cancelled: self.session.apply_correction(settings, overrides, progress, cancelled),
            on_progress=self._on_progress, on_success=self._on_success,
            on_failure=self._on_failure, on_cancelled=self._on_cancelled, on_finished=self._on_finished,
        )

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(fraction * 100))
        self.lbl_status.setText(message)

    def _on_success(self, take) -> None:
        self.status.emit(f"{take.name} creada.")
        self.refresh()

    def _on_failure(self, exc: Exception) -> None:
        log.exception("Fallo al aplicar la corrección")
        show_error(self, exc, "Al aplicar la corrección")

    def _on_cancelled(self) -> None:
        self.lbl_status.setText("Cancelado.")

    def _on_finished(self) -> None:
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_apply.setEnabled(self.session.project is not None)

    def _tick(self) -> None:
        self.editor.set_position(self.session.player.position)
        rec = self.session.recorder
        if self.btn_live_note.isChecked() and rec.state.value in ("armed", "recording", "paused"):
            freq, confidence = rec.live_pitch()
            if confidence > 0.3 and freq == freq:  # freq == freq ⇔ no es NaN
                self.editor.set_live_pitch(rec.elapsed, freq)
                return
        self.editor.set_live_pitch(None, None)
