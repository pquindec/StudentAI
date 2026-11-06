"""Exámenes (Fase 6): configuración, generación, intentos, corrección y resultados.

Durante un intento la API nunca envía la respuesta correcta ni la justificación de una pregunta
que aún no está corregida (ni comprobada en modo práctica)."""

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, StringConstraints

from app.api.deps import Db, UserId
from app.api.routes.ai import CitationOut
from app.generation.exam import ExamConfig
from app.jobs import queue
from app.rag.scope import Scope
from app.services import cloud
from app.services import exams as svc
from app.services import subjects as subj

router = APIRouter(tags=["exams"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
ExamStatus = Literal["queued", "running", "insufficient", "ready", "failed", "cancelled"]
AttemptStatus = Literal["in_progress", "grading", "graded"]
IdList = Annotated[list[str], Field(max_length=200)]


class ExamScopeIn(BaseModel):
    unit_ids: IdList = []
    source_ids: IdList = []
    exclude_source_ids: IdList = []


class ExamIn(BaseModel):
    title: Title | None = None
    config: ExamConfig
    scope: ExamScopeIn = ExamScopeIn()
    consent_id: Annotated[str, StringConstraints(max_length=64)] | None = None  # Fase 8


class ExamStatsOut(BaseModel):
    proposed: int = 0
    valid: int = 0
    rejected: dict[str, int] = {}


class AttemptSummaryOut(BaseModel):
    id: str
    status: AttemptStatus
    started_at: str
    finished_at: str | None
    score: float | None
    max_score: float | None


class ExamOut(BaseModel):
    id: str
    subject_id: str
    title: str
    config: ExamConfig
    scope: Scope
    status: ExamStatus
    requested: int
    available: int
    questions: int
    model: str | None
    progress: float
    message: str | None
    error_message: str | None
    stats: ExamStatsOut
    attempts: list[AttemptSummaryOut]
    created_at: str


class QuestionOut(BaseModel):
    id: str
    type: Literal["single", "true_false", "short"]
    stem: str
    options: list[str]
    difficulty: Literal["easy", "medium", "hard"]


class AnswerStateOut(BaseModel):
    question_id: str
    answer: Any = None
    flagged: bool
    checked: bool
    # Solo cuando la pregunta está comprobada (práctica) o el intento corregido:
    is_correct: bool | None = None
    points: float | None = None
    feedback: str | None = None
    graded_by: Literal["auto", "ai"] | None = None
    correct_answer: Any = None
    justification: str | None = None
    rubric: list[str] = []
    evidence: list[CitationOut] = []


class WeakTopicOut(BaseModel):
    source_id: str | None
    source_title: str
    units: list[str]
    questions: int
    correct: int
    ratio: float


class AttemptOut(BaseModel):
    id: str
    exam_id: str
    exam_title: str
    mode: Literal["practice", "timed"]
    penalty: float
    status: AttemptStatus
    started_at: str
    deadline_at: str | None
    finished_at: str | None
    current_index: int
    score: float | None
    max_score: float | None
    progress_message: str | None
    questions: list[QuestionOut]
    answers: list[AnswerStateOut]
    weak_topics: list[WeakTopicOut]


class AnswerIn(BaseModel):
    answer: int | bool | str | None = None
    set_answer: bool = False  # distingue «borrar la respuesta» de «solo marcar/navegar»
    flagged: bool | None = None
    index: int | None = Field(None, ge=0, le=100)


def _exam_out(db: Db, row: dict[str, Any]) -> ExamOut:
    job = (
        db.execute(
            "SELECT status, progress, message, error_message FROM jobs WHERE id = ?",
            (row["job_id"],),
        ).fetchone()
        if row["job_id"]
        else None
    )
    status, error = row["status"], row["error_message"]
    if status in ("queued", "running") and job and job["status"] in ("cancelled", "failed"):
        status, error = job["status"], job["error_message"]
    busy = status in ("queued", "running")
    message = job["message"] if busy and job else None
    if status == "queued" and not message:
        other = db.execute(
            "SELECT type FROM jobs WHERE status = 'running' AND resource_class IN ('stt', 'llm')"
            " AND id IS NOT ? LIMIT 1",
            (row["job_id"],),
        ).fetchone()
        if other and other["type"] == "transcribe":
            message = "Esperando a que termine la transcripción"
        elif other:
            message = "Esperando a que termine otro trabajo de IA"
    stats = json.loads(row["stats_json"] or "{}")
    attempts = db.execute(
        "SELECT id, status, started_at, finished_at, score, max_score FROM exam_attempts"
        " WHERE exam_id = ? ORDER BY started_at DESC",
        (row["id"],),
    ).fetchall()
    n = db.execute(
        "SELECT COUNT(*) FROM exam_questions WHERE exam_id = ? AND kept = 1", (row["id"],)
    ).fetchone()[0]
    return ExamOut(
        id=row["id"],
        subject_id=row["subject_id"],
        title=row["title"],
        config=ExamConfig.model_validate_json(row["config_json"]),
        scope=Scope.model_validate_json(row["scope_json"]),
        status=status,
        requested=row["requested"],
        available=row["available"],
        questions=n if status == "ready" else 0,
        model=row["model"],
        progress=float(job["progress"] or 0) if busy and job else (0.0 if busy else 1.0),
        message=message,
        error_message=error if status in ("failed", "cancelled") else None,
        stats=ExamStatsOut(**{k: v for k, v in stats.items() if k in ExamStatsOut.model_fields}),
        attempts=[AttemptSummaryOut(**dict(a)) for a in attempts],
        created_at=row["created_at"],
    )


@router.post("/subjects/{subject_id}/exams", response_model=ExamOut, status_code=202)
def create_exam(subject_id: str, body: ExamIn, db: Db, user: UserId) -> ExamOut:
    sub = subj.get_subject(db, user, subject_id)
    title = body.title or f"Examen · {sub['name']}"[:300]
    scope = Scope(subject_id=subject_id, **body.scope.model_dump())
    eid = svc.create_exam(db, user, subject_id, title, body.config, scope, body.consent_id)
    return _exam_out(db, svc.get_exam(db, user, eid))


@router.get("/subjects/{subject_id}/exams", response_model=list[ExamOut])
def list_exams(subject_id: str, db: Db, user: UserId) -> list[ExamOut]:
    subj.get_subject(db, user, subject_id)
    rows = db.execute(
        "SELECT * FROM exams WHERE subject_id = ? ORDER BY created_at DESC", (subject_id,)
    ).fetchall()
    return [_exam_out(db, dict(r)) for r in rows]


@router.get("/exams/{exam_id}", response_model=ExamOut)
def get_exam(exam_id: str, db: Db, user: UserId) -> ExamOut:
    return _exam_out(db, svc.get_exam(db, user, exam_id))


@router.post("/exams/{exam_id}/accept", response_model=ExamOut)
def accept_fewer(exam_id: str, db: Db, user: UserId) -> ExamOut:
    svc.accept_fewer(db, svc.get_exam(db, user, exam_id))
    return _exam_out(db, svc.get_exam(db, user, exam_id))


@router.post("/exams/{exam_id}/retry", response_model=ExamOut, status_code=202)
def retry_exam(exam_id: str, db: Db, user: UserId) -> ExamOut:
    svc.retry(db, svc.get_exam(db, user, exam_id), cloud.session_consent(db, user, "exam"))
    return _exam_out(db, svc.get_exam(db, user, exam_id))


@router.delete("/exams/{exam_id}", status_code=204)
def delete_exam(exam_id: str, db: Db, user: UserId) -> Response:
    exam = svc.get_exam(db, user, exam_id)
    if exam["job_id"]:
        queue.request_cancel(db, exam["job_id"])
    db.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
    return Response(status_code=204)


# ------------------------------------------------------------------ intentos
def _attempt_out(db: Db, att: dict[str, Any]) -> AttemptOut:
    cfg = ExamConfig.model_validate_json(att["config_json"])
    qs = svc.questions(db, att["exam_id"])
    ans = svc.answers(db, att["id"])
    graded = att["status"] == "graded"
    ev = svc.evidence(db, [q["id"] for q in qs])
    states = []
    for q in qs:
        a = ans.get(q["id"], {})
        reveal = graded or bool(a.get("checked"))
        state = AnswerStateOut(
            question_id=q["id"],
            answer=json.loads(a["answer_json"]) if a.get("answer_json") is not None else None,
            flagged=bool(a.get("flagged")),
            checked=bool(a.get("checked")),
        )
        if reveal:
            state.is_correct = None if a.get("is_correct") is None else bool(a["is_correct"])
            state.points = a.get("points")
            state.feedback = a.get("feedback")
            state.graded_by = a.get("graded_by")
            state.correct_answer = json.loads(q["answer_json"])
            state.justification = q["justification"]
            state.rubric = json.loads(q["rubric_json"] or "[]")
            state.evidence = [
                CitationOut(ref=i + 1, **{k: e[k] for k in CitationOut.model_fields if k != "ref"})
                for i, e in enumerate(ev[q["id"]])
            ]
        states.append(state)
    progress = None
    if att["status"] == "grading" and att["job_id"]:
        job = db.execute("SELECT message FROM jobs WHERE id = ?", (att["job_id"],)).fetchone()
        progress = job["message"] if job else None
    return AttemptOut(
        id=att["id"],
        exam_id=att["exam_id"],
        exam_title=att["exam_title"],
        mode=cfg.mode,
        penalty=cfg.penalty,
        status=att["status"],
        started_at=att["started_at"],
        deadline_at=att["deadline_at"],
        finished_at=att["finished_at"],
        current_index=att["current_index"],
        score=att["score"],
        max_score=att["max_score"],
        progress_message=progress,
        questions=[
            QuestionOut(
                id=q["id"],
                type=q["type"],
                stem=q["stem"],
                options=json.loads(q["options_json"]),
                difficulty=q["difficulty"],
            )
            for q in qs
        ],
        answers=states,
        weak_topics=[WeakTopicOut(**w) for w in svc.weak_topics(db, att["id"])] if graded else [],
    )


def _attempt(db: Db, user: str, attempt_id: str) -> dict[str, Any]:
    return svc.ensure_closed_if_late(db, svc.get_attempt(db, user, attempt_id))


@router.post("/exams/{exam_id}/attempts", response_model=AttemptOut, status_code=201)
def start_attempt(exam_id: str, db: Db, user: UserId) -> AttemptOut:
    aid = svc.start_attempt(db, svc.get_exam(db, user, exam_id))
    return _attempt_out(db, svc.get_attempt(db, user, aid))


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(attempt_id: str, db: Db, user: UserId) -> AttemptOut:
    return _attempt_out(db, _attempt(db, user, attempt_id))


@router.put("/attempts/{attempt_id}/answers/{question_id}", response_model=AnswerStateOut)
def save_answer(
    attempt_id: str, question_id: str, body: AnswerIn, db: Db, user: UserId
) -> AnswerStateOut:
    att = _attempt(db, user, attempt_id)
    svc.save_answer(db, att, question_id, body.answer, body.flagged, body.index, body.set_answer)
    out = _attempt_out(db, att)
    return next(a for a in out.answers if a.question_id == question_id)


@router.post("/attempts/{attempt_id}/answers/{question_id}/check", response_model=AnswerStateOut)
def check_answer(attempt_id: str, question_id: str, db: Db, user: UserId) -> AnswerStateOut:
    att = _attempt(db, user, attempt_id)
    svc.check_answer(db, att, question_id)
    out = _attempt_out(db, att)
    return next(a for a in out.answers if a.question_id == question_id)


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptOut)
def submit(attempt_id: str, db: Db, user: UserId) -> AttemptOut:
    att = _attempt(db, user, attempt_id)
    svc.submit(db, att)
    return _attempt_out(db, svc.get_attempt(db, user, attempt_id))


@router.delete("/attempts/{attempt_id}", status_code=204)
def delete_attempt(attempt_id: str, db: Db, user: UserId) -> Response:
    att = svc.get_attempt(db, user, attempt_id)
    if att["job_id"]:
        queue.request_cancel(db, att["job_id"])
    db.execute("DELETE FROM exam_attempts WHERE id = ?", (attempt_id,))
    return Response(status_code=204)
