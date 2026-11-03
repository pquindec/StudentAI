from typing import Any

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.connection import connect
from app.jobs import queue

H = dict[str, str]


def _subject(client: TestClient, auth: H, name: str = "Bases de datos") -> Any:
    r = client.post("/api/v1/subjects", json={"name": name, "color": "#4f46e5"}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def test_subject_crud(client: TestClient, auth: H) -> None:
    s = _subject(client, auth)
    r = client.patch(f"/api/v1/subjects/{s['id']}", json={"term": "2026-27"}, headers=auth)
    assert r.json()["term"] == "2026-27"
    assert [x["name"] for x in client.get("/api/v1/subjects", headers=auth).json()] == [
        "Bases de datos"
    ]
    client.patch(f"/api/v1/subjects/{s['id']}", json={"archived": True}, headers=auth)
    assert client.get("/api/v1/subjects", headers=auth).json() == []
    assert len(client.get("/api/v1/subjects?archived=true", headers=auth).json()) == 1
    assert client.delete(f"/api/v1/subjects/{s['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/v1/subjects/{s['id']}", headers=auth).status_code == 404


def test_validation_messages(client: TestClient, auth: H) -> None:
    r = client.post("/api/v1/subjects", json={"name": "   "}, headers=auth)
    assert r.status_code == 422
    assert r.json()["error"] == {
        "code": "invalid_data",
        "message": "Revisa los datos introducidos",
        "details": {"fields": ["name"]},
    }
    r = client.post("/api/v1/subjects", json={"name": "X", "color": "red"}, headers=auth)
    assert r.status_code == 422


def test_unit_hierarchy(client: TestClient, auth: H) -> None:
    s = _subject(client, auth)
    url = f"/api/v1/subjects/{s['id']}/units"
    course = client.post(url, json={"kind": "course", "title": "Curso 1"}, headers=auth).json()
    module = client.post(
        url, json={"kind": "module", "title": "Módulo A", "parent_id": course["id"]}, headers=auth
    ).json()
    topic = client.post(
        url, json={"kind": "topic", "title": "Tema 1", "parent_id": module["id"]}, headers=auth
    ).json()
    # un curso no puede ir dentro de un tema
    r = client.post(
        url, json={"kind": "course", "title": "X", "parent_id": topic["id"]}, headers=auth
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_hierarchy"
    # mover el curso dentro de su propio módulo: jerarquía inválida
    r = client.patch(
        f"/api/v1/units/{course['id']}", json={"parent_id": module["id"]}, headers=auth
    )
    assert r.status_code == 400
    # un tema puede colgar directamente del curso
    r = client.patch(f"/api/v1/units/{topic['id']}", json={"parent_id": course["id"]}, headers=auth)
    assert r.status_code == 200 and r.json()["parent_id"] == course["id"]
    detail = client.get(f"/api/v1/subjects/{s['id']}", headers=auth).json()
    assert detail["unit_count"] == 3
    # borrar el curso borra sus subunidades
    client.delete(f"/api/v1/units/{course['id']}", headers=auth)
    assert client.get(f"/api/v1/subjects/{s['id']}", headers=auth).json()["units"] == []


def test_unit_parent_from_other_subject(client: TestClient, auth: H) -> None:
    a, b = _subject(client, auth, "A"), _subject(client, auth, "B")
    ua = client.post(
        f"/api/v1/subjects/{a['id']}/units", json={"kind": "course", "title": "C"}, headers=auth
    ).json()
    r = client.post(
        f"/api/v1/subjects/{b['id']}/units",
        json={"kind": "topic", "title": "T", "parent_id": ua["id"]},
        headers=auth,
    )
    assert r.status_code == 400


def test_sessions(client: TestClient, auth: H) -> None:
    s = _subject(client, auth)
    t = client.post(
        f"/api/v1/subjects/{s['id']}/units", json={"kind": "topic", "title": "T"}, headers=auth
    ).json()
    r = client.post(
        f"/api/v1/subjects/{s['id']}/sessions",
        headers=auth,
        json={
            "kind": "class",
            "title": "Clase 1",
            "unit_id": t["id"],
            "held_at": "2026-11-03T10:00:00Z",
        },
    )
    assert r.status_code == 201, r.text
    detail = client.get(f"/api/v1/subjects/{s['id']}", headers=auth).json()
    assert detail["sessions"][0]["title"] == "Clase 1"


def test_cancel_queued_job(settings: Settings) -> None:
    db = connect(settings.db_path)
    db.execute("INSERT INTO subjects(id, owner_id, name) VALUES ('s','local','S')")
    db.execute("INSERT INTO sources(id, subject_id, kind, title) VALUES ('x','s','pdf','X')")
    jid = queue.enqueue(db, "extract_document", "io", "x")
    assert queue.request_cancel(db, jid) == "cancelled"
    assert db.execute("SELECT status FROM sources WHERE id='x'").fetchone()[0] == "cancelled"


def test_interrupted_jobs_are_requeued(settings: Settings) -> None:
    db = connect(settings.db_path)
    jid = queue.enqueue(db, "extract_document", "io", None)
    assert queue.claim_next(db, ["io"]) is not None  # queda 'running'
    assert queue.recover_interrupted(db) == 1
    assert db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0] == "queued"
