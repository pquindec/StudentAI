"""Examen en vivo en el aula (Fase 9.5): sala del profesor por la API y teléfonos por la red.

Los «teléfonos» hablan HTTP con el servidor real de la sala (en 127.0.0.1 en las pruebas).
"""

# ruff: noqa: S310 (solo se abre http://127.0.0.1)

import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.live import room
from app.resources import manager
from app.services import live, llm
from tests.test_exams import FakeExamLLM, _exam, _source

H = dict[str, str]
ANDROID = (
    "Mozilla/5.0 (Linux; Android 16; Pixel 9) AppleWebKit/537.36 Chrome/142.0 Mobile Safari/537.36"
)


class Phone:
    def __init__(self, url: str, ua: str = ANDROID) -> None:
        self.url, self.ua, self.token = url, ua, ""

    def call(self, method: str, action: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        headers = {"User-Agent": self.ua, "Content-Type": "application/json"}
        if self.token:
            headers["X-Live-Token"] = self.token
        req = urllib.request.Request(self.url + action, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode()

    def join(self, name: str) -> tuple[int, Any]:
        status, body = self.call("POST", "join", {"name": name})
        if status == 201:
            self.token = body["token"]
        return status, body

    def state(self) -> dict[str, Any]:
        status, body = self.call("GET", "state")
        assert status == 200, body
        return dict(body)


@pytest.fixture
def exam(client: TestClient, auth: H, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(manager, "available_mb", lambda: 10_000)
    fake = FakeExamLLM()
    monkeypatch.setattr(llm, "provider", lambda: fake)
    sid = client.post("/api/v1/subjects", headers=auth, json={"name": "Redes"}).json()["id"]
    _source(client, auth, sid)
    e = _exam(client, auth, sid, count=3, types=["single", "true_false", "short"])
    assert e["status"] == "ready", e
    return e


def _open(client: TestClient, auth: H, exam_id: str, **body: Any) -> dict[str, Any]:
    r = client.post(f"/api/v1/exams/{exam_id}/live", headers=auth, json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def _host(client: TestClient, auth: H, lid: str, action: str = "", method: str = "POST") -> Any:
    url = f"/api/v1/live/{lid}" + (f"/{action}" if action else "")
    r = client.request(method if action else "GET", url, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def _correct(settings: Settings, qid: str) -> Any:
    db = sqlite3.connect(settings.db_path)
    row = db.execute("SELECT answer_json FROM exam_questions WHERE id = ?", (qid,)).fetchone()
    db.close()
    return json.loads(row[0])


def _wait_graded(phone: Phone) -> dict[str, Any]:
    for _ in range(300):
        st = phone.state()
        if st["result"] and st["result"]["status"] == "graded":
            return st
        time.sleep(0.02)
    raise AssertionError(st)


def test_graded_session_end_to_end(
    client: TestClient, auth: H, settings: Settings, exam: dict[str, Any]
) -> None:
    s = _open(client, auth, exam["id"], mode="graded", time_limit_min=30)
    assert s["status"] == "lobby" and s["url"].startswith("http://127.0.0.1:")
    assert s["url"].endswith(f"/s/{s['code']}/") and len(s["code"]) == 8
    assert s["qr"] and set("".join(s["qr"])) <= {"0", "1"} and len(s["qr"]) == len(s["qr"][0])
    lid = s["id"]

    # Entrar: con nota, cada persona espera a que el profesor la admita.
    ana, intruso = Phone(s["url"]), Phone(s["url"])
    assert ana.join("  Ana   Pérez​ ")[0] == 201
    assert ana.state()["me"] == {"name": "Ana Pérez", "status": "pending"}
    assert intruso.join("ana pérez")[1]["error"]["code"] == "name_taken"
    assert intruso.join("Otro")[0] == 201
    people = {p["name"]: p for p in _host(client, auth, lid)["participants"]}
    assert people["Ana Pérez"]["device"] == "Android · Chrome" and people["Ana Pérez"]["online"]
    _host(client, auth, lid, f"participants/{people['Ana Pérez']['id']}/admit")
    _host(client, auth, lid, f"participants/{people['Otro']['id']}/kick")
    assert intruso.call("GET", "state")[0] == 401  # expulsado: su token ya no vale
    st = ana.state()
    assert st["me"]["status"] == "admitted" and st["session"]["status"] == "lobby"
    assert st["exam"] is None  # aún no ha empezado

    # La app (y solo la app) ve la clave de respuestas con su fuente desde la sala de espera.
    key = client.get(f"/api/v1/live/{lid}/results", headers=auth).json()["questions"]
    assert all(q["answer"] is not None and q["justification"] for q in key)
    cite = key[0]["evidence"][0]
    assert cite["ref"] == 1 and cite["source_title"] and cite["text"]

    # Sala cerrada: nadie más entra.
    client.put(f"/api/v1/live/{lid}/lock", headers=auth, json={"locked": True})
    assert Phone(s["url"]).join("Tarde")[1]["error"]["code"] == "live_locked"

    # Empieza para todos a la vez; el teléfono nunca recibe las respuestas correctas.
    started = _host(client, auth, lid, "start")
    assert started["status"] == "running" and started["ends_at"]
    st = ana.state()
    qs = st["exam"]["questions"]
    assert len(qs) == 3 and st["exam"]["deadline_at"] == started["ends_at"]
    for q in qs:
        assert set(q) <= {"id", "type", "stem", "options", "answer"} and q["answer"] is None
    raw = json.dumps(st)
    assert all(q["justification"] not in raw and q["evidence"][0]["text"] not in raw for q in key)
    raw = json.dumps(st)
    assert "justification" not in raw and "rubric" not in raw and "quote" not in raw

    # Responde bien la de opción múltiple (con sus opciones mezcladas) y la de V/F.
    db = sqlite3.connect(settings.db_path)
    order = json.loads(
        db.execute("SELECT order_json FROM live_participants WHERE name = 'Ana Pérez'").fetchone()[
            0
        ]
    )
    db.close()
    for q in qs:
        good = _correct(settings, q["id"])
        if q["type"] == "single":
            value = order["options"][q["id"]].index(good)  # índice tal como lo ve ella
        elif q["type"] == "true_false":
            value = good
        else:
            value = "Los protocolos definen cómo se comunican las capas."
        assert ana.call("POST", "answer", {"question_id": q["id"], "value": value})[0] == 204
    shown = {q["id"]: q["answer"] for q in ana.state()["exam"]["questions"]}
    assert all(v is not None for v in shown.values())  # se recuperan al volver
    bad = ana.call("POST", "answer", {"question_id": qs[0]["id"], "value": 99})
    assert bad[0] in (400, 204)  # 99 solo vale en una corta (texto no) → nunca un 500
    assert ana.call("POST", "submit", {})[0] == 204

    # Con nota: no ve la nota hasta que el profesor publique.
    st = ana.state()
    assert st["result"]["visible"] is False and "score" not in st["result"]
    assert client.post(f"/api/v1/live/{lid}/publish", headers=auth).status_code == 409
    _host(client, auth, lid, "finish")
    for _ in range(300):
        res = client.get(f"/api/v1/live/{lid}/results", headers=auth).json()
        if res["participants"][0]["attempt_status"] == "graded":
            break
        time.sleep(0.02)
    row = res["participants"][0]
    assert row["score"] == 3 and row["max_score"] == 3 and len(res["questions"]) == 3
    short = next(q for q in res["questions"] if q["type"] == "short")
    assert {a["question_id"]: a for a in row["answers"]}[short["question_id"]]["graded_by"] == "ai"

    # El profesor ajusta la nota de la corta y se recalcula el total.
    r = client.put(
        f"/api/v1/live/{lid}/participants/{row['id']}/answers/{short['question_id']}",
        headers=auth,
        json={"points": 0.5},
    )
    assert r.status_code == 200 and r.json()["participants"][0]["score"] == 2.5
    assert (
        client.put(
            f"/api/v1/live/{lid}/participants/{row['id']}/answers/{short['question_id']}",
            headers=auth,
            json={"points": 0.7},
        ).status_code
        == 400
    )

    _host(client, auth, lid, "publish")
    st = ana.state()
    assert st["result"]["visible"] and st["result"]["score"] == 2.5
    assert len(st["result"]["questions"]) == 3 and all(
        "correct" in q for q in st["result"]["questions"]
    )

    # Los intentos de la sala no se mezclan con tu historial ni con tus estadísticas.
    assert client.get(f"/api/v1/exams/{exam['id']}", headers=auth).json()["attempts"] == []
    assert client.get("/api/v1/stats", headers=auth).json()["recent_exams"] == []

    # Cerrar: la sala desaparece de la red y el servidor se apaga.
    closed = _host(client, auth, lid, "close")
    assert closed["status"] == "closed" and closed["url"] is None
    assert not room.manager.running
    assert client.get("/api/v1/live", headers=auth).json()[0]["status"] == "closed"
    # Borrar elimina nombres, respuestas y notas de los participantes.
    assert client.delete(f"/api/v1/live/{lid}", headers=auth).status_code == 204
    db = sqlite3.connect(settings.db_path)
    assert db.execute("SELECT COUNT(*) FROM live_participants").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM exam_attempts").fetchone()[0] == 0
    db.close()


def test_practice_session_shows_the_grade_on_submit(
    client: TestClient, auth: H, settings: Settings, exam: dict[str, Any]
) -> None:
    s = _open(client, auth, exam["id"], mode="practice")
    assert _open_conflict(client, auth, exam["id"]) == "live_open"  # una sala abierta a la vez
    luis = Phone(s["url"])
    luis.join("Luis")
    assert luis.state()["me"]["status"] == "admitted"  # práctica: entra sin esperar
    assert client.post(f"/api/v1/live/{s['id']}/start", headers=auth).status_code == 200
    late = Phone(s["url"])
    late.join("Marta")  # en práctica se puede entrar ya empezado
    assert late.state()["exam"] is not None
    assert luis.call("POST", "submit", {})[0] == 204  # sin responder: cuenta 0
    st = _wait_graded(luis)
    assert st["result"]["visible"] and st["result"]["score"] == 0
    assert st["result"]["questions"][0]["given"] is None


def _open_conflict(client: TestClient, auth: H, exam_id: str) -> str:
    r = client.post(f"/api/v1/exams/{exam_id}/live", headers=auth, json={"mode": "practice"})
    assert r.status_code == 409
    return str(r.json()["error"]["code"])


def test_time_over_finishes_and_submits(
    client: TestClient, auth: H, exam: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _open(client, auth, exam["id"], mode="practice", time_limit_min=5)
    p = Phone(s["url"])
    p.join("Eva")
    _host(client, auth, s["id"], "start")
    q = p.state()["exam"]["questions"][0]
    real = live._now
    monkeypatch.setattr(live, "_now", lambda: real() + timedelta(minutes=6))
    from app.services import exams

    monkeypatch.setattr(exams, "_now", lambda: real() + timedelta(minutes=6))
    status, _ = p.call("POST", "answer", {"question_id": q["id"], "value": 0})
    assert status == 409  # ya no se acepta
    assert _host(client, auth, s["id"])["status"] == "finished"
    assert p.state()["me"]["attempt"] in ("grading", "graded")


def test_room_server_only_serves_the_room(
    client: TestClient, auth: H, exam: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _open(client, auth, exam["id"], mode="practice")
    base = s["url"].split("/s/")[0]
    p = Phone(base + "/")
    # La API principal y cualquier otra ruta no existen en la red.
    for path in ("api/v1/subjects", "s/../api/v1/subjects", "", "s/", "docs"):
        assert p.call("GET", path)[0] == 404
    # Página del participante con CSP estricta y sin caché.
    req = urllib.request.Request(s["url"], headers={"User-Agent": ANDROID})
    with urllib.request.urlopen(req, timeout=5) as r:
        html, headers = r.read().decode(), dict(r.headers)
    nonce = headers["Content-Security-Policy"].split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in html and "default-src 'none'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store" and "innerHTML" not in html
    # Sin token no hay nada; un token inventado tampoco.
    room_phone = Phone(s["url"])
    assert room_phone.call("GET", "state")[0] == 401
    room_phone.token = "x" * 43
    assert room_phone.call("GET", "state")[0] == 401
    # Cuerpos rotos o enormes: errores controlados.
    for body, code in ((b"{roto", 400), (b"[1]", 400), (b"x" * 30_000, 413)):
        req = urllib.request.Request(s["url"] + "join", data=body, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            assert e.code == code
    for name in ("", " ", "a", None, 5, "​​"):
        assert Phone(s["url"]).join(name)[1]["error"]["code"] == "invalid_name"  # type: ignore[arg-type]
    # Fuerza bruta del código: tras muchos códigos erróneos, esa IP queda bloqueada un rato.
    monkeypatch.setattr(room, "BAD_CODES_PER_10_MIN", 5)
    codes = [Phone(base + f"/s/AAAAAA{i:02d}/").call("GET", "state")[0] for i in range(7)]
    assert codes[:5] == [404] * 5 and codes[5:] == [429, 429]


def test_twenty_phones_at_once(
    client: TestClient, auth: H, settings: Settings, exam: dict[str, Any]
) -> None:
    """Aceptación: 20 teléfonos a la vez entran, esperan, responden y entregan sin errores."""
    from concurrent.futures import ThreadPoolExecutor

    s = _open(client, auth, exam["id"], mode="practice", time_limit_min=10)
    phones = [Phone(s["url"]) for _ in range(20)]
    with ThreadPoolExecutor(20) as pool:
        joined = list(pool.map(lambda ip: ip[1].join(f"Alumno {ip[0]:02d}")[0], enumerate(phones)))
    assert joined == [201] * 20
    _host(client, auth, s["id"], "start")

    def exam_flow(p: Phone) -> tuple[int, float]:
        t0 = time.perf_counter()
        qs = p.state()["exam"]["questions"]
        for _ in range(3):  # consultas como las del teléfono mientras responde
            p.state()
        for q in qs:
            value = 0 if q["type"] == "single" else True if q["type"] == "true_false" else "Capas."
            assert p.call("POST", "answer", {"question_id": q["id"], "value": value})[0] == 204
        status = p.call("POST", "submit", {})[0]
        return status, time.perf_counter() - t0

    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(exam_flow, phones))
    assert [r[0] for r in results] == [204] * 20
    assert max(r[1] for r in results) < 10  # cada teléfono termina su flujo en segundos
    for _ in range(600):
        people = _host(client, auth, s["id"])["participants"]
        if all(p["attempt_status"] == "graded" for p in people):
            break
        time.sleep(0.05)
    assert len(people) == 20 and all(p["attempt_status"] == "graded" for p in people)
    assert all(p["answered"] == p["total"] == 3 for p in people)


def test_port_80_only_answers_on_the_wifi_ip(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Puerto 80 (lo que menos filtran las redes): se escucha en todas las interfaces, pero solo
    se atiende lo que llega por la IP de la Wi-Fi. Puerto libre en la prueba, sin administrador."""
    from http.server import BaseHTTPRequestHandler

    monkeypatch.setattr(room, "WEB_PORT", 0)
    httpd = room.bind("10.254.254.254", BaseHTTPRequestHandler)  # «Wi-Fi» que no es localhost
    try:
        assert httpd.server_address[0] == "0.0.0.0"  # noqa: S104
        assert httpd.only_ip == "10.254.254.254"
        import threading

        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        with pytest.raises((urllib.error.URLError, ConnectionError)):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)  # no llega por la Wi-Fi
        httpd.only_ip = "127.0.0.1"
        with pytest.raises(urllib.error.HTTPError) as e:  # ahora sí se atiende (501: sin GET)
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
        assert e.value.code == 501
    finally:
        httpd.shutdown()
        httpd.server_close()
    # Con localhost (pruebas), nunca en todas las interfaces.
    local = room.bind("127.0.0.1", BaseHTTPRequestHandler)
    assert local.server_address[0] == "127.0.0.1" and local.only_ip is None
    local.server_close()


def test_mac_stays_awake_only_while_a_room_is_open(
    client: TestClient,
    auth: H,
    exam: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    started: list[list[str]] = []

    class FakeProc:
        def __init__(self, args: list[str], **_: Any) -> None:
            started.append(args)
            self.alive = True

        def terminate(self) -> None:
            self.alive = False

        def wait(self, timeout: float) -> int:
            return 0

    fake = tmp_path / "caffeinate"
    fake.write_text("")
    monkeypatch.setattr(room, "CAFFEINATE", fake)
    monkeypatch.setattr(room.subprocess, "Popen", FakeProc)
    s = _open(client, auth, exam["id"], mode="practice")
    assert room.manager.server is not None
    proc = room.manager.server.awake
    assert isinstance(proc, FakeProc) and proc.alive
    assert started[0][1:3] == ["-i", "-w"]  # atado al proceso del backend
    _host(client, auth, s["id"], "close")
    assert room.manager.server is None and not proc.alive


def test_manual_exam_can_be_shared_live(client: TestClient, auth: H) -> None:
    """Un examen escrito a mano se comparte en la sala como cualquier otro."""
    sid = client.post("/api/v1/subjects", headers=auth, json={"name": "Redes"}).json()["id"]
    body = {
        "title": "Repaso a mano",
        "questions": [
            {
                "type": "single",
                "stem": "¿Qué capa enruta?",
                "options": ["Enlace", "Red", "Transporte"],
                "answer": 1,
                "justification": "La de red decide la ruta.",
            },
            {"type": "true_false", "stem": "TCP ordena los paquetes.", "answer": True},
        ],
    }
    exam = client.post(f"/api/v1/subjects/{sid}/exams/manual", headers=auth, json=body).json()
    s = _open(client, auth, exam["id"], mode="practice", show_results=True)
    assert s["url"] and s["qr"]
    key = client.get(f"/api/v1/live/{s['id']}/results", headers=auth).json()["questions"]
    assert key[0]["justification"] == "La de red decide la ruta." and key[0]["evidence"] == []

    phone = Phone(s["url"])
    assert phone.join("Ana")[0] == 201
    _host(client, auth, s["id"], "start")
    st = phone.state()
    for q in st["exam"]["questions"]:
        value = q["options"].index("Red") if q["type"] == "single" else True
        assert phone.call("POST", "answer", {"question_id": q["id"], "value": value})[0] == 204
    assert "La de red" not in json.dumps(st)  # la explicación no llega antes de entregar
    assert phone.call("POST", "submit")[0] in (200, 204)
    res = _wait_graded(phone)["result"]
    assert res["score"] == 2 and res["max_score"] == 2
    # Ya tiene intentos: el examen deja de ser editable.
    assert client.get(f"/api/v1/exams/{exam['id']}", headers=auth).json()["editable"] is False
