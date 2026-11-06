"""FSRS con `py-fsrs` (MIT). Sin «fuzzing»: así la fecha que muestra cada botón es exactamente
la que se aplica y las pruebas son deterministas."""

from dataclasses import replace
from datetime import UTC, datetime

from fsrs import Card, Rating, State
from fsrs import Scheduler as Fsrs

from app.srs.base import RATINGS, CardState, CardStateName
from app.srs.base import Rating as R

_TO_FSRS = {"new": State.Learning, "learning": State.Learning, "review": State.Review,
            "relearning": State.Relearning}  # fmt: skip
_FROM_FSRS: dict[State, CardStateName] = {
    State.Learning: "learning",
    State.Review: "review",
    State.Relearning: "relearning",
}


class FsrsScheduler:
    name = "fsrs-6"

    def __init__(self, desired_retention: float = 0.9) -> None:
        self._fsrs = Fsrs(desired_retention=desired_retention, enable_fuzzing=False)

    def _card(self, s: CardState) -> Card:
        if s.state == "new":
            return Card(due=s.due.astimezone(UTC))
        return Card(
            state=_TO_FSRS[s.state],
            step=s.step,
            stability=s.stability,
            difficulty=s.difficulty,
            due=s.due.astimezone(UTC),
            last_review=s.last_review.astimezone(UTC) if s.last_review else None,
        )

    def review(self, card: CardState, rating: R, now: datetime) -> CardState:
        # py-fsrs trabaja en UTC; el resultado se devuelve igual (con zona horaria).
        new, _ = self._fsrs.review_card(self._card(card), Rating(rating), now.astimezone(UTC))
        lapse = card.state == "review" and rating == 1
        return replace(
            card,
            state=_FROM_FSRS[new.state],
            due=new.due,
            step=new.step,
            stability=new.stability,
            difficulty=new.difficulty,
            last_review=now,
            reps=card.reps + 1,
            lapses=card.lapses + (1 if lapse else 0),
        )

    def preview(self, card: CardState, now: datetime) -> dict[R, datetime]:
        return {r: self.review(card, r, now).due for r in RATINGS}


def default() -> FsrsScheduler:
    return FsrsScheduler()
