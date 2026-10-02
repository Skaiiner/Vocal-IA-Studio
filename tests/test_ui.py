from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from vocal_ai_studio.audio.io import save_audio
from vocal_ai_studio.core.config import Settings, SettingsStore
from vocal_ai_studio.recording.recorder import RecState
from vocal_ai_studio.session import Session
from vocal_ai_studio.ui.main_window import MainWindow
from vocal_ai_studio.ui.waveform_widget import LevelMeter, WaveformView, format_time
from tests.conftest import tone


@pytest.fixture
def window(qtbot, backend, tmp_path):
    settings = Settings(projects_dir=str(tmp_path / "Projects"))
    session = Session(backend, settings, SettingsStore(tmp_path / "settings.json"))
    session.new_project("UI Test")
    win = MainWindow(session, tmp_path / "logs" / "app.log")
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.song_view.refresh()
    yield win
    win.session.close()


def test_window_has_expected_tabs(window):
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert titles == ["Song", "Voice", "Pitch Editor", "Voice Lab", "AI Coach", "Live Voice", "Settings"]


def test_transport_disabled_without_audio(window):
    view = window.song_view
    assert view.btn_play.isEnabled() is False
    assert view.btn_record.isEnabled() is True
    assert view.btn_export.isEnabled() is True


def test_importing_song_enables_playback_and_updates_wave(window, tmp_path):
    save_audio(tmp_path / "s.wav", tone(2.0, 440, channels=2), "wav")
    window.session.import_song_file(tmp_path / "s.wav")
    window.song_view.refresh()
    assert window.song_view.btn_play.isEnabled() is True
    assert window.song_view.wave.duration == pytest.approx(2.0, abs=0.05)
    assert "2 tomas" not in window.lbl_project.text()


def test_play_button_toggles_and_timer_updates_clock(window, tmp_path, backend):
    save_audio(tmp_path / "s.wav", tone(2.0, 440, channels=2), "wav")
    window.session.import_song_file(tmp_path / "s.wav")
    window.song_view.refresh()
    window.song_view._toggle_play()
    assert window.song_view.btn_play.text() == "Pause"
    backend.output_stream.pump(10)
    window.song_view._tick()
    assert window.song_view.lbl_time.text().startswith("00:00.0") is False
    window.song_view._toggle_play()
    assert window.song_view.btn_play.text() == "Play"


def test_record_flow_creates_take_item(window, backend):
    view = window.song_view
    view._toggle_record()
    assert view.btn_record.text() == "Stop rec"
    assert window.session.recorder.state is RecState.RECORDING
    backend.input_stream.pump(10)
    view._tick()
    assert "REC" in view.lbl_rec.text()
    view._toggle_record()
    assert view.takes_list.count() == 1
    assert "Take 1" in view.takes_list.item(0).text()
    assert view.btn_record.text() == "Record"


def test_pause_resume_recording_updates_button(window, backend):
    view = window.song_view
    view._toggle_record()
    view._toggle_pause_record()
    assert window.session.recorder.state is RecState.PAUSED
    assert view.btn_pause_rec.text() == "Continuar"
    view._tick()
    assert "pausa" in view.lbl_rec.text()
    view._toggle_pause_record()
    assert window.session.recorder.state is RecState.RECORDING
    view._toggle_record()


def test_selecting_take_changes_active(window, backend):
    view = window.song_view
    for _ in range(2):
        view._toggle_record()
        backend.input_stream.pump(5)
        view._toggle_record()
    assert view.takes_list.count() == 2
    view.takes_list.setCurrentRow(0)
    assert window.session.project.data.active_take == 1
    assert view.takes_list.item(0).text().startswith("●")


def test_delete_take_from_ui(window, backend):
    view = window.song_view
    view._toggle_record()
    backend.input_stream.pump(5)
    view._toggle_record()
    view.takes_list.setCurrentRow(0)
    view._delete_take()
    assert view.takes_list.count() == 0
    assert window.session.project.data.takes == []


def test_seek_from_waveform_moves_player(window, tmp_path):
    save_audio(tmp_path / "s.wav", tone(4.0, 440, channels=2), "wav")
    window.session.import_song_file(tmp_path / "s.wav")
    window.song_view.refresh()
    window.song_view._on_seek(2.5)
    assert window.session.player.position == pytest.approx(2.5, abs=0.01)


def test_gain_sliders_update_project(window):
    window.song_view.song_gain.slider.setValue(50)
    assert window.session.project.data.song_gain == pytest.approx(0.5)
    window.song_view.vocal_gain.slider.setValue(120)
    assert window.session.project.data.vocal_gain == pytest.approx(1.2)


def test_new_and_save_as_project_update_header(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Otro proyecto", True))
    window.new_project()
    assert window.session.project.name == "Otro proyecto"
    assert "Otro proyecto" in window.lbl_project.text()
    window.save_project_as()
    assert window.session.project.name == "Otro proyecto"


def test_settings_lists_devices_and_toggles(window):
    view = window.settings_view
    assert view.cmb_input.count() >= 2  # predeterminado + micrófono falso
    view.chk_monitor.setChecked(True)
    assert window.session.recorder.monitor is True
    view.gain.slider.setValue(130)
    assert window.session.recorder.gain == pytest.approx(1.3)
    view.chk_external.setChecked(True)
    assert window.session.settings.allow_external_services is True
    view.spin_latency.setValue(25.0)
    assert window.session.settings.latency_compensation_ms == pytest.approx(25.0)


def test_settings_mic_test_arms_recorder(window):
    view = window.settings_view
    view.btn_test_mic.setChecked(True)
    assert window.session.recorder.state is RecState.ARMED
    view.tick()
    view.btn_test_mic.setChecked(False)
    assert window.session.recorder.state is RecState.CLOSED


def test_song_tab_has_mic_selector(window):
    view = window.song_view
    assert view.cmb_mic.count() >= 2  # predeterminado + micrófono falso
    assert view.cmb_mic.itemText(1) == "Fake Mic"
    view.cmb_mic.setCurrentIndex(1)
    assert window.session.settings.input_device == "Fake Mic [FakeAPI]"
    assert window.session.recorder.input_device == "Fake Mic [FakeAPI]"


def test_mic_is_armed_so_meter_works_without_recording(window, backend):
    assert window.session.recorder.state is RecState.ARMED
    backend.input_stream.pump(2)
    window.song_view._tick()
    assert window.session.recorder.level > 0.1


def test_mic_selector_disabled_while_recording(window, backend):
    view = window.song_view
    view._toggle_record()
    assert view.cmb_mic.isEnabled() is False
    view._toggle_record()
    assert view.cmb_mic.isEnabled() is True


def test_monitor_button_toggles_monitoring(window):
    window.song_view.btn_monitor.setChecked(True)
    assert window.session.recorder.monitor is True
    window.song_view.btn_monitor.setChecked(False)
    assert window.session.recorder.monitor is False


def test_settings_and_song_tab_stay_in_sync(window):
    window.tabs.setCurrentIndex(window.tabs.count() - 1)      # Settings
    window.settings_view.cmb_input.setCurrentIndex(1)
    window.settings_view.chk_monitor.setChecked(True)
    window.tabs.setCurrentIndex(0)                            # vuelta a Song
    assert window.song_view.cmb_mic.currentData() == window.session.settings.input_device
    assert window.song_view.cmb_mic.currentData() == "Fake Mic [FakeAPI]"
    assert window.song_view.btn_monitor.isChecked() is True


def test_search_dialog_finds_local_music(qtbot, window, tmp_path):
    from vocal_ai_studio.audio.io import save_audio
    from vocal_ai_studio.ui.search_dialog import SearchDialog

    library = tmp_path / "Musica"
    library.mkdir()
    save_audio(library / "Mi Cancion.mp3", tone(0.3, 440, channels=2), "mp3")
    window.session.settings.music_folders = [str(library)]

    dialog = SearchDialog(window.session, window)
    qtbot.addWidget(dialog)
    assert dialog.cmb_source.currentText() == "Mi música"
    dialog.field.setText("cancion")
    dialog._search()
    qtbot.waitUntil(lambda: not dialog._task.running, timeout=5000)
    assert dialog.results.count() == 1
    assert "Mi Cancion" in dialog.results.item(0).text()

    dialog.results.setCurrentRow(0)
    dialog._import()
    qtbot.waitUntil(lambda: not dialog._task.running, timeout=10000)
    assert dialog.imported_title == "Mi Cancion"
    assert window.session.project.data.song_title == "Mi Cancion"
    assert window.session.player.duration > 0.1


def test_search_dialog_youtube_disabled_shows_reason(qtbot, window):
    from vocal_ai_studio.ui.search_dialog import SearchDialog

    dialog = SearchDialog(window.session, window)
    qtbot.addWidget(dialog)
    dialog.cmb_source.setCurrentIndex(1)
    assert dialog.cmb_source.currentText() == "YouTube"
    assert dialog.btn_search.isEnabled() is False
    assert "Privacidad" in dialog.lbl_source.text()

    window.settings_view.chk_youtube.setChecked(True)
    dialog2 = SearchDialog(window.session, window)
    qtbot.addWidget(dialog2)
    dialog2.cmb_source.setCurrentIndex(1)
    assert dialog2.btn_search.isEnabled() is True
    assert "DRM" in dialog2.lbl_source.text()


def test_search_dialog_reports_errors_without_crashing(qtbot, window, monkeypatch):
    from vocal_ai_studio.ui import search_dialog as sd

    shown = []
    monkeypatch.setattr(sd, "show_error", lambda *a, **k: shown.append(a))
    dialog = sd.SearchDialog(window.session, window)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, "_source", lambda: _BrokenSource())
    dialog.field.setText("algo")
    dialog._search()
    qtbot.waitUntil(lambda: not dialog._task.running, timeout=5000)
    assert shown and dialog.results.count() == 0


class _BrokenSource:
    name = "Rota"
    needs_internet = False

    def is_available(self):
        return True, ""

    def search(self, query, limit=20, cancelled=None):
        raise RuntimeError("fallo simulado de la fuente")

    def fetch(self, result, dest_dir, progress=None, cancelled=None):
        raise RuntimeError("no implementado")


def test_lyrics_panel_shows_placeholder_when_empty(window):
    panel = window.song_view.lyrics_panel
    assert panel.list.count() == 1
    assert "Sin letra" in panel.list.item(0).text()
    assert panel.btn_sync.isEnabled() is False


def test_lyrics_panel_shows_lines_after_edit(window):
    window.session.set_lyrics_text("Primera\nSegunda\nTercera")
    window.song_view.lyrics_panel.refresh()
    panel = window.song_view.lyrics_panel
    assert panel.list.count() == 3
    assert panel.list.item(1).text() == "Segunda"
    assert panel.btn_sync.isEnabled() is True
    assert panel.btn_unsync.isVisible() is False


def test_lyrics_dialog_saves_text(qtbot, window):
    from vocal_ai_studio.ui.lyrics_dialog import LyricsDialog
    from PySide6.QtWidgets import QDialog

    dialog = LyricsDialog(window.session, window)
    qtbot.addWidget(dialog)
    dialog.editor.setPlainText("Una linea\nOtra linea")
    dialog._save()
    assert window.session.load_lyrics().to_plain_text() == "Una linea\nOtra linea"


def test_lyrics_dialog_prefills_existing_lyrics(qtbot, window):
    from vocal_ai_studio.ui.lyrics_dialog import LyricsDialog

    window.session.set_lyrics_text("Ya existia")
    dialog = LyricsDialog(window.session, window)
    qtbot.addWidget(dialog)
    assert dialog.editor.toPlainText() == "Ya existia"


def test_lyrics_dialog_imports_file(qtbot, window, tmp_path):
    from vocal_ai_studio.ui.lyrics_dialog import LyricsDialog

    letra = tmp_path / "letra.lrc"
    letra.write_text("[00:01.00]Importada", encoding="utf-8")
    dialog = LyricsDialog(window.session, window)
    qtbot.addWidget(dialog)
    dialog._import_file = lambda: dialog.editor.setPlainText(letra.read_text(encoding="utf-8"))
    dialog._import_file()
    assert "[00:01.00]Importada" in dialog.editor.toPlainText()
    dialog._save()
    assert window.session.load_lyrics().synced is True


def test_lyrics_sync_flow_marks_lines_in_order(window, backend, tmp_path):
    from vocal_ai_studio.audio.io import save_audio

    save_audio(tmp_path / "s.wav", tone(2.0, 440, channels=2), "wav")
    window.session.import_song_file(tmp_path / "s.wav")
    panel = window.song_view.lyrics_panel
    window.session.set_lyrics_text("Uno\nDos\nTres")
    panel.refresh()
    panel._start_sync()
    assert panel._syncing is True
    assert panel.btn_mark.isVisible() is True
    assert panel.btn_sync.isVisible() is False

    backend.output_stream.pump(1)
    panel._mark()
    assert panel._sync_index == 1
    lyrics = window.session.load_lyrics()
    assert lyrics.lines[0].time is not None
    assert lyrics.lines[1].time is None

    panel._mark()
    panel._mark()  # tras la tercera línea, termina sola
    assert panel._syncing is False
    assert panel.btn_sync.isVisible() is True
    final = window.session.load_lyrics()
    assert final.synced_count == 3


def test_lyrics_sync_undo_clears_last_mark(window, backend, tmp_path):
    from vocal_ai_studio.audio.io import save_audio

    save_audio(tmp_path / "s.wav", tone(2.0, 440, channels=2), "wav")
    window.session.import_song_file(tmp_path / "s.wav")
    panel = window.song_view.lyrics_panel
    window.session.set_lyrics_text("Uno\nDos")
    panel.refresh()
    panel._start_sync()
    panel._mark()
    assert panel._sync_index == 1
    panel._undo_mark()
    assert panel._sync_index == 0
    assert window.session.load_lyrics().lines[0].time is None


def test_lyrics_clear_sync_button(window):
    panel = window.song_view.lyrics_panel
    window.session.set_lyrics_text("[00:01.00]Uno\n[00:02.00]Dos")
    panel.refresh()
    assert panel.btn_unsync.isVisible() is True
    panel._clear_sync()
    assert window.session.load_lyrics().synced is False
    assert panel.btn_unsync.isVisible() is False


def test_lyrics_panel_highlights_current_line_during_playback(window):
    panel = window.song_view.lyrics_panel
    window.session.set_lyrics_text("[00:00.00]Uno\n[00:05.00]Dos\n[00:10.00]Tres")
    panel.refresh()
    panel.tick(0.0)
    assert panel.list.currentRow() == 0
    panel.tick(6.0)
    assert panel.list.currentRow() == 1
    panel.tick(11.0)
    assert panel.list.currentRow() == 2


def test_voice_tab_is_present_and_disabled_without_voice(window):
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert titles == ["Song", "Voice", "Pitch Editor", "Voice Lab", "AI Coach", "Live Voice", "Settings"]
    window.voice_view.refresh()
    assert window.voice_view.btn_analyze.isEnabled() is False


def test_voice_tab_analyze_runs_and_shows_results(qtbot, window):
    window.session.project.add_take(tone(seconds=0.8, freq=440.0, channels=1))
    window.song_view.refresh()
    window.voice_view.refresh()
    assert window.voice_view.btn_analyze.isEnabled() is True

    window.voice_view._analyze()
    qtbot.waitUntil(lambda: not window.voice_view._task.running, timeout=10000)

    assert window.voice_view._analysis is not None
    assert window.voice_view._stat_labels["range"].text() == "A4 – A4"
    assert "cents" in window.voice_view._stat_labels["deviation"].text()
    assert window.voice_view.pitch_view._track is not None


def test_voice_tab_analyze_without_voice_shows_error(qtbot, window, monkeypatch):
    from vocal_ai_studio.ui import voice_view as vv

    shown = []
    monkeypatch.setattr(vv, "show_error", lambda *a, **k: shown.append(a))
    window.voice_view.btn_analyze.setEnabled(True)  # fuerza el intento aunque no haya voz
    window.voice_view._analyze()
    qtbot.waitUntil(lambda: not window.voice_view._task.running, timeout=5000)
    assert shown


def test_voice_tab_reflects_active_take_switch(qtbot, window):
    t1 = window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.song_view.refresh()
    window.voice_view.refresh()
    window.voice_view._analyze()
    qtbot.waitUntil(lambda: not window.voice_view._task.running, timeout=10000)
    assert window.voice_view.lbl_source.text() == t1.name

    t2 = window.session.project.add_take(tone(seconds=0.6, freq=523.25, channels=1))
    window.song_view.refresh()
    window.voice_view.refresh()
    assert window.voice_view.lbl_source.text() == t2.name
    assert window.voice_view._analysis is None  # la toma nueva aún no se ha analizado


def test_voice_tab_cleared_when_project_changes(qtbot, window):
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.voice_view.refresh()
    window.voice_view._analyze()
    qtbot.waitUntil(lambda: not window.voice_view._task.running, timeout=10000)
    assert window.voice_view._analysis is not None

    from PySide6.QtWidgets import QInputDialog
    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(QInputDialog, "getText", lambda *a, **k: ("Otro", True))
        window.new_project()
    assert window.voice_view._analysis is None
    assert window.voice_view.btn_analyze.isEnabled() is False


def test_switching_to_voice_tab_refreshes_it(qtbot, window):
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.voice_view._analyze()
    qtbot.waitUntil(lambda: not window.voice_view._task.running, timeout=10000)
    voice_index = [window.tabs.tabText(i) for i in range(window.tabs.count())].index("Voice")
    window.tabs.setCurrentIndex(voice_index)
    assert window.voice_view.lbl_source.text()  # se refrescó sin lanzar excepciones


def test_pitch_view_renders_with_and_without_data(qtbot):
    from vocal_ai_studio.core.interfaces import PitchTrack
    from vocal_ai_studio.ui.pitch_view import PitchView

    w = PitchView()
    qtbot.addWidget(w)
    w.resize(400, 220)
    w.grab()
    track = PitchTrack(np.linspace(0, 1, 50), np.full(50, 440.0), np.ones(50))
    w.set_track(track, 1.0)
    w.set_position(0.5)
    w.set_zoom(4.0)
    w.grab()


def test_pitch_editor_tab_present_and_disabled_without_analysis(window):
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert "Pitch Editor" in titles
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.song_view.refresh()
    window.pitch_editor_view.refresh()
    assert window.pitch_editor_view.btn_apply.isEnabled() is False
    assert "Voice" in window.pitch_editor_view.lbl_status.text()


def test_pitch_editor_loads_seeded_overrides_after_analysis(qtbot, window):
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.song_view.refresh()
    window.session.analyze_vocal()
    window.pitch_editor_view.refresh()
    assert window.pitch_editor_view.btn_apply.isEnabled() is True
    assert len(window.pitch_editor_view.editor.overrides()) >= 1
    assert window.pitch_editor_view.editor._target_f0 is not None


def test_pitch_editor_mode_preset_updates_sliders(window):
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.song_view.refresh()
    window.session.analyze_vocal()
    window.pitch_editor_view.refresh()

    window.pitch_editor_view.cmb_mode.setCurrentText("Hard Autotune")
    assert window.pitch_editor_view.sld_amount.value() == 100
    assert window.pitch_editor_view.sld_humanize.value() == 0

    window.pitch_editor_view.cmb_mode.setCurrentText("Natural")
    assert window.pitch_editor_view.sld_amount.value() == 40


def test_pitch_editor_select_and_transpose_note(qtbot, window):
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.song_view.refresh()
    window.session.analyze_vocal()
    window.pitch_editor_view.refresh()

    editor = window.pitch_editor_view.editor
    assert len(editor.overrides()) == 1
    editor._select(0)
    assert "0" in window.pitch_editor_view.lbl_note.text() or "+0" in window.pitch_editor_view.lbl_note.text()

    window.pitch_editor_view.btn_up.click()
    window.pitch_editor_view.btn_up.click()
    assert editor.overrides()[0].semitone_offset == 2
    assert "+2" in window.pitch_editor_view.lbl_note.text()

    window.pitch_editor_view.btn_bypass.click()
    assert editor.overrides()[0].bypass is True
    window.pitch_editor_view.btn_reset.click()
    assert editor.overrides()[0].semitone_offset == 0 and editor.overrides()[0].bypass is False


def test_pitch_editor_split_and_merge(window):
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.song_view.refresh()
    window.session.analyze_vocal()
    window.pitch_editor_view.refresh()
    editor = window.pitch_editor_view.editor
    editor._select(0)
    original = editor.overrides()[0]
    mid = (original.start + original.end) / 2

    window.pitch_editor_view.btn_split.click.__self__  # noop, real seek below
    editor.split_selected_at(mid)
    assert len(editor.overrides()) == 2
    assert editor.overrides()[0].end == pytest.approx(mid)
    assert editor.overrides()[1].start == pytest.approx(mid)

    editor._select(0)
    editor.merge_selected_with_next()
    assert len(editor.overrides()) == 1


def test_pitch_editor_apply_creates_corrected_take(qtbot, window):
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.song_view.refresh()
    window.session.analyze_vocal()
    window.pitch_editor_view.refresh()

    before = len(window.session.project.data.takes)
    window.pitch_editor_view._apply()
    qtbot.waitUntil(lambda: not window.pitch_editor_view._task.running, timeout=10000)

    assert len(window.session.project.data.takes) == before + 1
    assert "corregida" in window.session.project.data.takes[-1].name


def test_pitch_editor_apply_without_analysis_shows_error(qtbot, window, monkeypatch):
    from vocal_ai_studio.ui import pitch_editor_view as pev

    shown = []
    monkeypatch.setattr(pev, "show_error", lambda *a, **k: shown.append(a))
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.song_view.refresh()
    window.pitch_editor_view.btn_apply.setEnabled(True)  # fuerza el intento sin análisis
    window.pitch_editor_view._apply()
    qtbot.waitUntil(lambda: not window.pitch_editor_view._task.running, timeout=5000)
    assert shown


def test_pitch_editor_persists_across_refresh(window):
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.song_view.refresh()
    window.session.analyze_vocal()
    window.pitch_editor_view.refresh()
    window.pitch_editor_view.cmb_mode.setCurrentText("Extreme")
    window.pitch_editor_view.cmb_key.setCurrentText("G")

    window.pitch_editor_view.refresh()
    assert window.pitch_editor_view.cmb_key.currentText() == "G"
    assert window.pitch_editor_view.sld_amount.value() == 100


def test_switching_to_pitch_editor_tab_refreshes_it(window):
    window.session.project.add_take(tone(seconds=0.6, freq=440.0, channels=1))
    window.session.analyze_vocal()
    index = [window.tabs.tabText(i) for i in range(window.tabs.count())].index("Pitch Editor")
    window.tabs.setCurrentIndex(index)
    assert window.pitch_editor_view.lbl_source.text()


def test_pitch_editor_widget_renders(qtbot):
    from vocal_ai_studio.core.interfaces import PitchTrack
    from vocal_ai_studio.pitch.correction import NoteOverride
    from vocal_ai_studio.ui.pitch_editor_widget import PitchEditorWidget

    w = PitchEditorWidget()
    qtbot.addWidget(w)
    w.resize(400, 220)
    track = PitchTrack(np.linspace(0, 1, 50), np.full(50, 440.0), np.ones(50))
    w.set_track(track, 1.0)
    w.set_target(np.full(50, 493.88))
    w.set_overrides([NoteOverride(0.0, 1.0, 0, False)])
    w.grab()
    w._select(0)
    w.grab()


def test_waveform_widget_renders_without_audio(qtbot):
    w = WaveformView()
    qtbot.addWidget(w)
    w.resize(400, 200)
    w.grab()  # fuerza paintEvent
    w.set_track("song", tone(1.0, 440, channels=1))
    w.set_position(0.5)
    w.set_recording_time(0.7)
    w.set_zoom(8.0)
    w.grab()
    assert w.duration == pytest.approx(1.0, abs=0.02)


def test_level_meter_renders(qtbot):
    m = LevelMeter()
    qtbot.addWidget(m)
    m.resize(120, 14)
    for level in (0.0, 0.3, 0.8, 1.0):
        m.set_level(level)
        m.grab()
    m.reset()


def test_format_time():
    assert format_time(0) == "00:00.0"
    assert format_time(65.4) == "01:05.4"
