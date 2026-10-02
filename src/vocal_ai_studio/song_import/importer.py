from __future__ import annotations

import logging
from pathlib import Path

from vocal_ai_studio.audio.io import IMPORT_EXTENSIONS, AudioData, load_audio
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.storage.project import Project

log = logging.getLogger(__name__)


def _load_normalized(path: Path, project: Project, channels: int) -> AudioData:
    path = Path(path)
    if path.suffix.lower() not in IMPORT_EXTENSIONS:
        log.info("Extensión %s no listada; se intenta con FFmpeg igualmente.", path.suffix)
    audio = load_audio(path, samplerate=project.samplerate, channels=channels)
    if audio.frames == 0:
        raise AppError(f"'{path.name}' no contiene audio.", "El archivo está vacío.", "Prueba con otro archivo.")
    return audio


def import_song(project: Project, path: str | Path) -> AudioData:
    path = Path(path)
    audio = _load_normalized(path, project, channels=2)
    project.set_song(audio, title=path.stem)
    log.info("Canción importada: %s (%.1f s)", path.name, audio.duration)
    return audio


def import_vocal(project: Project, path: str | Path) -> AudioData:
    path = Path(path)
    audio = _load_normalized(path, project, channels=1)
    project.set_vocal(audio)
    project.set_active_take(0)
    log.info("Voz importada: %s (%.1f s)", path.name, audio.duration)
    return audio


def import_vocal_as_take(project: Project, path: str | Path) -> AudioData:
    path = Path(path)
    audio = _load_normalized(path, project, channels=1)
    take = project.add_take(audio)
    project.rename_take(take.id, path.stem)
    project.set_active_take(take.id)
    log.info("Audio importado como toma '%s': %s (%.1f s)", path.stem, path.name, audio.duration)
    return audio
