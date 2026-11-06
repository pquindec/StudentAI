"""Conversaciones del asistente: hilos con ámbito, mensajes y citas."""

import json
import sqlite3
import uuid
from typing import Any

from app.core.errors import bad_request, conflict, not_found
from app.db.connection import tx
from app.jobs import queue
from app.rag.scope import Scope
from app.services import subjects as subj

DEFAULT_TITLE = "Nueva conversación"
BUSY = ("queued", "streaming")


def _check_ids(db: sqlite3.Connection, user: str, scope: Scope) -> None:
    """Todo id del ámbito debe ser del usuario (y de la asignatura, si se fija una)."""
    if scope.subject_id:
        subj.get_subject(db, user, scope.subject_id)
    checks = (
        ("sources", scope.source_ids + scope.exclude_source_ids, "fuente"),
        ("units", scope.unit_ids, "unidad"),
    )
    for table, ids, label in checks:
        wanted = set(ids)
        if not wanted:
            continue
        marks = ",".join("?" * len(wanted))
        rows = db.execute(
            f"SELECT t.subject_id FROM {table} t JOIN subjects s ON s.id = t.subject_id"  # noqa: S608
            f" WHERE s.owner_id = ? AND t.id IN ({marks})",
            [user, *wanted],
        ).fetchall()
        if len(rows) != len(wanted) or (
            scope.subject_id and any(r[0] != scope.subject_id for r in rows)
        ):
            raise bad_request("invalid_scope", f"Alguna {label} elegida no existe en el ámbito")


def create_thread(db: sqlite3.Connection, user: str, scope: Scope, title: str | None) -> str:
    _check_ids(db, user, scope)
    tid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO chat_threads(id, owner_id, subject_id, title, scope_json) VALUES (?,?,?,?,?)",
        (tid, user, scope.subject_id, title or DEFAULT_TITLE, scope.model_dump_json()),
    )
    return tid


def get_thread(db: sqlite3.Connection, user: str, thread_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM chat_threads WHERE id = ? AND owner_id = ?", (thread_id, user)
    ).fetchone()
    if row is None:
        raise not_found("Conversación")
    return dict(row)


def update_thread(
    db: sqlite3.Connection, user: str, thread_id: str, title: str | None, scope: Scope | None
) -> None:
    th = get_thread(db, user, thread_id)
    if scope is not None:
        _check_ids(db, user, scope)
    db.execute(
        "UPDATE chat_threads SET title = ?, scope_json = ?, subject_id = ?, updated_at = now_iso()"
        " WHERE id = ?",
        (
            title or th["title"],
            scope.model_dump_json() if scope else th["scope_json"],
            scope.subject_id if scope else th["subject_id"],
            thread_id,
        ),
    )


def scope_of(thread: dict[str, Any]) -> Scope:
    return Scope.model_validate(json.loads(thread["scope_json"] or "{}"))


_MSG = """SELECT m.*, j.status AS job_status, j.message AS job_message,
       j.error_code AS job_error_code, j.error_message AS job_error
FROM chat_messages m LEFT JOIN jobs j ON j.id = m.job_id"""


def _msg(row: sqlite3.Row) -> dict[str, Any]:
    m = dict(row)
    # Trabajo cancelado/fallido antes de empezar (o fuera del manejador): se refleja aquí.
    if m["status"] in BUSY and m["job_status"] in ("cancelled", "failed"):
        m["status"] = m["job_status"]
        m["error"] = m["job_error"]
    m["progress_message"] = m["job_message"] if m["status"] in BUSY else None
    return m


def messages(db: sqlite3.Connection, thread_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        f"{_MSG} WHERE m.thread_id = ? ORDER BY m.created_at, m.rowid",
        (thread_id,),
    ).fetchall()
    return [_msg(r) for r in rows]


def get_message(db: sqlite3.Connection, user: str, message_id: str) -> dict[str, Any]:
    row = db.execute(
        f"{_MSG} JOIN chat_threads t ON t.id = m.thread_id WHERE m.id = ? AND t.owner_id = ?",
        (message_id, user),
    ).fetchone()
    if row is None:
        raise not_found("Mensaje")
    return _msg(row)


def post(db: sqlite3.Connection, user: str, thread_id: str, text: str) -> str:
    """Guarda la pregunta y encola la respuesta. Devuelve el id del mensaje de respuesta."""
    th = get_thread(db, user, thread_id)
    with tx(db, immediate=True):
        busy = db.execute(
            "SELECT 1 FROM chat_messages m LEFT JOIN jobs j ON j.id = m.job_id"
            " WHERE m.thread_id = ? AND m.status IN ('queued', 'streaming')"
            " AND (j.status IS NULL OR j.status IN ('queued', 'running'))",
            (thread_id,),
        ).fetchone()
        if busy:
            raise conflict("answer_in_progress", "Espera a que termine la respuesta anterior")
        first = db.execute(
            "SELECT 1 FROM chat_messages WHERE thread_id = ? LIMIT 1", (thread_id,)
        ).fetchone()
        qid, aid = str(uuid.uuid4()), str(uuid.uuid4())
        db.execute(
            "INSERT INTO chat_messages(id, thread_id, role, content) VALUES (?,?, 'user', ?)",
            (qid, thread_id, text),
        )
        job = queue.enqueue(
            db,
            "chat_answer",
            "llm",
            None,
            {"message_id": aid, "question_id": qid},
            priority=queue.PRIORITY["interactive"],
        )
        db.execute(
            "INSERT INTO chat_messages(id, thread_id, role, status, job_id)"
            " VALUES (?,?, 'assistant', 'queued', ?)",
            (aid, thread_id, job),
        )
        title = text[:80] if first is None and th["title"] == DEFAULT_TITLE else th["title"]
        db.execute(
            "UPDATE chat_threads SET title = ?, updated_at = now_iso() WHERE id = ?",
            (title, thread_id),
        )
    return aid


def history(db: sqlite3.Connection, thread_id: str, before: str) -> list[tuple[str, str]]:
    """Pares (pregunta, respuesta) completados anteriores al mensaje `before`."""
    rows = db.execute(
        "SELECT role, content, status FROM chat_messages WHERE thread_id = ?"
        " AND rowid < (SELECT rowid FROM chat_messages WHERE id = ?) ORDER BY rowid",
        (thread_id, before),
    ).fetchall()
    pairs: list[tuple[str, str]] = []
    question: str | None = None
    for r in rows:
        if r["role"] == "user":
            question = r["content"]
        elif question is not None and r["status"] == "done":
            pairs.append((question, r["content"]))
            question = None
    return pairs


def last_kind(db: sqlite3.Connection, thread_id: str, before: str) -> str | None:
    """Tipo de la última respuesta completada antes de `before`: answer, created o general."""
    row = db.execute(
        "SELECT stats_json FROM chat_messages WHERE thread_id = ? AND role = 'assistant'"
        " AND status = 'done' AND rowid < (SELECT rowid FROM chat_messages WHERE id = ?)"
        " ORDER BY rowid DESC LIMIT 1",
        (thread_id, before),
    ).fetchone()
    if row is None:
        return None
    kind = json.loads(row[0] or "{}").get("kind", "answer")
    return str(kind)


def save_answer(
    db: sqlite3.Connection,
    message_id: str,
    status: str,
    content: str,
    citations: list[tuple[int, int]],
    model: str | None,
    stats: dict[str, Any],
    error: str | None = None,
) -> None:
    with tx(db):
        if db.execute("SELECT 1 FROM chat_messages WHERE id = ?", (message_id,)).fetchone() is None:
            return  # se borró la conversación mientras se respondía
        db.execute("DELETE FROM chat_message_citations WHERE message_id = ?", (message_id,))
        db.executemany(
            "INSERT INTO chat_message_citations(message_id, ref, segment_id) VALUES (?,?,?)",
            [(message_id, ref, seg) for ref, seg in citations],
        )
        db.execute(
            "UPDATE chat_messages SET status = ?, content = ?, model = ?, stats_json = ?,"
            " error = ? WHERE id = ?",
            (status, content, model, json.dumps(stats), error, message_id),
        )


def set_live(db: sqlite3.Connection, message_id: str, content: str) -> None:
    db.execute(
        "UPDATE chat_messages SET status = 'streaming', content = ? WHERE id = ?"
        " AND status IN ('queued', 'streaming')",
        (content, message_id),
    )


def citations(db: sqlite3.Connection, message_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {m: [] for m in message_ids}
    if not message_ids:
        return out
    marks = ",".join("?" * len(message_ids))
    rows = db.execute(
        f"""SELECT c.message_id, c.ref, g.text, g.page, g.start_ms, g.end_ms, v.source_id,
                  v.version, s.title AS source_title, s.kind AS source_kind
           FROM chat_message_citations c
           JOIN segments g ON g.id = c.segment_id
           JOIN source_versions v ON v.id = g.version_id
           JOIN sources s ON s.id = v.source_id
           WHERE c.message_id IN ({marks}) ORDER BY c.ref""",  # noqa: S608
        message_ids,
    ).fetchall()
    for r in rows:
        d = dict(r)
        out[d.pop("message_id")].append(d)
    return out
