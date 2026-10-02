from __future__ import annotations


class AppError(Exception):
    def __init__(self, what: str, why: str = "", fix: str = "", *, cause: BaseException | None = None):
        super().__init__(what)
        self.what = what
        self.why = why
        self.fix = fix
        self.cause = cause

    def user_message(self) -> str:
        parts = [self.what]
        if self.why:
            parts.append(f"Posible causa: {self.why}")
        if self.fix:
            parts.append(f"Cómo solucionarlo: {self.fix}")
        return "\n\n".join(parts)


def explain_exception(exc: BaseException, context: str = "") -> AppError:
    if isinstance(exc, AppError):
        return exc
    prefix = f"{context}: " if context else ""
    if isinstance(exc, FileNotFoundError):
        return AppError(
            f"{prefix}no se encontró el archivo.",
            "El archivo fue movido, renombrado o borrado.",
            "Comprueba la ruta e inténtalo de nuevo.",
            cause=exc,
        )
    if isinstance(exc, PermissionError):
        return AppError(
            f"{prefix}Windows no permite acceder a ese archivo o carpeta.",
            "El archivo está abierto en otro programa o la carpeta está protegida.",
            "Cierra el otro programa o elige una carpeta en la que puedas escribir (por ejemplo Documentos).",
            cause=exc,
        )
    if isinstance(exc, MemoryError):
        return AppError(
            f"{prefix}no hay memoria suficiente.",
            "El archivo de audio es muy grande.",
            "Cierra otros programas o usa un archivo más corto.",
            cause=exc,
        )
    name = type(exc).__name__
    if name == "PortAudioError":
        return AppError(
            f"{prefix}no se pudo abrir el dispositivo de audio.",
            f"El dispositivo está en uso por otra aplicación, está desconectado o no admite la configuración pedida ({exc}).",
            "Elige otro dispositivo en Ajustes, cierra programas que usen el micrófono/altavoces (OBS, Discord, DAW) "
            "o comprueba la privacidad del micrófono en Windows.",
            cause=exc,
        )
    return AppError(
        f"{prefix}ocurrió un error inesperado ({name}).",
        str(exc) or "Sin detalles adicionales.",
        "Revisa logs/app.log para ver el detalle técnico y vuelve a intentarlo.",
        cause=exc,
    )
