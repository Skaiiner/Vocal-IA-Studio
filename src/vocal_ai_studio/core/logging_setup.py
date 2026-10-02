from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(log_dir: Path, level: int = logging.INFO, console: bool = True) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, "_vas_handler", False):
            root.removeHandler(h)
            h.close()

    fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter(_FORMAT))
    fh._vas_handler = True  # type: ignore[attr-defined]
    root.addHandler(fh)
    if console and sys.stderr is not None:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(_FORMAT))
        ch._vas_handler = True  # type: ignore[attr-defined]
        root.addHandler(ch)
    return log_file
