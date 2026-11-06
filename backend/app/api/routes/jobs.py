from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import Db, UserId
from app.core.errors import not_found
from app.jobs import queue

router = APIRouter(tags=["jobs"])

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]


class JobOut(BaseModel):
    id: str
    type: str
    status: JobStatus
    progress: float
    message: str | None
    source_id: str | None
    source_title: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


# Trabajos del sistema, sin propietario (p. ej. descargar un modelo de whisper).
SYSTEM_TYPES = ("download_model",)

# Propietario de cada trabajo, deducido de lo que procesa: muchos trabajos no tienen `source_id`
# (apuntes, mazos, exámenes, correcciones, respuestas del asistente, indexado) y antes se veían
# y se podían cancelar desde cualquier usuario (ADR-009). Lo borrado queda sin dueño → oculto.
_P = "json_extract(j.payload_json, '$.{}')"
OWNER = f"""COALESCE(
  (SELECT s.owner_id FROM sources x JOIN subjects s ON s.id = x.subject_id
    WHERE x.id = COALESCE(j.source_id, {_P.format("source_id")})),
  (SELECT s.owner_id FROM generated_docs d JOIN subjects s ON s.id = d.subject_id
    WHERE d.id = {_P.format("doc_id")}),
  (SELECT s.owner_id FROM decks d JOIN subjects s ON s.id = d.subject_id
    WHERE d.id = {_P.format("deck_id")}),
  (SELECT s.owner_id FROM exams e JOIN subjects s ON s.id = e.subject_id
    WHERE e.id = {_P.format("exam_id")}),
  (SELECT s.owner_id FROM exam_attempts a JOIN exams e ON e.id = a.exam_id
    JOIN subjects s ON s.id = e.subject_id WHERE a.id = {_P.format("attempt_id")}),
  (SELECT t.owner_id FROM chat_messages m JOIN chat_threads t ON t.id = m.thread_id
    WHERE m.id = {_P.format("message_id")})
)"""  # noqa: S608 — solo constantes del módulo

SELECT = f"""
SELECT j.*, x.title AS source_title FROM jobs j
LEFT JOIN sources x ON x.id = j.source_id
WHERE ({OWNER} = ? OR j.type IN ({",".join(f"'{t}'" for t in SYSTEM_TYPES)}))
"""  # noqa: S608 — solo constantes del módulo


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    db: Db,
    user: UserId,
    active: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[JobOut]:
    """Activos (en cola o en curso) o, con active=false, los más recientes."""
    cond = "AND j.status IN ('queued', 'running')" if active else ""
    rows = db.execute(
        f"{SELECT} {cond} ORDER BY j.created_at DESC LIMIT ?", (user, limit)
    ).fetchall()
    return [JobOut(**{k: r[k] for k in JobOut.model_fields}) for r in rows]


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, db: Db, user: UserId) -> JobOut:
    row = db.execute(f"{SELECT} AND j.id = ?", (user, job_id)).fetchone()
    if row is None:
        raise not_found("Trabajo")
    queue.request_cancel(db, job_id)
    row = db.execute(f"{SELECT} AND j.id = ?", (user, job_id)).fetchone()
    return JobOut(**{k: row[k] for k in JobOut.model_fields})
