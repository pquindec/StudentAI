"""Índice de búsqueda por fuente: chunks de la versión actual + FTS5 (triggers) + vectores.

Solo se indexa la versión actual de cada fuente. El trabajo `index_source` (clase embed) se
encola al guardar una versión nueva y al arrancar para lo que falte. Si el modelo de embeddings
no está disponible, la fuente queda buscable igualmente por palabras (embedded = 0).
"""

import logging
import sqlite3
import struct
import time
from collections.abc import Callable
from typing import Any

from app.db.connection import tx
from app.jobs import queue
from app.llm.base import LLMError, LLMProvider
from app.rag.chunking import chunk_segments

log = logging.getLogger(__name__)

EMBED_MODEL = "qwen3-embedding:0.6b"
# Qwen3-Embedding rinde mejor con una instrucción en la consulta (los pasajes van tal cual).
QUERY_PREFIX = (
    "Instruct: Dada una pregunta de un estudiante, recupera el pasaje que la responde\nQuery: "
)
BATCH = 16
EMBED_CHARS = 2000  # el resto del chunk no aporta al vector (y alarga el cálculo)
MIN_FREE_MB = 1500  # memoria disponible para cargar el modelo de embeddings (~1 GB)
WAIT_STEP_S = 5.0
MAX_WAIT_S = 120.0


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def request_index(db: sqlite3.Connection, source_id: str) -> None:
    """Marca la fuente para (re)indexar y encola el trabajo si no hay ya uno pendiente."""
    db.execute(
        """INSERT INTO source_index(source_id, status) VALUES (?, 'queued')
           ON CONFLICT(source_id) DO UPDATE SET status = 'queued', error = NULL,
           updated_at = now_iso()""",
        (source_id,),
    )
    pending = db.execute(
        "SELECT 1 FROM jobs WHERE type = 'index_source' AND status = 'queued'"
        " AND json_extract(payload_json, '$.source_id') = ?",
        (source_id,),
    ).fetchone()
    if pending is None:
        # Sin source_id en el trabajo: indexar no cambia el estado visible de la fuente.
        queue.enqueue(
            db, "index_source", "embed", None, {"source_id": source_id}, queue.PRIORITY["batch"]
        )


def backfill(db: sqlite3.Connection) -> int:
    """Encola las fuentes con texto cuyo índice falta, está desfasado o quedó a medias."""
    rows = db.execute(
        """SELECT s.id FROM sources s
           JOIN source_versions v ON v.source_id = s.id
            AND v.version = (SELECT MAX(version) FROM source_versions WHERE source_id = s.id)
           LEFT JOIN source_index i ON i.source_id = s.id
           WHERE i.source_id IS NULL OR i.version_id IS NOT v.id
              OR i.status IN ('queued', 'indexing')
              OR (i.status = 'ready' AND i.embedded < i.chunks)"""
    ).fetchall()
    with tx(db):
        for r in rows:
            request_index(db, r["id"])
    return len(rows)


def _segments(db: sqlite3.Connection, version_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT ordinal, kind, text, page, start_ms, end_ms, section_path FROM segments"
        " WHERE version_id = ? ORDER BY ordinal",
        (version_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def build_chunks(db: sqlite3.Connection, source_id: str) -> tuple[str, int] | None:
    """Sustituye los chunks de la fuente por los de su versión actual. (version_id, nº)."""
    src = db.execute("SELECT subject_id FROM sources WHERE id = ?", (source_id,)).fetchone()
    ver = db.execute(
        "SELECT id FROM source_versions WHERE source_id = ? ORDER BY version DESC LIMIT 1",
        (source_id,),
    ).fetchone()
    if src is None or ver is None:
        return None
    chunks = chunk_segments(_segments(db, ver["id"]))
    with tx(db, immediate=True):
        db.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
        db.executemany(
            "INSERT INTO chunks(source_id, version_id, subject_id, ordinal, text, seg_from,"
            " seg_to, page_from, page_to, start_ms, end_ms, section_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    source_id,
                    ver["id"],
                    src["subject_id"],
                    c.ordinal,
                    c.text,
                    c.seg_from,
                    c.seg_to,
                    c.page_from,
                    c.page_to,
                    c.start_ms,
                    c.end_ms,
                    c.section_path,
                )
                for c in chunks
            ],
        )
        db.execute(
            """INSERT INTO source_index(source_id, version_id, status, chunks, embedded, model)
               VALUES (?, ?, 'indexing', ?, 0, NULL)
               ON CONFLICT(source_id) DO UPDATE SET version_id = excluded.version_id,
               status = 'indexing', chunks = excluded.chunks, embedded = 0, model = NULL,
               error = NULL, updated_at = now_iso()""",
            (source_id, ver["id"], len(chunks)),
        )
    return ver["id"], len(chunks)


def embed_chunks(
    db: sqlite3.Connection,
    source_id: str,
    provider: LLMProvider,
    report: Callable[[float], None] = lambda _: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> int:
    """Calcula los vectores que falten. Devuelve cuántos chunks tienen vector."""
    rows = db.execute(
        """SELECT c.id, c.text FROM chunks c
           LEFT JOIN chunk_vectors v ON v.chunk_id = c.id AND v.model = ?
           WHERE c.source_id = ? AND v.chunk_id IS NULL ORDER BY c.ordinal""",
        (EMBED_MODEL, source_id),
    ).fetchall()
    for i in range(0, len(rows), BATCH):
        if cancelled():
            break
        batch = rows[i : i + BATCH]
        vectors = provider.embed(EMBED_MODEL, [str(r["text"])[:EMBED_CHARS] for r in batch])
        with tx(db):
            db.executemany(
                "INSERT OR REPLACE INTO chunk_vectors(chunk_id, model, embedding) VALUES (?,?,?)",
                [(r["id"], EMBED_MODEL, pack(v)) for r, v in zip(batch, vectors, strict=True)],
            )
        report(min(1.0, (i + len(batch)) / len(rows)))
    row = db.execute(
        "SELECT COUNT(*) FROM chunk_vectors v JOIN chunks c ON c.id = v.chunk_id"
        " WHERE c.source_id = ? AND v.model = ?",
        (source_id, EMBED_MODEL),
    ).fetchone()
    return int(row[0])


def embeddings_available(provider: LLMProvider) -> str | None:
    """None si se pueden calcular vectores; si no, el motivo (para mostrarlo)."""
    info = provider.info()
    if not info.running:
        return "Ollama no está en marcha: solo búsqueda por palabras"
    if not any(m == EMBED_MODEL or m.startswith(f"{EMBED_MODEL}:") for m in info.models):
        return f"Falta el modelo {EMBED_MODEL}: solo búsqueda por palabras"
    return None


def wait_for_memory(
    memory: Callable[[], int],
    cancelled: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    waited = 0.0
    while memory() < MIN_FREE_MB:
        if cancelled() or waited >= MAX_WAIT_S:
            return False
        sleep(WAIT_STEP_S)
        waited += WAIT_STEP_S
    return True


def index_source(
    db: sqlite3.Connection,
    source_id: str,
    provider: LLMProvider,
    memory: Callable[[], int],
    report: Callable[[float, str | None], None] = lambda *_: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> None:
    report(0.05, "Preparando la búsqueda")
    built = build_chunks(db, source_id)
    if built is None:
        db.execute("DELETE FROM source_index WHERE source_id = ?", (source_id,))
        return
    _, total = built
    error = embeddings_available(provider) if total else None
    embedded = 0
    if total and error is None:
        if not wait_for_memory(memory, cancelled):
            error = "Poca memoria libre: solo búsqueda por palabras por ahora"
        else:
            report(0.1, "Calculando vectores de búsqueda")
            try:
                embedded = embed_chunks(
                    db,
                    source_id,
                    provider,
                    report=lambda f: report(0.1 + 0.9 * f, None),
                    cancelled=cancelled,
                )
            except LLMError as e:
                log.warning("Embeddings de %s: %s", source_id, e.message)
                error = f"{e.message}: solo búsqueda por palabras"
    db.execute(
        "UPDATE source_index SET status = 'ready', embedded = ?, model = ?, error = ?,"
        " updated_at = now_iso() WHERE source_id = ?",
        (embedded, EMBED_MODEL if embedded else None, error, source_id),
    )
