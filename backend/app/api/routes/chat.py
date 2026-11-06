"""Asistente (Fase 5): conversaciones con ámbito, preguntas y estado del índice de búsqueda."""

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, StringConstraints

from app.api.deps import Db, UserId
from app.api.routes.ai import CitationOut
from app.jobs import queue
from app.rag import index as rag_index
from app.rag import search as rag_search
from app.rag.scope import Scope
from app.services import chat as svc
from app.services import llm
from app.services import sources as src_svc

router = APIRouter(tags=["chat"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
MessageStatus = Literal["queued", "streaming", "done", "not_found", "failed", "cancelled"]
IndexStatus = Literal["none", "queued", "indexing", "ready", "failed"]


class ThreadIn(BaseModel):
    scope: Scope = Scope()
    title: Title | None = None


class ThreadPatch(BaseModel):
    title: Title | None = None
    scope: Scope | None = None


class ThreadOut(BaseModel):
    id: str
    subject_id: str | None
    title: str
    scope: Scope
    created_at: str
    updated_at: str


class MessageIn(BaseModel):
    text: Question
    consent_id: Annotated[str, StringConstraints(max_length=64)] | None = None  # Fase 8


class ChatStatsOut(BaseModel):
    # answer: responde con las fuentes · created: creado a partir de las fuentes ·
    # general: creado con conocimiento general del modelo (sin respaldo en las fuentes)
    kind: Literal["answer", "created", "general"] = "answer"
    search_mode: str | None = None
    search_ms: int | None = None
    proposed_cites: int = 0
    invented_cites: int = 0
    duration_ms: int | None = None
    fallback: bool = False


class MessageOut(BaseModel):
    id: str
    thread_id: str
    role: Literal["user", "assistant"]
    content: str
    status: MessageStatus
    error: str | None
    model: str | None
    progress_message: str | None
    created_at: str
    citations: list[CitationOut]
    stats: ChatStatsOut


class ThreadDetailOut(ThreadOut):
    messages: list[MessageOut]


class SourceIndexOut(BaseModel):
    status: IndexStatus
    chunks: int
    embedded: int
    error: str | None


class RagStatusOut(BaseModel):
    embed_model: str
    embed_ready: bool
    embed_problem: str | None
    vector_search: bool
    sources: int
    indexed: int
    pending: int


def _thread(row: dict[str, Any]) -> ThreadOut:
    return ThreadOut(
        id=row["id"],
        subject_id=row["subject_id"],
        title=row["title"],
        scope=svc.scope_of(row),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _messages(db: Db, rows: list[dict[str, Any]]) -> list[MessageOut]:
    cites = svc.citations(db, [m["id"] for m in rows if m["role"] == "assistant"])
    out = []
    for m in rows:
        raw = json.loads(m["stats_json"] or "{}")
        stats = {k: v for k, v in raw.items() if k in ChatStatsOut.model_fields}
        out.append(
            MessageOut(
                id=m["id"],
                thread_id=m["thread_id"],
                role=m["role"],
                content=m["content"],
                status=m["status"],
                error=m["error"],
                model=m["model"],
                progress_message=m["progress_message"],
                created_at=m["created_at"],
                citations=[CitationOut(**c) for c in cites.get(m["id"], [])],
                stats=ChatStatsOut(**stats),
            )
        )
    return out


@router.get("/chat/threads", response_model=list[ThreadOut])
def list_threads(
    db: Db, user: UserId, subject_id: Annotated[str | None, Query()] = None
) -> list[ThreadOut]:
    sql = "SELECT * FROM chat_threads WHERE owner_id = ?"
    params: list[Any] = [user]
    if subject_id:
        sql += " AND subject_id = ?"
        params.append(subject_id)
    rows = db.execute(f"{sql} ORDER BY updated_at DESC LIMIT 200", params).fetchall()
    return [_thread(dict(r)) for r in rows]


@router.post("/chat/threads", response_model=ThreadOut, status_code=201)
def create_thread(body: ThreadIn, db: Db, user: UserId) -> ThreadOut:
    tid = svc.create_thread(db, user, body.scope, body.title)
    return _thread(svc.get_thread(db, user, tid))


@router.get("/chat/threads/{thread_id}", response_model=ThreadDetailOut)
def get_thread(thread_id: str, db: Db, user: UserId) -> ThreadDetailOut:
    th = svc.get_thread(db, user, thread_id)
    return ThreadDetailOut(
        **_thread(th).model_dump(), messages=_messages(db, svc.messages(db, thread_id))
    )


@router.patch("/chat/threads/{thread_id}", response_model=ThreadOut)
def update_thread(thread_id: str, body: ThreadPatch, db: Db, user: UserId) -> ThreadOut:
    svc.update_thread(db, user, thread_id, body.title, body.scope)
    return _thread(svc.get_thread(db, user, thread_id))


@router.delete("/chat/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str, db: Db, user: UserId) -> Response:
    svc.get_thread(db, user, thread_id)
    for m in svc.messages(db, thread_id):
        if m["job_id"] and m["status"] in svc.BUSY:
            queue.request_cancel(db, m["job_id"])
    db.execute("DELETE FROM chat_threads WHERE id = ? AND owner_id = ?", (thread_id, user))
    return Response(status_code=204)


@router.post("/chat/threads/{thread_id}/messages", response_model=MessageOut, status_code=202)
def ask(thread_id: str, body: MessageIn, db: Db, user: UserId) -> MessageOut:
    mid = svc.post(db, user, thread_id, body.text, body.consent_id)
    return _messages(db, [svc.get_message(db, user, mid)])[0]


@router.get("/chat/messages/{message_id}", response_model=MessageOut)
def get_message(message_id: str, db: Db, user: UserId) -> MessageOut:
    return _messages(db, [svc.get_message(db, user, message_id)])[0]


@router.post("/chat/messages/{message_id}/cancel", response_model=MessageOut)
def cancel_message(message_id: str, db: Db, user: UserId) -> MessageOut:
    m = svc.get_message(db, user, message_id)
    if m["job_id"] and m["status"] in svc.BUSY:
        queue.request_cancel(db, m["job_id"])
    return _messages(db, [svc.get_message(db, user, message_id)])[0]


@router.get("/rag/status", response_model=RagStatusOut)
def rag_status(db: Db, user: UserId) -> RagStatusOut:
    problem = rag_index.embeddings_available(llm.provider())
    row = db.execute(
        """SELECT COUNT(*) AS sources,
                  SUM(i.status = 'ready') AS indexed,
                  SUM(i.status IN ('queued', 'indexing')) AS pending
           FROM sources s JOIN subjects j ON j.id = s.subject_id
           LEFT JOIN source_index i ON i.source_id = s.id
           WHERE j.owner_id = ? AND EXISTS (SELECT 1 FROM source_versions v
                                            WHERE v.source_id = s.id)""",
        (user,),
    ).fetchone()
    return RagStatusOut(
        embed_model=rag_index.EMBED_MODEL,
        embed_ready=problem is None,
        embed_problem=problem,
        vector_search=rag_search.load_vec(db),
        sources=row["sources"] or 0,
        indexed=row["indexed"] or 0,
        pending=row["pending"] or 0,
    )


@router.get("/sources/{source_id}/index", response_model=SourceIndexOut)
def source_index(source_id: str, db: Db, user: UserId) -> SourceIndexOut:
    src_svc.get_source(db, user, source_id)  # 404 si no es del usuario
    row = db.execute("SELECT * FROM source_index WHERE source_id = ?", (source_id,)).fetchone()
    if row is None:
        return SourceIndexOut(status="none", chunks=0, embedded=0, error=None)
    return SourceIndexOut(
        status=row["status"], chunks=row["chunks"], embedded=row["embedded"], error=row["error"]
    )
