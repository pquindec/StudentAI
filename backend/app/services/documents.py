"""Apuntes y resúmenes generados: alta, carga del material, guardado y lectura con citas."""

import json
import sqlite3
import string
import uuid
from typing import Any

from app.core.errors import bad_request, not_found
from app.db.connection import tx
from app.generation.docs import BLOCK_CHARS, Fragment, SourceText
from app.jobs import queue
from app.pipelines.extract.document import format_time_mark
from app.services import sources as src_svc

MAX_SOURCES = 20


def letter(i: int) -> str:
    """0 → A, 25 → Z, 26 → AA…"""
    abc = string.ascii_uppercase
    return abc[i] if i < 26 else abc[i // 26 - 1] + abc[i % 26]


def get_doc(db: sqlite3.Connection, user: str, doc_id: str) -> dict[str, Any]:
    row = db.execute(
        """SELECT d.* FROM generated_docs d JOIN subjects s ON s.id = d.subject_id
           WHERE d.id = ? AND s.owner_id = ?""",
        (doc_id, user),
    ).fetchone()
    if row is None:
        raise not_found("Documento")
    return dict(row)


def create(
    db: sqlite3.Connection,
    subject_id: str,
    kind: str,
    detail: str,
    title: str,
    source_ids: list[str],
    model: str,
) -> str:
    """Crea el documento y encola su generación. Las fuentes deben ser de la asignatura y tener
    texto; se fija la versión actual de cada una (las citas apuntan a esa versión)."""
    ids = list(dict.fromkeys(source_ids))
    if not ids:
        raise bad_request("no_sources", "Elige al menos una fuente")
    if len(ids) > MAX_SOURCES:
        raise bad_request("too_many_sources", f"Elige como máximo {MAX_SOURCES} fuentes")
    versions = []
    for sid in ids:
        row = db.execute(
            "SELECT title FROM sources WHERE id = ? AND subject_id = ?", (sid, subject_id)
        ).fetchone()
        if row is None:
            raise bad_request("invalid_source", "Una de las fuentes no es de esta asignatura")
        v = src_svc.current_version(db, sid)
        if v is None or not v["text"].strip():
            raise bad_request("source_without_text", f"«{row['title']}» todavía no tiene texto")
        versions.append((sid, v["id"]))
    doc_id = str(uuid.uuid4())
    with tx(db):
        db.execute(
            "INSERT INTO generated_docs(id, subject_id, kind, detail, title, model)"
            " VALUES (?,?,?,?,?,?)",
            (doc_id, subject_id, kind, detail, title, model),
        )
        db.executemany(
            "INSERT INTO generated_doc_sources(doc_id, source_id, version_id, position)"
            " VALUES (?,?,?,?)",
            [(doc_id, sid, vid, i) for i, (sid, vid) in enumerate(versions)],
        )
        job = queue.enqueue(
            db, "generate_doc", "llm", None, {"doc_id": doc_id}, priority=queue.PRIORITY["batch"]
        )
        db.execute("UPDATE generated_docs SET job_id = ? WHERE id = ?", (job, doc_id))
    return doc_id


def _where(seg: sqlite3.Row) -> str:
    if seg["start_ms"] is not None:
        return format_time_mark(int(seg["start_ms"]))
    if seg["page"] is not None:
        return f"p. {seg['page']}"
    return ""


def load_material(db: sqlite3.Connection, doc_id: str) -> list[SourceText]:
    rows = db.execute(
        """SELECT ds.position, ds.version_id, s.title FROM generated_doc_sources ds
           JOIN sources s ON s.id = ds.source_id WHERE ds.doc_id = ? ORDER BY ds.position""",
        (doc_id,),
    ).fetchall()
    out = []
    for i, r in enumerate(rows):
        lt = letter(i)
        segs = db.execute(
            "SELECT id, ordinal, text, page, start_ms FROM segments WHERE version_id = ?"
            " ORDER BY ordinal",
            (r["version_id"],),
        ).fetchall()
        frags = [
            Fragment(
                id=f"{lt}{s['ordinal']}",
                segment_id=int(s["id"]),
                source=lt,
                where=_where(s),
                text=str(s["text"])[:BLOCK_CHARS],
            )
            for s in segs
            if str(s["text"]).strip()
        ]
        out.append(SourceText(lt, str(r["title"]), frags))
    return out


def set_status(
    db: sqlite3.Connection,
    doc_id: str,
    status: str,
    code: str | None = None,
    message: str | None = None,
) -> None:
    db.execute(
        "UPDATE generated_docs SET status = ?, error_code = ?, error_message = ?,"
        " updated_at = now_iso() WHERE id = ?",
        (status, code, message, doc_id),
    )


def save_result(
    db: sqlite3.Connection,
    doc_id: str,
    content: dict[str, Any],
    citations: list[tuple[int, int]],
    model: str,
    stats: dict[str, Any],
) -> None:
    with tx(db):
        if db.execute("SELECT 1 FROM generated_docs WHERE id = ?", (doc_id,)).fetchone() is None:
            return  # se borró mientras se generaba
        db.execute("DELETE FROM generated_doc_citations WHERE doc_id = ?", (doc_id,))
        db.executemany(
            "INSERT INTO generated_doc_citations(doc_id, ref, segment_id) VALUES (?,?,?)",
            [(doc_id, ref, seg) for ref, seg in citations],
        )
        db.execute(
            "UPDATE generated_docs SET content_json = ?, model = ?, stats_json = ?,"
            " status = 'ready', error_code = NULL, error_message = NULL, updated_at = now_iso()"
            " WHERE id = ?",
            (json.dumps(content, ensure_ascii=False), model, json.dumps(stats), doc_id),
        )


def citations(db: sqlite3.Connection, doc_id: str) -> list[dict[str, Any]]:
    """Citas con su texto literal y localización. Si la fuente se borró, la cita no aparece y la
    UI muestra la referencia como «fuente eliminada»."""
    rows = db.execute(
        """SELECT c.ref, g.text, g.page, g.start_ms, g.end_ms, v.source_id, v.version,
                  s.title AS source_title, s.kind AS source_kind
           FROM generated_doc_citations c
           JOIN segments g ON g.id = c.segment_id
           JOIN source_versions v ON v.id = g.version_id
           JOIN sources s ON s.id = v.source_id
           WHERE c.doc_id = ? ORDER BY c.ref""",
        (doc_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def doc_sources(db: sqlite3.Connection, doc_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT s.id, s.title, s.kind FROM generated_doc_sources ds
           JOIN sources s ON s.id = ds.source_id WHERE ds.doc_id = ? ORDER BY ds.position""",
        (doc_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def record_run(
    db: sqlite3.Connection,
    job_id: str | None,
    model: str,
    task: str,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_ms: int,
    loaded_mb: int | None,
) -> None:
    db.execute(
        "INSERT INTO model_runs(job_id, provider, model, task, input_tokens, output_tokens,"
        " duration_ms, loaded_mb) VALUES (?, 'ollama', ?, ?, ?, ?, ?, ?)",
        (job_id, model, task, input_tokens, output_tokens, duration_ms, loaded_mb),
    )
