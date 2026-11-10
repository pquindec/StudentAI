"""Exámenes con preguntas escritas a mano: listos al momento, misma corrección que los generados."""

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.resources import manager
from app.services import llm
from tests.test_exams import FakeExamLLM, _source, _start, _subject

H = dict[str, str]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeExamLLM:
    f = FakeExamLLM()
    monkeypatch.setattr(llm, "provider", lambda: f)
    monkeypatch.setattr(manager, "available_mb", lambda: 10_000)
    return f


QUESTIONS: list[dict[str, Any]] = [
    {
        "type": "single",
        "stem": "¿Qué capa del modelo OSI enruta paquetes?",
        "options": ["Enlace", "Red", "Transporte"],
        "answer": 1,
        "justification": "La capa de red decide la ruta.",
    },
    {"type": "true_false", "stem": "TCP garantiza el orden de entrega.", "answer": True},
    {
        "type": "short",
        "stem": "Define latencia.",
        "answer": "El tiempo que tarda un paquete en llegar de origen a destino.",
        "rubric": ["Tiempo", "De origen a destino"],
    },
]


def _manual(client: TestClient, auth: H, sub: str, **over: Any) -> Any:
    body = {"title": "Redes · parcial", "questions": QUESTIONS, **over}
    return client.post(f"/api/v1/subjects/{sub}/exams/manual", headers=auth, json=body)


def test_manual_exam_is_ready_and_graded_like_any_other(
    client: TestClient, auth: H, fake: FakeExamLLM
) -> None:
    sub = _subject(client, auth)
    src = _source(client, auth, sub, title="Apuntes de redes")
    qs = [{**QUESTIONS[0], "source_id": src}, *QUESTIONS[1:]]
    r = _manual(client, auth, sub, questions=qs, mode="timed", time_limit_min=20, penalty=0.25)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["status"] == "ready" and e["questions"] == 3 and e["manual"] and e["editable"]
    assert e["config"]["types"] == ["single", "true_false", "short"]
    assert e["config"]["time_limit_min"] == 20 and e["model"] is None
    assert not fake.requests  # crear no usa la IA

    att = _start(client, auth, e["id"])
    assert att["deadline_at"] and all("answer" not in q for q in att["questions"])
    by_type = {q["type"]: q for q in att["questions"]}
    url = f"/api/v1/attempts/{att['id']}/answers"
    for t, value in (("single", 1), ("true_false", False), ("short", "lo que tarda en llegar")):
        r = client.put(
            f"{url}/{by_type[t]['id']}", headers=auth, json={"answer": value, "set_answer": True}
        )
        assert r.status_code == 200, r.text
    client.post(f"/api/v1/attempts/{att['id']}/submit", headers=auth)
    for _ in range(300):
        res = client.get(f"/api/v1/attempts/{att['id']}", headers=auth).json()
        if res["status"] == "graded":
            break
        time.sleep(0.02)
    pts = {a["question_id"]: a for a in res["answers"]}
    assert pts[by_type["single"]["id"]]["points"] == 1
    assert pts[by_type["true_false"]["id"]]["points"] == -0.25  # penalización
    short = pts[by_type["short"]["id"]]
    assert short["graded_by"] == "ai" and short["points"] == 1
    assert short["rubric"] == ["Tiempo", "De origen a destino"]
    # La IA corrige con la respuesta modelo y la rúbrica escritas a mano.
    grade_req = fake.requests[-1].messages[-1].content
    assert "de origen a destino" in grade_req and "- Tiempo" in grade_req
    titles = {w["source_title"] for w in res["weak_topics"]}
    assert titles == {"Apuntes de redes", "Sin fuente"}


def test_manual_exam_validation(client: TestClient, auth: H) -> None:
    sub = _subject(client, auth)
    single = QUESTIONS[0]
    bad: list[dict[str, Any]] = [
        {**single, "options": ["Solo una"]},
        {**single, "options": ["A", "a", "B"]},  # repetidas
        {**single, "answer": 3},
        {**single, "answer": True},  # un booleano no es un índice
        {**single, "options": ["A", " ", "B"]},
        {**single, "stem": "   "},
        {"type": "true_false", "stem": "x", "answer": 1},
        {"type": "short", "stem": "x", "answer": ""},
        {"type": "ensayo", "stem": "x", "answer": "y"},
    ]
    for q in bad:
        assert _manual(client, auth, sub, questions=[q]).status_code == 422, q
    assert _manual(client, auth, sub, questions=[]).status_code == 422
    assert _manual(client, auth, sub, questions=[single] * 51).status_code == 422
    assert _manual(client, auth, sub, mode="timed").status_code == 422  # sin tiempo
    assert _manual(client, auth, sub, title=" ").status_code == 422
    # Una fuente de otra asignatura no vale.
    other = _subject(client, auth, "Otra")
    src = _source(client, auth, other)
    r = _manual(client, auth, sub, questions=[{**single, "source_id": src}])
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_source"
    # V/F y cortas no guardan opciones; solo las cortas tienen rúbrica.
    r = _manual(
        client,
        auth,
        sub,
        questions=[{"type": "true_false", "stem": "x", "answer": False, "options": ["a", "b"],
                    "rubric": ["z"]}],
    )  # fmt: skip
    eid = r.json()["id"]
    q = client.get(f"/api/v1/exams/{eid}/manual", headers=auth).json()["questions"][0]
    assert q["options"] == [] and q["rubric"] == [] and q["answer"] is False


def test_edit_until_used_then_duplicate(client: TestClient, auth: H, fake: FakeExamLLM) -> None:
    sub = _subject(client, auth)
    eid = _manual(client, auth, sub).json()["id"]
    data = client.get(f"/api/v1/exams/{eid}/manual", headers=auth).json()
    assert data["editable"] and data["questions"][0]["answer"] == 1

    # Editar: título, orden y una pregunta nueva.
    new_qs = [
        data["questions"][2],
        data["questions"][0],
        {**QUESTIONS[1], "stem": "UDP es fiable."},
    ]
    body = {"title": "Redes · final", "mode": "practice", "questions": new_qs}
    r = client.put(f"/api/v1/exams/{eid}/manual", headers=auth, json=body)
    assert r.status_code == 200 and r.json()["title"] == "Redes · final"
    got = client.get(f"/api/v1/exams/{eid}/manual", headers=auth).json()["questions"]
    assert [q["stem"] for q in got] == ["Define latencia.", QUESTIONS[0]["stem"], "UDP es fiable."]

    # Con un intento ya no se edita (las notas dejarían de cuadrar); se duplica.
    _start(client, auth, eid)
    assert client.get(f"/api/v1/exams/{eid}", headers=auth).json()["editable"] is False
    r = client.put(f"/api/v1/exams/{eid}/manual", headers=auth, json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "exam_in_use"
    copy = client.post(f"/api/v1/exams/{eid}/duplicate", headers=auth).json()
    assert copy["title"] == "Redes · final (copia)" and copy["editable"] and copy["questions"] == 3
    assert copy["attempts"] == []

    # Los exámenes generados por la IA no se editan por aquí.
    _source(client, auth, sub)
    gen = client.post(
        f"/api/v1/subjects/{sub}/exams", headers=auth, json={"config": {"count": 1}}
    ).json()
    assert gen["manual"] is False and gen["editable"] is False
    for method, path in (("GET", "manual"), ("PUT", "manual"), ("POST", "duplicate")):
        r = client.request(method, f"/api/v1/exams/{gen['id']}/{path}", headers=auth, json=body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "not_manual"
