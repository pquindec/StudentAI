"""Fuentes de conocimiento: alta, versiones de texto y vínculos."""

import json
import sqlite3
import uuid
from typing import Any

from app.core.errors import bad_request, from_integrity_error, not_found
from app.db.connection import tx
from app.pipelines.extract.document import segment


def get_source(db: sqlite3.Connection, user: str, source_id: str) -> dict[str, Any]:
    row = db.execute(
        """SELECT x.* FROM sources x JOIN subjects s ON s.id = x.subject_id
           WHERE x.id = ? AND s.owner_id = ?""",
        (source_id, user),
    ).fetchone()
    if row is None:
        raise not_found("Fuente")
    return dict(row)


def links(db: sqlite3.Connection, source_id: str) -> tuple[list[str], list[str]]:
    rows = db.execute(
        "SELECT unit_id, session_id FROM source_links WHERE source_id = ?", (source_id,)
    ).fetchall()
    return (
        [r["unit_id"] for r in rows if r["unit_id"]],
        [r["session_id"] for r in rows if r["session_id"]],
    )


def set_links(
    db: sqlite3.Connection, source_id: str, unit_ids: list[str], session_ids: list[str]
) -> None:
    """Reemplaza los vínculos. Debe llamarse dentro de una transacción."""
    db.execute("DELETE FROM source_links WHERE source_id = ?", (source_id,))
    try:
        for u in dict.fromkeys(unit_ids):
            db.execute("INSERT INTO source_links(source_id, unit_id) VALUES (?, ?)", (source_id, u))
        for x in dict.fromkeys(session_ids):
            db.execute(
                "INSERT INTO source_links(source_id, session_id) VALUES (?, ?)", (source_id, x)
            )
    except sqlite3.IntegrityError as exc:
        raise from_integrity_error(exc) from exc


def check_link_targets(
    db: sqlite3.Connection, subject_id: str, unit_ids: list[str], session_ids: list[str]
) -> None:
    queries = (
        ("SELECT subject_id FROM units WHERE id = ?", unit_ids, "unidad"),
        ("SELECT subject_id FROM sessions WHERE id = ?", session_ids, "sesión"),
    )
    for sql, ids, label in queries:
        for i in ids:
            row = db.execute(sql, (i,)).fetchone()
            if row is None or row[0] != subject_id:
                raise bad_request(
                    "invalid_link", f"La {label} elegida no existe en esta asignatura"
                )


def current_version(db: sqlite3.Connection, source_id: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT * FROM source_versions WHERE source_id = ? ORDER BY version DESC LIMIT 1",
        (source_id,),
    ).fetchone()
    return dict(row) if row else None


def add_version(db: sqlite3.Connection, source_id: str, text: str, origin: str) -> int:
    """Guarda una versión nueva con sus segmentos. Debe llamarse dentro de una transacción."""
    row = db.execute(
        "SELECT COALESCE(MAX(version), 0) FROM source_versions WHERE source_id = ?", (source_id,)
    ).fetchone()
    version = int(row[0]) + 1
    vid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO source_versions(id, source_id, version, origin, text, char_count)"
        " VALUES (?,?,?,?,?,?)",
        (vid, source_id, version, origin, text, len(text)),
    )
    db.executemany(
        "INSERT INTO segments(version_id, ordinal, kind, level, text, page, section_path,"
        " start_ms, end_ms, char_start, char_end) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                vid,
                s.ordinal,
                s.kind,
                s.level,
                s.text,
                s.page,
                s.section_path,
                s.start_ms,
                s.end_ms,
                s.char_start,
                s.char_end,
            )
            for s in segment(text)
        ],
    )
    return version


def create_text_source(
    db: sqlite3.Connection,
    subject_id: str,
    kind: str,
    title: str,
    text: str,
    unit_ids: list[str],
    session_ids: list[str],
) -> str:
    sid = str(uuid.uuid4())
    with tx(db):
        check_link_targets(db, subject_id, unit_ids, session_ids)
        db.execute(
            "INSERT INTO sources(id, subject_id, kind, title, status, mime, size_bytes,"
            " processed_at) VALUES (?,?,?,?, 'ready', 'text/markdown', ?, now_iso())",
            (sid, subject_id, kind, title, len(text.encode())),
        )
        set_links(db, sid, unit_ids, session_ids)
        add_version(db, sid, text, "pasted")
    return sid


def merge_metadata(db: sqlite3.Connection, source_id: str, extra: dict[str, Any]) -> None:
    row = db.execute("SELECT metadata_json FROM sources WHERE id = ?", (source_id,)).fetchone()
    meta = json.loads(row[0]) if row else {}
    meta.update(extra)
    db.execute("UPDATE sources SET metadata_json = ? WHERE id = ?", (json.dumps(meta), source_id))
