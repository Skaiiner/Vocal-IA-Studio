from __future__ import annotations

import logging
from pathlib import Path

from vocal_ai_studio.ai.feedback import CoachFeedback
from vocal_ai_studio.ai.providers import LocalRulesProvider, OllamaProvider
from vocal_ai_studio.ai import rules as coach_rules
from vocal_ai_studio.audio.io import AudioData, load_audio, save_audio
from vocal_ai_studio.core.config import Settings, SettingsStore
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.core.hardware import detect_hardware
from vocal_ai_studio.core.interfaces import AudioBackend, PitchTrack
from vocal_ai_studio.lyrics.model import Lyrics, parse_text
from vocal_ai_studio.pitch.correction import (
    CorrectionSettings,
    NoteOverride,
    build_target_curve,
    overrides_from_notes,
)
from vocal_ai_studio.effects.chain import VoiceLabSettings, apply_chain
from vocal_ai_studio.pitch.shifter import psola_resynthesize
from vocal_ai_studio.playback.player import Player
from vocal_ai_studio.realtime.engine import LiveVoiceEngine
from vocal_ai_studio.recording.recorder import Recorder
from vocal_ai_studio.separation.demucs_separator import DemucsSeparator
from vocal_ai_studio.song_import.importer import import_song, import_vocal, import_vocal_as_take
from vocal_ai_studio.song_import.sources import (
    Cancelled,
    LocalLibrarySource,
    Progress,
    SearchResult,
    SongSource,
)
from vocal_ai_studio.storage import exporter
from vocal_ai_studio.storage.project import Project, TakeInfo
from vocal_ai_studio.voice_conversion.model import RVCVoiceConversionModel
from vocal_ai_studio.voice_analysis import metrics as vocal_metrics
from vocal_ai_studio.voice_analysis import song as song_metrics
from vocal_ai_studio.voice_analysis.metrics import VocalAnalysis
from vocal_ai_studio.voice_analysis.song import SongAnalysis
from vocal_ai_studio.youtube.source import YouTubeSource

log = logging.getLogger(__name__)


class Session:
    def __init__(self, backend: AudioBackend, settings: Settings, store: SettingsStore | None = None):
        self.backend = backend
        self.settings = settings
        self.store = store
        self.project: Project | None = None
        self.player = Player(backend, settings.sample_rate, settings.output_device)
        self.recorder = Recorder(backend, settings.sample_rate, settings.input_device)
        self.recorder.gain = settings.input_gain
        self.recorder.monitor = settings.monitor_input
        self.player.add_source(self.recorder.monitor_source)
        self.live_voice = LiveVoiceEngine(backend, settings.sample_rate,
                                          settings.input_device, settings.output_device)
        self._record_start_pos = 0.0

    # --- ajustes ---
    def save_settings(self) -> None:
        if self.store:
            self.store.save(self.settings)

    def apply_devices(self, input_device: str | None = None, output_device: str | None = None) -> None:
        devices_changed = False
        if output_device is not None and output_device != self.settings.output_device:
            self.settings.output_device = output_device
            self.player.set_output_device(output_device)
            devices_changed = True
        if input_device is not None and input_device != self.settings.input_device:
            self.settings.input_device = input_device
            self.recorder.set_device(input_device)
            devices_changed = True
        if devices_changed:
            self.live_voice.set_devices(self.settings.input_device, self.settings.output_device)
        self.save_settings()

    # --- proyecto ---
    def new_project(self, name: str) -> Project:
        root = Project.unique_root(self.settings.projects_path(), name)
        root.mkdir(parents=True, exist_ok=True)
        self._load(Project.create(root, name))
        return self.project  # type: ignore[return-value]

    def open_project(self, root: str | Path) -> Project:
        self._load(Project.open(Path(root)))
        return self.project  # type: ignore[return-value]

    def save_project_as(self, parent: Path, name: str) -> Project:
        self._require_project()
        root = Project.unique_root(Path(parent), name)
        self._load(self.project.save_as(root, name))  # type: ignore[union-attr]
        return self.project  # type: ignore[return-value]

    def _load(self, project: Project) -> None:
        self.player.stop()
        self.project = project
        self.settings.last_project = str(project.root)
        self.save_settings()
        self.refresh_tracks()

    def _require_project(self) -> Project:
        if self.project is None:
            raise AppError("No hay ningún proyecto abierto.", "", "Crea un proyecto nuevo o abre uno existente.")
        return self.project

    def refresh_tracks(self) -> None:
        if self.project is None:
            self.player.set_track("song", None)
            self.player.set_track("vocal", None)
            return
        song = self.project.load_song()
        self.player.set_track("song", song, gain=self.project.data.song_gain)
        vocal = self.project.active_vocal()
        if vocal is None:
            self.player.set_track("vocal", None)
        else:
            audio, offset = vocal
            self.player.set_track("vocal", audio, offset_sec=offset, gain=self.project.data.vocal_gain)

    # --- importación / exportación ---
    def import_song_file(self, path: str | Path) -> AudioData:
        audio = import_song(self._require_project(), path)
        self.refresh_tracks()
        return audio

    def import_vocal_file(self, path: str | Path) -> AudioData:
        audio = import_vocal(self._require_project(), path)
        self.refresh_tracks()
        return audio

    def import_vocal_as_take(self, path: str | Path) -> AudioData:
        audio = import_vocal_as_take(self._require_project(), path)
        self.refresh_tracks()
        return audio

    def import_vocal_files_as_takes(self, paths: list[str | Path]) -> list[AudioData]:
        results = []
        for p in paths:
            results.append(self.import_vocal_as_take(p))
        return results

    # --- búsqueda de canciones ---
    def sources(self) -> list[SongSource]:
        return [
            LocalLibrarySource(self.settings.music_paths()),
            YouTubeSource(enabled=self.settings.allow_youtube),
        ]

    def import_search_result(self, result: SearchResult, source: SongSource,
                             progress: Progress | None = None,
                             cancelled: Cancelled | None = None) -> AudioData:
        project = self._require_project()
        temp_dir = project.path(".download")
        downloaded: Path | None = None
        try:
            path = Path(source.fetch(result, temp_dir, progress, cancelled))
            downloaded = path if temp_dir in path.parents else None
            if progress:
                progress(1.0, "Importando en el proyecto…")
            audio = import_song(project, path)
            project.data.song_title = result.title
            project.save()
        finally:
            if downloaded is not None:
                _cleanup(temp_dir)
        self.refresh_tracks()
        return audio

    def export(self, kind: str, dest: str | Path, fmt: str | None = None) -> Path:
        return exporter.export_project(self._require_project(), kind, dest, fmt)

    def default_export_name(self, kind: str, fmt: str) -> str:
        project = self._require_project()
        return f"{project.name} - {kind}.{fmt}"

    # --- letra ---
    def load_lyrics(self) -> Lyrics | None:
        return self.project.load_lyrics() if self.project else None

    def set_lyrics_text(self, raw_text: str) -> Lyrics:
        project = self._require_project()
        lyrics = parse_text(raw_text)
        project.set_lyrics(lyrics)
        return lyrics

    def set_lyric_time(self, index: int, time: float | None) -> Lyrics:
        project = self._require_project()
        lyrics = project.load_lyrics() or Lyrics([])
        if 0 <= index < len(lyrics.lines):
            lyrics.lines[index].time = time
            project.set_lyrics(lyrics)
        return lyrics

    def clear_lyrics_sync(self) -> Lyrics:
        project = self._require_project()
        lyrics = project.load_lyrics() or Lyrics([])
        for line in lyrics.lines:
            line.time = None
        project.set_lyrics(lyrics)
        return lyrics

    # --- análisis vocal ---
    def _vocal_analysis_key(self) -> str:
        project = self._require_project()
        return f"vocal_take{project.data.active_take}" if project.data.active_take else "vocal_imported"

    def analyze_vocal(self, progress: Progress | None = None, cancelled: Cancelled | None = None) -> VocalAnalysis:
        project = self._require_project()
        vocal = project.active_vocal()
        if vocal is None:
            raise AppError("No hay voz para analizar.", "No hay ninguna toma ni voz importada.",
                           "Graba una toma o usa Import Vocal en la pestaña Song.")
        audio, _offset = vocal
        analysis = vocal_metrics.analyze_vocal(audio.to_mono(), audio.samplerate, progress, cancelled)
        key = self._vocal_analysis_key()
        project.save_analysis_arrays(key, times=analysis.pitch.times, f0=analysis.pitch.f0,
                                     confidence=analysis.pitch.confidence)
        project.save_analysis_json(key, vocal_metrics.to_dict(analysis))
        return analysis

    def load_vocal_analysis(self) -> VocalAnalysis | None:
        if self.project is None:
            return None
        key = self._vocal_analysis_key()
        data = self.project.load_analysis_json(key)
        arrays = self.project.load_analysis_arrays(key)
        if not data or not arrays:
            return None
        pitch = PitchTrack(arrays["times"], arrays["f0"], arrays["confidence"])
        return vocal_metrics.from_dict(data, pitch)

    # --- análisis de la canción (BPM / tonalidad) ---
    def analyze_song(self) -> SongAnalysis:
        project = self._require_project()
        song = project.load_song()
        if song is None:
            raise AppError("No hay canción para analizar.", "Todavía no has importado ninguna.",
                           "Pulsa Import Song o Buscar canción primero.")
        analysis = song_metrics.analyze_song(song.to_mono(), song.samplerate)
        project.save_analysis_json("song_tempo_key", song_metrics.to_dict(analysis))
        return analysis

    def load_song_analysis(self) -> SongAnalysis | None:
        if self.project is None:
            return None
        data = self.project.load_analysis_json("song_tempo_key")
        return song_metrics.from_dict(data) if data else None

    # --- corrección de afinación (autotune + edición manual) ---
    def _correction_key(self) -> str:
        return f"correction_{self._vocal_analysis_key()}"

    def load_correction(self) -> tuple[CorrectionSettings, list[NoteOverride]]:
        if self.project is None:
            return CorrectionSettings(), []
        data = self.project.load_analysis_json(self._correction_key())
        if not data:
            return CorrectionSettings(), []
        settings = CorrectionSettings.from_dict(data.get("settings", {}))
        overrides = [NoteOverride.from_dict(o) for o in data.get("overrides", [])]
        return settings, overrides

    def save_correction(self, settings: CorrectionSettings, overrides: list[NoteOverride]) -> None:
        project = self._require_project()
        project.save_analysis_json(self._correction_key(), {
            "settings": settings.to_dict(), "overrides": [o.to_dict() for o in overrides],
        })

    def seed_overrides_from_analysis(self) -> list[NoteOverride]:
        analysis = self.load_vocal_analysis()
        return overrides_from_notes(analysis.notes) if analysis else []

    def preview_correction_curve(self, settings: CorrectionSettings, overrides: list[NoteOverride]):
        analysis = self.load_vocal_analysis()
        if analysis is None:
            raise AppError("Analiza tu voz primero.", "Hace falta el análisis de afinación (pestaña Voice).",
                           "Ve a Voice y pulsa Analizar.")
        return build_target_curve(analysis.pitch, analysis.notes, settings, overrides)

    def apply_correction(self, settings: CorrectionSettings, overrides: list[NoteOverride],
                          progress: Progress | None = None, cancelled: Cancelled | None = None) -> TakeInfo:
        project = self._require_project()
        vocal = project.active_vocal()
        if vocal is None:
            raise AppError("No hay voz que corregir.", "No hay ninguna toma ni voz importada.",
                           "Graba una toma o usa Import Vocal en la pestaña Song.")
        analysis = self.load_vocal_analysis()
        if analysis is None:
            raise AppError("Analiza tu voz primero.", "Hace falta el análisis de afinación (pestaña Voice).",
                           "Ve a Voice y pulsa Analizar, y vuelve aquí.")
        audio, offset = vocal
        source_key = self._correction_key()
        if progress:
            progress(0.0, "Calculando la curva de corrección…")
        target = build_target_curve(analysis.pitch, analysis.notes, settings, overrides)

        def shift_progress(frac: float) -> None:
            if progress:
                progress(frac, "Renderizando el audio corregido…")

        corrected = psola_resynthesize(
            audio.to_mono(), audio.samplerate, analysis.pitch.times, analysis.pitch.f0,
            analysis.pitch.times, target, preserve_formants=settings.preserve_formants,
            progress=shift_progress, cancelled=cancelled,
        )
        payload = {"settings": settings.to_dict(), "overrides": [o.to_dict() for o in overrides]}
        project.save_analysis_json(source_key, payload)
        take = project.add_take(AudioData(corrected, audio.samplerate), offset_sec=offset)
        project.rename_take(take.id, f"{take.name} (corregida)")
        self.save_correction(settings, overrides)
        self.refresh_tracks()
        return project.get_take(take.id)  # type: ignore[return-value]

    # --- Voice Lab ---
    def _voice_lab_key(self) -> str:
        project = self._require_project()
        return f"voice_lab_take{project.data.active_take}" if project.data.active_take else "voice_lab_imported"

    def load_voice_lab(self) -> VoiceLabSettings:
        if self.project is None:
            return VoiceLabSettings()
        data = self.project.load_analysis_json(self._voice_lab_key())
        if data and "settings" in data:
            return VoiceLabSettings.from_dict(data["settings"])
        return VoiceLabSettings()

    def save_voice_lab(self, settings: VoiceLabSettings) -> None:
        if self.project is None:
            return
        self.project.save_analysis_json(self._voice_lab_key(), {"settings": settings.to_dict()})

    def apply_voice_lab(
        self,
        settings: VoiceLabSettings,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> TakeInfo:
        project = self._require_project()
        vocal = project.active_vocal()
        if vocal is None:
            raise AppError("No hay voz para procesar.", "No hay ninguna toma ni voz importada.",
                           "Graba una toma o usa Import Vocal en la pestaña Song.")
        audio, offset = vocal
        source_key = self._voice_lab_key()
        processed = apply_chain(audio.to_mono(), audio.samplerate, settings, progress, cancelled)
        payload = {"settings": settings.to_dict()}
        project.save_analysis_json(source_key, payload)
        take = project.add_take(AudioData(processed, audio.samplerate), offset_sec=offset)
        label = settings.preset_name if settings.preset_name != "Custom" else "procesada"
        project.rename_take(take.id, f"{take.name} ({label})")
        self.save_voice_lab(settings)
        self.refresh_tracks()
        return project.get_take(take.id)  # type: ignore[return-value]

    # --- separación voz/instrumental (Demucs) ---
    _SEPARATION_KEY = "separation_song"

    def separate_song(
        self,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> dict[str, AudioData]:
        project = self._require_project()
        song = project.load_song()
        if song is None:
            raise AppError("No hay canción para separar.", "No se ha importado ninguna canción.",
                           "Importa una canción en la pestaña Song.")
        separator = DemucsSeparator()
        stems = separator.separate(song.to_mono(), song.samplerate, progress, cancelled)
        vocals = AudioData(stems["vocals"], song.samplerate)
        instrumental = AudioData(stems["instrumental"], song.samplerate)
        save_audio(project.path("separated", "vocals.wav"), vocals, "wav")
        save_audio(project.path("separated", "instrumental.wav"), instrumental, "wav")
        project.save_analysis_json(self._SEPARATION_KEY, {"done": True})
        return {"vocals": vocals, "instrumental": instrumental}

    def load_separation(self) -> dict[str, AudioData] | None:
        project = self._require_project()
        if not project.load_analysis_json(self._SEPARATION_KEY):
            return None
        vocals_path = project.path("separated", "vocals.wav")
        instrumental_path = project.path("separated", "instrumental.wav")
        if not vocals_path.exists() or not instrumental_path.exists():
            return None
        return {
            "vocals": load_audio(vocals_path, samplerate=project.samplerate),
            "instrumental": load_audio(instrumental_path, samplerate=project.samplerate),
        }

    def use_separated_instrumental_as_song(self) -> None:
        project = self._require_project()
        separation = self.load_separation()
        if separation is None:
            raise AppError("No hay separación disponible.", "Todavía no se separó la canción.",
                           "Pulsa Separar en la pestaña de separación antes de usar el resultado.")
        project.set_song(separation["instrumental"], f"{project.data.song_title} (instrumental)")
        self.refresh_tracks()

    def use_separated_vocals_as_take(self) -> TakeInfo:
        project = self._require_project()
        separation = self.load_separation()
        if separation is None:
            raise AppError("No hay separación disponible.", "Todavía no se separó la canción.",
                           "Pulsa Separar en la pestaña de separación antes de usar el resultado.")
        take = project.add_take(separation["vocals"], offset_sec=0.0)
        project.rename_take(take.id, f"{take.name} (voz separada)")
        self.refresh_tracks()
        return project.get_take(take.id)  # type: ignore[return-value]

    # --- conversión de voz (RVC) ---
    def convert_voice(
        self,
        model_path: str,
        index_path: str | None = None,
        transpose: float = 0.0,
        protect: float = 0.33,
        index_rate: float = 0.0,
        rms_mix_rate: float = 1.0,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> TakeInfo:
        project = self._require_project()
        vocal = project.active_vocal()
        if vocal is None:
            raise AppError("No hay voz para convertir.", "No hay ninguna toma ni voz importada.",
                           "Graba una toma o usa Import Vocal en la pestaña Song.")
        audio, offset = vocal
        device = detect_hardware().recommended_device
        model = RVCVoiceConversionModel()
        model.load(device)
        converted = model.convert(
            audio.to_mono(), audio.samplerate,
            model_path=model_path, index_path=index_path, transpose=transpose,
            protect=protect, index_rate=index_rate, rms_mix_rate=rms_mix_rate,
            progress=progress, cancelled=cancelled,
        )
        take = project.add_take(AudioData(converted, audio.samplerate), offset_sec=offset)
        project.rename_take(take.id, f"{take.name} (conversión de voz)")
        self.refresh_tracks()
        return project.get_take(take.id)  # type: ignore[return-value]

    # --- AI Coach ---
    def _coach_provider(self):
        if self.settings.ai_provider == "ollama":
            provider = OllamaProvider(self.settings.ollama_endpoint, self.settings.ollama_model,
                                      self.settings.ai_temperature)
            if provider.is_available():
                return provider
        return LocalRulesProvider()

    def generate_coach_feedback(self) -> CoachFeedback:
        analysis = self.load_vocal_analysis()
        if analysis is None:
            raise AppError("Analiza tu voz primero.", "Hace falta el análisis de afinación (pestaña Voice).",
                           "Ve a Voice y pulsa Analizar, y vuelve aquí.")
        song = self.load_song_analysis()
        feedback = coach_rules.build_feedback(analysis, song)
        provider = self._coach_provider()
        if not isinstance(provider, LocalRulesProvider):
            prompt = (
                "Reescribe este feedback de coach vocal en un tono cercano y motivador, en español, "
                "conservando todos los datos concretos (cents, notas, tiempos). No inventes datos nuevos.\n\n"
                f"Resumen: {feedback.summary}\n"
                f"Puntos fuertes: {'; '.join(feedback.strengths) or 'ninguno destacado'}\n"
                f"A mejorar: {'; '.join(feedback.issues) or 'ninguno'}"
            )
            try:
                rewritten = provider.complete(prompt)
            except OSError as exc:
                log.warning("Ollama no respondió, se usa el feedback de reglas locales: %s", exc)
            else:
                if rewritten:
                    feedback.summary = rewritten
                    feedback.generated_by = f"Ollama ({self.settings.ollama_model})"
        key = f"coach_{self._vocal_analysis_key()}"
        self._require_project().save_analysis_json(key, feedback.to_dict())
        return feedback

    def load_coach_feedback(self) -> CoachFeedback | None:
        if self.project is None:
            return None
        data = self.project.load_analysis_json(f"coach_{self._vocal_analysis_key()}")
        return CoachFeedback.from_dict(data) if data else None

    # --- transporte ---
    def play(self) -> None:
        self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def stop(self) -> None:
        if self.recorder.is_recording or self.recorder.state.value == "paused":
            self.finish_recording()
        self.player.stop()

    def seek(self, seconds: float) -> None:
        self.player.seek(seconds)

    def set_song_gain(self, gain: float) -> None:
        self.player.set_gain("song", gain)
        if self.project:
            self.project.set_gains(song=gain)

    def set_vocal_gain(self, gain: float) -> None:
        self.player.set_gain("vocal", gain)
        if self.project:
            self.project.set_gains(vocal=gain)

    # --- grabación ---
    def start_recording(self, with_backing: bool = True) -> None:
        self._require_project()
        self._record_start_pos = self.player.position
        self.player.set_muted("vocal", True)
        self.recorder.start()
        if with_backing and self.player.duration > 0:
            self.player.play()

    def pause_recording(self) -> None:
        self.recorder.pause()
        self.player.pause()

    def resume_recording(self) -> None:
        self.recorder.resume()
        if self.player.duration > 0:
            self.player.play()

    def finish_recording(self) -> TakeInfo | None:
        project = self._require_project()
        audio = self.recorder.stop()
        self.player.pause()
        self.player.set_muted("vocal", False)
        if audio.frames == 0:
            log.info("Grabación vacía descartada.")
            return None
        offset = max(0.0, self._record_start_pos - self.settings.latency_compensation_ms / 1000.0)
        take = project.add_take(audio, offset_sec=offset)
        self.refresh_tracks()
        return take

    def cancel_recording(self) -> None:
        self.recorder.cancel()
        self.player.pause()
        self.player.set_muted("vocal", False)

    @property
    def recording_position(self) -> float:
        return self._record_start_pos + self.recorder.elapsed

    # --- takes ---
    def select_take(self, take_id: int) -> None:
        self._require_project().set_active_take(take_id)
        self.refresh_tracks()

    def delete_take(self, take_id: int) -> None:
        self._require_project().delete_take(take_id)
        self.refresh_tracks()

    def rename_take(self, take_id: int, name: str) -> None:
        self._require_project().rename_take(take_id, name)

    def close(self) -> None:
        try:
            self.recorder.close()
        finally:
            try:
                self.live_voice.close()
            finally:
                self.player.close()


def _cleanup(folder: Path) -> None:
    import shutil

    try:
        shutil.rmtree(folder, ignore_errors=True)
    except OSError as exc:
        log.warning("No se pudo limpiar %s: %s", folder, exc)
