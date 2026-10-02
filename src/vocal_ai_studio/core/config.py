from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_SAMPLE_RATE = 44100


def data_dir() -> Path:
    env = os.environ.get("VAS_HOME")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[3]
    if (repo / "pyproject.toml").exists():
        return repo
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "VocalAIStudio"


def default_projects_dir() -> Path:
    return Path.home() / "Documents" / "VocalAIStudio" / "Projects"


def load_dotenv(path: Path | None = None) -> None:
    path = path or (data_dir() / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    input_device: str = ""           # etiqueta del dispositivo; "" = predeterminado del sistema
    output_device: str = ""
    monitor_device: str = ""         # reservado (fase 7)
    sample_rate: int = PROJECT_SAMPLE_RATE
    latency_compensation_ms: float = 0.0
    input_gain: float = 1.0
    monitor_input: bool = False
    projects_dir: str = ""
    last_project: str = ""
    music_folders: list[str] = field(default_factory=list)
    # Privacidad: todo local por defecto. Ningún audio sale del equipo sin activar esto.
    allow_external_services: bool = False
    allow_youtube: bool = False
    # IA (fases futuras): el endpoint/modelo son configurables; las claves van en variables de entorno.
    ai_provider: str = "local"
    ollama_endpoint: str = "http://localhost:11434"
    ollama_model: str = ""
    ai_temperature: float = 0.7
    ai_context: int = 4096

    def projects_path(self) -> Path:
        return Path(self.projects_dir) if self.projects_dir else default_projects_dir()

    def music_paths(self) -> list[Path]:
        if self.music_folders:
            return [Path(f) for f in self.music_folders]
        return [p for p in (Path.home() / "Music", Path.home() / "Downloads") if p.exists()]


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "settings.json")

    def load(self) -> Settings:
        s = Settings()
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                known = {f.name for f in fields(Settings)}
                for k, v in raw.items():
                    if k in known:
                        setattr(s, k, v)
            except (OSError, ValueError) as exc:
                log.warning("No se pudo leer %s (%s); se usan los valores por defecto.", self.path, exc)
        env_dir = os.environ.get("VAS_PROJECTS_DIR")
        if env_dir:
            s.projects_dir = env_dir
        return s

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
