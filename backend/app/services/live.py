"""Examen en vivo en el aula (Fase 9.5, ADR-012).

Ciclo de una sala: `lobby` (entran y esperan) → `running` (examen en marcha, mismo reloj para
todos) → `finished` (entregado; se revisan y publican notas) → `closed` (sin servidor de red).

Cada participante admitido tiene su propio intento (`exam_attempts`): se guardan y corrigen sus
respuestas con el mismo código que los exámenes normales. Las respuestas correctas nunca salen
hacia el teléfono hasta que se puedan ver los resultados.
"""

import hashlib
import json
import random
import re
import secrets
import sqlite3
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.core.errors import AppError, bad_request, conflict, not_found
from app.db.connection import tx
from app.services import exams, quiz

Mode = Literal["practice", "graded", "quiz"]
OPEN = ("lobby", "running", "finished")
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sin 0/O, 1/I/L: se pueden dictar
CODE_LEN = 8
MAX_PARTICIPANTS = 40
ONLINE_S = 10  # sin noticias del teléfono en este tiempo → «sin conexión»
POINTS = (0.0, 0.5, 1.0)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_name(raw: Any) -> str:
    """Nombre visible: sin caracteres de control ni invisibles, espacios simples, ≤ 60."""
    if not isinstance(raw, str):
        raise bad_request("invalid_name", "Escribe tu nombre")
    text = unicodedata.normalize("NFC", raw)
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C")
    text = re.sub(r"\s+", " ", text).strip()[:60].strip()
    if len(text) < 2:
        raise bad_request("invalid_name", "Escribe tu nombre (al menos 2 letras)")
    return text


# ------------------------------------------------------------------ sala (profesor)
def get(db: sqlite3.Connection, user: str, session_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT l.*, e.title AS exam_title, e.config_json FROM live_sessions l"
        " JOIN exams e ON e.id = l.exam_id WHERE l.id = ? AND l.owner_id = ?",
        (session_id, user),
    ).fetchone()
    if row is None:
        raise not_found("Sala")
    return dict(row)


def list_for(db: sqlite3.Connection, user: str, exam_id: str | None = None) -> list[dict[str, Any]]:
    args: list[Any] = [user]
    extra = ""
    if exam_id:
        extra, args = " AND l.exam_id = ?", [user, exam_id]
    rows = db.execute(
        "SELECT l.*, e.title AS exam_title, e.config_json,"  # noqa: S608 (solo marcadores ?)
        " (SELECT COUNT(*) FROM live_participants p WHERE p.session_id = l.id"
        "  AND p.status = 'admitted') AS admitted"
        " FROM live_sessions l JOIN exams e ON e.id = l.exam_id"
        f" WHERE l.owner_id = ?{extra} ORDER BY l.created_at DESC LIMIT 100",
        args,
    ).fetchall()
    return [dict(r) for r in rows]


def open_sessions(db: sqlite3.Connection) -> int:
    return int(
        db.execute(
            f"SELECT COUNT(*) FROM live_sessions WHERE status IN {OPEN}"  # noqa: S608
        ).fetchone()[0]
    )


def _new_code(db: sqlite3.Connection) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        taken = db.execute(
            f"SELECT 1 FROM live_sessions WHERE code = ? AND status IN {OPEN}",  # noqa: S608
            (code,),
        ).fetchone()
        if not taken:
            return code
    raise AppError(500, "internal_error", "No se pudo crear el código de la sala")


def create(
    db: sqlite3.Connection,
    user: str,
    exam_id: str,
    mode: Mode,
    time_limit_min: int | None,
    show_results: bool,
    question_s: int = 20,
) -> str:
    exam = exams.get_exam(db, user, exam_id)
    if exam["status"] != "ready":
        raise conflict("exam_not_ready", "El examen aún no está listo")
    if not exams.questions(db, exam_id):
        raise conflict("exam_empty", "El examen no tiene preguntas")
    is_quiz = mode == "quiz"
    if is_quiz and not quiz.objective(db, exam_id):
        raise conflict(
            "quiz_no_questions",
            "El concurso usa preguntas de opción múltiple o de verdadero/falso, y este examen"
            " no tiene ninguna",
        )
    current = db.execute(
        f"SELECT id FROM live_sessions WHERE owner_id = ? AND status IN {OPEN}",  # noqa: S608
        (user,),
    ).fetchone()
    if current:
        raise conflict(
            "live_open",
            "Ya tienes una sala abierta: ciérrala antes de abrir otra",
            session_id=current["id"],
        )
    sid = str(uuid.uuid4())
    with tx(db):
        db.execute(
            "INSERT INTO live_sessions(id, exam_id, owner_id, mode, code, time_limit_min,"
            " show_results, quiz, question_s) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                sid,
                exam_id,
                user,
                "practice" if is_quiz else mode,  # concurso: entrada directa y sin nota
                _new_code(db),
                None if is_quiz else time_limit_min,
                int(show_results),
                int(is_quiz),
                question_s if is_quiz else None,
            ),
        )
    return sid


def participants(db: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT p.id, p.name, p.device, p.status, p.attempt_id, p.left_count,
                  p.last_seen_at, p.joined_at, a.status AS attempt_status, a.score, a.max_score,
                  a.finished_at,
                  (SELECT COUNT(*) FROM attempt_answers x
                    WHERE x.attempt_id = p.attempt_id AND x.answer_json IS NOT NULL) AS answered,
                  (SELECT COUNT(*) FROM attempt_answers x
                    WHERE x.attempt_id = p.attempt_id) AS total
           FROM live_participants p LEFT JOIN exam_attempts a ON a.id = p.attempt_id
           WHERE p.session_id = ? AND p.status != 'kicked' ORDER BY p.joined_at""",
        (session_id,),
    ).fetchall()
    now = _now()
    out = []
    for r in rows:
        d = dict(r)
        seen = d["last_seen_at"]
        d["online"] = bool(seen) and (now - _parse(seen)).total_seconds() <= ONLINE_S
        out.append(d)
    return out


def _participant(db: sqlite3.Connection, session_id: str, pid: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM live_participants WHERE id = ? AND session_id = ?", (pid, session_id)
    ).fetchone()
    if row is None:
        raise not_found("Participante")
    return dict(row)


def _attempt(db: sqlite3.Connection, attempt_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT a.*, e.config_json, e.title AS exam_title, e.subject_id FROM exam_attempts a"
        " JOIN exams e ON e.id = a.exam_id WHERE a.id = ?",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise not_found("Intento")
    return dict(row)


def _order(qs: list[dict[str, Any]], rng: random.Random) -> dict[str, Any]:
    """Orden propio de preguntas y de opciones (las opciones mezcladas se traducen al guardar)."""
    ids = [q["id"] for q in qs]
    rng.shuffle(ids)
    opts: dict[str, list[int]] = {}
    for q in qs:
        if q["type"] == "single":
            perm = list(range(len(json.loads(q["options_json"]))))
            rng.shuffle(perm)
            opts[q["id"]] = perm
    return {"questions": ids, "options": opts}


def _create_attempt(db: sqlite3.Connection, session: dict[str, Any], p: dict[str, Any]) -> None:
    """Intento del participante, con la hora límite de la sala. Va dentro de una transacción."""
    if p["attempt_id"] or session.get("quiz"):
        return  # el concurso no usa intentos: sus respuestas van en live_quiz_answers
    qs = exams.questions(db, session["exam_id"])
    aid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO exam_attempts(id, exam_id, started_at, deadline_at) VALUES (?,?,?,?)",
        (aid, session["exam_id"], _iso(_now()), session["ends_at"]),
    )
    db.executemany(
        "INSERT INTO attempt_answers(attempt_id, question_id) VALUES (?,?)",
        [(aid, q["id"]) for q in qs],
    )
    order = _order(qs, random.Random(secrets.randbits(64)))  # noqa: S311 (barajar)
    db.execute(
        "UPDATE live_participants SET attempt_id = ?, order_json = ? WHERE id = ?",
        (aid, json.dumps(order), p["id"]),
    )


def admit(db: sqlite3.Connection, session: dict[str, Any], pid: str) -> None:
    if session["status"] not in ("lobby", "running"):
        raise conflict("live_closed", "La sala ya no admite participantes")
    p = _participant(db, session["id"], pid)
    if p["status"] == "kicked":
        raise conflict("kicked", "Este participante fue expulsado")
    with tx(db):
        db.execute("UPDATE live_participants SET status = 'admitted' WHERE id = ?", (pid,))
        if session["status"] == "running":
            _create_attempt(db, session, {**p, "status": "admitted"})


def kick(db: sqlite3.Connection, session: dict[str, Any], pid: str) -> None:
    """Expulsa: su intento se borra y su token deja de valer."""
    p = _participant(db, session["id"], pid)
    with tx(db):
        db.execute(
            "UPDATE live_participants SET status = 'kicked', attempt_id = NULL WHERE id = ?",
            (pid,),
        )
        if p["attempt_id"]:
            db.execute("DELETE FROM exam_attempts WHERE id = ?", (p["attempt_id"],))


def set_locked(db: sqlite3.Connection, session: dict[str, Any], locked: bool) -> None:
    db.execute("UPDATE live_sessions SET locked = ? WHERE id = ?", (int(locked), session["id"]))


def start(db: sqlite3.Connection, session: dict[str, Any]) -> None:
    if session["status"] != "lobby":
        raise conflict("live_started", "El examen ya empezó")
    admitted = [p for p in participants(db, session["id"]) if p["status"] == "admitted"]
    if not admitted:
        raise conflict("live_empty", "Aún no hay participantes admitidos")
    if session.get("quiz"):
        with tx(db):
            quiz.start(db, session)
        return
    now = _now()
    limit = session["time_limit_min"]
    ends = _iso(now + timedelta(minutes=limit)) if limit else None
    started = {**session, "status": "running", "started_at": _iso(now), "ends_at": ends}
    with tx(db):
        db.execute(
            "UPDATE live_sessions SET status = 'running', started_at = ?, ends_at = ?"
            " WHERE id = ? AND status = 'lobby'",
            (started["started_at"], ends, session["id"]),
        )
        for p in admitted:
            _create_attempt(db, started, p)


def finish(db: sqlite3.Connection, session: dict[str, Any]) -> None:
    """Termina el examen: se entrega lo respondido de quien no entregó."""
    if session["status"] == "lobby":
        raise conflict("live_not_started", "El examen aún no ha empezado")
    if session["status"] != "running":
        return
    db.execute(
        "UPDATE live_sessions SET status = 'finished', finished_at = ? WHERE id = ?",
        (_iso(_now()), session["id"]),
    )
    for p in participants(db, session["id"]):
        if p["attempt_id"] and p["attempt_status"] == "in_progress":
            exams.submit(db, _attempt(db, p["attempt_id"]))


def tick(db: sqlite3.Connection, session: dict[str, Any]) -> dict[str, Any]:
    """Si se acabó el tiempo, termina el examen. Devuelve la sala actualizada."""
    if session.get("quiz"):
        return quiz.tick(db, session)
    ends = session.get("ends_at")
    if session["status"] == "running" and isinstance(ends, str) and _now() >= _parse(ends):
        finish(db, session)
        row = db.execute("SELECT * FROM live_sessions WHERE id = ?", (session["id"],)).fetchone()
        return {**session, **dict(row)}
    return session


def publish(db: sqlite3.Connection, session: dict[str, Any]) -> None:
    if session["status"] not in ("finished", "closed"):
        raise conflict("live_not_finished", "Termina el examen antes de publicar las notas")
    db.execute("UPDATE live_sessions SET published = 1 WHERE id = ?", (session["id"],))


def close(db: sqlite3.Connection, session: dict[str, Any]) -> None:
    """Cierra la sala: nadie más puede entrar ni ver nada desde la red."""
    if session["status"] == "running":
        finish(db, session)
    db.execute("UPDATE live_sessions SET status = 'closed' WHERE id = ?", (session["id"],))


def delete(db: sqlite3.Connection, session: dict[str, Any]) -> None:
    """Borra la sala con los datos de los participantes (nombres, respuestas y notas)."""
    with tx(db):
        db.execute(
            "DELETE FROM exam_attempts WHERE id IN (SELECT attempt_id FROM live_participants"
            " WHERE session_id = ? AND attempt_id IS NOT NULL)",
            (session["id"],),
        )
        db.execute("DELETE FROM live_sessions WHERE id = ?", (session["id"],))


def adjust(
    db: sqlite3.Connection, session: dict[str, Any], pid: str, question_id: str, points: float
) -> None:
    """El profesor fija la nota de una respuesta (0, 0,5 o 1) y se recalcula el total."""
    if points not in POINTS:
        raise bad_request("invalid_points", "La nota de una pregunta es 0, 0,5 o 1")
    p = _participant(db, session["id"], pid)
    if not p["attempt_id"]:
        raise not_found("Intento")
    att = _attempt(db, p["attempt_id"])
    if att["status"] != "graded":
        raise conflict("not_graded", "Espera a que termine la corrección")
    with tx(db):
        cur = db.execute(
            "UPDATE attempt_answers SET points = ?, is_correct = ?, adjusted = 1"
            " WHERE attempt_id = ? AND question_id = ?",
            (points, int(points >= 1), att["id"], question_id),
        )
        if cur.rowcount == 0:
            raise not_found("Pregunta")
        exams.finalize(db, att["id"])


def results(db: sqlite3.Connection, session: dict[str, Any]) -> dict[str, Any]:
    """Todas las respuestas, para revisar y exportar, y la clave de respuestas con su fuente.
    Solo para la app del profesor: nunca se envía al teléfono (ver `state_for`)."""
    qs = exams.questions(db, session["exam_id"])
    rows = []
    for p in participants(db, session["id"]):
        if not p["attempt_id"]:
            continue
        ans = exams.answers(db, p["attempt_id"])
        rows.append(
            {
                **p,
                "answers": [
                    {
                        "question_id": q["id"],
                        "answer": json.loads(a["answer_json"]) if a["answer_json"] else None,
                        "points": a["points"],
                        "is_correct": None if a["is_correct"] is None else bool(a["is_correct"]),
                        "feedback": a["feedback"],
                        "graded_by": a["graded_by"],
                        "adjusted": bool(a["adjusted"]),
                    }
                    for q in qs
                    if (a := ans.get(q["id"]))
                ],
            }
        )
    ev = exams.evidence(db, [q["id"] for q in qs])
    stats = []
    for q in qs:
        pts = [
            a["points"] for r in rows for a in r["answers"]
            if a["question_id"] == q["id"] and a["points"] is not None
        ]  # fmt: skip
        stats.append(
            {
                "question_id": q["id"],
                "position": q["position"],
                "type": q["type"],
                "stem": q["stem"],
                "options": json.loads(q["options_json"]),
                "answer": json.loads(q["answer_json"]),
                "justification": q["justification"],
                "rubric": json.loads(q["rubric_json"] or "[]"),
                "evidence": ev[q["id"]],
                "answered": len(pts),
                "ratio": max(0.0, sum(pts)) / len(pts) if pts else None,
            }
        )
    return {"participants": rows, "questions": stats}


# ------------------------------------------------------------------ participantes (teléfono)
def by_code(db: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    if not re.fullmatch(f"[{CODE_ALPHABET}]{{{CODE_LEN}}}", code):
        return None
    row = db.execute(
        "SELECT l.*, e.title AS exam_title, e.config_json FROM live_sessions l"  # noqa: S608
        f" JOIN exams e ON e.id = l.exam_id WHERE l.code = ? AND l.status IN {OPEN}",
        (code,),
    ).fetchone()
    return tick(db, dict(row)) if row else None


def join(
    db: sqlite3.Connection, session: dict[str, Any], raw_name: Any, device: str
) -> tuple[dict[str, Any], str]:
    name = clean_name(raw_name)
    if session["status"] == "finished":
        raise conflict("live_finished", "El examen ya terminó")
    if session["locked"]:
        raise conflict("live_locked", "La sala está cerrada: pide al profesor que la abra")
    with tx(db):
        rows = db.execute(
            "SELECT name FROM live_participants WHERE session_id = ? AND status != 'kicked'",
            (session["id"],),
        ).fetchall()
        if len(rows) >= MAX_PARTICIPANTS:
            raise conflict("live_full", "La sala está llena")
        if any(r["name"].casefold() == name.casefold() for r in rows):
            raise conflict(
                "name_taken", "Ese nombre ya está en la sala: añade tu apellido o una inicial"
            )
        token = secrets.token_urlsafe(32)
        p = {
            "id": str(uuid.uuid4()),
            "name": name,
            "status": "admitted" if session["mode"] == "practice" else "pending",
            "attempt_id": None,
        }
        db.execute(
            "INSERT INTO live_participants(id, session_id, name, token_hash, device, status,"
            " last_seen_at) VALUES (?,?,?,?,?,?,?)",
            (p["id"], session["id"], name, hash_token(token), device[:40], p["status"],
             _iso(_now())),
        )  # fmt: skip
        if p["status"] == "admitted" and session["status"] == "running":
            _create_attempt(db, session, p)
    return p, token


def by_token(db: sqlite3.Connection, session: dict[str, Any], token: str) -> dict[str, Any] | None:
    if not token or len(token) > 100:
        return None
    row = db.execute(
        "SELECT * FROM live_participants WHERE token_hash = ? AND session_id = ?",
        (hash_token(token), session["id"]),
    ).fetchone()
    return dict(row) if row else None


def seen(db: sqlite3.Connection, session: dict[str, Any], p: dict[str, Any], left: bool) -> None:
    left_inc = int(left and session["status"] == "running" and p["attempt_id"] is not None)
    db.execute(
        "UPDATE live_participants SET last_seen_at = ?, left_count = left_count + ? WHERE id = ?",
        (_iso(_now()), left_inc, p["id"]),
    )


def _can_see_results(session: dict[str, Any]) -> bool:
    if session["mode"] == "practice":
        return bool(session["show_results"]) or bool(session["published"])
    return bool(session["published"])


def state_for(db: sqlite3.Connection, session: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    """Lo que ve el teléfono. Nunca incluye las respuestas correctas antes de poder verlas."""
    out: dict[str, Any] = {
        "session": {
            "status": session["status"],
            "mode": "quiz" if session.get("quiz") else session["mode"],
            "title": session["exam_title"],
            "ends_at": session["ends_at"],
            "server_now": _iso(_now()),
            "time_limit_min": session["time_limit_min"],
        },
        "me": {"name": p["name"], "status": p["status"]},
        "exam": None,
        "result": None,
    }
    if session.get("quiz"):
        out["quiz"] = quiz.phone_state(db, session, p)
        return out
    if p["status"] != "admitted" or not p["attempt_id"]:
        return out
    att = exams.ensure_closed_if_late(db, _attempt(db, p["attempt_id"]))
    order = json.loads(p["order_json"])
    qs = {q["id"]: q for q in exams.questions(db, session["exam_id"])}
    ans = exams.answers(db, att["id"])
    out["me"]["attempt"] = att["status"]
    if att["status"] == "in_progress":
        items = []
        for qid in order["questions"]:
            q = qs.get(qid)
            if q is None:
                continue
            given = ans[qid]["answer_json"] if qid in ans else None
            value = json.loads(given) if given is not None else None
            item: dict[str, Any] = {"id": qid, "type": q["type"], "stem": q["stem"]}
            if q["type"] == "single":
                perm = order["options"][qid]
                opts = json.loads(q["options_json"])
                item["options"] = [opts[i] for i in perm]
                value = perm.index(value) if isinstance(value, int) else None
            item["answer"] = value
            items.append(item)
        out["exam"] = {"questions": items, "deadline_at": att["deadline_at"]}
        return out
    result: dict[str, Any] = {"status": att["status"], "visible": _can_see_results(session)}
    if result["visible"] and att["status"] == "graded":
        result["score"], result["max_score"] = att["score"], att["max_score"]
        detail = []
        for qid in order["questions"]:
            q, a = qs.get(qid), ans.get(qid)
            if q is None or a is None:
                continue
            given = json.loads(a["answer_json"]) if a["answer_json"] is not None else None
            correct = json.loads(q["answer_json"])
            row: dict[str, Any] = {
                "stem": q["stem"],
                "type": q["type"],
                "points": a["points"],
                "is_correct": None if a["is_correct"] is None else bool(a["is_correct"]),
                "feedback": a["feedback"],
                "justification": q["justification"],
            }
            if q["type"] == "single":
                opts = json.loads(q["options_json"])
                row["given"] = opts[given] if isinstance(given, int) else None
                row["correct"] = opts[correct]
            elif q["type"] == "true_false":
                row["given"] = None if given is None else ("Verdadero" if given else "Falso")
                row["correct"] = "Verdadero" if correct else "Falso"
            else:
                row["given"], row["correct"] = given, correct
            detail.append(row)
        result["questions"] = detail
    out["result"] = result
    return out


def answer(
    db: sqlite3.Connection, session: dict[str, Any], p: dict[str, Any], qid: Any, value: Any
) -> None:
    if session.get("quiz"):
        quiz.answer(db, session, p, qid, value)
        return
    if session["status"] != "running" or p["status"] != "admitted" or not p["attempt_id"]:
        raise conflict("live_not_running", "El examen no está en marcha")
    if not isinstance(qid, str):
        raise bad_request("invalid_answer", "Respuesta no válida")
    order = json.loads(p["order_json"])
    if qid in order["options"] and value is not None:
        perm = order["options"][qid]
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < len(perm):
            raise bad_request("invalid_answer", "Respuesta no válida para esta pregunta")
        value = perm[value]
    att = exams.ensure_closed_if_late(db, _attempt(db, p["attempt_id"]))
    exams.save_answer(db, att, qid, value, None, None, True)


def submit(db: sqlite3.Connection, session: dict[str, Any], p: dict[str, Any]) -> None:
    if p["status"] != "admitted" or not p["attempt_id"]:
        raise conflict("live_not_running", "El examen no está en marcha")
    exams.submit(db, _attempt(db, p["attempt_id"]))
