"""Flashcards (Fase 7): mazos generados desde las fuentes, repaso con FSRS y edición."""

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, StringConstraints

from app.api.deps import Db, Now, UserId
from app.api.routes.ai import CitationOut
from app.api.routes.exams import ExamScopeIn
from app.jobs import queue
from app.rag.scope import Scope
from app.services import flashcards as svc
from app.services import settings as prefs
from app.services import subjects as subj
from app.srs import fsrs_scheduler
from app.srs.base import RATINGS

router = APIRouter(tags=["flashcards"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
DeckStatus = Literal["queued", "running", "ready", "failed", "cancelled"]
CardStateName = Literal["new", "learning", "review", "relearning"]


class DeckIn(BaseModel):
    title: Title | None = None
    count: int = Field(20, ge=5, le=100)
    scope: ExamScopeIn = ExamScopeIn()


class DeckCountsOut(BaseModel):
    total: int
    new: int
    learning: int
    mastered: int
    suspended: int
    due: int
    next_due_at: str | None


class DeckStatsOut(BaseModel):
    proposed: int = 0
    valid: int = 0
    saved: int = 0
    rejected: dict[str, int] = {}


class DeckOut(BaseModel):
    id: str
    subject_id: str
    title: str
    scope: Scope
    status: DeckStatus
    requested: int
    model: str | None
    progress: float
    message: str | None
    error_message: str | None
    stats: DeckStatsOut
    counts: DeckCountsOut
    created_at: str


class CardOut(BaseModel):
    id: str
    deck_id: str
    front: str
    back: str
    state: CardStateName
    due_at: str
    stability: float | None
    reps: int
    lapses: int
    mastered: bool
    suspended: bool
    edited: bool
    evidence: CitationOut | None  # None: la fuente se borró


class DeckDetailOut(DeckOut):
    cards: list[CardOut]


class CardPatch(BaseModel):
    front: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
        | None
    ) = None
    back: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None
    suspended: bool | None = None


class IntervalOut(BaseModel):
    rating: Literal[1, 2, 3, 4]
    due_at: str
    seconds: int


class StudyOut(BaseModel):
    card: CardOut | None
    intervals: list[IntervalOut]  # fecha que pondría cada botón (vacío si no hay tarjeta)
    learning: int
    review: int
    new: int
    next_due_at: str | None
    new_per_day: int


class ReviewIn(BaseModel):
    rating: Literal[1, 2, 3, 4]
    duration_ms: int = Field(0, ge=0, le=3_600_000)


class StudySettingsIn(BaseModel):
    new_per_day: int = Field(ge=0, le=200)


def _job_view(db: Db, row: dict[str, Any]) -> tuple[str, str | None, float, str | None]:
    """(estado, mensaje, progreso, error) teniendo en cuenta el trabajo de generación."""
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
        if other:
            message = (
                "Esperando a que termine la transcripción"
                if other["type"] == "transcribe"
                else "Esperando a que termine otro trabajo de IA"
            )
    progress = float(job["progress"] or 0) if busy and job else (0.0 if busy else 1.0)
    return status, message, progress, error if status in ("failed", "cancelled") else None


def _deck_out(db: Db, row: dict[str, Any], counts: dict[str, Any]) -> DeckOut:
    status, message, progress, error = _job_view(db, row)
    stats = json.loads(row["stats_json"] or "{}")
    return DeckOut(
        id=row["id"],
        subject_id=row["subject_id"],
        title=row["title"],
        scope=Scope.model_validate_json(row["scope_json"]),
        status=status,  # type: ignore[arg-type]
        requested=row["requested"],
        model=row["model"],
        progress=progress,
        message=message,
        error_message=error,
        stats=DeckStatsOut(**{k: v for k, v in stats.items() if k in DeckStatsOut.model_fields}),
        counts=DeckCountsOut(**counts),
        created_at=row["created_at"],
    )


def _card_out(row: dict[str, Any], ev: dict[str, Any] | None) -> CardOut:
    return CardOut(
        id=row["id"],
        deck_id=row["deck_id"],
        front=row["front"],
        back=row["back"],
        state=row["state"],
        due_at=row["due_at"],
        stability=row["stability"],
        reps=row["reps"],
        lapses=row["lapses"],
        mastered=svc.is_mastered(row),
        suspended=bool(row["suspended"]),
        edited=bool(row["edited"]),
        evidence=CitationOut(ref=1, **ev) if ev else None,
    )


@router.post("/subjects/{subject_id}/decks", response_model=DeckOut, status_code=202)
def create_deck(subject_id: str, body: DeckIn, db: Db, user: UserId, now: Now) -> DeckOut:
    sub = subj.get_subject(db, user, subject_id)
    title = body.title or f"Tarjetas · {sub['name']}"[:300]
    scope = Scope(subject_id=subject_id, **body.scope.model_dump())
    did = svc.create_deck(db, user, subject_id, title, body.count, scope)
    return _deck_out(db, svc.get_deck(db, user, did), svc.deck_counts(db, [did], now)[did])


@router.get("/subjects/{subject_id}/decks", response_model=list[DeckOut])
def list_decks(subject_id: str, db: Db, user: UserId, now: Now) -> list[DeckOut]:
    subj.get_subject(db, user, subject_id)
    rows = [
        dict(r)
        for r in db.execute(
            "SELECT * FROM decks WHERE subject_id = ? ORDER BY created_at DESC", (subject_id,)
        )
    ]
    counts = svc.deck_counts(db, [r["id"] for r in rows], now)
    return [_deck_out(db, r, counts[r["id"]]) for r in rows]


@router.get("/decks/{deck_id}", response_model=DeckDetailOut)
def get_deck(deck_id: str, db: Db, user: UserId, now: Now) -> DeckDetailOut:
    deck = svc.get_deck(db, user, deck_id)
    cards = svc.deck_cards(db, deck_id)
    ev = svc.evidence(db, [c["id"] for c in cards])
    base = _deck_out(db, deck, svc.deck_counts(db, [deck_id], now)[deck_id])
    return DeckDetailOut(**base.model_dump(), cards=[_card_out(c, ev.get(c["id"])) for c in cards])


@router.post("/decks/{deck_id}/retry", response_model=DeckOut, status_code=202)
def retry_deck(deck_id: str, db: Db, user: UserId, now: Now) -> DeckOut:
    svc.retry(db, svc.get_deck(db, user, deck_id))
    return _deck_out(
        db, svc.get_deck(db, user, deck_id), svc.deck_counts(db, [deck_id], now)[deck_id]
    )


@router.delete("/decks/{deck_id}", status_code=204)
def delete_deck(deck_id: str, db: Db, user: UserId) -> Response:
    deck = svc.get_deck(db, user, deck_id)
    if deck["job_id"]:
        queue.request_cancel(db, deck["job_id"])
    db.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
    return Response(status_code=204)


@router.patch("/cards/{card_id}", response_model=CardOut)
def update_card(card_id: str, body: CardPatch, db: Db, user: UserId) -> CardOut:
    card = svc.get_card(db, user, card_id)
    svc.update_card(db, card, body.front, body.back, body.suspended)
    return _card_out(svc.get_card(db, user, card_id), svc.evidence(db, [card_id]).get(card_id))


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: str, db: Db, user: UserId) -> Response:
    svc.get_card(db, user, card_id)
    db.execute("DELETE FROM flashcards WHERE id = ?", (card_id,))
    return Response(status_code=204)


# ------------------------------------------------------------------ repaso
def _study(db: Db, user: str, subject_id: str | None, deck_id: str | None, now: Any) -> StudyOut:
    if deck_id:
        subject_id = svc.get_deck(db, user, deck_id)["subject_id"]
    elif subject_id:
        subj.get_subject(db, user, subject_id)
    q = svc.study_queue(db, user, subject_id, deck_id, now)
    card, intervals = None, []
    if q["card"]:
        row = q["card"]
        card = _card_out(row, svc.evidence(db, [row["id"]]).get(row["id"]))
        preview = fsrs_scheduler.default().preview(svc.state_of(row), now)
        intervals = [
            IntervalOut(
                rating=r, due_at=svc.iso(preview[r]),
                seconds=int((preview[r] - now).total_seconds()),
            )
            for r in RATINGS
        ]  # fmt: skip
    return StudyOut(
        card=card,
        intervals=intervals,
        learning=q["learning"],
        review=q["review"],
        new=q["new"],
        next_due_at=q["next_due_at"],
        new_per_day=svc.new_per_day(db),
    )


@router.get("/study", response_model=StudyOut)
def study(
    db: Db,
    user: UserId,
    now: Now,
    subject_id: Annotated[str | None, Query(max_length=64)] = None,
    deck_id: Annotated[str | None, Query(max_length=64)] = None,
) -> StudyOut:
    """Siguiente tarjeta que toca (de una asignatura, de un mazo o de todo)."""
    return _study(db, user, subject_id, deck_id, now)


@router.post("/cards/{card_id}/review", response_model=CardOut)
def review_card(card_id: str, body: ReviewIn, db: Db, user: UserId, now: Now) -> CardOut:
    card = svc.get_card(db, user, card_id)
    svc.review(db, card, body.rating, body.duration_ms, now, fsrs_scheduler.default())
    return _card_out(svc.get_card(db, user, card_id), svc.evidence(db, [card_id]).get(card_id))


@router.put("/study/settings", response_model=StudyOut)
def study_settings(body: StudySettingsIn, db: Db, user: UserId, now: Now) -> StudyOut:
    prefs.put(db, svc.NEW_PER_DAY_KEY, body.new_per_day)
    return _study(db, user, None, None, now)
