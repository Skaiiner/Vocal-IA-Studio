from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from vocal_ai_studio.audio.io import AudioData, load_audio, save_audio
from vocal_ai_studio.core.config import PROJECT_SAMPLE_RATE
from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.lyrics.model import Lyrics

log = logging.getLogger(__name__)

SUBDIRS = ("takes", "analysis", "presets", "exports")
PROJECT_FILE = "project.json"
FORMAT_VERSION = 1


@dataclass
class TakeInfo:
    id: int
    name: str
    file: str
    offset_sec: float = 0.0
    duration_sec: float = 0.0
    created: str = ""


@dataclass
class ProjectData:
    name: str = "Untitled"
    version: int = FORMAT_VERSION
    sample_rate: int = PROJECT_SAMPLE_RATE
    created: str = ""
    modified: str = ""
    song_file: str = ""
    song_title: str = ""
    vocal_file: str = ""
    lyrics_file: str = ""
    takes: list[TakeInfo] = field(default_factory=list)
    active_take: int = 0                # 0 = ninguna (se usa vocal importado si existe)
    song_gain: float = 1.0
    vocal_gain: float = 1.0
    next_take_id: int = 1


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "Untitled"


class Project:
    def __init__(self, root: Path, data: ProjectData):
        self.root = Path(root)
        self.data = data

    # --- creación / apertura ---
    @classmethod
    def create(cls, root: Path, name: str | None = None) -> "Project":
        root = Path(root)
        if (root / PROJECT_FILE).exists():
            raise AppError(f"Ya existe un proyecto en '{root}'.", "", "Elige otro nombre o usa Abrir proyecto.")
        for sub in SUBDIRS:
            (root / sub).mkdir(parents=True, exist_ok=True)
        data = ProjectData(name=name or root.name, created=_now(), modified=_now())
        proj = cls(root, data)
        proj.save()
        return proj

    @classmethod
    def open(cls, root: Path) -> "Project":
        root = Path(root)
        pf = root / PROJECT_FILE
        if not pf.exists():
            raise AppError(
                f"'{root}' no es una carpeta de proyecto.",
                f"Falta el archivo {PROJECT_FILE}.",
                "Selecciona la carpeta que contiene project.json o crea un proyecto nuevo.",
            )
        try:
            raw = json.loads(pf.read_text(encoding="utf-8"))
            takes = [TakeInfo(**t) for t in raw.pop("takes", [])]
            known = ProjectData.__dataclass_fields__.keys()
            data = ProjectData(**{k: v for k, v in raw.items() if k in known}, takes=takes)
        except (ValueError, TypeError, OSError) as exc:
            raise AppError(
                f"No se pudo leer el proyecto '{root.name}'.",
                f"project.json está dañado ({exc}).",
                "Restaura una copia de seguridad o crea un proyecto nuevo e importa de nuevo el audio.",
                cause=exc,
            ) from exc
        for sub in SUBDIRS:
            (root / sub).mkdir(exist_ok=True)
        return cls(root, data)

    @classmethod
    def unique_root(cls, parent: Path, name: str) -> Path:
        base = Path(parent) / safe_name(name)
        root, n = base, 2
        while root.exists():
            root = base.with_name(f"{base.name} {n}")
            n += 1
        return root

    # --- persistencia ---
    def save(self) -> None:
        self.data.modified = _now()
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / (PROJECT_FILE + ".tmp")
        tmp.write_text(json.dumps(asdict(self.data), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.root / PROJECT_FILE)

    def save_as(self, new_root: Path, name: str | None = None) -> "Project":
        new_root = Path(new_root)
        if new_root.exists() and any(new_root.iterdir()):
            raise AppError(f"La carpeta '{new_root}' ya existe y no está vacía.", "", "Elige otra carpeta.")
        self.save()
        shutil.copytree(self.root, new_root, dirs_exist_ok=True)
        proj = Project.open(new_root)
        if name:
            proj.data.name = name
            proj.save()
        return proj

    @property
    def name(self) -> str:
        return self.data.name

    @property
    def samplerate(self) -> int:
        return self.data.sample_rate

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    @property
    def exports_dir(self) -> Path:
        return self.path("exports")

    # --- canción / voz importada ---
    def set_song(self, audio: AudioData, title: str) -> None:
        save_audio(self.path("song.wav"), audio, "wav")
        self.data.song_file = "song.wav"
        self.data.song_title = title
        self.clear_analysis("song_tempo_key")  # la canción cambió: el BPM/tonalidad en caché ya no vale
        self.save()

    def set_vocal(self, audio: AudioData) -> None:
        save_audio(self.path("vocal.wav"), audio, "wav")
        self.data.vocal_file = "vocal.wav"
        self.clear_analysis("vocal_imported")
        self.save()

    def load_song(self) -> AudioData | None:
        return self._load(self.data.song_file)

    def load_vocal(self) -> AudioData | None:
        return self._load(self.data.vocal_file)

    def _load(self, rel: str) -> AudioData | None:
        if not rel:
            return None
        return load_audio(self.path(rel), samplerate=self.samplerate)

    # --- letra ---
    def set_lyrics(self, lyrics: Lyrics) -> None:
        if not lyrics.lines:
            self.clear_lyrics()
            return
        self.path("lyrics.json").write_text(lyrics.to_json(), encoding="utf-8")
        self.data.lyrics_file = "lyrics.json"
        self.save()

    def load_lyrics(self) -> Lyrics | None:
        if not self.data.lyrics_file:
            return None
        path = self.path(self.data.lyrics_file)
        if not path.exists():
            return None
        return Lyrics.from_json(path.read_text(encoding="utf-8"))

    def clear_lyrics(self) -> None:
        if self.data.lyrics_file:
            try:
                self.path(self.data.lyrics_file).unlink(missing_ok=True)
            except OSError as exc:
                log.warning("No se pudo borrar %s: %s", self.data.lyrics_file, exc)
        self.data.lyrics_file = ""
        self.save()

    # --- análisis (caché) ---
    def _analysis_paths(self, key: str) -> tuple[Path, Path]:
        base = self.path("analysis", re.sub(r"[^\w.-]", "_", key))
        return base.with_suffix(".json"), base.with_suffix(".npz")

    def save_analysis_json(self, key: str, data: dict) -> None:
        json_path, _ = self._analysis_paths(key)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_analysis_json(self, key: str) -> dict | None:
        json_path, _ = self._analysis_paths(key)
        if not json_path.exists():
            return None
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warning("Caché de análisis dañada (%s): %s", key, exc)
            return None

    def save_analysis_arrays(self, key: str, **arrays: np.ndarray) -> None:
        _, npz_path = self._analysis_paths(key)
        npz_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(npz_path, **arrays)

    def load_analysis_arrays(self, key: str) -> dict[str, np.ndarray] | None:
        _, npz_path = self._analysis_paths(key)
        if not npz_path.exists():
            return None
        try:
            with np.load(npz_path) as data:
                return {k: data[k] for k in data.files}
        except (ValueError, OSError) as exc:
            log.warning("Caché de análisis dañada (%s): %s", key, exc)
            return None

    def clear_analysis(self, key: str) -> None:
        json_path, npz_path = self._analysis_paths(key)
        for path in (json_path, npz_path):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("No se pudo borrar %s: %s", path, exc)

    # --- takes ---
    def add_take(self, audio: AudioData, offset_sec: float = 0.0) -> TakeInfo:
        tid = self.data.next_take_id
        self.data.next_take_id += 1
        rel = f"takes/take_{tid:02d}.wav"
        save_audio(self.path(rel), audio, "wav")
        take = TakeInfo(tid, f"Take {tid}", rel, float(offset_sec), audio.duration, _now())
        self.data.takes.append(take)
        self.data.active_take = tid
        self.save()
        return take

    def get_take(self, tid: int) -> TakeInfo | None:
        return next((t for t in self.data.takes if t.id == tid), None)

    def load_take(self, tid: int) -> AudioData | None:
        take = self.get_take(tid)
        return self._load(take.file) if take else None

    def set_active_take(self, tid: int) -> None:
        if tid != 0 and self.get_take(tid) is None:
            raise AppError(f"No existe la toma {tid}.", "", "Selecciona una toma de la lista.")
        self.data.active_take = tid
        self.save()

    def rename_take(self, tid: int, name: str) -> None:
        take = self.get_take(tid)
        if take and name.strip():
            take.name = name.strip()
            self.save()

    def set_take_offset(self, tid: int, offset_sec: float) -> None:
        take = self.get_take(tid)
        if take:
            take.offset_sec = float(offset_sec)
            self.save()

    def delete_take(self, tid: int) -> None:
        take = self.get_take(tid)
        if not take:
            return
        self.clear_analysis(f"vocal_take{tid}")
        self.data.takes = [t for t in self.data.takes if t.id != tid]
        try:
            self.path(take.file).unlink(missing_ok=True)
        except OSError as exc:
            log.warning("No se pudo borrar %s: %s", take.file, exc)
        if self.data.active_take == tid:
            self.data.active_take = self.data.takes[-1].id if self.data.takes else 0
        self.save()

    # --- pista vocal activa ---
    def active_vocal(self) -> tuple[AudioData, float] | None:
        if self.data.active_take:
            audio = self.load_take(self.data.active_take)
            take = self.get_take(self.data.active_take)
            if audio is not None and take is not None:
                return audio, take.offset_sec
        vocal = self.load_vocal()
        return (vocal, 0.0) if vocal is not None else None

    def set_gains(self, song: float | None = None, vocal: float | None = None) -> None:
        if song is not None:
            self.data.song_gain = float(song)
        if vocal is not None:
            self.data.vocal_gain = float(vocal)
        self.save()
