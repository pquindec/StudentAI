"""Estadísticas de estudio: tiempo, repasos, retención, racha, tarjetas, próximos repasos y
exámenes. Todo se calcula a partir de lo que ya se guarda (repasos e intentos de examen); los
días son días locales de `now`.

Tiempo de estudio = tiempo con cada tarjeta (máx. 2 min por tarjeta) + duración de los intentos
de examen entregados (máx. el tiempo límite o 3 h). No mide el tiempo leyendo apuntes.
"""

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from app.services.flashcards import is_mastered, iso, parse

MAX_ATTEMPT_MS = 3 * 3600_000
STREAK_LOOKBACK_DAYS = 366


def grade10(score: float | None, max_score: float | None) -> float | None:
    """Nota sobre 10 con un decimal (igual que la interfaz, lib/exams.ts)."""
    if score is None or not max_score:
        return None
    return round(max(0.0, score) / max_score * 100) / 10


def _local_day(ts: str, now: datetime) -> date:
    return parse(ts).astimezone(now.tzinfo).date()


def _subject_filter(col: str, subject_id: str | None) -> tuple[str, list[Any]]:
    return (f" AND {col} = ?", [subject_id]) if subject_id else ("", [])


def _attempts(
    db: sqlite3.Connection, user: str, subject_id: str | None, since: str
) -> list[dict[str, Any]]:
    extra, args = _subject_filter("e.subject_id", subject_id)
    rows = db.execute(
        f"""SELECT a.id, a.exam_id, a.status, a.started_at, a.finished_at, a.deadline_at,
                   a.score, a.max_score, e.title, e.subject_id
            FROM exam_attempts a JOIN exams e ON e.id = a.exam_id
            JOIN subjects s ON s.id = e.subject_id
            WHERE s.owner_id = ? AND a.started_at >= ?{extra}
              AND NOT EXISTS (SELECT 1 FROM live_participants p WHERE p.attempt_id = a.id)
            ORDER BY a.started_at""",  # noqa: S608
        [user, since, *args],
    ).fetchall()
    return [dict(r) for r in rows]


def _attempt_ms(a: dict[str, Any]) -> int:
    if not a["finished_at"]:
        return 0
    ms = int((parse(a["finished_at"]) - parse(a["started_at"])).total_seconds() * 1000)
    limit = MAX_ATTEMPT_MS
    if a["deadline_at"]:
        limit = int((parse(a["deadline_at"]) - parse(a["started_at"])).total_seconds() * 1000)
    return max(0, min(ms, limit))


def _reviews(
    db: sqlite3.Connection, user: str, subject_id: str | None, since: str
) -> list[dict[str, Any]]:
    extra, args = _subject_filter("r.subject_id", subject_id)
    rows = db.execute(
        f"""SELECT r.reviewed_at, r.rating, r.state_before, r.duration_ms
            FROM card_reviews r JOIN subjects s ON s.id = r.subject_id
            WHERE s.owner_id = ? AND r.reviewed_at >= ?{extra}""",  # noqa: S608
        [user, since, *args],
    ).fetchall()
    return [dict(r) for r in rows]


def streak(active: set[date], today: date) -> int:
    """Días seguidos con estudio hasta hoy (si hoy aún no se ha estudiado, cuenta hasta ayer)."""
    d = today if today in active else today - timedelta(days=1)
    n = 0
    while d in active:
        n += 1
        d -= timedelta(days=1)
    return n


def overview(
    db: sqlite3.Connection, user: str, subject_id: str | None, days: int, now: datetime
) -> dict[str, Any]:
    today = now.date()
    first = today - timedelta(days=days - 1)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    lookback = iso(now - timedelta(days=STREAK_LOOKBACK_DAYS))

    reviews = _reviews(db, user, subject_id, lookback)
    attempts = _attempts(db, user, subject_id, lookback)

    per_day: dict[date, dict[str, Any]] = {
        first + timedelta(days=i): {"study_ms": 0, "reviews": 0, "again": 0, "exams": 0}
        for i in range(days)
    }
    active: set[date] = set()
    win_reviews = win_mature = win_mature_ok = 0
    for r in reviews:
        d = _local_day(r["reviewed_at"], now)
        active.add(d)
        if d not in per_day:
            continue
        p = per_day[d]
        p["study_ms"] += r["duration_ms"]
        p["reviews"] += 1
        p["again"] += 1 if r["rating"] == 1 else 0
        win_reviews += 1
        if r["state_before"] == "review":  # retención real: solo repasos ya aprendidos
            win_mature += 1
            win_mature_ok += 1 if r["rating"] > 1 else 0

    graded: list[dict[str, Any]] = []
    for a in attempts:
        d = _local_day(a["started_at"], now)
        if a["finished_at"]:
            active.add(d)
        if d in per_day:
            per_day[d]["study_ms"] += _attempt_ms(a)
            per_day[d]["exams"] += 1 if a["finished_at"] else 0
        if a["status"] == "graded" and a["max_score"]:
            graded.append(a)

    in_window = [a for a in graded if _local_day(a["started_at"], now) >= first]
    grades = [g for a in in_window if (g := grade10(a["score"], a["max_score"])) is not None]
    recent = [
        {
            "attempt_id": a["id"],
            "exam_id": a["exam_id"],
            "title": a["title"],
            "date": a["started_at"],
            "grade": grade10(a["score"], a["max_score"]),
        }
        for a in reversed(graded[-10:])
    ]

    cards = _cards(db, user, subject_id, now)
    return {
        "days": [
            {
                "date": d.isoformat(),
                **{k: v for k, v in p.items() if k != "again"},
                "retention": None,
            }
            for d, p in sorted(per_day.items())
        ],
        "study_ms": sum(p["study_ms"] for p in per_day.values()),
        "reviews": win_reviews,
        "retention": round(win_mature_ok / win_mature, 3) if win_mature else None,
        "streak": streak(active, today),
        "active_days": sum(1 for d in per_day if d in active),
        "exams_taken": len(in_window),
        "exam_average": round(sum(grades) / len(grades), 2) if grades else None,
        "recent_exams": recent,
        "cards": cards,
        "since": iso(start),
    }


def _cards(
    db: sqlite3.Connection, user: str, subject_id: str | None, now: datetime
) -> dict[str, Any]:
    extra, args = _subject_filter("f.subject_id", subject_id)
    rows = db.execute(
        f"""SELECT f.suspended, c.state, c.stability, c.due_at
            FROM flashcards f JOIN card_states c ON c.card_id = f.id
            JOIN decks d ON d.id = f.deck_id JOIN subjects s ON s.id = f.subject_id
            WHERE s.owner_id = ? AND d.status = 'ready'{extra}""",  # noqa: S608
        [user, *args],
    ).fetchall()
    out: dict[str, Any] = {"total": 0, "new": 0, "learning": 0, "mastered": 0, "suspended": 0}
    today = now.date()
    forecast = {today + timedelta(days=i): 0 for i in range(7)}
    for r in rows:
        out["total"] += 1
        if r["suspended"]:
            out["suspended"] += 1
            continue
        if r["state"] == "new":
            out["new"] += 1
            continue
        out["mastered" if is_mastered(dict(r)) else "learning"] += 1
        d = max(_local_day(r["due_at"], now), today)  # las atrasadas tocan hoy
        if d in forecast:
            forecast[d] += 1
    out["forecast"] = [{"date": d.isoformat(), "due": n} for d, n in sorted(forecast.items())]
    out["due_today"] = forecast[today]
    return out
