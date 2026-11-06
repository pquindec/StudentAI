"""Interfaz del planificador. La lógica de repaso solo conoce esto: cambiar de algoritmo (p. ej.
SM-2) no toca servicios, API ni interfaz."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Rating = Literal[1, 2, 3, 4]  # Otra vez · Difícil · Bien · Fácil
RATINGS: tuple[Rating, ...] = (1, 2, 3, 4)
CardStateName = Literal["new", "learning", "review", "relearning"]


@dataclass(frozen=True)
class CardState:
    state: CardStateName
    due: datetime  # con zona horaria
    step: int | None = None
    stability: float | None = None  # días
    difficulty: float | None = None
    last_review: datetime | None = None
    reps: int = 0
    lapses: int = 0


class Scheduler(Protocol):
    name: str

    def review(self, card: CardState, rating: Rating, now: datetime) -> CardState:
        """Estado tras valorar la tarjeta en `now`."""
        ...

    def preview(self, card: CardState, now: datetime) -> dict[Rating, datetime]:
        """Próxima fecha según cada valoración (para mostrarla en los botones)."""
        ...
