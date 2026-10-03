from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.effects.chain import VoiceLabSettings
from vocal_ai_studio.effects.presets import PRESET_NAMES
from vocal_ai_studio.realtime.engine import detect_virtual_devices
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.waveform_widget import LevelMeter
from vocal_ai_studio.ui.widgets import hint, panel, show_error

log = logging.getLogger(__name__)
DEFAULT_LABEL = "Predeterminado del sistema"


class LiveVoiceView(QWidget):
    status = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._build()
        self._fill_devices()
        self._refresh_virtual_hint()

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

        # --- dispositivos ---
        dev_panel, dev_box = panel("Entrada / Salida")
        self.cmb_input = QComboBox()
        self.cmb_output = QComboBox()
        dev_box.addLayout(_row("Micrófono (entrada)", self.cmb_input))
        dev_box.addLayout(_row("Salida en vivo", self.cmb_output))
        self.cmb_input.currentIndexChanged.connect(self._apply_devices)
        self.cmb_output.currentIndexChanged.connect(self._apply_devices)

        btn_refresh = QPushButton("Volver a buscar dispositivos")
        btn_refresh.clicked.connect(self._refresh_devices)
        dev_box.addWidget(btn_refresh)

        self.lbl_virtual_hint = hint("")
        dev_box.addWidget(self.lbl_virtual_hint)
        root.addWidget(dev_panel)

        # --- control ---
        ctrl_panel, ctrl_box = panel("Procesamiento en vivo")
        toolbar = QHBoxLayout()
        self.btn_start = QPushButton("Iniciar voz en vivo")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setCheckable(True)
        self.btn_start.toggled.connect(self._toggle_engine)
        toolbar.addWidget(self.btn_start)

        self.chk_bypass = QCheckBox("Bypass (sin efectos)")
        self.chk_bypass.toggled.connect(self._apply_bypass)
        toolbar.addWidget(self.chk_bypass)
        toolbar.addStretch(1)
        ctrl_box.addLayout(toolbar)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems(PRESET_NAMES)
        self.cmb_preset.currentTextChanged.connect(self._apply_preset)
        preset_row.addWidget(self.cmb_preset)
        preset_row.addStretch(1)
        ctrl_box.addLayout(preset_row)

        wet_row = QHBoxLayout()
        wet_row.addWidget(QLabel("Dry/Wet"))
        self.dry_wet_slider = QSlider(Qt.Orientation.Horizontal)
        self.dry_wet_slider.setRange(0, 100)
        self.dry_wet_slider.setValue(100)
        self.lbl_dry_wet = QLabel("100% procesada")
        self.lbl_dry_wet.setMinimumWidth(110)
        self.dry_wet_slider.valueChanged.connect(self._apply_dry_wet)
        wet_row.addWidget(self.dry_wet_slider, 1)
        wet_row.addWidget(self.lbl_dry_wet)
        ctrl_box.addLayout(wet_row)
        root.addWidget(ctrl_panel)

        # --- medidores ---
        meter_panel, meter_box = panel("Medidores")
        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("Entrada"))
        self.meter_in = LevelMeter()
        in_row.addWidget(self.meter_in, 1)
        meter_box.addLayout(in_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Salida"))
        self.meter_out = LevelMeter()
        out_row.addWidget(self.meter_out, 1)
        meter_box.addLayout(out_row)

        stats_row = QHBoxLayout()
        self.lbl_cpu = QLabel("CPU: —")
        self.lbl_latency = QLabel("Latencia: —")
        stats_row.addWidget(self.lbl_cpu)
        stats_row.addWidget(self.lbl_latency)
        stats_row.addStretch(1)
        meter_box.addLayout(stats_row)
        root.addWidget(meter_panel)

        root.addStretch(1)

    # --- dispositivos ---
    def _fill_devices(self) -> None:
        engine = self.session.live_voice
        for combo, getter, current in (
            (self.cmb_input, self.session.backend.input_devices, engine.input_device),
            (self.cmb_output, self.session.backend.output_devices, engine.output_device),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(DEFAULT_LABEL, "")
            try:
                for dev in getter():
                    combo.addItem(dev.label, dev.label)
            except Exception as exc:  # noqa: BLE001
                log.warning("No se pudieron listar dispositivos: %s", exc)
            idx = combo.findData(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def _refresh_devices(self) -> None:
        self._fill_devices()
        self._refresh_virtual_hint()
        self.status.emit("Lista de dispositivos actualizada.")

    def _apply_devices(self) -> None:
        self.session.live_voice.set_devices(self.cmb_input.currentData() or "", self.cmb_output.currentData() or "")
        self.status.emit("Dispositivos de voz en vivo actualizados.")

    def _refresh_virtual_hint(self) -> None:
        found = detect_virtual_devices(self.session.backend)
        if found:
            self.lbl_virtual_hint.setText(
                "Micrófono virtual detectado: " + ", ".join(found) +
                ". Selecciónalo como salida en vivo para usarlo en OBS o Discord.")
        else:
            self.lbl_virtual_hint.setText(
                "No se detectó ningún micrófono virtual (VB-CABLE o VoiceMeeter). "
                "Instala uno y vuelve a buscar dispositivos para enviar tu voz procesada a OBS o Discord.")

    # --- control del motor ---
    def _toggle_engine(self, on: bool) -> None:
        engine = self.session.live_voice
        if on:
            try:
                engine.start()
            except Exception as exc:  # noqa: BLE001
                self.btn_start.blockSignals(True)
                self.btn_start.setChecked(False)
                self.btn_start.blockSignals(False)
                show_error(self, exc, "Al iniciar la voz en vivo")
                return
            self.btn_start.setText("Detener voz en vivo")
            self.status.emit("Voz en vivo iniciada.")
        else:
            engine.stop()
            self.btn_start.setText("Iniciar voz en vivo")
            self.meter_in.reset()
            self.meter_out.reset()
            self.lbl_cpu.setText("CPU: —")
            self.lbl_latency.setText("Latencia: —")
            self.status.emit("Voz en vivo detenida.")

    def _apply_bypass(self, on: bool) -> None:
        self.session.live_voice.set_bypass(on)

    def _apply_preset(self, name: str) -> None:
        self.session.live_voice.update_settings(VoiceLabSettings.from_preset(name))

    def _apply_dry_wet(self, value: int) -> None:
        wet = value / 100.0
        self.session.live_voice.set_dry_wet(wet)
        self.lbl_dry_wet.setText(f"{value}% procesada")

    # --- refresco periódico ---
    def tick(self) -> None:
        engine = self.session.live_voice
        if not engine.is_running:
            return
        self.meter_in.set_level(engine.input_level)
        self.meter_out.set_level(engine.output_level)
        self.lbl_cpu.setText(f"CPU: {engine.cpu_usage * 100:.0f}%")
        self.lbl_latency.setText(f"Latencia: {engine.latency * 1000:.0f} ms")

    def refresh(self) -> None:
        self._fill_devices()
        self._refresh_virtual_hint()


def _row(label: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    name = QLabel(label)
    name.setMinimumWidth(170)
    row.addWidget(name)
    row.addWidget(widget, 1)
    return row
