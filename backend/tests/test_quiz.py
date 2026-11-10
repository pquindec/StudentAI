"""Modo concurso de la sala en vivo: misma pregunta para todos, cuenta atrás, puntos por acierto y
rapidez (medida en el Mac), clasificación y podio. Con un reloj controlado: sin esperas reales."""

# ruff: noqa: F811 (`exam` es un fixture importado de test_live)

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services import live, quiz
from tests.test_live import Phone, _correct, _host, _open, exam  # noqa: F401

H = dict[str, str]


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def add(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(live, "_now", c)
    return c


def _quiz(client: TestClient, auth: H, lid: str) -> dict[str, Any]:
    q: dict[str, Any] = _host(client, auth, lid)["quiz"]
    return q


def test_quiz_round_trip(
    client: TestClient,
    auth: H,
    exam: dict[str, Any],
    settings: Settings,
    clock: Clock,
) -> None:
    s = _open(client, auth, exam["id"], mode="quiz", question_s=10)
    lid = s["id"]
    assert s["mode"] == "quiz" and s["time_limit_min"] is None
    q = s["quiz"]
    assert q["phase"] == "lobby" and q["total"] == 2 and q["skipped"] == 1  # la corta no entra
    assert client.get("/api/v1/live", headers=auth).json()[0]["mode"] == "quiz"

    # Entran con el nombre o apodo que quieren mostrar; sin admisión manual.
    ana, luis, eva, tarde = Phone(s["url"]), Phone(s["url"]), Phone(s["url"]), Phone(s["url"])
    for p, name in ((ana, "Ana"), (luis, "Luisito"), (eva, "Eva")):
        assert p.join(name)[0] == 201
    assert ana.state()["me"]["status"] == "admitted"
    assert ana.state()["quiz"]["phase"] == "lobby"

    # Empieza: cuenta atrás, sin enunciado en el teléfono ni respuestas posibles.
    q = _host(client, auth, lid, "start")["quiz"]
    assert q["phase"] == "countdown" and q["index"] == 0 and q["remaining_ms"] == 4000
    first = q["question"]["id"]
    st = ana.state()["quiz"]
    assert st["phase"] == "countdown" and st["question"] is None
    assert ana.call("POST", "answer", {"question_id": first, "value": 0})[1]["error"]["code"] == (
        "quiz_closed"
    )

    # Pregunta abierta: el teléfono ve enunciado y opciones, nunca la correcta.
    clock.add(quiz.LEAD_S)
    st = ana.state()
    assert st["quiz"]["phase"] == "question" and st["quiz"]["question"]["id"] == first
    raw = json.dumps(st) + json.dumps(_quiz(client, auth, lid))
    assert "correct_index" not in json.dumps(st) and '"correct_index": null' in raw
    good = _correct(settings, first)
    qtype = st["quiz"]["question"]["type"]
    wrong: Any = (
        (not good) if qtype == "true_false" else (good + 1) % len(st["quiz"]["question"]["options"])
    )
    # Ana acierta al instante (1000), Luis a mitad de tiempo (750), Eva falla (0).
    assert ana.call("POST", "answer", {"question_id": first, "value": good})[0] == 204
    assert (
        ana.call("POST", "answer", {"question_id": first, "value": good})[1]["error"]["code"]
        == "already_answered"
    )
    clock.add(5)
    assert luis.call("POST", "answer", {"question_id": first, "value": good})[0] == 204
    assert _quiz(client, auth, lid)["answered"] == 2
    bad = luis.call("POST", "answer", {"question_id": first, "value": "x"})
    assert bad[0] == 400  # valor no válido: se rechaza antes de mirar nada más
    assert eva.call("POST", "answer", {"question_id": first, "value": "x"})[0] == 400
    assert eva.call("POST", "answer", {"question_id": first, "value": wrong})[0] == 204

    # Respondieron todos: se cierra sin esperar al final del tiempo.
    q = _quiz(client, auth, lid)
    assert q["phase"] == "reveal" and q["correct_index"] is not None and sum(q["counts"]) == 3
    board = {r["name"]: r for r in q["leaderboard"]}
    assert board["Ana"]["score"] == 1000 and board["Luisito"]["score"] == 750
    assert board["Eva"]["score"] == 0 and board["Ana"]["rank"] == 1
    st = luis.state()["quiz"]
    assert st["last"] == {"correct": True, "points": 750, "answered": True}
    assert st["me"] == {"score": 750, "rank": 2, "players": 3} and st["my_choice"] is not None
    assert [r["name"] for r in st["top"]] == ["Ana", "Luisito", "Eva"]

    # Quien llega tarde entra con 0 puntos.
    assert tarde.join("Tarde")[0] == 201

    # Tras la clasificación pasa sola a la siguiente pregunta.
    clock.add(quiz.REVEAL_S)
    q = _quiz(client, auth, lid)
    assert q["phase"] == "countdown" and q["index"] == 1 and q["counts"] is None
    second = q["question"]["id"]

    # «Pasar ya»: abre, cierra (aunque falten respuestas) y termina.
    assert _host(client, auth, lid, "quiz/next")["quiz"]["phase"] == "question"
    for p in (ana, luis, eva, tarde):
        p.state()  # siguen conectados
    good2 = _correct(settings, second)
    assert eva.call("POST", "answer", {"question_id": second, "value": good2})[0] == 204
    assert _host(client, auth, lid, "quiz/next")["quiz"]["phase"] == "reveal"
    st = ana.state()["quiz"]
    assert st["last"] == {"correct": False, "points": 0, "answered": False}
    done = _host(client, auth, lid, "quiz/next")
    assert done["status"] == "finished" and done["quiz"]["phase"] == "finished"
    final = [(r["name"], r["score"], r["rank"]) for r in done["quiz"]["leaderboard"]]
    # Empate exacto (mismos puntos y mismo tiempo): comparten puesto.
    assert final == [("Ana", 1000, 1), ("Eva", 1000, 1), ("Luisito", 750, 3), ("Tarde", 0, 4)]
    st = eva.state()["quiz"]
    assert st["phase"] == "finished" and st["me"]["rank"] == 1 and len(st["top"]) == 4
    assert eva.call("POST", "submit")[0] == 409  # en el concurso no hay entrega

    # Expulsar a alguien lo quita de la clasificación; borrar la sala borra sus respuestas.
    tid = next(p["id"] for p in done["participants"] if p["name"] == "Tarde")
    _host(client, auth, lid, f"participants/{tid}/kick")
    assert len(_quiz(client, auth, lid)["leaderboard"]) == 3
    assert client.delete(f"/api/v1/live/{lid}", headers=auth).status_code == 204
    import sqlite3

    db = sqlite3.connect(settings.db_path)
    assert db.execute("SELECT COUNT(*) FROM live_quiz_answers").fetchone()[0] == 0
    db.close()


def test_quiz_time_runs_out_and_needs_objective_questions(
    client: TestClient,
    auth: H,
    exam: dict[str, Any],
    clock: Clock,
) -> None:
    s = _open(client, auth, exam["id"], mode="quiz", question_s=5)
    lid = s["id"]
    phone = Phone(s["url"])
    phone.join("Solo")
    assert client.post(f"/api/v1/live/{lid}/quiz/next", headers=auth).status_code == 409
    _host(client, auth, lid, "start")
    clock.add(quiz.LEAD_S + 5)  # nadie responde: se acaba el tiempo
    phone.state()
    q = _quiz(client, auth, lid)
    assert q["phase"] == "reveal" and q["answered"] == 0
    qid = q["question"]["id"]
    late = phone.call("POST", "answer", {"question_id": qid, "value": 0})
    assert late[1]["error"]["code"] == "quiz_closed"
    _host(client, auth, lid, "close")

    # Un examen solo con respuestas cortas no sirve para el concurso.
    sub = exam["subject_id"]
    body = {"title": "Cortas", "questions": [{"type": "short", "stem": "x", "answer": "y"}]}
    short = client.post(f"/api/v1/subjects/{sub}/exams/manual", headers=auth, json=body).json()
    r = client.post(f"/api/v1/exams/{short['id']}/live", headers=auth, json={"mode": "quiz"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "quiz_no_questions"
    r = client.post(
        f"/api/v1/exams/{short['id']}/live", headers=auth, json={"mode": "quiz", "question_s": 2}
    )
    assert r.status_code == 422


def test_fifteen_phones_answer_at_once(
    client: TestClient,
    auth: H,
    exam: dict[str, Any],
    settings: Settings,
    clock: Clock,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    s = _open(client, auth, exam["id"], mode="quiz", question_s=20)
    phones = [Phone(s["url"]) for _ in range(15)]
    for i, p in enumerate(phones):
        assert p.join(f"Jugador {i + 1}")[0] == 201
    first = _host(client, auth, s["id"], "start")["quiz"]["question"]["id"]
    clock.add(quiz.LEAD_S)
    good = _correct(settings, first)

    def play(p: Phone) -> int:
        p.state()
        return p.call("POST", "answer", {"question_id": first, "value": good})[0]

    with ThreadPoolExecutor(max_workers=15) as pool:
        assert list(pool.map(play, phones)) == [204] * 15
    q = _quiz(client, auth, s["id"])
    assert q["phase"] == "reveal" and q["answered"] == 15 and q["players"] == 15
    assert all(r["score"] == 1000 and r["rank"] == 1 for r in q["leaderboard"])
