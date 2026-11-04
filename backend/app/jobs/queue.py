"""Cola de trabajos persistente en SQLite (ADR-008)."""

import json
import sqlite3
import uuid
from typing import Any

from app.db.connection import tx

MAX_ATTEMPTS = 3

# Prioridades (mayor = antes). Ver ARCHITECTURE §8.
PRIORITY = {"interactive": 90, "recording": 80, "import": 50, "batch": 20}


def enqueue(
    db: sqlite3.Connection,
    job_type: str,
    resource_class: str,
    source_id: str | None,
    payload: dict[str, Any] | None = None,
    priority: int = PRIORITY["import"],
) -> str:
    jid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO jobs(id, type, resource_class, priority, source_id, payload_json)"
        " VALUES (?,?,?,?,?,?)",
        (jid, job_type, resource_class, priority, source_id, json.dumps(payload or {})),
    )
    return jid


def claim_next(db: sqlite3.Connection, free_classes: list[str]) -> dict[str, Any] | None:
    """Toma atómicamente el siguiente trabajo de las clases con hueco libre."""
    if not free_classes:
        return None
    marks = ",".join("?" * len(free_classes))
    with tx(db, immediate=True):
        row = db.execute(
            f"SELECT * FROM jobs WHERE status = 'queued' AND resource_class IN ({marks})"  # noqa: S608
            " ORDER BY priority DESC, created_at LIMIT 1",
            free_classes,
        ).fetchone()
        if row is None:
            return None
        db.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1, started_at = now_iso(),"
            " progress = 0, message = NULL WHERE id = ?",
            (row["id"],),
        )
    return dict(row)


def progress(db: sqlite3.Connection, job_id: str, value: float, message: str | None) -> None:
    db.execute(
        "UPDATE jobs SET progress = ?, message = COALESCE(?, message) WHERE id = ?",
        (max(0.0, min(value, 1.0)), message, job_id),
    )


def save_checkpoint(db: sqlite3.Connection, job_id: str, data: dict[str, Any]) -> None:
    db.execute("UPDATE jobs SET checkpoint_json = ? WHERE id = ?", (json.dumps(data), job_id))


def higher_waiting(db: sqlite3.Connection, priority: int) -> bool:
    """¿Hay en cola un trabajo pesado más prioritario (p. ej. transcribir una grabación)?"""
    row = db.execute(
        "SELECT 1 FROM jobs WHERE status = 'queued' AND resource_class IN ('stt', 'llm')"
        " AND priority > ? LIMIT 1",
        (priority,),
    ).fetchone()
    return row is not None


def requeue(db: sqlite3.Connection, job_id: str, message: str) -> None:
    """Devuelve a la cola un trabajo que cede el turno; conserva su checkpoint y no cuenta como
    intento fallido."""
    db.execute(
        "UPDATE jobs SET status = 'queued', attempts = MAX(attempts - 1, 0), started_at = NULL,"
        " message = ? WHERE id = ?",
        (message, job_id),
    )


def finish(
    db: sqlite3.Connection,
    job_id: str,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    db.execute(
        "UPDATE jobs SET status = ?, error_code = ?, error_message = ?, finished_at = now_iso(),"
        " progress = CASE WHEN ? = 'done' THEN 1 ELSE progress END WHERE id = ?",
        (status, error_code, error_message, status, job_id),
    )


def cancel_requested(db: sqlite3.Connection, job_id: str) -> bool:
    row = db.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row is None or bool(row[0])  # si se borró (fuente eliminada), se cancela


def request_cancel(db: sqlite3.Connection, job_id: str) -> str:
    """Devuelve el estado resultante. Un trabajo en cola se cancela al momento."""
    with tx(db, immediate=True):
        row = db.execute("SELECT status, source_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return "missing"
        if row["status"] == "queued":
            db.execute(
                "UPDATE jobs SET status = 'cancelled', finished_at = now_iso() WHERE id = ?",
                (job_id,),
            )
            if row["source_id"]:
                db.execute(
                    "UPDATE sources SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                    (row["source_id"],),
                )
            return "cancelled"
        if row["status"] == "running":
            db.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
            return "cancelling"
        return str(row["status"])


def recover_interrupted(db: sqlite3.Connection) -> int:
    """Al arrancar: los trabajos que quedaron 'running' (cierre o fallo) vuelven a la cola."""
    with tx(db, immediate=True):
        db.execute(
            "UPDATE jobs SET status = 'failed', error_code = 'interrupted',"
            " error_message = 'Interrumpido demasiadas veces', finished_at = now_iso()"
            " WHERE status = 'running' AND attempts >= ?",
            (MAX_ATTEMPTS,),
        )
        cur = db.execute(
            "UPDATE jobs SET status = 'queued', cancel_requested = 0 WHERE status = 'running'"
        )
    return cur.rowcount
