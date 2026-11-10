"""Modo concurso de la sala en vivo (Fase 9.5).

Todos ven la misma pregunta a la vez: cuenta atrás «¡Prepárate!», pregunta con su tiempo,
respuesta correcta con la clasificación unos segundos y, sola, la siguiente; al final, el podio.

- Puntos: solo por acierto, más cuanto antes (de 1000 a 500); fallar o no responder da 0.
  El tiempo se mide en el Mac al recibir la respuesta, nunca con el reloj del teléfono.
- Solo preguntas de opción múltiple y verdadero/falso: las cortas necesitan la IA y no
  encajan en un ritmo de segundos.
- La respuesta correcta no sale (ni al teléfono ni a la vista del proyector) hasta que se
  cierra la pregunta.
- El avance lo hace `tick`, que se llama en cada consulta de los teléfonos y de la app.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Literal

from app.core.errors import bad_request, conflict
from app.services import exams
from app.services import live as lv  # importación circular: solo se usa dentro de funciones

LEAD_S = 4  # «¡Prepárate!» antes de cada pregunta
REVEAL_S = 8  # respuesta correcta y clasificación antes de pasar a la siguiente
MAX_POINTS = 1000
TYPES = ("single", "true_false")
TOP = 5
Phase = Literal["lobby", "countdown", "question", "reveal", "finished"]


def objective(db: sqlite3.Connection, exam_id: str) -> list[dict[str, Any]]:
    return [q for q in exams.questions(db, exam_id) if q["type"] in TYPES]


def _ids(session: dict[str, Any]) -> list[str]:
    return list(json.loads(session.get("quiz_json") or "{}").get("questions", []))


def _ms(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() * 1000))


def phase(session: dict[str, Any], now: datetime) -> Phase:
    if session["status"] in ("finished", "closed"):
        return "finished" if session["started_at"] else "lobby"
    if session["status"] != "running" or session["quiz_index"] is None:
        return "lobby"
    if now < lv._parse(session["quiz_opens_at"]):
        return "countdown"
    if now < lv._parse(session["quiz_closes_at"]):
        return "question"
    return "reveal"


def _reload(db: sqlite3.Connection, session: dict[str, Any]) -> dict[str, Any]:
    row = db.execute("SELECT * FROM live_sessions WHERE id = ?", (session["id"],)).fetchone()
    return {**session, **dict(row)}


def _schedule(db: sqlite3.Connection, session: dict[str, Any], index: int, opens: datetime) -> None:
    closes = opens + timedelta(seconds=session["question_s"])
    db.execute(
        "UPDATE live_sessions SET quiz_index = ?, quiz_opens_at = ?, quiz_closes_at = ?"
        " WHERE id = ?",
        (index, lv._iso(opens), lv._iso(closes), session["id"]),
    )


def _advance(db: sqlite3.Connection, session: dict[str, Any], now: datetime) -> None:
    nxt = session["quiz_index"] + 1
    if nxt >= len(_ids(session)):
        db.execute(
            "UPDATE live_sessions SET status = 'finished', finished_at = ? WHERE id = ?",
            (lv._iso(now), session["id"]),
        )
    else:
        _schedule(db, session, nxt, now + timedelta(seconds=LEAD_S))


def start(db: sqlite3.Connection, session: dict[str, Any]) -> None:
    qs = objective(db, session["exam_id"])
    if not qs:
        raise conflict(
            "quiz_no_questions",
            "El concurso usa preguntas de opción múltiple o de verdadero/falso, y este examen"
            " no tiene ninguna",
        )
    now = lv._now()
    db.execute(
        "UPDATE live_sessions SET status = 'running', started_at = ?, quiz_json = ?"
        " WHERE id = ? AND status = 'lobby'",
        (lv._iso(now), json.dumps({"questions": [q["id"] for q in qs]}), session["id"]),
    )
    _schedule(db, session, 0, now + timedelta(seconds=LEAD_S))


def _current(session: dict[str, Any]) -> str | None:
    ids, i = _ids(session), session.get("quiz_index")
    return ids[i] if i is not None and 0 <= i < len(ids) else None


def _all_answered(db: sqlite3.Connection, session: dict[str, Any], now: datetime) -> bool:
    """Han respondido todos los conectados (quien perdió la conexión no hace esperar)."""
    since = lv._iso(now - timedelta(seconds=lv.ONLINE_S))
    row = db.execute(
        """SELECT COUNT(*) AS online,
                  SUM(EXISTS (SELECT 1 FROM live_quiz_answers a
                              WHERE a.participant_id = p.id AND a.question_id = ?)) AS done
           FROM live_participants p
           WHERE p.session_id = ? AND p.status = 'admitted' AND p.last_seen_at >= ?""",
        (_current(session), session["id"], since),
    ).fetchone()
    return bool(row["online"]) and (row["done"] or 0) >= row["online"]


def tick(db: sqlite3.Connection, session: dict[str, Any]) -> dict[str, Any]:
    if session["status"] != "running":
        return session
    now = lv._now()
    ph = phase(session, now)
    if ph == "question" and _all_answered(db, session, now):
        db.execute(
            "UPDATE live_sessions SET quiz_closes_at = ? WHERE id = ?",
            (lv._iso(now), session["id"]),
        )
    elif ph == "reveal" and now >= lv._parse(session["quiz_closes_at"]) + timedelta(
        seconds=REVEAL_S
    ):
        _advance(db, session, now)
    else:
        return session
    return _reload(db, session)


def skip(db: sqlite3.Connection, session: dict[str, Any]) -> None:
    """«Pasar ya»: abre la pregunta, la cierra o pasa a la siguiente sin esperar."""
    if session["status"] != "running" or not session["quiz"]:
        raise conflict("live_not_running", "El concurso no está en marcha")
    now = lv._now()
    ph = phase(session, now)
    if ph == "countdown":
        _schedule(db, session, session["quiz_index"], now)
    elif ph == "question":
        db.execute(
            "UPDATE live_sessions SET quiz_closes_at = ? WHERE id = ?",
            (lv._iso(now), session["id"]),
        )
    else:
        _advance(db, session, now)


def answer(
    db: sqlite3.Connection, session: dict[str, Any], p: dict[str, Any], qid: Any, value: Any
) -> None:
    if session["status"] != "running" or p["status"] != "admitted":
        raise conflict("live_not_running", "El concurso no está en marcha")
    now = lv._now()
    if phase(session, now) != "question" or qid != _current(session):
        raise conflict("quiz_closed", "Esta pregunta ya no admite respuestas")
    q = next(x for x in objective(db, session["exam_id"]) if x["id"] == qid)
    if q["type"] == "single":
        n = len(json.loads(q["options_json"]))
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < n:
            raise bad_request("invalid_answer", "Respuesta no válida para esta pregunta")
    elif not isinstance(value, bool):
        raise bad_request("invalid_answer", "Respuesta no válida para esta pregunta")
    correct = value == json.loads(q["answer_json"])
    elapsed = _ms(now - lv._parse(session["quiz_opens_at"]))
    window = session["question_s"] * 1000
    points = round(MAX_POINTS * (1 - min(elapsed, window) / (2 * window))) if correct else 0
    cur = db.execute(
        "INSERT OR IGNORE INTO live_quiz_answers(participant_id, question_id, choice_json,"
        " correct, points, answer_ms) VALUES (?,?,?,?,?,?)",
        (p["id"], qid, json.dumps(value), int(correct), points, elapsed),
    )
    if cur.rowcount == 0:
        raise conflict("already_answered", "Ya respondiste esta pregunta")


def leaderboard(db: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """Clasificación: más puntos; a igualdad, menos tiempo en los aciertos."""
    rows = db.execute(
        """SELECT p.id AS participant_id, p.name,
                  COALESCE(SUM(a.points), 0) AS score, COALESCE(SUM(a.correct), 0) AS correct,
                  COUNT(a.question_id) AS answered,
                  COALESCE(SUM(CASE WHEN a.correct = 1 THEN a.answer_ms END), 0) AS ms
           FROM live_participants p LEFT JOIN live_quiz_answers a ON a.participant_id = p.id
           WHERE p.session_id = ? AND p.status = 'admitted'
           GROUP BY p.id ORDER BY score DESC, ms ASC, p.joined_at""",
        (session_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        d = dict(r)
        prev = out[-1] if out else None
        tie = prev and prev["score"] == d["score"] and prev["ms"] == d["ms"]
        d["rank"] = prev["rank"] if prev and tie else i + 1
        out.append(d)
    return out


def _question(q: dict[str, Any]) -> dict[str, Any]:
    opts = json.loads(q["options_json"]) if q["type"] == "single" else ["Verdadero", "Falso"]
    return {"id": q["id"], "type": q["type"], "stem": q["stem"], "options": opts}


def _correct_index(q: dict[str, Any]) -> int:
    a = json.loads(q["answer_json"])
    return int(a) if q["type"] == "single" else (0 if a else 1)


def _index_of(q: dict[str, Any], value: Any) -> int:
    return int(value) if q["type"] == "single" else (0 if value else 1)


def _remaining(session: dict[str, Any], ph: Phase, now: datetime) -> int | None:
    if ph == "countdown":
        return _ms(lv._parse(session["quiz_opens_at"]) - now)
    if ph == "question":
        return _ms(lv._parse(session["quiz_closes_at"]) - now)
    if ph == "reveal":
        end = lv._parse(session["quiz_closes_at"]) + timedelta(seconds=REVEAL_S)
        return _ms(end - now)
    return None


def _board(rows: list[dict[str, Any]], n: int | None = None) -> list[dict[str, Any]]:
    keys = ("participant_id", "name", "score", "correct", "answered", "rank")
    return [{k: r[k] for k in keys} for r in (rows if n is None else rows[:n])]


def host_state(db: sqlite3.Connection, session: dict[str, Any]) -> dict[str, Any]:
    """Para la app del profesor (y su vista del proyector)."""
    now = lv._now()
    ph = phase(session, now)
    all_qs = exams.questions(db, session["exam_id"])
    qs = {q["id"]: q for q in all_qs if q["type"] in TYPES}
    ids = _ids(session) or list(qs)
    board = leaderboard(db, session["id"])
    out: dict[str, Any] = {
        "phase": ph,
        "index": session["quiz_index"],
        "total": len(ids),
        "skipped": len(all_qs) - len(qs),  # respuestas cortas: no entran en el concurso
        "question_s": session["question_s"],
        "remaining_ms": _remaining(session, ph, now),
        "players": len(board),
        "answered": 0,
        "question": None,
        "correct_index": None,
        "counts": None,
        "leaderboard": _board(board),
    }
    qid = _current(session) if ph in ("countdown", "question", "reveal") else None
    if qid and qid in qs:
        q = qs[qid]
        out["question"] = _question(q)
        rows = db.execute(
            "SELECT a.choice_json FROM live_quiz_answers a JOIN live_participants p"
            " ON p.id = a.participant_id WHERE a.question_id = ? AND p.session_id = ?"
            " AND p.status = 'admitted'",
            (qid, session["id"]),
        ).fetchall()
        out["answered"] = len(rows)
        if ph == "reveal":
            counts = [0] * len(out["question"]["options"])
            for r in rows:
                counts[_index_of(q, json.loads(r["choice_json"]))] += 1
            out["counts"] = counts
            out["correct_index"] = _correct_index(q)
    return out


def phone_state(
    db: sqlite3.Connection, session: dict[str, Any], p: dict[str, Any]
) -> dict[str, Any]:
    """Para el teléfono: nunca la respuesta correcta mientras la pregunta está abierta."""
    now = lv._now()
    ph = phase(session, now)
    ids = _ids(session)
    out: dict[str, Any] = {
        "phase": ph,
        "index": session["quiz_index"],
        "total": len(ids) or len(objective(db, session["exam_id"])),
        "remaining_ms": _remaining(session, ph, now),
        "question": None,
        "my_choice": None,
    }
    if p["status"] != "admitted":
        return out
    board = leaderboard(db, session["id"])
    me = next((r for r in board if r["participant_id"] == p["id"]), None)
    if me:
        out["me"] = {"score": me["score"], "rank": me["rank"], "players": len(board)}
    qid = _current(session) if ph in ("question", "reveal") else None
    if qid:
        q = next(x for x in objective(db, session["exam_id"]) if x["id"] == qid)
        out["question"] = _question(q)
        mine = db.execute(
            "SELECT choice_json, correct, points FROM live_quiz_answers"
            " WHERE participant_id = ? AND question_id = ?",
            (p["id"], qid),
        ).fetchone()
        if mine:
            out["my_choice"] = _index_of(q, json.loads(mine["choice_json"]))
        if ph == "reveal":
            out["correct_index"] = _correct_index(q)
            out["last"] = {
                "correct": bool(mine and mine["correct"]),
                "points": mine["points"] if mine else 0,
                "answered": mine is not None,
            }
    if ph in ("reveal", "finished"):
        out["top"] = _board(board, TOP)
    return out
