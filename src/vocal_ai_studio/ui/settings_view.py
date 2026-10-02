from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.core.hardware import detect_hardware
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.waveform_widget import LevelMeter
from vocal_ai_studio.ui.widgets import GainSlider, hint, panel, show_error
from vocal_ai_studio.youtube.source import AVISO_LEGAL

log = logging.getLogger(__name__)
DEFAULT_LABEL = "Predeterminado del sistema"


class SettingsView(QWidget):
    status = Signal(str)

    def __init__(self, session: Session, log_file: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.log_file = log_file
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        s = self.session.settings

        # --- audio ---
        audio_panel, audio_box = panel("Audio")
        self.cmb_input = QComboBox()
        self.cmb_output = QComboBox()
        self._fill_devices()
        self.cmb_input.currentIndexChanged.connect(self._apply_devices)
        self.cmb_output.currentIndexChanged.connect(self._apply_devices)
        audio_box.addLayout(_row("Micrófono (entrada)", self.cmb_input))
        audio_box.addLayout(_row("Salida (altavoces)", self.cmb_output))

        btn_refresh = QPushButton("Volver a buscar dispositivos")
        btn_refresh.clicked.connect(self._refresh_devices)
        audio_box.addWidget(btn_refresh)

        self.gain = GainSlider("Ganancia mic", s.input_gain)
        self.gain.slider.valueChanged.connect(self._apply_gain)
        audio_box.addWidget(self.gain)

        self.chk_monitor = QCheckBox("Escuchar mi voz por los altavoces mientras grabo (usa auriculares)")
        self.chk_monitor.setChecked(s.monitor_input)
        self.chk_monitor.toggled.connect(self._apply_monitor)
        audio_box.addWidget(self.chk_monitor)

        meter_row = QHBoxLayout()
        self.btn_test_mic = QPushButton("Probar micrófono")
        self.btn_test_mic.setCheckable(True)
        self.btn_test_mic.toggled.connect(self._toggle_mic_test)
        self.meter = LevelMeter()
        meter_row.addWidget(self.btn_test_mic)
        meter_row.addWidget(self.meter, 1)
        audio_box.addLayout(meter_row)

        self.spin_latency = QDoubleSpinBox()
        self.spin_latency.setRange(-500.0, 500.0)
        self.spin_latency.setSuffix(" ms")
        self.spin_latency.setValue(s.latency_compensation_ms)
        self.spin_latency.valueChanged.connect(self._apply_latency)
        audio_box.addLayout(_row("Compensación de latencia", self.spin_latency))
        audio_box.addWidget(hint("Si tu voz grabada suena retrasada respecto a la canción, aumenta este valor: "
                                 "la toma se adelantará esos milisegundos."))
        root.addWidget(audio_panel)

        # --- privacidad ---
        priv_panel, priv_box = panel("Privacidad")
        priv_box.addWidget(hint("Todo el audio se procesa en tu ordenador. Nada se sube a Internet "
                                "salvo que lo autorices aquí."))
        self.chk_external = QCheckBox("Permitir servicios externos (APIs de IA en la nube)")
        self.chk_external.setChecked(s.allow_external_services)
        self.chk_external.toggled.connect(self._apply_privacy)
        self.chk_youtube = QCheckBox("Permitir buscar y descargar canciones de YouTube")
        self.chk_youtube.setChecked(s.allow_youtube)
        self.chk_youtube.toggled.connect(self._apply_youtube)
        priv_box.addWidget(self.chk_external)
        priv_box.addWidget(self.chk_youtube)
        priv_box.addWidget(hint(AVISO_LEGAL))
        priv_box.addWidget(hint("Las claves de API nunca se guardan en el código: se leen de variables de entorno "
                                "o del archivo .env (ver .env.example)."))
        root.addWidget(priv_panel)

        # --- carpetas ---
        folders_panel, folders_box = panel("Carpetas")
        folders_box.addWidget(QLabel("Proyectos"))
        self.lbl_projects = QLabel(str(s.projects_path()))
        self.lbl_projects.setWordWrap(True)
        folders_box.addWidget(self.lbl_projects)
        btn_change = QPushButton("Cambiar carpeta de proyectos…")
        btn_change.clicked.connect(self._change_projects_dir)
        btn_logs = QPushButton("Abrir carpeta de logs")
        btn_logs.clicked.connect(self._open_logs)
        buttons = QHBoxLayout()
        buttons.addWidget(btn_change)
        buttons.addWidget(btn_logs)
        buttons.addStretch(1)
        folders_box.addLayout(buttons)

        folders_box.addSpacing(8)
        folders_box.addWidget(QLabel("Tu música (donde busca «Buscar canción»)"))
        self.music_list = QListWidget()
        self.music_list.setMaximumHeight(110)
        self._refresh_music_folders()
        folders_box.addWidget(self.music_list)
        music_buttons = QHBoxLayout()
        btn_add_music = QPushButton("Añadir carpeta…")
        btn_add_music.clicked.connect(self._add_music_folder)
        self.btn_remove_music = QPushButton("Quitar")
        self.btn_remove_music.clicked.connect(self._remove_music_folder)
        music_buttons.addWidget(btn_add_music)
        music_buttons.addWidget(self.btn_remove_music)
        music_buttons.addStretch(1)
        folders_box.addLayout(music_buttons)
        folders_box.addWidget(hint(f"Registro de errores: {self.log_file}"))
        root.addWidget(folders_panel)

        # --- equipo ---
        hw_panel, hw_box = panel("Tu equipo")
        info = detect_hardware()
        label = QLabel(info.summary())
        label.setWordWrap(True)
        hw_box.addWidget(label)
        if not info.has_nvidia:
            hw_box.addWidget(hint("Sin GPU NVIDIA la app funciona igual: los modelos de IA de las próximas "
                                  "fases usarán la CPU (más lento, pero funcional)."))
        elif not info.torch_installed:
            hw_box.addWidget(hint("PyTorch todavía no está instalado; se añadirá al llegar a las fases de IA "
                                  "para aprovechar tu GPU."))
        root.addWidget(hw_panel)
        root.addStretch(1)

    # --- dispositivos ---
    def _fill_devices(self) -> None:
        s = self.session.settings
        for combo, getter, current in (
            (self.cmb_input, self.session.backend.input_devices, s.input_device),
            (self.cmb_output, self.session.backend.output_devices, s.output_device),
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
        self.status.emit("Lista de dispositivos actualizada.")

    def _apply_devices(self) -> None:
        try:
            self.session.apply_devices(self.cmb_input.currentData(), self.cmb_output.currentData())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Al cambiar el dispositivo de audio")
            return
        self.status.emit("Dispositivos de audio actualizados.")

    def _apply_gain(self) -> None:
        self.session.settings.input_gain = self.gain.gain()
        self.session.recorder.gain = self.gain.gain()
        self.session.save_settings()

    def _apply_monitor(self, on: bool) -> None:
        self.session.settings.monitor_input = on
        self.session.recorder.monitor = on
        if on:
            try:
                self.session.player.ensure_stream()
            except Exception as exc:  # noqa: BLE001
                show_error(self, exc, "Al activar la monitorización")
        self.session.save_settings()

    def _apply_latency(self, value: float) -> None:
        self.session.settings.latency_compensation_ms = value
        self.session.save_settings()

    def _apply_privacy(self, on: bool) -> None:
        self.session.settings.allow_external_services = on
        self.session.save_settings()
        self.status.emit("Servicios externos permitidos." if on else "Modo local: no se usarán servicios externos.")

    def _toggle_mic_test(self, on: bool) -> None:
        if on:
            try:
                self.session.recorder.arm()
            except Exception as exc:  # noqa: BLE001
                self.btn_test_mic.setChecked(False)
                show_error(self, exc, "Al abrir el micrófono")
                return
            self.btn_test_mic.setText("Detener prueba")
            self.status.emit("Habla: deberías ver moverse el medidor.")
        else:
            if not self.session.recorder.is_recording:
                self.session.recorder.close()
            self.btn_test_mic.setText("Probar micrófono")
            self.meter.reset()

    def tick(self) -> None:
        if self.btn_test_mic.isChecked():
            self.meter.set_level(self.session.recorder.level)

    def _apply_youtube(self, on: bool) -> None:
        self.session.settings.allow_youtube = on
        self.session.save_settings()
        self.status.emit("Búsqueda en YouTube activada." if on
                         else "Búsqueda en YouTube desactivada: solo se buscará en tu música.")

    # --- carpetas de música ---
    def _refresh_music_folders(self) -> None:
        self.music_list.clear()
        configured = self.session.settings.music_folders
        for path in (configured or [str(p) for p in self.session.settings.music_paths()]):
            item = QListWidgetItem(path if configured else f"{path}   (automática)")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.music_list.addItem(item)
        if not self.music_list.count():
            self.music_list.addItem("Ninguna carpeta encontrada: añade una.")
        if hasattr(self, "btn_remove_music"):
            self.btn_remove_music.setEnabled(bool(configured))

    def _add_music_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Carpeta con tu música", str(Path.home()))
        if not path:
            return
        folders = self.session.settings.music_folders or [str(p) for p in self.session.settings.music_paths()]
        if path not in folders:
            folders.append(path)
        self.session.settings.music_folders = folders
        self.session.save_settings()
        self._refresh_music_folders()
        self.status.emit(f"Carpeta de música añadida: {path}")

    def _remove_music_folder(self) -> None:
        item = self.music_list.currentItem()
        if item is None:
            return
        target = item.data(Qt.ItemDataRole.UserRole)
        self.session.settings.music_folders = [f for f in self.session.settings.music_folders if f != target]
        self.session.save_settings()
        self._refresh_music_folders()

    def _change_projects_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Carpeta de proyectos", str(self.session.settings.projects_path()))
        if path:
            self.session.settings.projects_dir = path
            self.session.save_settings()
            self.lbl_projects.setText(path)
            self.status.emit("Carpeta de proyectos actualizada.")

    def _open_logs(self) -> None:
        folder = self.log_file.parent
        try:
            subprocess.Popen(["explorer", str(folder)])  # noqa: S607
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Al abrir la carpeta de logs")


def _row(label: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    name = QLabel(label)
    name.setMinimumWidth(170)
    row.addWidget(name)
    row.addWidget(widget, 1)
    return row
