from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from vocal_ai_studio.core.errors import AppError

_LRC_TAG = re.compile(r"\[(\d{1,2}):(\d{2}(?:\.\d{1,3})?)\]")
LYRICS_EXTENSIONS = (".txt", ".lrc")


@dataclass
class LyricLine:
    text: str
    time: float | None = None  # segundos desde el inicio de la canción; None = sin sincronizar


@dataclass
class Lyrics:
    lines: list[LyricLine] = field(default_factory=list)

    @property
    def synced(self) -> bool:
        return any(line.time is not None for line in self.lines)

    @property
    def synced_count(self) -> int:
        return sum(1 for line in self.lines if line.time is not None)

    def current_index(self, position: float) -> int | None:
        best = None
        for i, line in enumerate(self.lines):
            if line.time is None:
                continue
            if line.time <= position:
                best = i
            else:
                break
        return best

    def to_plain_text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def to_json(self) -> str:
        return json.dumps([{"text": l.text, "time": l.time} for l in self.lines], ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "Lyrics":
        data = json.loads(raw)
        return cls([LyricLine(d["text"], d.get("time")) for d in data])


def parse_text(raw: str) -> Lyrics:
    lines: list[LyricLine] = []
    has_any_tag = False
    for raw_line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        tags = _LRC_TAG.findall(raw_line)
        text = _LRC_TAG.sub("", raw_line).strip()
        if tags:
            has_any_tag = True
            for minutes, seconds in tags:
                lines.append(LyricLine(text, int(minutes) * 60 + float(seconds)))
        else:
            lines.append(LyricLine(raw_line.rstrip()))
    while lines and not lines[0].text:
        lines.pop(0)
    while lines and not lines[-1].text:
        lines.pop()
    if has_any_tag:
        lines.sort(key=lambda l: (l.time is None, l.time if l.time is not None else 0.0))
    return Lyrics(lines)


def read_lyrics_file(path: str | Path) -> str:
    path = Path(path)
    if not path.exists():
        raise AppError(f"No existe el archivo '{path.name}'.", "", "Elige otro archivo.")
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise AppError(
        f"No se pudo leer '{path.name}'.",
        "La codificación del archivo no es reconocida.",
        "Ábrelo en un editor de texto, guárdalo como UTF-8 y vuelve a intentarlo.",
    )
