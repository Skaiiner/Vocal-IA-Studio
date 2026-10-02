from __future__ import annotations

import logging
from pathlib import Path

from vocal_ai_studio.core.errors import AppError
from vocal_ai_studio.song_import.sources import Cancelled, Progress, SearchCancelled, SearchResult

log = logging.getLogger(__name__)

AVISO_LEGAL = (
    "Descarga audio de YouTube para practicar canto. Úsalo solo con contenido que tengas derecho a "
    "utilizar (material propio, con licencia libre, o dentro de lo que permita la ley de tu país para "
    "uso privado). No se saltan protecciones de acceso ni DRM: los vídeos restringidos no se podrán "
    "descargar. Respeta los términos de servicio de YouTube y los derechos de los autores."
)


def _ydl():
    try:
        import yt_dlp
    except ImportError as exc:
        raise AppError(
            "Falta el componente de descarga (yt-dlp).",
            "No está instalado en el entorno de la aplicación.",
            "Ejecuta: .\\.venv\\Scripts\\python.exe -m pip install yt-dlp",
            cause=exc,
        ) from exc
    return yt_dlp


class YouTubeSource:
    name = "YouTube"
    needs_internet = True

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def is_available(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, ("La búsqueda en YouTube está desactivada. Puedes activarla en "
                           "Ajustes ▸ Privacidad.")
        try:
            _ydl()
        except AppError as exc:
            return False, exc.user_message()
        return True, ""

    def _require_enabled(self) -> None:
        ok, reason = self.is_available()
        if not ok:
            raise AppError("No se puede usar YouTube ahora mismo.", reason,
                           "Actívalo en Ajustes ▸ Privacidad o usa Import Song con un archivo tuyo.")

    # --- búsqueda ---
    def search(self, query: str, limit: int = 20, cancelled: Cancelled | None = None) -> list[SearchResult]:
        self._require_enabled()
        yt_dlp = _ydl()
        query = query.strip()
        if not query:
            return []
        # Una URL pegada se resuelve directamente en lugar de buscarla como texto.
        target = query if query.startswith(("http://", "https://")) else f"ytsearch{limit}:{query}"
        opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "extract_flat": "in_playlist", "noplaylist": False, "socket_timeout": 20}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target, download=False)
        except Exception as exc:  # noqa: BLE001
            raise _explain_ydl(exc, "buscar en YouTube") from exc
        if cancelled and cancelled():
            raise SearchCancelled
        entries = info.get("entries") if isinstance(info, dict) and "entries" in info else [info]
        results = []
        for entry in entries or []:
            if not entry:
                continue
            vid = entry.get("id") or ""
            url = entry.get("webpage_url") or entry.get("url") or (f"https://www.youtube.com/watch?v={vid}")
            results.append(SearchResult(
                title=entry.get("title") or "(sin título)",
                source=self.name,
                ref=url,
                artist=entry.get("uploader") or entry.get("channel") or "",
                duration=float(entry.get("duration") or 0.0),
                extra={"id": vid},
            ))
        return results[:limit]

    # --- descarga ---
    def fetch(self, result: SearchResult, dest_dir: Path,
              progress: Progress | None = None, cancelled: Cancelled | None = None) -> Path:
        self._require_enabled()
        yt_dlp = _ydl()
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        def hook(d: dict) -> None:
            if cancelled and cancelled():
                raise SearchCancelled
            if not progress:
                return
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                frac = (done / total) if total else 0.0
                progress(min(0.95, frac), f"Descargando… {int(frac * 100)}%")
            elif d.get("status") == "finished":
                progress(0.97, "Preparando el audio…")

        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,          # el progreso lo muestra la aplicación, no la consola
            "noplaylist": True,
            "progress_hooks": [hook],
            "socket_timeout": 30,
            "retries": 3,
            "overwrites": True,
        }
        if progress:
            progress(0.02, "Conectando…")

        # YouTube devuelve a veces un flujo parcial que se da por completo: la canción quedaría
        # cortada sin avisar. Se compara el tamaño real con el esperado y se reintenta una vez.
        last_short: tuple[int, int] | None = None
        for attempt in (1, 2):
            if attempt == 2 and progress:
                progress(0.05, "La descarga llegó incompleta; reintentando…")
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(result.ref, download=True)
                    path = Path(ydl.prepare_filename(info))
            except SearchCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                raise _explain_ydl(exc, "descargar el audio") from exc

            if not path.exists():
                # yt-dlp pudo guardar con otra extensión de la prevista.
                matches = sorted(dest_dir.glob(f"{info.get('id', '')}.*"))
                if not matches:
                    raise AppError(
                        "La descarga terminó pero no se encontró el archivo.",
                        "El formato elegido no se guardó donde se esperaba.",
                        "Vuelve a intentarlo, o descarga el audio por tu cuenta e impórtalo con Import Song.",
                    )
                path = matches[0]

            actual = path.stat().st_size
            expected = int(info.get("filesize") or info.get("filesize_approx") or 0)
            if expected <= 0 or actual >= expected * 0.8:
                if progress:
                    progress(1.0, "Descarga completada")
                return path
            log.warning("Descarga incompleta (%s de %s bytes), intento %s", actual, expected, attempt)
            last_short = (actual, expected)

        raise AppError(
            "La descarga llegó incompleta y la canción quedaría cortada.",
            f"YouTube envió solo {last_short[0] // 1024} KB de los {last_short[1] // 1024} KB esperados, "
            "normalmente por limitación de velocidad temporal.",
            "Espera un momento y vuelve a intentarlo, o descarga el audio por tu cuenta e impórtalo "
            "con Import Song.",
        )


def _explain_ydl(exc: Exception, action: str) -> AppError:
    text = str(exc).lower()
    if any(k in text for k in ("sign in", "age", "confirm your age", "login required", "private video",
                               "members-only", "drm", "protected")):
        return AppError(
            f"No se puede {action}: el vídeo tiene restricciones de acceso.",
            "Es privado, de pago, solo para miembros o requiere verificación de edad. "
            "La aplicación no salta ese tipo de protecciones.",
            "Elige otro resultado, o consigue el archivo de audio legalmente e impórtalo con Import Song.",
            cause=exc,
        )
    if any(k in text for k in ("unavailable", "removed", "not available", "no longer")):
        return AppError(
            f"No se puede {action}: el vídeo ya no está disponible.",
            "Fue eliminado o no está disponible en tu país.",
            "Prueba con otro resultado de la lista.",
            cause=exc,
        )
    if any(k in text for k in ("timed out", "timeout", "connection", "network", "resolve", "unreachable",
                               "getaddrinfo")):
        return AppError(
            f"No se pudo {action}: sin conexión con YouTube.",
            "No hay Internet, o un cortafuegos está bloqueando la conexión.",
            "Comprueba tu conexión y vuelve a intentarlo.",
            cause=exc,
        )
    return AppError(
        f"No se pudo {action}.",
        f"YouTube devolvió un error: {str(exc)[:200]}",
        "Prueba con otro resultado. Si falla siempre, puede que yt-dlp necesite actualizarse: "
        ".\\.venv\\Scripts\\python.exe -m pip install -U yt-dlp",
        cause=exc,
    )
