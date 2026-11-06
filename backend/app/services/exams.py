"""Exámenes: alta, generación (en un trabajo), intentos, corrección y resultados."""

import json
import math
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import bad_request, conflict, not_found
from app.db.connection import tx
from app.generation import exam as gen
from app.generation.docs import Yielded
from app.generation.grading import grade_objective
from app.jobs import queue
from app.llm.base import ChatRequest, ChatResult, LLMError
from app.pipelines.extract.document import format_time_mark
from app.rag import index as rag_index
from app.rag.scope import Scope, scope_sql
from app.services import subjects as subj

GROUP_CHARS = 1800  # material por lote: uno o dos chunks consecutivos
MIN_GROUP_CHARS = 250
STOP_AT = 1.4  # candidatas deterministas suficientes (veces las pedidas) para dejar de generar


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


# ------------------------------------------------------------------ exámenes
def get_exam(db: sqlite3.Connection, user: str, exam_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT e.* FROM exams e JOIN subjects s ON s.id = e.subject_id"
        " WHERE e.id = ? AND s.owner_id = ?",
        (exam_id, user),
    ).fetchone()
    if row is None:
        raise not_found("Examen")
    return dict(row)


def _check_scope(db: sqlite3.Connection, subject_id: str, scope: Scope) -> None:
    for table, ids, label in (
        ("sources", scope.source_ids + scope.exclude_source_ids, "fuente"),
        ("units", scope.unit_ids, "unidad"),
    ):
        wanted = set(ids)
        if not wanted:
            continue
        marks = ",".join("?" * len(wanted))
        n = db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE subject_id = ? AND id IN ({marks})",  # noqa: S608
            [subject_id, *wanted],
        ).fetchone()[0]
        if n != len(wanted):
            raise bad_request("invalid_scope", f"Alguna {label} elegida no es de esta asignatura")


def create_exam(
    db: sqlite3.Connection,
    user: str,
    subject_id: str,
    title: str,
    cfg: gen.ExamConfig,
    scope: Scope,
    consent_id: str | None = None,
) -> str:
    subj.get_subject(db, user, subject_id)
    scope = scope.model_copy(update={"subject_id": subject_id})
    _check_scope(db, subject_id, scope)
    where, params = scope_sql(scope, user, alias="s2")
    cond = where.replace("s2.source_id", "s2.id")  # la condición se aplica a la tabla sources
    sql = (
        f"SELECT COUNT(*) FROM sources s2 WHERE {cond} AND EXISTS"  # noqa: S608
        " (SELECT 1 FROM source_versions v WHERE v.source_id = s2.id)"
    )
    has_text = db.execute(
        sql,
        params,
    ).fetchone()[0]
    if not has_text:
        raise bad_request("no_sources", "No hay fuentes con texto en lo que has elegido")
    eid = str(uuid.uuid4())
    with tx(db):
        job = queue.enqueue(
            db,
            "generate_exam",
            "llm",
            None,
            {"exam_id": eid, "consent_id": consent_id},
            priority=queue.PRIORITY["batch"],
        )
        db.execute(
            "INSERT INTO exams(id, subject_id, title, config_json, scope_json, requested, job_id)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                eid,
                subject_id,
                title,
                cfg.model_dump_json(),
                scope.model_dump_json(),
                cfg.count,
                job,
            ),
        )
    return eid


def set_status(
    db: sqlite3.Connection,
    exam_id: str,
    status: str,
    code: str | None = None,
    message: str | None = None,
) -> None:
    db.execute(
        "UPDATE exams SET status = ?, error_code = ?, error_message = ?, updated_at = now_iso()"
        " WHERE id = ?",
        (status, code, message, exam_id),
    )


def retry(db: sqlite3.Connection, exam: dict[str, Any], consent_id: str | None = None) -> None:
    if exam["status"] not in ("failed", "cancelled"):
        raise conflict("not_retryable", "Solo se puede reintentar si falló o se canceló")
    with tx(db):
        job = queue.enqueue(
            db,
            "generate_exam",
            "llm",
            None,
            {"exam_id": exam["id"], "consent_id": consent_id},
            priority=queue.PRIORITY["batch"],
        )
        db.execute("DELETE FROM exam_questions WHERE exam_id = ?", (exam["id"],))
        db.execute(
            "UPDATE exams SET job_id = ?, status = 'queued', error_code = NULL,"
            " error_message = NULL, available = 0, updated_at = now_iso() WHERE id = ?",
            (job, exam["id"]),
        )


def accept_fewer(db: sqlite3.Connection, exam: dict[str, Any]) -> None:
    """«Tus fuentes permiten 14 de las 20»: el usuario acepta el examen con las disponibles."""
    if exam["status"] != "insufficient" or exam["available"] == 0:
        raise conflict("not_insufficient", "Este examen no está pendiente de confirmar")
    with tx(db):
        db.execute("UPDATE exam_questions SET kept = 1 WHERE exam_id = ?", (exam["id"],))
        db.execute(
            "UPDATE exams SET status = 'ready', updated_at = now_iso() WHERE id = ?", (exam["id"],)
        )


def questions(db: sqlite3.Connection, exam_id: str, kept_only: bool = True) -> list[dict[str, Any]]:
    kept = " AND kept = 1" if kept_only else ""
    rows = db.execute(
        f"SELECT * FROM exam_questions WHERE exam_id = ?{kept} ORDER BY position",  # noqa: S608
        (exam_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def evidence(db: sqlite3.Connection, question_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {q: [] for q in question_ids}
    if not question_ids:
        return out
    marks = ",".join("?" * len(question_ids))
    rows = db.execute(
        f"""SELECT e.question_id, e.quote, e.char_start, e.char_end, g.text, g.page,
                   g.start_ms, g.end_ms, v.source_id, v.version, s.title AS source_title,
                   s.kind AS source_kind
            FROM exam_question_evidence e
            JOIN segments g ON g.id = e.segment_id
            JOIN source_versions v ON v.id = g.version_id
            JOIN sources s ON s.id = v.source_id
            WHERE e.question_id IN ({marks})""",  # noqa: S608
        question_ids,
    ).fetchall()
    for r in rows:
        d = dict(r)
        out[d.pop("question_id")].append(d)
    return out


# ------------------------------------------------------------------ material para generar
def material(
    db: sqlite3.Connection, owner: str, scope: Scope
) -> list[tuple[str, str, list[gen.Frag]]]:
    """Grupos de chunks consecutivos del ámbito con sus segmentos (ids = ordinal)."""
    # Fuentes sin trocear todavía (índice en cola): se trocean ya (sin vectores, no hacen falta).
    pending = db.execute(
        "SELECT s.id FROM sources s JOIN subjects j ON j.id = s.subject_id"
        " WHERE j.owner_id = ? AND s.subject_id = ? AND NOT EXISTS"
        " (SELECT 1 FROM chunks c WHERE c.source_id = s.id) AND EXISTS"
        " (SELECT 1 FROM source_versions v WHERE v.source_id = s.id)",
        (owner, scope.subject_id),
    ).fetchall()
    for (sid,) in pending:
        rag_index.build_chunks(db, sid)
    where, params = scope_sql(scope, owner)
    rows = db.execute(
        f"""SELECT c.id, c.source_id, c.version_id, c.seg_from, c.seg_to, s.title
            FROM chunks c JOIN sources s ON s.id = c.source_id
            WHERE {where} ORDER BY s.imported_at, c.source_id, c.ordinal""",  # noqa: S608
        params,
    ).fetchall()
    groups: list[tuple[str, str, list[gen.Frag]]] = []
    current: list[gen.Frag] = []
    current_src: str | None = None
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current and size >= MIN_GROUP_CHARS and current_src:
            groups.append((current_src, title_of[current_src], current))
        current, size = [], 0

    title_of: dict[str, str] = {}
    for r in rows:
        title_of[r["source_id"]] = r["title"]
        if r["source_id"] != current_src or size >= GROUP_CHARS:
            flush()
            current_src = r["source_id"]
        for s in db.execute(
            "SELECT id, ordinal, text, page, start_ms FROM segments WHERE version_id = ?"
            " AND ordinal BETWEEN ? AND ? ORDER BY ordinal",
            (r["version_id"], r["seg_from"], r["seg_to"]),
        ):
            text = str(s["text"]).strip()
            if not text:
                continue
            where_ = (
                format_time_mark(int(s["start_ms"]))
                if s["start_ms"] is not None
                else (f"p. {s['page']}" if s["page"] is not None else "")
            )
            current.append(gen.Frag(str(s["ordinal"]), int(s["id"]), text, where_))
            size += len(text)
    flush()
    return groups


# ------------------------------------------------------------------ generación (trabajo)
def run_generation(
    db: sqlite3.Connection,
    exam: dict[str, Any],
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
    """Genera, valida y guarda. Devuelve las métricas. Reanudable desde `checkpoint`."""
    cfg = gen.ExamConfig.model_validate_json(exam["config_json"])
    scope = Scope.model_validate_json(exam["scope_json"])
    batches, asked = gen.plan_batches(material(db, owner, scope), cfg)
    if not batches:
        raise LLMError("no_material", "Las fuentes elegidas no tienen texto suficiente")
    rej = gen.Rejections(**checkpoint.get("rej", {}))
    cands = [gen.Question.from_json(q) for q in checkpoint.get("candidates", [])]
    done = int(checkpoint.get("batches_done", 0))
    stop_at = math.ceil(cfg.count * STOP_AT)

    def save(**extra: Any) -> None:
        save_checkpoint(
            {
                "batches_done": done,
                "candidates": [q.to_json() for q in cands],
                "rej": rej.__dict__,
                **extra,
            }
        )

    proposed = int(checkpoint.get("proposed", 0))
    while done < len(batches) and len(cands) < stop_at:
        if done and should_yield():
            save(proposed=proposed)
            raise Yielded
        b = batches[done]
        report(0.75 * done / len(batches), f"Generando preguntas ({done + 1} de {len(batches)})")
        req = ChatRequest(
            model=model,
            messages=gen.gen_messages(b, cfg),
            schema=gen.QUESTION_SCHEMA,
            max_tokens=gen.GEN_TOKENS,
            temperature=0.4,
            keep_alive=keep_alive,
        )
        data = gen.ask_json(chat, req, "exam:generate")
        raws = data.get("questions", []) if isinstance(data, dict) else []
        proposed += len(raws)
        for raw in raws:
            q = gen.check_question(raw, b, cfg, rej)
            if q is None:
                continue
            if gen.is_duplicate(q, cands, similarity):
                rej.add("duplicada", q.stem)
                continue
            cands.append(q)
        done += 1
        save(proposed=proposed)

    # Juez: lotes de JUDGE_BATCH; el avance también queda en el checkpoint.
    judged = [gen.Question.from_json(q) for q in checkpoint.get("judged", [])]
    jdone = int(checkpoint.get("judge_done", 0))
    total_j = math.ceil(len(cands) / gen.JUDGE_BATCH) or 1
    while jdone * gen.JUDGE_BATCH < len(cands):
        if should_yield():
            save(proposed=proposed, judged=[q.to_json() for q in judged], judge_done=jdone)
            raise Yielded
        report(0.75 + 0.23 * jdone / total_j, f"Revisando preguntas ({jdone + 1} de {total_j})")
        chunk = cands[jdone * gen.JUDGE_BATCH : (jdone + 1) * gen.JUDGE_BATCH]
        req = ChatRequest(
            model=model,
            messages=gen.judge_messages(chunk),
            schema=gen.JUDGE_SCHEMA,
            max_tokens=gen.JUDGE_TOKENS,
            temperature=0.0,
            keep_alive=keep_alive,
        )
        judged += gen.apply_verdicts(chunk, gen.ask_json(chat, req, "exam:judge"), rej)
        jdone += 1
        save(proposed=proposed, judged=[q.to_json() for q in judged], judge_done=jdone)

    picked, rest = gen.select(judged, cfg.count, exam["id"])
    status = "ready" if len(picked) >= cfg.count else "insufficient"
    stats = {
        "batches": len(batches),
        "batches_used": done,
        "proposed": proposed,
        "asked": asked,
        "valid": len(judged),
        "rejected": rej.counts,
        "rejected_samples": rej.samples,
    }
    save_questions(db, exam["id"], picked, rest, status, model, stats)
    return stats


def save_questions(
    db: sqlite3.Connection,
    exam_id: str,
    picked: list[gen.Question],
    rest: list[gen.Question],
    status: str,
    model: str,
    stats: dict[str, Any],
) -> None:
    with tx(db):
        if db.execute("SELECT 1 FROM exams WHERE id = ?", (exam_id,)).fetchone() is None:
            return  # se borró mientras se generaba
        db.execute("DELETE FROM exam_questions WHERE exam_id = ?", (exam_id,))
        for pos, (q, kept) in enumerate([(q, 1) for q in picked] + [(q, 0) for q in rest]):
            qid = str(uuid.uuid4())
            db.execute(
                "INSERT INTO exam_questions(id, exam_id, position, kept, type, stem, options_json,"
                " answer_json, justification, rubric_json, difficulty, source_id, judge_notes)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    qid,
                    exam_id,
                    pos,
                    kept,
                    q.type,
                    q.stem,
                    json.dumps(q.options, ensure_ascii=False),
                    json.dumps(q.answer, ensure_ascii=False),
                    q.justification,
                    json.dumps(q.rubric, ensure_ascii=False),
                    q.difficulty,
                    q.source_id,
                    q.judge_notes,
                ),
            )
            db.executemany(
                "INSERT OR IGNORE INTO exam_question_evidence(question_id, segment_id, quote,"
                " char_start, char_end) VALUES (?,?,?,?,?)",
                [(qid, e.segment_id, e.quote, e.start, e.end) for e in q.evidence],
            )
        available = len(picked) + (len(rest) if status == "insufficient" else 0)
        db.execute(
            "UPDATE exams SET status = ?, available = ?, model = ?, stats_json = ?,"
            " error_code = NULL, error_message = NULL, updated_at = now_iso() WHERE id = ?",
            (status, available, model, json.dumps(stats, ensure_ascii=False), exam_id),
        )


# ------------------------------------------------------------------ intentos
def get_attempt(db: sqlite3.Connection, user: str, attempt_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT a.*, e.config_json, e.title AS exam_title, e.subject_id FROM exam_attempts a"
        " JOIN exams e ON e.id = a.exam_id JOIN subjects s ON s.id = e.subject_id"
        " WHERE a.id = ? AND s.owner_id = ?",
        (attempt_id, user),
    ).fetchone()
    if row is None:
        raise not_found("Intento")
    return dict(row)


def start_attempt(db: sqlite3.Connection, exam: dict[str, Any]) -> str:
    if exam["status"] != "ready":
        raise conflict("exam_not_ready", "El examen aún no está listo")
    cfg = gen.ExamConfig.model_validate_json(exam["config_json"])
    aid = str(uuid.uuid4())
    now = _now()
    deadline = _iso(now + timedelta(minutes=cfg.time_limit_min)) if cfg.time_limit_min else None
    with tx(db):
        db.execute(
            "INSERT INTO exam_attempts(id, exam_id, started_at, deadline_at) VALUES (?,?,?,?)",
            (aid, exam["id"], _iso(now), deadline),
        )
        db.executemany(
            "INSERT INTO attempt_answers(attempt_id, question_id) VALUES (?,?)",
            [(aid, q["id"]) for q in questions(db, exam["id"])],
        )
    return aid


def time_over(attempt: dict[str, Any]) -> bool:
    d = attempt.get("deadline_at")
    return isinstance(d, str) and _now() >= _parse(d)


def answers(db: sqlite3.Connection, attempt_id: str) -> dict[str, dict[str, Any]]:
    rows = db.execute("SELECT * FROM attempt_answers WHERE attempt_id = ?", (attempt_id,))
    return {r["question_id"]: dict(r) for r in rows}


def _valid_answer(q: dict[str, Any], value: Any) -> bool:
    if value is None:
        return True
    if q["type"] == "single":
        n = len(json.loads(q["options_json"]))
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < n
    if q["type"] == "true_false":
        return isinstance(value, bool)
    return isinstance(value, str) and len(value) <= 4000


def save_answer(
    db: sqlite3.Connection,
    attempt: dict[str, Any],
    question_id: str,
    value: Any,
    flagged: bool | None,
    index: int | None,
    set_value: bool,
) -> None:
    if attempt["status"] != "in_progress":
        raise conflict("attempt_closed", "Este intento ya se entregó")
    if time_over(attempt):
        raise conflict("time_over", "Se acabó el tiempo: el examen se entrega con lo respondido")
    q = db.execute(
        "SELECT * FROM exam_questions WHERE id = ? AND exam_id = ? AND kept = 1",
        (question_id, attempt["exam_id"]),
    ).fetchone()
    if q is None:
        raise not_found("Pregunta")
    current = db.execute(
        "SELECT checked FROM attempt_answers WHERE attempt_id = ? AND question_id = ?",
        (attempt["id"], question_id),
    ).fetchone()
    if set_value:
        if current and current["checked"]:
            raise conflict("already_checked", "Ya comprobaste esta pregunta")
        if not _valid_answer(dict(q), value):
            raise bad_request("invalid_answer", "Respuesta no válida para esta pregunta")
    with tx(db):
        if set_value:
            db.execute(
                "UPDATE attempt_answers SET answer_json = ?"
                " WHERE attempt_id = ? AND question_id = ?",
                (
                    None if value is None else json.dumps(value, ensure_ascii=False),
                    attempt["id"],
                    question_id,
                ),
            )
        if flagged is not None:
            db.execute(
                "UPDATE attempt_answers SET flagged = ? WHERE attempt_id = ? AND question_id = ?",
                (int(flagged), attempt["id"], question_id),
            )
        if index is not None:
            db.execute(
                "UPDATE exam_attempts SET current_index = ? WHERE id = ?",
                (max(0, index), attempt["id"]),
            )


def check_answer(db: sqlite3.Connection, attempt: dict[str, Any], question_id: str) -> None:
    """Modo práctica: corrige ya una pregunta objetiva (o muestra la respuesta modelo de una
    corta, que la IA corrige al entregar) y la bloquea."""
    cfg = gen.ExamConfig.model_validate_json(attempt["config_json"])
    if cfg.mode != "practice":
        raise conflict("not_practice", "Solo se puede comprobar en modo práctica")
    if attempt["status"] != "in_progress":
        raise conflict("attempt_closed", "Este intento ya se entregó")
    q = db.execute(
        "SELECT * FROM exam_questions WHERE id = ? AND exam_id = ? AND kept = 1",
        (question_id, attempt["exam_id"]),
    ).fetchone()
    if q is None:
        raise not_found("Pregunta")
    a = answers(db, attempt["id"])[question_id]
    given = json.loads(a["answer_json"]) if a["answer_json"] is not None else None
    if given is None:
        raise bad_request("no_answer", "Responde antes de comprobar")
    ok, pts = (None, None)
    if q["type"] != "short":
        ok, pts = grade_objective(q["type"], json.loads(q["answer_json"]), given, cfg.penalty)
    db.execute(
        "UPDATE attempt_answers SET checked = 1, is_correct = ?, points = ?,"
        " graded_by = CASE WHEN ? IS NULL THEN graded_by ELSE 'auto' END"
        " WHERE attempt_id = ? AND question_id = ?",
        (None if ok is None else int(ok), pts, pts, attempt["id"], question_id),
    )


def submit(db: sqlite3.Connection, attempt: dict[str, Any]) -> None:
    """Corrige lo objetivo ya; si hay respuestas cortas, encola su corrección con la IA."""
    if attempt["status"] != "in_progress":
        return
    cfg = gen.ExamConfig.model_validate_json(attempt["config_json"])
    qs = {q["id"]: q for q in questions(db, attempt["exam_id"])}
    ans = answers(db, attempt["id"])
    pending_ai = False
    with tx(db):
        for qid, q in qs.items():
            a = ans.get(qid)
            given = json.loads(a["answer_json"]) if a and a["answer_json"] is not None else None
            if q["type"] == "short":
                if given is None or not str(given).strip():
                    db.execute(
                        "UPDATE attempt_answers SET is_correct = NULL, points = 0,"
                        " graded_by = 'auto',"
                        " feedback = NULL WHERE attempt_id = ? AND question_id = ?",
                        (attempt["id"], qid),
                    )
                else:
                    pending_ai = True
                continue
            ok, pts = grade_objective(q["type"], json.loads(q["answer_json"]), given, cfg.penalty)
            db.execute(
                "UPDATE attempt_answers SET is_correct = ?, points = ?, graded_by = 'auto'"
                " WHERE attempt_id = ? AND question_id = ?",
                (None if ok is None else int(ok), pts, attempt["id"], qid),
            )
        job = None
        if pending_ai:
            job = queue.enqueue(
                db,
                "grade_attempt",
                "llm",
                None,
                {"attempt_id": attempt["id"]},
                priority=queue.PRIORITY["interactive"],
            )
        db.execute(
            "UPDATE exam_attempts SET status = ?, finished_at = ?, job_id = ? WHERE id = ?",
            ("grading" if pending_ai else "graded", _iso(_now()), job, attempt["id"]),
        )
    if not pending_ai:
        finalize(db, attempt["id"])


def finalize(db: sqlite3.Connection, attempt_id: str) -> None:
    row = db.execute(
        "SELECT COALESCE(SUM(points), 0), COUNT(*) FROM attempt_answers WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    db.execute(
        "UPDATE exam_attempts SET status = 'graded', score = ?, max_score = ? WHERE id = ?",
        (max(0.0, float(row[0])), float(row[1]), attempt_id),
    )


def ensure_closed_if_late(db: sqlite3.Connection, attempt: dict[str, Any]) -> dict[str, Any]:
    """Si el tiempo acabó con el intento abierto, se entrega con lo respondido."""
    if attempt["status"] == "in_progress" and time_over(attempt):
        submit(db, attempt)
        return {
            **attempt,
            **dict(
                db.execute(
                    "SELECT status, finished_at, score, max_score, job_id"
                    " FROM exam_attempts WHERE id = ?",
                    (attempt["id"],),
                ).fetchone()
            ),
        }
    return attempt


def weak_topics(db: sqlite3.Connection, attempt_id: str) -> list[dict[str, Any]]:
    """Rendimiento por fuente (y sus temas vinculados): los peores primero."""
    rows = db.execute(
        """SELECT q.source_id, s.title, COUNT(*) AS n, SUM(COALESCE(a.points, 0) > 0.99) AS ok,
                  SUM(COALESCE(a.points, 0)) AS pts
           FROM attempt_answers a JOIN exam_questions q ON q.id = a.question_id
           LEFT JOIN sources s ON s.id = q.source_id
           WHERE a.attempt_id = ? GROUP BY q.source_id ORDER BY pts * 1.0 / COUNT(*)""",
        (attempt_id,),
    ).fetchall()
    out = []
    for r in rows:
        units = [
            u[0]
            for u in db.execute(
                "SELECT u.title FROM source_links l JOIN units u ON u.id = l.unit_id"
                " WHERE l.source_id = ?",
                (r["source_id"],),
            )
        ]
        out.append(
            {
                "source_id": r["source_id"],
                "source_title": r["title"] or "Fuente eliminada",
                "units": units,
                "questions": r["n"],
                "correct": r["ok"] or 0,
                "ratio": max(0.0, float(r["pts"] or 0)) / r["n"],
            }
        )
    return out
