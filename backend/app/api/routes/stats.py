"""Estadísticas de estudio (Fase 7): tiempo, repasos, retención, tarjetas y exámenes."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import Db, Now, UserId
from app.services import stats as svc
from app.services import subjects as subj

router = APIRouter(tags=["stats"])


class DayOut(BaseModel):
    date: str  # AAAA-MM-DD (día local)
    study_ms: int
    reviews: int
    exams: int


class ForecastOut(BaseModel):
    date: str
    due: int


class CardStatsOut(BaseModel):
    total: int
    new: int
    learning: int
    mastered: int
    suspended: int
    due_today: int
    forecast: list[ForecastOut]  # repasos de los próximos 7 días (las atrasadas cuentan hoy)


class RecentExamOut(BaseModel):
    attempt_id: str
    exam_id: str
    title: str
    date: str
    grade: float | None


class StatsOut(BaseModel):
    days: list[DayOut]
    study_ms: int
    reviews: int
    retention: float | None  # aciertos en repasos de tarjetas ya aprendidas (de 0 a 1)
    streak: int
    active_days: int
    exams_taken: int
    exam_average: float | None  # sobre 10
    recent_exams: list[RecentExamOut]
    cards: CardStatsOut
    since: str


@router.get("/stats", response_model=StatsOut)
def stats(
    db: Db,
    user: UserId,
    now: Now,
    subject_id: Annotated[str | None, Query(max_length=64)] = None,
    days: Annotated[int, Query(ge=1, le=366)] = 30,
) -> StatsOut:
    if subject_id:
        subj.get_subject(db, user, subject_id)
    return StatsOut(**svc.overview(db, user, subject_id, days, now))
