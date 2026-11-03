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


SELECT = """
SELECT j.*, x.title AS source_title FROM jobs j
LEFT JOIN sources x ON x.id = j.source_id
LEFT JOIN subjects s ON s.id = x.subject_id
WHERE (j.source_id IS NULL OR s.owner_id = ?)
"""


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
