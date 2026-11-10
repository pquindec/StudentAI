"""Examen en vivo en el aula: la parte del profesor (Fase 9.5, ADR-012).

Estas rutas van por la API principal (Unix socket + token), como todas. Lo único que se abre a
la red local es el servidor de la sala (`app.live.room`), con las rutas del participante.
"""

from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, field_validator

from app.api.deps import AppSettings, Db, UserId
from app.api.routes.ai import CitationOut
from app.core.errors import AppError
from app.live import lan, room
from app.services import live, quiz

router = APIRouter(tags=["live"])


LiveMode = Literal["practice", "graded", "quiz"]


class LiveIn(BaseModel):
    mode: LiveMode = "practice"
    time_limit_min: int | None = Field(None, ge=1, le=240)
    show_results: bool = True  # práctica: ver la nota al entregar
    question_s: int = Field(20, ge=5, le=120)  # concurso: segundos por pregunta


class LockIn(BaseModel):
    locked: bool


class AdjustIn(BaseModel):
    points: float


class LiveParticipantOut(BaseModel):
    id: str
    name: str
    device: str | None
    status: Literal["pending", "admitted"]
    online: bool
    answered: int
    total: int
    attempt_status: Literal["in_progress", "grading", "graded"] | None
    score: float | None
    max_score: float | None
    left_count: int
    joined_at: str
    finished_at: str | None


class QuizQuestionOut(BaseModel):
    id: str
    type: Literal["single", "true_false"]
    stem: str
    options: list[str]  # V/F: ["Verdadero", "Falso"]


class QuizRankOut(BaseModel):
    participant_id: str
    name: str
    score: int
    correct: int
    answered: int
    rank: int


class QuizOut(BaseModel):
    phase: Literal["lobby", "countdown", "question", "reveal", "finished"]
    index: int | None  # pregunta actual (desde 0)
    total: int
    skipped: int  # preguntas de respuesta corta: no entran en el concurso
    question_s: int
    remaining_ms: int | None  # hasta que se abre, se cierra o pasa a la siguiente
    players: int
    answered: int  # respuestas a la pregunta actual
    question: QuizQuestionOut | None
    correct_index: int | None  # solo con la pregunta ya cerrada
    counts: list[int] | None  # respuestas por opción, solo con la pregunta ya cerrada
    leaderboard: list[QuizRankOut]


class TunnelOut(BaseModel):
    """Acceso por internet (Cloudflare). Uno para todas las salas abiertas: el túnel lleva al
    servidor de la sala, no a una sala concreta."""

    status: Literal["off", "starting", "on", "error"]
    url: str | None  # https://….trycloudflare.com cuando está activo
    error: str | None


class LiveSessionOut(BaseModel):
    id: str
    exam_id: str
    exam_title: str
    mode: LiveMode
    status: Literal["lobby", "running", "finished", "closed"]
    code: str
    locked: bool
    show_results: bool
    published: bool
    time_limit_min: int | None
    started_at: str | None
    ends_at: str | None
    finished_at: str | None
    created_at: str
    server_now: str
    url: str | None  # enlace para los teléfonos (None si la sala está cerrada o sin red)
    qr: list[str] | None  # filas de «1»/«0»
    network_problem: str | None
    https_attempts: int  # navegadores que intentaron HTTPS (p. ej. Samsung Internet)
    tunnel: TunnelOut
    participants: list[LiveParticipantOut]
    quiz: QuizOut | None = None


class LiveSummaryOut(BaseModel):
    id: str
    exam_id: str
    exam_title: str
    mode: LiveMode
    status: Literal["lobby", "running", "finished", "closed"]
    published: bool
    admitted: int
    created_at: str


class LiveAnswerOut(BaseModel):
    question_id: str
    answer: Any
    points: float | None
    is_correct: bool | None
    feedback: str | None
    graded_by: Literal["auto", "ai"] | None
    adjusted: bool


class LiveResultRowOut(LiveParticipantOut):
    answers: list[LiveAnswerOut]


class LiveQuestionStatOut(BaseModel):
    question_id: str
    position: int
    type: Literal["single", "true_false", "short"]
    stem: str
    options: list[str]
    answer: Any
    justification: str | None
    rubric: list[str]
    evidence: list[CitationOut]  # fragmentos de las fuentes que respaldan la respuesta
    answered: int
    ratio: float | None  # puntos medios, de 0 a 1

    @field_validator("evidence", mode="before")
    @classmethod
    def _refs(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**e, "ref": e.get("ref", i + 1)} for i, e in enumerate(v)]


class LiveResultsOut(BaseModel):
    participants: list[LiveResultRowOut]
    questions: list[LiveQuestionStatOut]


def _out(db: Db, settings: AppSettings, s: dict[str, Any]) -> LiveSessionOut:
    s = live.tick(db, s)
    url = qr = problem = None
    if s["status"] != "closed":
        base = room.manager.public_base(settings.db_path)
        if base is None:
            problem = "No hay conexión Wi-Fi: conecta el Mac a la red del aula."
        else:
            url = f"{base}/s/{s['code']}/"
            qr = lan.qr_matrix(url)
    else:
        room.manager.stop_if_idle(db)
    return LiveSessionOut(
        id=s["id"],
        exam_id=s["exam_id"],
        exam_title=s["exam_title"],
        mode="quiz" if s["quiz"] else s["mode"],
        status=s["status"],
        code=s["code"],
        locked=bool(s["locked"]),
        show_results=bool(s["show_results"]),
        published=bool(s["published"]),
        time_limit_min=s["time_limit_min"],
        started_at=s["started_at"],
        ends_at=s["ends_at"],
        finished_at=s["finished_at"],
        created_at=s["created_at"],
        server_now=live._iso(live._now()),
        url=url,
        qr=qr,
        network_problem=problem,
        https_attempts=room.manager.guard.https_attempts,
        tunnel=TunnelOut.model_validate(room.manager.tunnel_state()),
        participants=[LiveParticipantOut(**p) for p in live.participants(db, s["id"])],
        quiz=QuizOut.model_validate(quiz.host_state(db, s)) if s["quiz"] else None,
    )


def _reload(db: Db, settings: AppSettings, user: str, sid: str) -> LiveSessionOut:
    return _out(db, settings, live.get(db, user, sid))


@router.post("/exams/{exam_id}/live", response_model=LiveSessionOut, status_code=201)
def create_session(
    exam_id: str, body: LiveIn, db: Db, user: UserId, settings: AppSettings
) -> LiveSessionOut:
    sid = live.create(
        db, user, exam_id, body.mode, body.time_limit_min, body.show_results, body.question_s
    )
    return _reload(db, settings, user, sid)


@router.get("/live", response_model=list[LiveSummaryOut])
def list_sessions(db: Db, user: UserId, exam_id: str | None = None) -> list[LiveSummaryOut]:
    return [
        LiveSummaryOut(**{k: r[k] for k in LiveSummaryOut.model_fields
                          if k not in ("published", "mode")},
                       published=bool(r["published"]),
                       mode="quiz" if r["quiz"] else r["mode"])
        for r in live.list_for(db, user, exam_id)
    ]  # fmt: skip


@router.get("/live/{live_id}", response_model=LiveSessionOut)
def get_session(live_id: str, db: Db, user: UserId, settings: AppSettings) -> LiveSessionOut:
    return _reload(db, settings, user, live_id)


@router.post("/live/{live_id}/participants/{participant_id}/admit", response_model=LiveSessionOut)
def admit(
    live_id: str, participant_id: str, db: Db, user: UserId, settings: AppSettings
) -> LiveSessionOut:
    live.admit(db, live.get(db, user, live_id), participant_id)
    return _reload(db, settings, user, live_id)


@router.post("/live/{live_id}/participants/{participant_id}/kick", response_model=LiveSessionOut)
def kick(
    live_id: str, participant_id: str, db: Db, user: UserId, settings: AppSettings
) -> LiveSessionOut:
    live.kick(db, live.get(db, user, live_id), participant_id)
    return _reload(db, settings, user, live_id)


@router.put("/live/{live_id}/lock", response_model=LiveSessionOut)
def lock(live_id: str, body: LockIn, db: Db, user: UserId, settings: AppSettings) -> LiveSessionOut:
    live.set_locked(db, live.get(db, user, live_id), body.locked)
    return _reload(db, settings, user, live_id)


@router.post("/live/{live_id}/start", response_model=LiveSessionOut)
def start(live_id: str, db: Db, user: UserId, settings: AppSettings) -> LiveSessionOut:
    live.start(db, live.get(db, user, live_id))
    return _reload(db, settings, user, live_id)


@router.post("/live/{live_id}/quiz/next", response_model=LiveSessionOut)
def quiz_next(live_id: str, db: Db, user: UserId, settings: AppSettings) -> LiveSessionOut:
    """Concurso: «Pasar ya» (abrir la pregunta, cerrarla o ir a la siguiente sin esperar)."""
    quiz.skip(db, live.tick(db, live.get(db, user, live_id)))
    return _reload(db, settings, user, live_id)


@router.post("/live/{live_id}/finish", response_model=LiveSessionOut)
def finish(live_id: str, db: Db, user: UserId, settings: AppSettings) -> LiveSessionOut:
    live.finish(db, live.get(db, user, live_id))
    return _reload(db, settings, user, live_id)


@router.post("/live/{live_id}/publish", response_model=LiveSessionOut)
def publish(live_id: str, db: Db, user: UserId, settings: AppSettings) -> LiveSessionOut:
    live.publish(db, live.get(db, user, live_id))
    return _reload(db, settings, user, live_id)


@router.post("/live/{live_id}/close", response_model=LiveSessionOut)
def close(live_id: str, db: Db, user: UserId, settings: AppSettings) -> LiveSessionOut:
    live.close(db, live.get(db, user, live_id))
    return _reload(db, settings, user, live_id)


@router.get("/live/{live_id}/results", response_model=LiveResultsOut)
def results(live_id: str, db: Db, user: UserId) -> LiveResultsOut:
    return LiveResultsOut.model_validate(live.results(db, live.get(db, user, live_id)))


@router.put(
    "/live/{live_id}/participants/{participant_id}/answers/{question_id}",
    response_model=LiveResultsOut,
)
def adjust(
    live_id: str, participant_id: str, question_id: str, body: AdjustIn, db: Db, user: UserId
) -> LiveResultsOut:
    s = live.get(db, user, live_id)
    live.adjust(db, s, participant_id, question_id, body.points)
    return LiveResultsOut.model_validate(live.results(db, s))


@router.post("/live/{live_id}/tunnel", response_model=LiveSessionOut)
def start_tunnel(live_id: str, db: Db, user: UserId, settings: AppSettings) -> LiveSessionOut:
    """Acceso por internet con Cloudflare. La UI pide consentimiento antes de llamar aquí."""
    s = live.get(db, user, live_id)
    if s["status"] == "closed":
        raise AppError(409, "live_closed", "La sala está cerrada.")
    room.manager.start_tunnel(settings.db_path)
    return _out(db, settings, s)


@router.delete("/live/{live_id}/tunnel", response_model=LiveSessionOut)
def stop_tunnel(live_id: str, db: Db, user: UserId, settings: AppSettings) -> LiveSessionOut:
    s = live.get(db, user, live_id)
    room.manager.stop_tunnel()
    return _out(db, settings, s)


@router.delete("/live/{live_id}", status_code=204)
def delete_session(live_id: str, db: Db, user: UserId) -> Response:
    live.delete(db, live.get(db, user, live_id))
    room.manager.stop_if_idle(db)
    return Response(status_code=204)
