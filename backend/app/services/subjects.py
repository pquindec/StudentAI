"""Asignaturas, unidades (curso/módulo/tema) y sesiones. Toda consulta filtra por propietario."""

import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from app.core.errors import AppError, bad_request, not_found

# Orden jerárquico: una unidad solo puede colgar de otra de rango MENOR.
UNIT_RANK = {"course": 0, "module": 1, "topic": 2}
UNIT_NAMES = {"course": "un curso", "module": "un módulo", "topic": "un tema"}


def new_id() -> str:
    return str(uuid.uuid4())


def get_subject(db: sqlite3.Connection, user: str, subject_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM subjects WHERE id = ? AND owner_id = ?", (subject_id, user)
    ).fetchone()
    if row is None:
        raise not_found("Asignatura")
    return dict(row)


def list_subjects(db: sqlite3.Connection, user: str, archived: bool) -> list[dict[str, Any]]:
    rows = db.execute(
        f"""
        SELECT s.*,
          (SELECT COUNT(*) FROM sources x WHERE x.subject_id = s.id) AS source_count,
          (SELECT COUNT(*) FROM units u WHERE u.subject_id = s.id) AS unit_count
        FROM subjects s
        WHERE s.owner_id = ? AND s.archived_at IS {"NOT" if archived else ""} NULL
        ORDER BY s.name COLLATE NOCASE
        """,  # noqa: S608 — solo se interpola una palabra clave fija
        (user,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_unit(db: sqlite3.Connection, user: str, unit_id: str) -> dict[str, Any]:
    row = db.execute(
        """SELECT u.* FROM units u JOIN subjects s ON s.id = u.subject_id
           WHERE u.id = ? AND s.owner_id = ?""",
        (unit_id, user),
    ).fetchone()
    if row is None:
        raise not_found("Unidad")
    return dict(row)


def check_unit_parent(
    db: sqlite3.Connection, subject_id: str, kind: str, parent_id: str | None, unit_id: str | None
) -> None:
    """Valida rango jerárquico, misma asignatura y ausencia de ciclos."""
    if parent_id is None:
        return
    parent = db.execute(
        "SELECT id, subject_id, kind FROM units WHERE id = ?", (parent_id,)
    ).fetchone()
    if parent is None or parent["subject_id"] != subject_id:
        raise bad_request("invalid_parent", "La unidad superior no existe en esta asignatura")
    if UNIT_RANK[parent["kind"]] >= UNIT_RANK[kind]:
        raise bad_request(
            "invalid_hierarchy",
            f"No se puede colocar {UNIT_NAMES[kind]} dentro de {UNIT_NAMES[parent['kind']]}",
        )
    # Ciclos: subir desde el nuevo padre; si aparece la propia unidad, hay ciclo.
    current: str | None = parent_id
    for _ in range(100):
        if current is None:
            return
        if current == unit_id:
            raise bad_request("cycle", "Una unidad no puede quedar dentro de sí misma")
        row = db.execute("SELECT parent_id FROM units WHERE id = ?", (current,)).fetchone()
        current = row["parent_id"] if row else None
    raise bad_request("cycle", "Jerarquía demasiado profunda")


def get_session(db: sqlite3.Connection, user: str, session_id: str) -> dict[str, Any]:
    row = db.execute(
        """SELECT x.* FROM sessions x JOIN subjects s ON s.id = x.subject_id
           WHERE x.id = ? AND s.owner_id = ?""",
        (session_id, user),
    ).fetchone()
    if row is None:
        raise not_found("Sesión")
    return dict(row)


def check_unit_in_subject(db: sqlite3.Connection, subject_id: str, unit_id: str | None) -> None:
    if unit_id is None:
        return
    row = db.execute("SELECT subject_id FROM units WHERE id = ?", (unit_id,)).fetchone()
    if row is None or row["subject_id"] != subject_id:
        raise bad_request("invalid_unit", "La unidad no existe en esta asignatura")


def delete_subject_files(data_dir: Path, source_ids: list[str]) -> None:
    for sid in source_ids:
        remove_source_dir(data_dir, sid)


def remove_source_dir(data_dir: Path, source_id: str) -> None:
    """Borra la carpeta de una fuente. El nombre es un UUID validado: nunca una ruta externa."""
    try:
        uuid.UUID(source_id)
    except ValueError as exc:
        raise AppError(400, "invalid_id", "Identificador no válido") from exc
    root = (data_dir / "sources").resolve()
    target = (root / source_id).resolve()
    if target.parent != root:
        raise AppError(400, "invalid_id", "Identificador no válido")
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
