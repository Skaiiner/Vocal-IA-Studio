from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vocal_ai_studio.audio.io import EXPORT_FORMATS, IMPORT_EXTENSIONS
from vocal_ai_studio.pitch.notes import hz_to_midi, midi_to_note_name
from vocal_ai_studio.recording.recorder import RecState
from vocal_ai_studio.session import Session
from vocal_ai_studio.storage.exporter import KINDS
from vocal_ai_studio.ui import theme
from vocal_ai_studio.ui.lyrics_panel import LyricsPanel
from vocal_ai_studio.ui.waveform_widget import LevelMeter, WaveformView, format_time
from vocal_ai_studio.ui.widgets import GainSlider, hint, panel, show_error

log = logging.getLogger(__name__)

_IMPORT_FILTER = (
    "Audio y vídeo (" + " ".join(f"*{e}" for e in IMPORT_EXTENSIONS) + ");;Todos los archivos (*.*)"
)


class SongView(QWidget):
    status = Signal(str)
    project_changed = Signal()

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.refresh()

    # --- construcción ---
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # fila de acciones
        actions, actions_box = panel()
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_search_song = QPushButton("Buscar canción")
        self.btn_search_song.setObjectName("Primary")
        self.btn_search_song.clicked.connect(self._search_song)
        self.btn_import_song = QPushButton("Import Song")
        self.btn_import_song.clicked.connect(self._import_song)
        self.btn_import_vocal = QPushButton("Import Vocal")
        self.btn_import_vocal.clicked.connect(self._import_vocal)
        self.btn_record = QPushButton("Record")
        self.btn_record.setObjectName("Record")
        self.btn_record.clicked.connect(self._toggle_record)
        self.btn_pause_rec = QPushButton("Pausar grabación")
        self.btn_pause_rec.clicked.connect(self._toggle_pause_record)
        self.btn_play = QPushButton("Play")
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.clicked.connect(self._stop)
        for b in (self.btn_search_song, self.btn_import_song, self.btn_import_vocal, self.btn_record,
                  self.btn_pause_rec, self.btn_play, self.btn_stop):
            row.addWidget(b)
        row.addStretch(1)
        self.lbl_time = QLabel("00:00.0 / 00:00.0")
        self.lbl_time.setStyleSheet("font-family: Consolas, monospace; font-size: 14px;")
        row.addWidget(self.lbl_time)
        actions_box.addLayout(row)

        meter_row = QHBoxLayout()
        meter_row.addWidget(QLabel("Micrófono"))
        self.cmb_mic = QComboBox()
        self.cmb_mic.setMinimumWidth(260)
        self.cmb_mic.setToolTip("Elige aquí el micrófono con el que vas a cantar.")
        self.cmb_mic.currentIndexChanged.connect(self._apply_mic)
        meter_row.addWidget(self.cmb_mic)
        self.btn_monitor = QPushButton("Escucharme")
        self.btn_monitor.setCheckable(True)
        self.btn_monitor.setToolTip("Oye tu propia voz mientras grabas. Usa auriculares o habrá acoplamiento.")
        self.btn_monitor.toggled.connect(self._apply_monitor)
        meter_row.addWidget(self.btn_monitor)
        self.meter = LevelMeter()
        meter_row.addWidget(self.meter, 1)
        self.btn_live_note = QPushButton("Nota en vivo")
        self.btn_live_note.setCheckable(True)
        self.btn_live_note.setToolTip("Muestra tu nota actual mientras cantas. Apagado por defecto: "
                                      "analizar el tono en cada instante tiene un coste de CPU, así "
                                      "que solo se calcula cuando tú lo activas.")
        meter_row.addWidget(self.btn_live_note)
        self.lbl_live_note = QLabel("")
        self.lbl_live_note.setMinimumWidth(90)
        self.lbl_live_note.setStyleSheet(f"color:{theme.ACCENT}; font-weight:700;")
        meter_row.addWidget(self.lbl_live_note)
        self.lbl_rec = QLabel("")
        self.lbl_rec.setMinimumWidth(190)
        meter_row.addWidget(self.lbl_rec)
        actions_box.addLayout(meter_row)
        root.addWidget(actions)
        self.btn_monitor.setChecked(self.session.settings.monitor_input)
        self._fill_mics()

        # waveform
        wave_panel, wave_box = panel()
        self.wave = WaveformView()
        self.wave.seeked.connect(self._on_seek)
        wave_box.addWidget(self.wave, 1)
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(hint("Clic en la onda para situarte · Ctrl+rueda para zoom", wrap=False))
        zoom_row.addStretch(1)
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setFixedWidth(34)
        btn_zoom_out.clicked.connect(lambda: self.wave.set_zoom(self.wave.zoom / 1.5))
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedWidth(34)
        btn_zoom_in.clicked.connect(lambda: self.wave.set_zoom(self.wave.zoom * 1.5))
        btn_zoom_fit = QPushButton("Ajustar")
        btn_zoom_fit.clicked.connect(lambda: self.wave.set_zoom(1.0))
        for b in (btn_zoom_out, btn_zoom_in, btn_zoom_fit):
            zoom_row.addWidget(b)
        wave_box.addLayout(zoom_row)

        wave_row = QHBoxLayout()
        wave_row.addWidget(wave_panel, 3)
        self.lyrics_panel = LyricsPanel(self.session)
        self.lyrics_panel.status.connect(self.status.emit)
        wave_row.addWidget(self.lyrics_panel, 1)
        root.addLayout(wave_row, 1)

        # abajo: mezcla + tomas + exportación
        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        mix_panel, mix_box = panel("Mezcla")
        self.song_gain = GainSlider("Canción")
        self.song_gain.slider.valueChanged.connect(lambda: self.session.set_song_gain(self.song_gain.gain()))
        self.vocal_gain = GainSlider("Voz")
        self.vocal_gain.slider.valueChanged.connect(lambda: self.session.set_vocal_gain(self.vocal_gain.gain()))
        mix_box.addWidget(self.song_gain)
        mix_box.addWidget(self.vocal_gain)
        mix_box.addWidget(hint("La voz se silencia mientras grabas para que no se mezcle con la toma nueva."))
        mix_box.addWidget(hint("¿La canción trae la voz original de otro cantante? Ve a la pestaña "
                               "«Separar voz/instrumental» para quedarte solo con el instrumental antes "
                               "de grabar — así tu voz no se mezclará con la del cantante original."))
        mix_box.addStretch(1)
        bottom.addWidget(mix_panel, 1)

        takes_panel, takes_box = panel("Tomas")
        self.takes_list = QListWidget()
        self.takes_list.itemSelectionChanged.connect(self._on_take_selected)
        self.takes_list.itemDoubleClicked.connect(lambda _: self._rename_take())
        takes_box.addWidget(self.takes_list, 1)
        take_buttons = QHBoxLayout()
        self.btn_add_take = QPushButton("+ Añadir audio")
        self.btn_add_take.setObjectName("Primary")
        self.btn_add_take.setToolTip("Importa uno o varios archivos de audio como tomas nuevas.")
        self.btn_add_take.clicked.connect(self._import_as_take)
        self.btn_rename_take = QPushButton("Renombrar")
        self.btn_rename_take.clicked.connect(self._rename_take)
        self.btn_delete_take = QPushButton("Eliminar")
        self.btn_delete_take.clicked.connect(self._delete_take)
        self.btn_use_imported = QPushButton("Usar voz importada")
        self.btn_use_imported.clicked.connect(lambda: self._select_take(0))
        for b in (self.btn_add_take, self.btn_rename_take, self.btn_delete_take, self.btn_use_imported):
            take_buttons.addWidget(b)
        takes_box.addLayout(take_buttons)
        bottom.addWidget(takes_panel, 1)

        export_panel, export_box = panel("Exportar")
        self.export_kind = QComboBox()
        for key, label in KINDS.items():
            self.export_kind.addItem(label, key)
        self.export_fmt = QComboBox()
        self.export_fmt.addItems([f.upper() for f in EXPORT_FORMATS])
        export_box.addWidget(self.export_kind)
        export_box.addWidget(self.export_fmt)
        self.btn_export = QPushButton("Exportar…")
        self.btn_export.setObjectName("Primary")
        self.btn_export.clicked.connect(self._export)
        export_box.addWidget(self.btn_export)
        export_box.addWidget(hint("Se guarda en la carpeta exports/ del proyecto salvo que elijas otra."))
        export_box.addStretch(1)
        bottom.addWidget(export_panel, 1)
        root.addLayout(bottom)

    # --- micrófono ---
    def _fill_mics(self) -> None:
        self.cmb_mic.blockSignals(True)
        self.cmb_mic.clear()
        self.cmb_mic.addItem("Predeterminado del sistema", "")
        try:
            for dev in self.session.backend.input_devices():
                self.cmb_mic.addItem(dev.name, dev.label)
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudieron listar micrófonos: %s", exc)
        idx = self.cmb_mic.findData(self.session.settings.input_device)
        self.cmb_mic.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_mic.blockSignals(False)
        self._arm_mic()

    def _apply_mic(self) -> None:
        try:
            self.session.apply_devices(input_device=self.cmb_mic.currentData())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Al cambiar de micrófono")
            return
        self.meter.reset()
        self._arm_mic()
        self.status.emit(f"Micrófono: {self.cmb_mic.currentText()}. Habla y comprueba que el medidor se mueve.")

    def _arm_mic(self) -> None:
        # si falla (micro en uso por otra app) no se interrumpe al usuario, solo se avisa
        if self.session.recorder.state is not RecState.CLOSED:
            return
        try:
            self.session.recorder.arm()
        except Exception as exc:  # noqa: BLE001
            log.info("No se pudo abrir el micrófono: %s", exc)
            self.status.emit("No se pudo abrir el micrófono: elige otro en la lista.")

    def _apply_monitor(self, on: bool) -> None:
        self.session.settings.monitor_input = on
        self.session.recorder.monitor = on
        self.session.save_settings()
        if on:
            try:
                self.session.player.ensure_stream()
            except Exception as exc:  # noqa: BLE001
                self.btn_monitor.setChecked(False)
                show_error(self, exc, "Al activar la escucha")
                return
            self.status.emit("Te oirás mientras grabas. Usa auriculares para evitar acoplamiento.")

    # --- acciones ---
    def _search_song(self) -> None:
        from vocal_ai_studio.ui.search_dialog import SearchDialog

        dialog = SearchDialog(self.session, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.imported_title:
            self.status.emit(f"Canción cargada: {dialog.imported_title}")
            self.refresh()
            self.project_changed.emit()

    def _import_song(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar canción", "", _IMPORT_FILTER)
        if not path:
            return
        try:
            audio = self.session.import_song_file(path)
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo al importar canción")
            show_error(self, exc, "Al importar la canción")
            return
        self.status.emit(f"Canción importada: {Path(path).name} ({format_time(audio.duration)})")
        self.refresh()
        self.project_changed.emit()

    def _import_vocal(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar voz", "", _IMPORT_FILTER)
        if not path:
            return
        try:
            self.session.import_vocal_file(path)
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo al importar voz")
            show_error(self, exc, "Al importar la voz")
            return
        self.status.emit(f"Voz importada: {Path(path).name}")
        self.refresh()
        self.project_changed.emit()

    def _import_as_take(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Añadir audio como toma", "", _IMPORT_FILTER)
        if not paths:
            return
        errors: list[str] = []
        imported = 0
        for path in paths:
            try:
                audio = self.session.import_vocal_as_take(path)
                imported += 1
                self.status.emit(f"Toma añadida: {Path(path).name} ({format_time(audio.duration)})")
            except Exception as exc:  # noqa: BLE001
                log.exception("Fallo al importar toma: %s", path)
                errors.append(f"{Path(path).name}: {exc}")
        if errors:
            show_error(self, errors[0], "Al importar tomas")
        if imported:
            self.refresh()
            self.project_changed.emit()

    def _toggle_play(self) -> None:
        if self.session.player.is_playing:
            self.session.pause()
        else:
            try:
                self.session.play()
            except Exception as exc:  # noqa: BLE001
                log.exception("Fallo al reproducir")
                show_error(self, exc, "Al reproducir")
        self._update_buttons()

    def _stop(self) -> None:
        self.session.stop()
        self.meter.reset()
        self.wave.set_recording_time(None)
        self.refresh()

    def _toggle_record(self) -> None:
        rec = self.session.recorder
        if rec.state in (RecState.RECORDING, RecState.PAUSED):
            try:
                take = self.session.finish_recording()
            except Exception as exc:  # noqa: BLE001
                log.exception("Fallo al terminar la grabación")
                show_error(self, exc, "Al terminar la grabación")
                return
            self.wave.set_recording_time(None)
            self.status.emit(f"{take.name} guardada ({format_time(take.duration_sec)})" if take
                             else "Grabación vacía: no se guardó ninguna toma.")
            self.refresh()
            self.project_changed.emit()
            return
        try:
            self.session.start_recording()
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo al iniciar la grabación")
            show_error(self, exc, "Al iniciar la grabación")
            return
        self.status.emit("Grabando… pulsa Stop rec para guardar la toma.")
        self._update_buttons()

    def _toggle_pause_record(self) -> None:
        rec = self.session.recorder
        if rec.state == RecState.RECORDING:
            self.session.pause_recording()
        elif rec.state == RecState.PAUSED:
            self.session.resume_recording()
        self._update_buttons()

    def _on_seek(self, seconds: float) -> None:
        self.session.seek(seconds)
        self.wave.set_position(seconds)

    def _select_take(self, take_id: int) -> None:
        try:
            self.session.select_take(take_id)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Al seleccionar la toma")
            return
        self.refresh()

    def _on_take_selected(self) -> None:
        item = self.takes_list.currentItem()
        if item is None:
            return
        take_id = item.data(Qt.ItemDataRole.UserRole)
        project = self.session.project
        if project and take_id != project.data.active_take:
            self._select_take(take_id)

    def _rename_take(self) -> None:
        item = self.takes_list.currentItem()
        if item is None:
            return
        take_id = item.data(Qt.ItemDataRole.UserRole)
        name, ok = QInputDialog.getText(self, "Renombrar toma", "Nombre:", text=item.text().split("  ")[0])
        if ok and name.strip():
            self.session.rename_take(take_id, name)
            self.refresh()

    def _delete_take(self) -> None:
        item = self.takes_list.currentItem()
        if item is None:
            return
        self.session.delete_take(item.data(Qt.ItemDataRole.UserRole))
        self.status.emit("Toma eliminada.")
        self.refresh()
        self.project_changed.emit()

    def _export(self) -> None:
        project = self.session.project
        if project is None:
            return
        kind = self.export_kind.currentData()
        fmt = self.export_fmt.currentText().lower()
        suggested = project.exports_dir / self.session.default_export_name(kind, fmt)
        path, _ = QFileDialog.getSaveFileName(self, "Exportar", str(suggested), f"{fmt.upper()} (*.{fmt})")
        if not path:
            return
        try:
            out = self.session.export(kind, path, fmt)
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo al exportar")
            show_error(self, exc, "Al exportar")
            return
        self.status.emit(f"Exportado: {out}")

    # --- refresco ---
    def sync_devices(self) -> None:
        if self.cmb_mic.currentData() != self.session.settings.input_device:
            self._fill_mics()
        self.btn_monitor.setChecked(self.session.settings.monitor_input)

    def refresh(self) -> None:
        project = self.session.project
        self.wave.set_track("song", project.load_song() if project else None)
        vocal = project.active_vocal() if project else None
        self.wave.set_track("vocal", vocal[0] if vocal else None, vocal[1] if vocal else 0.0)
        if project:
            self.song_gain.slider.blockSignals(True)
            self.vocal_gain.slider.blockSignals(True)
            self.song_gain.slider.setValue(int(project.data.song_gain * 100))
            self.vocal_gain.slider.setValue(int(project.data.vocal_gain * 100))
            self.song_gain.slider.blockSignals(False)
            self.vocal_gain.slider.blockSignals(False)
        self._refresh_takes()
        self.lyrics_panel.refresh()
        self._update_buttons()

    def _refresh_takes(self) -> None:
        project = self.session.project
        self.takes_list.blockSignals(True)
        self.takes_list.clear()
        if project:
            for take in project.data.takes:
                mark = "●  " if take.id == project.data.active_take else "    "
                item = QListWidgetItem(f"{mark}{take.name}  ({format_time(take.duration_sec)})")
                item.setData(Qt.ItemDataRole.UserRole, take.id)
                self.takes_list.addItem(item)
                if take.id == project.data.active_take:
                    self.takes_list.setCurrentItem(item)
        self.takes_list.blockSignals(False)
        has_vocal_file = bool(project and project.data.vocal_file)
        self.btn_use_imported.setEnabled(has_vocal_file and project.data.active_take != 0)

    def _update_buttons(self) -> None:
        has_project = self.session.project is not None
        rec = self.session.recorder
        recording = rec.state in (RecState.RECORDING, RecState.PAUSED)
        for b in (self.btn_search_song, self.btn_import_song, self.btn_import_vocal, self.btn_export):
            b.setEnabled(has_project and not recording)
        self.cmb_mic.setEnabled(not recording)
        self.btn_record.setEnabled(has_project)
        self.btn_record.setText("Stop rec" if recording else "Record")
        self.btn_pause_rec.setEnabled(recording)
        self.btn_pause_rec.setText("Continuar" if rec.state == RecState.PAUSED else "Pausar grabación")
        playable = self.session.player.duration > 0
        self.btn_play.setEnabled(playable and not recording)
        self.btn_play.setText("Pause" if self.session.player.is_playing else "Play")
        self.btn_stop.setEnabled(playable or recording)
        selected = self.takes_list.currentItem() is not None
        self.btn_rename_take.setEnabled(selected and not recording)
        self.btn_delete_take.setEnabled(selected and not recording)

    def _tick(self) -> None:
        player = self.session.player
        rec = self.session.recorder
        self.wave.set_position(player.position)
        self.lbl_time.setText(f"{format_time(player.position)} / {format_time(player.duration)}")
        self.lyrics_panel.tick(player.position)
        if rec.state in (RecState.ARMED, RecState.RECORDING, RecState.PAUSED):
            self.meter.set_level(rec.level)
            if self.btn_live_note.isChecked():
                freq, confidence = rec.live_pitch()
                if confidence > 0.3 and freq == freq:  # freq == freq ⇔ no es NaN
                    midi = hz_to_midi(freq)
                    cents = (midi - round(midi)) * 100.0
                    self.lbl_live_note.setText(f"{midi_to_note_name(round(midi))} {cents:+.0f}¢")
                else:
                    self.lbl_live_note.setText("")
            else:
                self.lbl_live_note.setText("")
        else:
            self.lbl_live_note.setText("")
        if rec.state == RecState.RECORDING:
            self.lbl_rec.setText(f"<span style='color:{theme.REC}'>● REC {format_time(rec.elapsed)}</span>")
            self.wave.set_recording_time(self.session.recording_position)
        elif rec.state == RecState.PAUSED:
            self.lbl_rec.setText(f"<span style='color:{theme.WARN}'>❙❙ Grabación en pausa "
                                 f"{format_time(rec.elapsed)}</span>")
        else:
            self.lbl_rec.setText("")
        if player.pop_finished():
            self._update_buttons()
        elif self.btn_play.text() == "Pause" and not player.is_playing:
            self._update_buttons()
        elif self.btn_play.text() == "Play" and player.is_playing:
            self._update_buttons()
