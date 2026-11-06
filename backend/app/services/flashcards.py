"""Flashcards: mazos generados desde las fuentes, cola de repaso y valoraciones (FSRS).

Fechas en la BD: ISO-8601 UTC. El «día» (tarjetas nuevas de hoy, estadísticas) es el día local
de `now`, que llega de la ruta (reloj inyectable en las pruebas).
"""

import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import bad_request, conflict, not_found
from app.db.connection import tx
from app.generation import cards as gen
from app.generation.docs import Yielded
from app.generation.exam import Rejections, ask_json
from app.jobs import queue
from app.llm.base import ChatRequest, ChatResult, LLMError
from app.rag.scope import Scope, scope_sql
from app.services import exams as exams_svc
from app.services import settings as prefs
from app.services import subjects as subj
from app.srs.base import CardState, Rating, Scheduler

NEW_PER_DAY_KEY = "srs.new_per_day"
DEFAULT_NEW_PER_DAY = 20
LEARN_AHEAD = timedelta(minutes=20)  # si no queda nada, se adelantan pasos cortos de aprendizaje
MASTERED_DAYS = 21  # estabilidad a partir de la cual una tarjeta cuenta como dominada
MAX_REVIEW_MS = 120_000  # tiempo máximo que cuenta por tarjeta (si se deja la app abierta)


def iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def day_start(now: datetime) -> datetime:
    """Medianoche local del día de `now`."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def new_per_day(db: sqlite3.Connection) -> int:
    n = prefs.get(db, NEW_PER_DAY_KEY, DEFAULT_NEW_PER_DAY)
    return n if isinstance(n, int) and 0 <= n <= 200 else DEFAULT_NEW_PER_DAY


# ------------------------------------------------------------------ mazos
def get_deck(db: sqlite3.Connection, user: str, deck_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT d.* FROM decks d JOIN subjects s ON s.id = d.subject_id"
        " WHERE d.id = ? AND s.owner_id = ?",
        (deck_id, user),
    ).fetchone()
    if row is None:
        raise not_found("Mazo")
    return dict(row)


def create_deck(
    db: sqlite3.Connection,
    user: str,
    subject_id: str,
    title: str,
    count: int,
    scope: Scope,
    consent_id: str | None = None,
) -> str:
    subj.get_subject(db, user, subject_id)
    scope = scope.model_copy(update={"subject_id": subject_id})
    exams_svc._check_scope(db, subject_id, scope)
    where, params = scope_sql(scope, user, alias="s2")
    cond = where.replace("s2.source_id", "s2.id")
    has_text = db.execute(
        f"SELECT COUNT(*) FROM sources s2 WHERE {cond} AND EXISTS"  # noqa: S608
        " (SELECT 1 FROM source_versions v WHERE v.source_id = s2.id)",
        params,
    ).fetchone()[0]
    if not has_text:
        raise bad_request("no_sources", "No hay fuentes con texto en lo que has elegido")
    did = str(uuid.uuid4())
    with tx(db):
        job = queue.enqueue(
            db, "generate_deck", "llm", None, {"deck_id": did, "consent_id": consent_id},
            priority=queue.PRIORITY["batch"],
        )  # fmt: skip
        db.execute(
            "INSERT INTO decks(id, subject_id, title, scope_json, requested, job_id)"
            " VALUES (?,?,?,?,?,?)",
            (did, subject_id, title, scope.model_dump_json(), count, job),
        )
    return did


def set_status(
    db: sqlite3.Connection,
    deck_id: str,
    status: str,
    code: str | None = None,
    message: str | None = None,
) -> None:
    db.execute(
        "UPDATE decks SET status = ?, error_code = ?, error_message = ?, updated_at = now_iso()"
        " WHERE id = ?",
        (status, code, message, deck_id),
    )


def retry(db: sqlite3.Connection, deck: dict[str, Any], consent_id: str | None = None) -> None:
    if deck["status"] not in ("failed", "cancelled"):
        raise conflict("not_retryable", "Solo se puede reintentar si falló o se canceló")
    with tx(db):
        job = queue.enqueue(
            db, "generate_deck", "llm", None, {"deck_id": deck["id"], "consent_id": consent_id},
            priority=queue.PRIORITY["batch"],
        )  # fmt: skip
        db.execute(
            "UPDATE decks SET job_id = ?, status = 'queued', error_code = NULL,"
            " error_message = NULL, updated_at = now_iso() WHERE id = ?",
            (job, deck["id"]),
        )


# ------------------------------------------------------------------ generación (trabajo)
def run_generation(
    db: sqlite3.Connection,
    deck: dict[str, Any],
    chat: Callable[[ChatRequest, str], ChatResult],
    model: str,
    keep_alive: str,
    owner: str,
    report: Callable[[float, str | None], None],
    checkpoint: dict[str, Any],
    save_checkpoint: Callable[[dict[str, Any]], None],
    should_yield: Callable[[], bool],
    similarity: Callable[[str, list[str]], list[float]] | None,
) -> dict[str, Any]:
    """Genera, valida y guarda las tarjetas. Reanudable desde `checkpoint`."""
    scope = Scope.model_validate_json(deck["scope_json"])
    count = int(deck["requested"])
    batches = gen.plan_batches(exams_svc.material(db, owner, scope), count)
    if not batches:
        raise LLMError("no_material", "Las fuentes elegidas no tienen texto suficiente")
    rej = Rejections(**checkpoint.get("rej", {}))
    pending = [gen.Card.from_json(c) for c in checkpoint.get("pending", [])]
    judged = [gen.Card.from_json(c) for c in checkpoint.get("judged", [])]
    done = int(checkpoint.get("batches_done", 0))
    proposed = int(checkpoint.get("proposed", 0))

    def save() -> None:
        save_checkpoint(
            {
                "batches_done": done,
                "pending": [c.to_json() for c in pending],
                "judged": [c.to_json() for c in judged],
                "rej": rej.__dict__,
                "proposed": proposed,
            }
        )

    def judge() -> None:
        """Pasa por el revisor las candidatas pendientes (en lotes de JUDGE_BATCH)."""
        nonlocal pending
        while pending:
            chunk, rest = pending[: gen.JUDGE_BATCH], pending[gen.JUDGE_BATCH :]
            req = ChatRequest(
                model=model,
                messages=gen.judge_messages(chunk),
                schema=gen.JUDGE_SCHEMA,
                max_tokens=gen.JUDGE_TOKENS,
                temperature=0.0,
                keep_alive=keep_alive,
            )
            judged.extend(gen.apply_verdicts(chunk, ask_json(chat, req, "cards:judge"), rej))
            pending = rest
            save()

    # Generar y revisar por tandas hasta tener las pedidas (o agotar los lotes planificados).
    while done < len(batches) and len(judged) < count:
        if done and should_yield():
            save()
            raise Yielded
        b = batches[done]
        report(
            min(0.98, max(done / len(batches), len(judged) / count)),
            f"Creando tarjetas: {len(judged)} de {count} listas",
        )
        req = ChatRequest(
            model=model,
            messages=gen.gen_messages(b),
            schema=gen.CARD_SCHEMA,
            max_tokens=gen.GEN_TOKENS,
            temperature=0.4,
            keep_alive=keep_alive,
        )
        data = ask_json(chat, req, "cards:generate")
        raws = data.get("cards", []) if isinstance(data, dict) else []
        proposed += len(raws)
        for raw in raws:
            c = gen.check_card(raw, b, rej)
            if c is None:
                continue
            if gen.is_duplicate(c, judged + pending, similarity):
                rej.add("duplicada", c.front)
                continue
            pending.append(c)
        done += 1
        save()
        if (
            len(pending) >= gen.JUDGE_BATCH
            or len(judged) + len(pending) >= count
            or done == len(batches)
        ):
            judge()
    judge()

    if not judged:
        raise LLMError("no_cards", "No se pudo crear ninguna tarjeta fiable con este material")
    stats = {
        "batches": len(batches),
        "batches_used": done,
        "proposed": proposed,
        "valid": len(judged),
        "saved": min(len(judged), count),
        "rejected": rej.counts,
        "rejected_samples": rej.samples,
    }
    save_cards(db, deck["id"], judged[:count], model, stats)
    return stats


def save_cards(
    db: sqlite3.Connection, deck_id: str, cards: list[gen.Card], model: str, stats: dict[str, Any]
) -> None:
    with tx(db):
        row = db.execute("SELECT subject_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
        if row is None:
            return  # se borró mientras se generaba
        db.execute("DELETE FROM flashcards WHERE deck_id = ?", (deck_id,))
        created = iso(datetime.now(UTC))
        for pos, c in enumerate(cards):
            cid = str(uuid.uuid4())
            db.execute(
                "INSERT INTO flashcards(id, deck_id, subject_id, position, front, back, source_id,"
                " segment_id, quote, char_start, char_end) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (cid, deck_id, row[0], pos, c.front, c.back, c.source_id,
                 c.evidence.segment_id, c.evidence.quote, c.evidence.start, c.evidence.end),
            )  # fmt: skip
            db.execute("INSERT INTO card_states(card_id, due_at) VALUES (?, ?)", (cid, created))
        db.execute(
            "UPDATE decks SET status = 'ready', model = ?, stats_json = ?, error_code = NULL,"
            " error_message = NULL, updated_at = now_iso() WHERE id = ?",
            (model, json.dumps(stats, ensure_ascii=False), deck_id),
        )


# ------------------------------------------------------------------ tarjetas
_CARD_SQL = """SELECT f.*, c.state, c.step, c.stability, c.difficulty, c.due_at,
       c.last_review_at, c.reps, c.lapses
FROM flashcards f JOIN card_states c ON c.card_id = f.id
JOIN subjects s ON s.id = f.subject_id"""


def get_card(db: sqlite3.Connection, user: str, card_id: str) -> dict[str, Any]:
    row = db.execute(f"{_CARD_SQL} WHERE f.id = ? AND s.owner_id = ?", (card_id, user)).fetchone()
    if row is None:
        raise not_found("Tarjeta")
    return dict(row)


def deck_cards(db: sqlite3.Connection, deck_id: str) -> list[dict[str, Any]]:
    rows = db.execute(f"{_CARD_SQL} WHERE f.deck_id = ? ORDER BY f.position", (deck_id,))
    return [dict(r) for r in rows]


def evidence(db: sqlite3.Connection, card_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Cita literal de cada tarjeta con su localización (si la fuente sigue existiendo)."""
    if not card_ids:
        return {}
    marks = ",".join("?" * len(card_ids))
    rows = db.execute(
        f"""SELECT f.id AS card_id, f.quote AS text, g.page, g.start_ms, g.end_ms, v.source_id,
                   v.version, s.title AS source_title, s.kind AS source_kind
            FROM flashcards f
            JOIN segments g ON g.id = f.segment_id
            JOIN source_versions v ON v.id = g.version_id
            JOIN sources s ON s.id = v.source_id
            WHERE f.id IN ({marks})""",  # noqa: S608
        card_ids,
    ).fetchall()
    return {r["card_id"]: dict(r) for r in rows}


def update_card(
    db: sqlite3.Connection,
    card: dict[str, Any],
    front: str | None,
    back: str | None,
    suspended: bool | None,
) -> None:
    with tx(db):
        if front is not None or back is not None:
            db.execute(
                "UPDATE flashcards SET front = ?, back = ?, edited = 1, updated_at = now_iso()"
                " WHERE id = ?",
                (front or card["front"], back or card["back"], card["id"]),
            )
        if suspended is not None:
            db.execute(
                "UPDATE flashcards SET suspended = ?, updated_at = now_iso() WHERE id = ?",
                (1 if suspended else 0, card["id"]),
            )


def state_of(row: dict[str, Any]) -> CardState:
    return CardState(
        state=row["state"],
        due=parse(row["due_at"]),
        step=row["step"],
        stability=row["stability"],
        difficulty=row["difficulty"],
        last_review=parse(row["last_review_at"]) if row["last_review_at"] else None,
        reps=row["reps"],
        lapses=row["lapses"],
    )


def is_mastered(row: dict[str, Any]) -> bool:
    return row["state"] == "review" and (row["stability"] or 0) >= MASTERED_DAYS


# ------------------------------------------------------------------ cola de repaso
def _filter(user: str, subject_id: str | None, deck_id: str | None) -> tuple[str, list[Any]]:
    where = ["s.owner_id = ?", "f.suspended = 0", "d.status = 'ready'"]
    args: list[Any] = [user]
    if subject_id:
        where.append("f.subject_id = ?")
        args.append(subject_id)
    if deck_id:
        where.append("f.deck_id = ?")
        args.append(deck_id)
    return " AND ".join(where), args


def new_seen_today(db: sqlite3.Connection, user: str, subject_id: str | None, now: datetime) -> int:
    """Tarjetas vistas por primera vez hoy (el límite diario de nuevas es por asignatura)."""
    sql = (
        "SELECT COUNT(*) FROM card_reviews r JOIN subjects s ON s.id = r.subject_id"
        " WHERE s.owner_id = ? AND r.state_before = 'new' AND r.reviewed_at >= ?"
    )
    args: list[Any] = [user, iso(day_start(now))]
    if subject_id:
        sql += " AND r.subject_id = ?"
        args.append(subject_id)
    return int(db.execute(sql, args).fetchone()[0])


def study_queue(
    db: sqlite3.Connection,
    user: str,
    subject_id: str | None,
    deck_id: str | None,
    now: datetime,
) -> dict[str, Any]:
    """Siguiente tarjeta y cuántas quedan: primero las de aprendizaje que tocan, luego los
    repasos vencidos y por último las nuevas (hasta el límite diario)."""
    where, args = _filter(user, subject_id, deck_id)
    base = f"{_CARD_SQL} JOIN decks d ON d.id = f.deck_id WHERE {where}"
    t = iso(now)
    learning = db.execute(
        f"{base} AND c.state IN ('learning', 'relearning') AND c.due_at <= ? ORDER BY c.due_at",
        [*args, t],
    ).fetchall()
    review = db.execute(
        f"{base} AND c.state = 'review' AND c.due_at <= ? ORDER BY c.due_at", [*args, t]
    ).fetchall()
    new_left = max(0, new_per_day(db) - new_seen_today(db, user, subject_id, now))
    new = db.execute(
        f"{base} AND c.state = 'new' ORDER BY d.created_at, f.position LIMIT ?",
        [*args, new_left],
    ).fetchall()
    order = [*learning, *review, *new]
    ahead = False
    if not order:
        order = db.execute(
            f"{base} AND c.state IN ('learning', 'relearning') AND c.due_at <= ?"
            " ORDER BY c.due_at LIMIT 1",
            [*args, iso(now + LEARN_AHEAD)],
        ).fetchall()
        ahead = bool(order)
    inner = f"{base} AND c.state != 'new' AND c.due_at > ?"
    sql_next = "SELECT MIN(due_at) FROM (" + inner + ")"  # noqa: S608
    nxt = db.execute(sql_next, [*args, t]).fetchone()[0]
    return {
        "card": dict(order[0]) if order else None,
        "learning": len(learning) + (1 if ahead else 0),
        "review": len(review),
        "new": len(new),
        "next_due_at": nxt,
    }


def review(
    db: sqlite3.Connection,
    card: dict[str, Any],
    rating: Rating,
    duration_ms: int,
    now: datetime,
    scheduler: Scheduler,
) -> CardState:
    if card["suspended"]:
        raise conflict("suspended", "Esta tarjeta está suspendida")
    before = state_of(card)
    after = scheduler.review(before, rating, now)
    elapsed = (now - before.last_review).total_seconds() / 86400 if before.last_review else None
    with tx(db):
        db.execute(
            "UPDATE card_states SET state = ?, step = ?, stability = ?, difficulty = ?,"
            " due_at = ?, last_review_at = ?, reps = ?, lapses = ? WHERE card_id = ?",
            (after.state, after.step, after.stability, after.difficulty, iso(after.due),
             iso(now), after.reps, after.lapses, card["id"]),
        )  # fmt: skip
        db.execute(
            "INSERT INTO card_reviews(card_id, subject_id, rating, reviewed_at, duration_ms,"
            " state_before, elapsed_days, scheduled_days) VALUES (?,?,?,?,?,?,?,?)",
            (card["id"], card["subject_id"], rating, iso(now),
             max(0, min(duration_ms, MAX_REVIEW_MS)), before.state, elapsed,
             (after.due - now).total_seconds() / 86400),
        )  # fmt: skip
    return after


# ------------------------------------------------------------------ resumen por mazo
def deck_counts(db: sqlite3.Connection, deck_ids: list[str], now: datetime) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {
        d: {"total": 0, "new": 0, "learning": 0, "mastered": 0, "suspended": 0, "due": 0,
            "next_due_at": None}
        for d in deck_ids
    }  # fmt: skip
    if not deck_ids:
        return out
    marks = ",".join("?" * len(deck_ids))
    t = iso(now)
    rows = db.execute(
        f"""SELECT f.deck_id, f.suspended, c.state, c.stability, c.due_at
            FROM flashcards f JOIN card_states c ON c.card_id = f.id
            WHERE f.deck_id IN ({marks})""",  # noqa: S608
        deck_ids,
    ).fetchall()
    for r in rows:
        o = out[r["deck_id"]]
        o["total"] += 1
        if r["suspended"]:
            o["suspended"] += 1
            continue
        if r["state"] == "new":
            o["new"] += 1
            continue
        if is_mastered(dict(r)):
            o["mastered"] += 1
        else:
            o["learning"] += 1
        if r["due_at"] <= t:
            o["due"] += 1
        elif o["next_due_at"] is None or r["due_at"] < o["next_due_at"]:
            o["next_due_at"] = r["due_at"]
    return out
