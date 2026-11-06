"""Vista previa de un envío a Claude: qué fuentes, cuántos fragmentos y el texto exacto.

Es lo que se enseña en la pantalla de consentimiento y lo que queda aprobado en él: el trabajo
solo puede enviar ese material (para el asistente, exactamente esos fragmentos).
"""

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import bad_request
from app.rag import answer as rag_answer
from app.rag import index as rag_index
from app.rag import search as rag_search
from app.rag.scope import Scope
from app.services import chat as chat_svc
from app.services import exams as exams_svc
from app.services import llm as llm_svc
from app.services import sources as src_svc

MAX_PREVIEW_CHARS = 200_000  # lo que se devuelve para mostrar; el recuento es siempre completo


@dataclass
class Preview:
    sources: list[dict[str, str]]
    fragments: int
    text: str
    scope: dict[str, Any]
    sends: bool = True  # False: no hay nada que enviar (p. ej. «no encontrado» sin modelo)
    notes: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return len(self.text)


def for_docs(db: sqlite3.Connection, user: str, subject_id: str, source_ids: list[str]) -> Preview:
    ids = list(dict.fromkeys(source_ids))
    if not ids:
        raise bad_request("no_sources", "Elige al menos una fuente")
    parts, sources, n = [], [], 0
    for sid in ids:
        row = db.execute(
            "SELECT s.id, s.title, s.kind FROM sources s JOIN subjects j ON j.id = s.subject_id"
            " WHERE s.id = ? AND s.subject_id = ? AND j.owner_id = ?",
            (sid, subject_id, user),
        ).fetchone()
        if row is None:
            raise bad_request("invalid_source", "Una de las fuentes no es de esta asignatura")
        v = src_svc.current_version(db, sid)
        segs = (
            db.execute(
                "SELECT text FROM segments WHERE version_id = ? ORDER BY ordinal", (v["id"],)
            ).fetchall()
            if v
            else []
        )
        texts = [str(s[0]).strip() for s in segs if str(s[0]).strip()]
        n += len(texts)
        sources.append(dict(row))
        parts.append(f"── {row['title']} ──\n" + "\n".join(texts))
    return Preview(sources, n, "\n\n".join(parts), {"source_ids": ids})


def for_material(db: sqlite3.Connection, user: str, scope: Scope, review_only: bool) -> Preview:
    exams_svc._check_scope(db, str(scope.subject_id), scope)
    groups = exams_svc.material(db, user, scope)
    if not groups:
        raise bad_request("no_sources", "No hay fuentes con texto en lo que has elegido")
    by_source: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    n = 0
    for sid, title, frags in groups:
        titles[sid] = title
        by_source.setdefault(sid, []).extend(f.text for f in frags)
        n += len(frags)
    kinds = dict(
        db.execute(
            f"SELECT id, kind FROM sources WHERE id IN ({','.join('?' * len(titles))})",  # noqa: S608
            list(titles),
        ).fetchall()
    )
    text = "\n\n".join(f"── {titles[s]} ──\n" + "\n".join(t) for s, t in by_source.items())
    notes = ["review_only"] if review_only else []
    return Preview(
        [{"id": s, "title": titles[s], "kind": str(kinds.get(s, ""))} for s in titles],
        n,
        text,
        {"source_ids": list(titles)},
        notes=notes,
    )


def for_chat(db: sqlite3.Connection, user: str, thread_id: str, question: str) -> Preview:
    """Misma búsqueda que hará la respuesta; se aprueban exactamente esos fragmentos."""
    thread = chat_svc.get_thread(db, user, thread_id)
    scope = chat_svc.scope_of(thread)
    prov = llm_svc.provider()
    embedder = prov if rag_index.embeddings_available(prov) is None else None
    found = rag_search.search(db, user, scope, question, embedder)
    previous = chat_svc.last_kind(db, thread_id, None)
    creative = rag_answer.is_creative(question, previous in ("created", "general"))
    hits = rag_answer._with_next(db, found.hits) if found.relevant else []
    history = chat_svc.history(db, thread_id, None)[-rag_answer.HISTORY_TURNS :]
    parts = [
        f"Pregunta anterior: {q}\nRespuesta anterior: {rag_answer.strip_refs(a)}"
        for q, a in history
    ]
    sources: list[dict[str, str]] = []
    n = 0
    notes = ["creative"] if creative else []
    if hits:
        ctx = rag_answer.build_context(db, hits)
        n = len(ctx.segment_of)
        parts.append(ctx.block)
        ids = list(dict.fromkeys(h.source_id for h in hits))
        marks = ",".join("?" * len(ids))
        sources = [
            dict(r)
            for r in db.execute(
                f"SELECT id, title, kind FROM sources WHERE id IN ({marks})",  # noqa: S608
                ids,
            )
        ]
    elif creative:
        notes.append("general")  # se creará sin fragmentos, con conocimiento general
    parts.append(f"Pregunta: {question}")
    sends = bool(hits) or creative
    if not sends:
        notes.append("not_found")
    return Preview(
        sources,
        n,
        "\n\n".join(parts),
        {"chunk_ids": [h.chunk_id for h in hits], "thread_id": thread_id},
        sends,
        notes,
    )
