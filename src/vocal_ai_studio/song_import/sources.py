from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from vocal_ai_studio.audio.io import IMPORT_EXTENSIONS
from vocal_ai_studio.core.errors import AppError

log = logging.getLogger(__name__)

Progress = Callable[[float, str], None]
Cancelled = Callable[[], bool]


class SearchCancelled(Exception):
    pass


@dataclass
class SearchResult:
    title: str
    source: str                 # nombre de la fuente ("Mi música", "YouTube")
    ref: str                    # ruta local o identificador/URL
    artist: str = ""
    duration: float = 0.0       # segundos; 0 = desconocida
    extra: dict = field(default_factory=dict)

    @property
    def duration_text(self) -> str:
        if self.duration <= 0:
            return "—"
        m, s = divmod(int(self.duration), 60)
        return f"{m}:{s:02d}"

    @property
    def subtitle(self) -> str:
        parts = [p for p in (self.artist, self.duration_text, self.source) if p and p != "—"]
        return "  ·  ".join(parts)


class SongSource(Protocol):
    name: str
    needs_internet: bool

    def is_available(self) -> tuple[bool, str]:
        ...

    def search(self, query: str, limit: int = 20, cancelled: Cancelled | None = None) -> list[SearchResult]: ...

    def fetch(self, result: SearchResult, dest_dir: Path,
              progress: Progress | None = None, cancelled: Cancelled | None = None) -> Path:
        ...


def _tokens(query: str) -> list[str]:
    return [t for t in re.split(r"[\s\-_]+", query.lower().strip()) if t]


class LocalLibrarySource:
    name = "Mi música"
    needs_internet = False

    def __init__(self, folders: list[Path]):
        self.folders = [Path(f) for f in folders]

    def is_available(self) -> tuple[bool, str]:
        existing = [f for f in self.folders if f.exists()]
        if not existing:
            return False, ("No hay ninguna carpeta de música configurada que exista. "
                           "Añade una en Ajustes ▸ Carpetas.")
        return True, ""

    def search(self, query: str, limit: int = 20, cancelled: Cancelled | None = None) -> list[SearchResult]:
        tokens = _tokens(query)
        results: list[SearchResult] = []
        for folder in self.folders:
            if not folder.exists():
                continue
            for path in folder.rglob("*"):
                if cancelled and cancelled():
                    raise SearchCancelled
                if len(results) >= limit:
                    return results
                if not path.is_file() or path.suffix.lower() not in IMPORT_EXTENSIONS:
                    continue
                haystack = f"{path.parent.name} {path.stem}".lower()
                if tokens and not all(t in haystack for t in tokens):
                    continue
                results.append(SearchResult(
                    title=path.stem,
                    source=self.name,
                    ref=str(path),
                    artist=path.parent.name,
                    extra={"path": str(path)},
                ))
        return results

    def fetch(self, result: SearchResult, dest_dir: Path,
              progress: Progress | None = None, cancelled: Cancelled | None = None) -> Path:
        path = Path(result.ref)
        if not path.exists():
            raise AppError(
                f"Ya no existe '{path.name}'.",
                "El archivo se movió o se borró desde que buscaste.",
                "Vuelve a buscar la canción.",
            )
        if progress:
            progress(1.0, "Listo")
        return path  # se importa directamente desde su sitio; no hace falta copiarlo
