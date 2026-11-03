import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, StringConstraints

from app.api.deps import Db, UserId
from app.core.errors import bad_request, conflict
from app.db.connection import tx
from app.jobs import queue
from app.resources import manager
from app.services import documents as svc
from app.services import llm
from app.services import settings as prefs
from app.services import subjects as subj

router = APIRouter(tags=["ai"])

DocKind = Literal["notes", "summary"]
Detail = Literal["brief", "medium", "detailed"]
DocStatus = Literal["queued", "running", "ready", "failed", "cancelled"]
KeepAlive = Literal["1m", "2m", "5m", "10m"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class LlmModelOut(BaseModel):
    name: str
    installed: bool
    min_free_mb: int
    budget_mb: int


class LoadedOut(BaseModel):
    name: str
    size_mb: int


class AiStatusOut(BaseModel):
    running: bool
    version: str | None
    model: str
    light_model: str | None
    keep_alive: KeepAlive
    models: list[LlmModelOut]
    loaded: list[LoadedOut]
    available_mb: int | None


class AiSettingsIn(BaseModel):
    model: str | None = None
    keep_alive: KeepAlive | None = None


@router.get("/ai/status", response_model=AiStatusOut)
def ai_status(db: Db) -> AiStatusOut:
    p = llm.provider()
    info = p.info()
    try:
        free: int | None = manager.available_mb()
    except Exception:  # medir la memoria es informativo; nunca rompe la pantalla
        free = None
    return AiStatusOut(
        running=info.running,
        version=info.version,
        model=llm.chosen_model(db),
        light_model=llm.light_model(db),
        keep_alive=llm.keep_alive(db),  # type: ignore[arg-type]
        models=[
            LlmModelOut(
                name=name,
                installed=name in info.models,
                min_free_mb=prof.min_free_mb,
                budget_mb=prof.budget_mb,
            )
            for name, prof in manager.PROFILES.items()
        ],
        loaded=[LoadedOut(name=m.name, size_mb=m.size_mb) for m in p.loaded()]
        if info.running
        else [],
        available_mb=free,
    )


@router.put("/ai/settings", response_model=AiStatusOut)
def update_ai_settings(body: AiSettingsIn, db: Db) -> AiStatusOut:
    if body.model is not None:
        if body.model not in manager.PROFILES:
            raise bad_request("unknown_model", "Modelo no disponible")
        prefs.put(db, "llm.model", body.model)
    if body.keep_alive is not None:
        prefs.put(db, "llm.keep_alive", body.keep_alive)
    return ai_status(db)


# ------------------------------------------------------------------ apuntes y resúmenes
class DocIn(BaseModel):
    kind: DocKind
    detail: Detail = "medium"
    source_ids: Annotated[list[str], Field(min_length=1, max_length=svc.MAX_SOURCES)]
    title: Title | None = None


class DocSourceOut(BaseModel):
    id: str
    title: str
    kind: str


class DocOut(BaseModel):
    id: str
    subject_id: str
    kind: DocKind
    detail: Detail
    title: str
    status: DocStatus
    model: str | None
    error_code: str | None
    error_message: str | None
    progress: float
    message: str | None
    sources: list[DocSourceOut]
    created_at: str
    updated_at: str


class PointOut(BaseModel):
    text: str
    refs: list[int]


class SectionOut(BaseModel):
    title: str
    points: list[PointOut]


class ContradictionOut(BaseModel):
    topic: str
    claims: list[PointOut]


class CitationOut(BaseModel):
    ref: int
    text: str
    page: int | None
    start_ms: int | None
    end_ms: int | None
    source_id: str
    source_title: str
    source_kind: str
    version: int


class DocStatsOut(BaseModel):
    calls: int = 0
    proposed_cites: int = 0
    invented_cites: int = 0
    dropped_points: int = 0
    dropped_contradictions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    fallback: bool = False
    peak_loaded_mb: int = 0
    budget_mb: int = 0


class DocDetailOut(DocOut):
    sections: list[SectionOut]
    contradictions: list[ContradictionOut]
    citations: list[CitationOut]
    stats: DocStatsOut


_SELECT = """SELECT d.*, j.progress AS job_progress, j.message AS job_message,
       j.status AS job_status, j.error_code AS job_error_code, j.error_message AS job_error
FROM generated_docs d JOIN subjects s ON s.id = d.subject_id
LEFT JOIN jobs j ON j.id = d.job_id"""


def _out(db: Db, row: dict[str, Any]) -> DocOut:
    status = row["status"]
    code, message = row["error_code"], row["error_message"]
    # Un trabajo cancelado en cola o fallido fuera del manejador se refleja en el documento.
    if status in ("queued", "running") and row["job_status"] in ("cancelled", "failed"):
        status, code, message = row["job_status"], row["job_error_code"], row["job_error"]
    return DocOut(
        id=row["id"],
        subject_id=row["subject_id"],
        kind=row["kind"],
        detail=row["detail"],
        title=row["title"],
        status=status,
        model=row["model"],
        error_code=code,
        error_message=message,
        progress=float(row["job_progress"] or 0) if status in ("queued", "running") else 1.0,
        message=row["job_message"] if status in ("queued", "running") else None,
        sources=[DocSourceOut(**s) for s in svc.doc_sources(db, row["id"])],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row(db: Db, user: str, doc_id: str) -> dict[str, Any]:
    svc.get_doc(db, user, doc_id)  # 404 si no existe o no es del usuario
    row = db.execute(f"{_SELECT} WHERE d.id = ? AND s.owner_id = ?", (doc_id, user)).fetchone()
    return dict(row)


@router.post("/subjects/{subject_id}/documents", response_model=DocOut, status_code=202)
def create_document(subject_id: str, body: DocIn, db: Db, user: UserId) -> DocOut:
    subj.get_subject(db, user, subject_id)
    title = body.title
    if not title:
        first = db.execute(
            "SELECT title FROM sources WHERE id = ? AND subject_id = ?",
            (body.source_ids[0], subject_id),
        ).fetchone()
        base = "Apuntes" if body.kind == "notes" else "Resumen"
        more = f" (+{len(body.source_ids) - 1})" if len(body.source_ids) > 1 else ""
        title = f"{base} · {first['title'] if first else 'material'}{more}"[:300]
    doc_id = svc.create(
        db, subject_id, body.kind, body.detail, title, body.source_ids, llm.chosen_model(db)
    )
    return _out(db, _row(db, user, doc_id))


@router.get("/subjects/{subject_id}/documents", response_model=list[DocOut])
def list_documents(subject_id: str, db: Db, user: UserId) -> list[DocOut]:
    subj.get_subject(db, user, subject_id)
    rows = db.execute(
        f"{_SELECT} WHERE d.subject_id = ? AND s.owner_id = ? ORDER BY d.created_at DESC",
        (subject_id, user),
    ).fetchall()
    return [_out(db, dict(r)) for r in rows]


@router.get("/documents/{doc_id}", response_model=DocDetailOut)
def get_document(doc_id: str, db: Db, user: UserId) -> DocDetailOut:
    row = _row(db, user, doc_id)
    content = json.loads(row["content_json"] or "{}")
    return DocDetailOut(
        **_out(db, row).model_dump(),
        sections=content.get("sections", []),
        contradictions=content.get("contradictions", []),
        citations=[CitationOut(**c) for c in svc.citations(db, doc_id)],
        stats=DocStatsOut(
            **{
                k: v
                for k, v in json.loads(row["stats_json"] or "{}").items()
                if k in DocStatsOut.model_fields
            }
        ),
    )


@router.post("/documents/{doc_id}/retry", response_model=DocOut, status_code=202)
def retry_document(doc_id: str, db: Db, user: UserId) -> DocOut:
    out = _out(db, _row(db, user, doc_id))
    if out.status not in ("failed", "cancelled"):
        raise conflict("not_retryable", "Solo se puede reintentar si falló o se canceló")
    with tx(db):
        job = queue.enqueue(
            db, "generate_doc", "llm", None, {"doc_id": doc_id}, priority=queue.PRIORITY["batch"]
        )
        db.execute(
            "UPDATE generated_docs SET job_id = ?, status = 'queued', error_code = NULL,"
            " error_message = NULL, updated_at = now_iso() WHERE id = ?",
            (job, doc_id),
        )
    return _out(db, _row(db, user, doc_id))


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, db: Db, user: UserId) -> Response:
    doc = svc.get_doc(db, user, doc_id)
    if doc["job_id"]:
        queue.request_cancel(db, doc["job_id"])  # si está generándose, se corta
    db.execute("DELETE FROM generated_docs WHERE id = ?", (doc_id,))
    return Response(status_code=204)
