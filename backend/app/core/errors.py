"""Errores de la aplicación con mensajes en español aptos para mostrar al usuario."""

from typing import Any


class AppError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def body(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            err["details"] = self.details
        return {"error": err}


def not_found(what: str) -> AppError:
    return AppError(404, "not_found", f"{what} no encontrado")


def conflict(code: str, message: str, **details: Any) -> AppError:
    return AppError(409, code, message, details)


def bad_request(code: str, message: str, **details: Any) -> AppError:
    return AppError(400, code, message, details)


# Mensajes de los triggers de integridad de SQLite → errores comprensibles.
INTEGRITY_MESSAGES = {
    "parent_unit_other_subject": "La unidad superior pertenece a otra asignatura",
    "session_unit_other_subject": "La unidad elegida pertenece a otra asignatura",
    "link_other_subject": "Solo puedes vincular unidades o sesiones de la misma asignatura",
}


def from_integrity_error(exc: Exception) -> AppError:
    text = str(exc)
    for key, msg in INTEGRITY_MESSAGES.items():
        if key in text:
            return AppError(409, key, msg)
    return AppError(409, "integrity_error", "La operación entra en conflicto con datos existentes")
