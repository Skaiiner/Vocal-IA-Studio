from __future__ import annotations

from pathlib import Path

from vocal_ai_studio.audio.io import AudioData, save_audio
from vocal_ai_studio.audio.mix import MixTrack, mix_tracks
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.storage.project import Project

KINDS = {
    "vocal": "Solo voz (toma activa)",
    "song": "Solo canción / instrumental",
    "mix": "Mezcla completa",
}


def render(project: Project, kind: str) -> AudioData:
    if kind not in KINDS:
        raise AppError(f"Tipo de exportación desconocido: '{kind}'.", "", f"Usa uno de: {', '.join(KINDS)}.")
    sr = project.samplerate
    song = project.load_song()
    vocal = project.active_vocal()
    if kind == "song":
        if song is None:
            raise AppError("No hay canción para exportar.", "Todavía no has importado ninguna.", "Pulsa Import Song.")
        return AudioData(song.samples * project.data.song_gain, sr)
    if kind == "vocal":
        if vocal is None:
            raise AppError("No hay voz para exportar.", "No hay ninguna toma ni voz importada.",
                           "Graba una toma o usa Import Vocal.")
        audio, offset = vocal
        return mix_tracks([MixTrack(audio, project.data.vocal_gain, offset)], sr, channels=audio.channels)
    tracks = []
    if song is not None:
        tracks.append(MixTrack(song, project.data.song_gain))
    if vocal is not None:
        tracks.append(MixTrack(vocal[0], project.data.vocal_gain, vocal[1]))
    if not tracks:
        raise AppError("No hay nada que exportar.", "El proyecto no tiene canción ni voz.",
                       "Importa una canción o graba una toma.")
    return mix_tracks(tracks, sr, channels=2)


def export_project(project: Project, kind: str, dest: str | Path, fmt: str | None = None) -> Path:
    audio = render(project, kind)
    return save_audio(Path(dest), audio, fmt)
