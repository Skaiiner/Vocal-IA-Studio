from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.effects.chain import (
    CompressorSettings,
    DeEsserSettings,
    DelaySettings,
    ReverbSettings,
    VoiceLabSettings,
)
from vocal_ai_studio.effects.presets import PRESET_NAMES
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.background import BackgroundTask
from vocal_ai_studio.ui.widgets import hint, panel, show_error

log = logging.getLogger(__name__)


def _db_slider(lo: float = -18.0, hi: float = 18.0, default: float = 0.0) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(int(lo * 10), int(hi * 10))
    s.setValue(int(default * 10))
    s.setMinimumWidth(120)
    return s


def _slider_label(slider: QSlider) -> QLabel:
    lbl = QLabel(f"{slider.value() / 10:+.1f} dB")
    lbl.setMinimumWidth(60)
    slider.valueChanged.connect(lambda v, l=lbl: l.setText(f"{v / 10:+.1f} dB"))
    return lbl


class EQBandRow(QWidget):
    changed = Signal()

    def __init__(self, band: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._band = band
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        type_label = {"low_shelf": "Graves", "high_shelf": "Agudos", "peak": "Med"}.get(
            band.get("type", "peak"), "Peak")
        row.addWidget(QLabel(type_label))

        self.freq = QDoubleSpinBox()
        self.freq.setRange(20, 20000)
        self.freq.setValue(float(band.get("freq", 1000)))
        self.freq.setSuffix(" Hz")
        self.freq.setDecimals(0)
        self.freq.setMinimumWidth(90)
        row.addWidget(self.freq)

        self.gain = _db_slider(-18, 18, float(band.get("gain_db", 0)))
        self.gain_lbl = _slider_label(self.gain)
        row.addWidget(self.gain)
        row.addWidget(self.gain_lbl)

        if band.get("type", "peak") == "peak":
            row.addWidget(QLabel("Q"))
            self.q = QDoubleSpinBox()
            self.q.setRange(0.1, 10.0)
            self.q.setValue(float(band.get("q", 1.0)))
            self.q.setSingleStep(0.1)
            self.q.setDecimals(1)
            self.q.setMinimumWidth(60)
            row.addWidget(self.q)
        else:
            self.q = None  # type: ignore[assignment]
        row.addStretch(1)

        self.freq.valueChanged.connect(lambda _: self.changed.emit())
        self.gain.valueChanged.connect(lambda _: self.changed.emit())
        if self.q is not None:
            self.q.valueChanged.connect(lambda _: self.changed.emit())

    def to_dict(self) -> dict:
        d = {
            "type": self._band.get("type", "peak"),
            "freq": self.freq.value(),
            "gain_db": self.gain.value() / 10.0,
            "q": self.q.value() if self.q is not None else 0.7,
        }
        return d


class VoiceLabView(QWidget):
    status = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._task = BackgroundTask()
        self._settings = VoiceLabSettings()
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

        # Toolbar
        toolbar_panel, toolbar_box = panel()
        toolbar_row = QHBoxLayout()
        toolbar_row.addWidget(QLabel("Preset:"))
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems(PRESET_NAMES)
        self.cmb_preset.currentTextChanged.connect(self._load_preset)
        toolbar_row.addWidget(self.cmb_preset)
        toolbar_row.addStretch(1)
        self.btn_apply = QPushButton("Aplicar como toma")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.clicked.connect(self._apply)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._task.cancel)
        toolbar_row.addWidget(self.btn_apply)
        toolbar_row.addWidget(self.btn_cancel)
        toolbar_box.addLayout(toolbar_row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        toolbar_box.addWidget(self.progress)
        self.lbl_status = hint("")
        toolbar_box.addWidget(self.lbl_status)
        root.addWidget(toolbar_panel)

        # Formant shift
        form_panel, form_box = panel("Formantes")
        form_row = QHBoxLayout()
        form_row.addWidget(QLabel("Desplazamiento:"))
        self.formant_slider = QSlider(Qt.Orientation.Horizontal)
        self.formant_slider.setRange(-60, 60)
        self.formant_slider.setValue(0)
        self.formant_slider.setTickInterval(10)
        self.formant_slider.setMinimumWidth(200)
        self.formant_lbl = QLabel("  0.0 st")
        self.formant_lbl.setMinimumWidth(60)
        self.formant_slider.valueChanged.connect(
            lambda v: self.formant_lbl.setText(f"{v / 10:+.1f} st"))
        form_row.addWidget(self.formant_slider)
        form_row.addWidget(self.formant_lbl)
        form_row.addStretch(1)
        form_box.addLayout(form_row)
        form_box.addWidget(hint("−6 st = voz más grave/oscura · +6 st = más aguda/brillante"))
        root.addWidget(form_panel)

        # EQ
        eq_panel, eq_box = panel("EQ Paramétrica (5 bandas)")
        self._eq_rows: list[EQBandRow] = []
        for band in self._settings.eq_bands:
            row_w = EQBandRow(band)
            row_w.changed.connect(lambda: None)  # sin preview en tiempo real
            eq_box.addWidget(row_w)
            self._eq_rows.append(row_w)
        root.addWidget(eq_panel)

        # Compresor
        comp_group = QGroupBox("Compresor")
        comp_group.setCheckable(True)
        comp_group.setChecked(False)
        comp_layout = QGridLayout(comp_group)
        self._build_compressor(comp_layout)
        self.comp_group = comp_group
        root.addWidget(comp_group)

        # De-esser
        de_group = QGroupBox("De-esser")
        de_group.setCheckable(True)
        de_group.setChecked(False)
        de_layout = QGridLayout(de_group)
        self._build_deesser(de_layout)
        self.de_group = de_group
        root.addWidget(de_group)

        # Reverb
        rv_group = QGroupBox("Reverb")
        rv_group.setCheckable(True)
        rv_group.setChecked(False)
        rv_layout = QGridLayout(rv_group)
        self._build_reverb(rv_layout)
        self.rv_group = rv_group
        root.addWidget(rv_group)

        # Delay
        dl_group = QGroupBox("Delay")
        dl_group.setCheckable(True)
        dl_group.setChecked(False)
        dl_layout = QGridLayout(dl_group)
        self._build_delay(dl_layout)
        self.dl_group = dl_group
        root.addWidget(dl_group)

        root.addStretch(1)

    def _build_compressor(self, g: QGridLayout) -> None:
        def row(label, lo, hi, default, suffix="", decimals=1):
            lbl = QLabel(label)
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(default)
            spin.setSuffix(suffix)
            spin.setDecimals(decimals)
            return lbl, spin

        _, self.c_thresh = row("Umbral", -60, 0, -18, " dB")
        _, self.c_ratio  = row("Ratio", 1, 20, 3, ":1")
        _, self.c_attack = row("Ataque", 0.1, 200, 5, " ms")
        _, self.c_release= row("Release", 1, 500, 50, " ms")
        _, self.c_makeup = row("Makeup", -12, 24, 0, " dB")
        items = [("Umbral", self.c_thresh), ("Ratio", self.c_ratio),
                 ("Ataque", self.c_attack), ("Release", self.c_release),
                 ("Makeup", self.c_makeup)]
        for col, (name, spin) in enumerate(items):
            g.addWidget(QLabel(name), 0, col)
            g.addWidget(spin, 1, col)

    def _build_deesser(self, g: QGridLayout) -> None:
        self.de_thresh = QDoubleSpinBox(); self.de_thresh.setRange(-60, 0); self.de_thresh.setValue(-20); self.de_thresh.setSuffix(" dB")
        self.de_freq   = QDoubleSpinBox(); self.de_freq.setRange(1000, 16000); self.de_freq.setValue(7000); self.de_freq.setSuffix(" Hz"); self.de_freq.setDecimals(0)
        self.de_bw     = QDoubleSpinBox(); self.de_bw.setRange(500, 8000); self.de_bw.setValue(3000); self.de_bw.setSuffix(" Hz"); self.de_bw.setDecimals(0)
        for col, (name, spin) in enumerate([("Umbral", self.de_thresh), ("Frecuencia", self.de_freq), ("Anchura", self.de_bw)]):
            g.addWidget(QLabel(name), 0, col)
            g.addWidget(spin, 1, col)

    def _build_reverb(self, g: QGridLayout) -> None:
        self.rv_room = QDoubleSpinBox(); self.rv_room.setRange(0, 1); self.rv_room.setValue(0.3); self.rv_room.setSingleStep(0.05); self.rv_room.setDecimals(2)
        self.rv_wet  = QDoubleSpinBox(); self.rv_wet.setRange(0, 1); self.rv_wet.setValue(0.15); self.rv_wet.setSingleStep(0.05); self.rv_wet.setDecimals(2)
        for col, (name, spin) in enumerate([("Tamaño sala", self.rv_room), ("Wet", self.rv_wet)]):
            g.addWidget(QLabel(name), 0, col)
            g.addWidget(spin, 1, col)

    def _build_delay(self, g: QGridLayout) -> None:
        self.dl_time = QDoubleSpinBox(); self.dl_time.setRange(1, 2000); self.dl_time.setValue(250); self.dl_time.setSuffix(" ms"); self.dl_time.setDecimals(0)
        self.dl_fb   = QDoubleSpinBox(); self.dl_fb.setRange(0, 0.95); self.dl_fb.setValue(0.3); self.dl_fb.setSingleStep(0.05); self.dl_fb.setDecimals(2)
        self.dl_wet  = QDoubleSpinBox(); self.dl_wet.setRange(0, 1); self.dl_wet.setValue(0.2); self.dl_wet.setSingleStep(0.05); self.dl_wet.setDecimals(2)
        for col, (name, spin) in enumerate([("Tiempo", self.dl_time), ("Feedback", self.dl_fb), ("Wet", self.dl_wet)]):
            g.addWidget(QLabel(name), 0, col)
            g.addWidget(spin, 1, col)

    # --- leer/escribir settings ---
    def _read_settings(self) -> VoiceLabSettings:
        eq = [r.to_dict() for r in self._eq_rows]
        return VoiceLabSettings(
            formant_shift=self.formant_slider.value() / 10.0,
            eq_bands=eq,
            compressor=CompressorSettings(
                enabled=self.comp_group.isChecked(),
                threshold_db=self.c_thresh.value(),
                ratio=self.c_ratio.value(),
                attack_ms=self.c_attack.value(),
                release_ms=self.c_release.value(),
                makeup_db=self.c_makeup.value(),
            ),
            de_esser=DeEsserSettings(
                enabled=self.de_group.isChecked(),
                threshold_db=self.de_thresh.value(),
                freq_hz=self.de_freq.value(),
                bandwidth=self.de_bw.value(),
            ),
            reverb=ReverbSettings(
                enabled=self.rv_group.isChecked(),
                room_size=self.rv_room.value(),
                wet=self.rv_wet.value(),
            ),
            delay=DelaySettings(
                enabled=self.dl_group.isChecked(),
                time_ms=self.dl_time.value(),
                feedback=self.dl_fb.value(),
                wet=self.dl_wet.value(),
            ),
            preset_name=self.cmb_preset.currentText(),
        )

    def _apply_settings(self, s: VoiceLabSettings) -> None:
        self.formant_slider.setValue(int(s.formant_shift * 10))
        for i, row_w in enumerate(self._eq_rows):
            if i < len(s.eq_bands):
                row_w.freq.setValue(s.eq_bands[i].get("freq", 1000))
                row_w.gain.setValue(int(s.eq_bands[i].get("gain_db", 0) * 10))
                if row_w.q is not None:
                    row_w.q.setValue(s.eq_bands[i].get("q", 1.0))
        c = s.compressor
        self.comp_group.setChecked(c.enabled)
        self.c_thresh.setValue(c.threshold_db)
        self.c_ratio.setValue(c.ratio)
        self.c_attack.setValue(c.attack_ms)
        self.c_release.setValue(c.release_ms)
        self.c_makeup.setValue(c.makeup_db)
        de = s.de_esser
        self.de_group.setChecked(de.enabled)
        self.de_thresh.setValue(de.threshold_db)
        self.de_freq.setValue(de.freq_hz)
        self.de_bw.setValue(de.bandwidth)
        rv = s.reverb
        self.rv_group.setChecked(rv.enabled)
        self.rv_room.setValue(rv.room_size)
        self.rv_wet.setValue(rv.wet)
        dl = s.delay
        self.dl_group.setChecked(dl.enabled)
        self.dl_time.setValue(dl.time_ms)
        self.dl_fb.setValue(dl.feedback)
        self.dl_wet.setValue(dl.wet)

    def _load_preset(self, name: str) -> None:
        if name == "Custom":
            return
        s = VoiceLabSettings.from_preset(name)
        self._apply_settings(s)

    # --- aplicar ---
    def _apply(self) -> None:
        if self._task.running:
            return
        settings = self._read_settings()

        def job(progress, cancelled):
            return self.session.apply_voice_lab(settings, progress=progress, cancelled=cancelled)

        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.btn_cancel.setVisible(True)
        self.btn_apply.setEnabled(False)
        self.lbl_status.setText("Procesando…")
        self._task.start(
            job, on_progress=self._on_progress, on_success=self._on_success,
            on_failure=self._on_failure, on_cancelled=self._on_cancelled,
            on_finished=self._on_finished,
        )

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(fraction * 100))
        self.lbl_status.setText(message)

    def _on_success(self, take) -> None:
        self.status.emit(f"Voice Lab aplicado → '{take.name}'")
        self.lbl_status.setText(f"Listo: {take.name}")

    def _on_failure(self, exc: Exception) -> None:
        log.exception("Fallo en Voice Lab")
        show_error(self, exc, "Voice Lab")

    def _on_cancelled(self) -> None:
        self.lbl_status.setText("Cancelado.")

    def _on_finished(self) -> None:
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_apply.setEnabled(True)

    # --- refresh ---
    def refresh(self) -> None:
        if self.session.project is None:
            self.btn_apply.setEnabled(False)
            return
        has_vocal = self.session.project.active_vocal() is not None
        self.btn_apply.setEnabled(has_vocal and not self._task.running)
        s = self.session.load_voice_lab()
        if s.preset_name != "Custom":
            self.cmb_preset.blockSignals(True)
            idx = self.cmb_preset.findText(s.preset_name)
            if idx >= 0:
                self.cmb_preset.setCurrentIndex(idx)
            self.cmb_preset.blockSignals(False)
        self._apply_settings(s)
