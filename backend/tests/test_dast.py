"""Fase 9 — DAST propio de la API local (en lugar de ZAP: la API solo escucha en un Unix socket).

Recorre **todas** las rutas del esquema OpenAPI de la app, así que una ruta nueva queda cubierta
sin tocar este archivo:
- sin token o con un token falso → 401;
- datos de otro propietario → 404 en cada ruta y sin cambiar nada en la BD (ADR-009);
- entradas hostiles (inyección SQL, rutas, bytes nulos, tipos erróneos, JSON roto, cuerpos
  enormes) → nunca un 500 ni una traza.
"""

import hashlib
import sqlite3
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.limits import MAX_REQUEST_BYTES
from app.llm.base import LLMError
from app.resources import manager
from app.services import llm
from tests.test_chat import FakeChat, _ask
from tests.test_exams import TEXT, FakeExamLLM, _exam, _source, _start
from tests.test_flashcards import FakeCardLLM, _deck
from tests.test_generation import FakeLLM, _wait

H = dict[str, str]
Op = tuple[str, str, dict[str, Any]]  # método, ruta, operación OpenAPI


class BrokenLLM(FakeLLM):
    """Para la batería de entradas hostiles: cualquier trabajo que llegue a encolarse falla
    de forma controlada (no hay modelo), nunca con un error inesperado."""

    def chat(self, *a: Any, **k: Any) -> Any:
        raise LLMError("llm_unavailable", "sin modelo en las pruebas")


def _ops(client: TestClient) -> list[Op]:
    spec = client.app.openapi()  # type: ignore[attr-defined]
    return [(m.upper(), p, op) for p, ops in spec["paths"].items() for m, op in ops.items()]


def _params(op: dict[str, Any], where: str) -> list[str]:
    return [p["name"] for p in op.get("parameters", []) if p["in"] == where]


def _idle(client: TestClient, auth: H) -> None:
    for _ in range(500):
        if not client.get("/api/v1/jobs", headers=auth).json():
            return
        time.sleep(0.02)
    raise AssertionError("quedan trabajos en curso")


def _snapshot(db_path: Any) -> str:
    """Huella de todo el contenido de la BD (para comprobar que nada cambió)."""
    db = sqlite3.connect(db_path)
    h = hashlib.sha256()
    tables = [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            " AND name NOT LIKE 'chunks_fts%' ORDER BY name"
        )
    ]
    for t in tables:
        for row in db.execute(f'SELECT * FROM "{t}" ORDER BY 1'):  # noqa: S608 — nombres de la BD
            h.update(repr(row).encode())
    db.close()
    return h.hexdigest()


@pytest.fixture
def world(
    client: TestClient, auth: H, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, str]]:
    """Un ejemplo de cada objeto de la API, creado por el usuario local con modelos falsos."""
    monkeypatch.setattr(manager, "available_mb", lambda: 10_000)

    def use(fake: Any) -> None:
        monkeypatch.setattr(llm, "provider", lambda: fake)

    ids: dict[str, str] = {}
    use(FakeChat())
    ids["subject_id"] = client.post("/api/v1/subjects", headers=auth, json={"name": "A"}).json()[
        "id"
    ]
    s = ids["subject_id"]
    ids["unit_id"] = client.post(
        f"/api/v1/subjects/{s}/units", headers=auth, json={"kind": "course", "title": "U"}
    ).json()["id"]
    ids["session_id"] = client.post(
        f"/api/v1/subjects/{s}/sessions", headers=auth, json={"kind": "class", "title": "C"}
    ).json()["id"]
    ids["source_id"] = _source(client, auth, s, TEXT)
    _idle(client, auth)

    use(FakeLLM())
    r = client.post(
        f"/api/v1/subjects/{s}/documents",
        headers=auth,
        json={"kind": "summary", "source_ids": [ids["source_id"]]},
    )
    assert r.status_code == 202, r.text
    ids["doc_id"] = _wait(client, auth, r.json()["id"])["id"]

    use(FakeChat())
    ids["thread_id"] = client.post("/api/v1/chat/threads", headers=auth, json={}).json()["id"]
    ids["message_id"] = _ask(client, auth, ids["thread_id"], "¿Qué define la arquitectura?")["id"]

    use(FakeExamLLM())
    exam = _exam(client, auth, s, count=2, types=["single"])
    assert exam["status"] == "ready", exam
    ids["exam_id"] = exam["id"]
    attempt = _start(client, auth, exam["id"])
    ids["attempt_id"] = attempt["id"]
    ids["question_id"] = attempt["questions"][0]["id"]

    use(FakeCardLLM())
    deck = _deck(client, auth, s, count=5)
    assert deck["status"] == "ready", deck
    ids["deck_id"] = deck["id"]
    ids["card_id"] = deck["cards"][0]["id"]

    _idle(client, auth)
    jobs = client.get("/api/v1/jobs?active=false&limit=200", headers=auth).json()
    ids["job_id"] = next(j["id"] for j in jobs if j["source_id"] is None)
    ids["model_id"] = "base"

    db = sqlite3.connect(settings.db_path)
    ids["consent_id"] = "c-local"
    db.execute(
        "INSERT INTO cloud_consents(id, owner_id, kind, tasks_json, mode, via, model,"
        " max_cost_usd) VALUES ('c-local', 'local', 'chat', '[\"chat\"]', 'session', 'plan',"
        " 'claude-sonnet-5-5', 1)"
    )
    db.commit()
    db.close()
    yield ids


# Cuerpos válidos: así lo único que puede fallar es el propietario, no la validación.
BODIES: dict[tuple[str, str], Any] = {
    ("PATCH", "/subjects/{subject_id}"): {"name": "Robada"},
    ("POST", "/subjects/{subject_id}/units"): {"kind": "course", "title": "X"},
    ("PATCH", "/units/{unit_id}"): {"title": "X"},
    ("POST", "/subjects/{subject_id}/sessions"): {"kind": "class", "title": "X"},
    ("PATCH", "/sessions/{session_id}"): {"title": "X"},
    ("PATCH", "/sources/{source_id}"): {"title": "X"},
    ("PUT", "/sources/{source_id}/content"): {"text": "otro texto", "base_version": 1},
    ("POST", "/sources/{source_id}/transcribe"): {},
    ("POST", "/subjects/{subject_id}/documents"): {
        "kind": "summary",
        "source_ids": ["{source_id}"],
    },
    ("PATCH", "/chat/threads/{thread_id}"): {"title": "X"},
    ("POST", "/chat/threads/{thread_id}/messages"): {"text": "hola"},
    ("POST", "/subjects/{subject_id}/exams"): {"config": {"count": 1, "types": ["single"]}},
    ("PUT", "/attempts/{attempt_id}/answers/{question_id}"): {"answer": 0, "set_answer": True},
    ("POST", "/subjects/{subject_id}/decks"): {"count": 5},
    ("PATCH", "/cards/{card_id}"): {"front": "X"},
    ("POST", "/cards/{card_id}/review"): {"rating": 3, "duration_ms": 1000},
}


def _fill(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        for k, v in ids.items():
            value = value.replace("{" + k + "}", v)
        return value
    if isinstance(value, list):
        return [_fill(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    return value


def test_every_route_requires_the_token(client: TestClient) -> None:
    ops = _ops(client)
    assert len(ops) >= 79
    for method, path, _ in ops:
        url = path.replace("{", "").replace("}", "")
        for headers in ({}, {"Authorization": "Bearer " + "0" * 64}):
            r = client.request(method, url, headers=headers, json={})
            assert r.status_code == 401, (method, path, r.status_code)


def test_another_owner_cannot_reach_or_change_anything(
    client: TestClient, auth: H, settings: Settings, world: dict[str, str]
) -> None:
    """Todo lo creado pasa a otro propietario: el usuario local no debe poder verlo, cambiarlo,
    borrarlo ni lanzar trabajos sobre ello desde ninguna ruta."""
    db = sqlite3.connect(settings.db_path)
    db.execute("INSERT INTO users(id, display_name, role) VALUES ('intruso', 'Otro', 'member')")
    for table in ("subjects", "chat_threads", "cloud_consents"):
        db.execute(f"UPDATE {table} SET owner_id = 'intruso'")  # noqa: S608
    db.commit()
    db.close()
    before = _snapshot(settings.db_path)

    tested = 0
    for method, path, op in _ops(client):
        names = _params(op, "path")
        if not names or names == ["model_id"]:
            continue  # sin ids de usuario (las descargas de modelos son del sistema)
        url = "/api/v1" + _fill(path.removeprefix("/api/v1"), world)
        body = _fill(BODIES.get((method, path.removeprefix("/api/v1"))), world)
        r = client.request(method, url, headers=auth, json=body)
        if path.endswith("/cloud/consents/{consent_id}"):
            assert r.status_code == 204  # idempotente; se comprueba abajo que no revocó nada
        else:
            assert r.status_code == 404, (method, path, r.status_code, r.text)
        tested += 1
    assert tested >= 45

    # Rutas que reciben los ids en la consulta o en el cuerpo.
    s, src = world["subject_id"], world["source_id"]
    for url in (
        f"/api/v1/sources?subject_id={s}",
        f"/api/v1/chat/threads?subject_id={s}",
        f"/api/v1/study?subject_id={s}",
        f"/api/v1/study?deck_id={world['deck_id']}",
        f"/api/v1/stats?subject_id={s}",
    ):
        r = client.get(url, headers=auth)
        assert r.status_code in (200, 404), (url, r.status_code)
        if r.status_code == 200:
            text = r.text
            assert src not in text and world["card_id"] not in text and "Tema" not in text, url
    for url, body in (
        ("/api/v1/sources/text", {"subject_id": s, "title": "X", "text": "x"}),
        ("/api/v1/chat/threads", {"scope": {"subject_id": s}}),
        ("/api/v1/chat/threads", {"scope": {"source_ids": [src]}}),
    ):
        r = client.post(url, headers=auth, json=body)
        assert r.status_code in (400, 404), (url, r.status_code, r.text)

    # Listados globales: vacíos para el usuario local.
    assert client.get("/api/v1/subjects", headers=auth).json() == []
    assert client.get("/api/v1/sources", headers=auth).json()["total"] == 0
    assert client.get("/api/v1/chat/threads", headers=auth).json() == []
    assert client.get("/api/v1/jobs?active=false&limit=200", headers=auth).json() == []
    assert client.get("/api/v1/study", headers=auth).json()["card"] is None
    assert client.get("/api/v1/cloud/status", headers=auth).json()["session_consents"] == []

    assert _snapshot(settings.db_path) == before, "una petición cambió datos de otro usuario"


PAYLOADS = [
    "' OR '1'='1",
    "1; DROP TABLE subjects; --",
    "../../../../etc/passwd",
    "%00",
    "\x00",
    "<script>alert(1)</script>",
    "😀" * 50,
    "A" * 5000,
    "-1",
    "99999999999999999999999",
    "null",
    "{}",
]
JUNK_VALUES: list[Any] = [None, -1, 10**30, 1.5e308, "", "x" * 100_000, [], {}, True, PAYLOADS[0]]


def _body_mutations(op: dict[str, Any], spec: dict[str, Any]) -> list[Any]:
    content = op.get("requestBody", {}).get("content", {})
    if not content:
        return [None]
    ref = next(iter(content.values()))["schema"].get("$ref", "")
    schema = spec["components"]["schemas"].get(ref.split("/")[-1], {})
    props = list(schema.get("properties", {}))
    out: list[Any] = [None, {}, [], "texto", 0, {"__proto__": {"x": 1}}]
    out += [{p: v} for p in props for v in JUNK_VALUES]
    return out


def test_hostile_input_never_breaks_the_api(
    client: TestClient, auth: H, world: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm, "provider", lambda: BrokenLLM())
    spec = client.app.openapi()  # type: ignore[attr-defined]
    sent = 0

    def check(method: str, url: str, **kw: Any) -> None:
        nonlocal sent
        r = client.request(method, url, headers={**auth, **kw.pop("headers", {})}, **kw)
        sent += 1
        assert r.status_code < 500, (method, url, kw, r.status_code, r.text[:300])
        assert "Traceback" not in r.text and 'File "' not in r.text, (method, url)
        if r.status_code >= 400:
            assert "error" in r.json(), (method, url, r.text[:200])

    ops = sorted(_ops(client), key=lambda o: o[0] == "DELETE")  # borrar, al final
    for method, path, op in ops:
        names, queries = _params(op, "path"), _params(op, "query")
        rel = path.removeprefix("/api/v1")
        # 1) Cada id de la ruta y cada parámetro de consulta con valores hostiles.
        for p in PAYLOADS:
            url = "/api/v1" + rel
            for n in names:
                url = url.replace("{" + n + "}", quote(p, safe=""))
            qs = "&".join(f"{q}={quote(p, safe='')}" for q in queries)
            check(
                method, url + ("?" + qs if qs else ""), json=_fill(BODIES.get((method, rel)), world)
            )
        # 2) Con ids válidos, cuerpos mutados (tipos erróneos, valores extremos, extras).
        if method != "DELETE":
            url = "/api/v1" + _fill(rel, world)
            for body in _body_mutations(op, spec):
                check(method, url, json=body)
            if op.get("requestBody"):
                for raw in (b"{", b"\xff\xfe", b'{"a":' * 5000, b"[" * 10000):
                    check(method, url, content=raw, headers={"Content-Type": "application/json"})
    assert sent > 2000


def test_request_size_is_limited(client: TestClient, auth: H, world: dict[str, str]) -> None:
    url = "/api/v1/sources/text"
    big = b'{"text": "' + b"a" * MAX_REQUEST_BYTES + b'"}'
    r = client.post(url, headers={**auth, "Content-Type": "application/json"}, content=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"

    def chunks() -> Iterator[bytes]:
        yield b'{"subject_id": "x", "title": "x", "text": "x"}'

    r = client.post(url, headers={**auth, "Content-Type": "application/json"}, content=chunks())
    assert r.status_code == 411

    # Lo legítimo más grande cabe: 2 millones de caracteres pegados.
    body = {"subject_id": world["subject_id"], "title": "Largo", "text": "á" * 2_000_000}
    assert client.post(url, headers=auth, json=body).status_code == 201
