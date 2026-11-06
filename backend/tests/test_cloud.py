"""Fase 8: Claude con consentimiento. Sin consentimiento no sale ningún byte (servidor falso de la
API que cuenta cada petición y `claude` falso que registra cada ejecución); límites, auditoría,
vuelta a local sin conexión y la misma lógica de negocio en local y en la nube."""

import json
import os
import stat
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.connection import connect
from app.llm import claude_code
from app.llm.base import ChatRequest, Message
from app.services import cloud, engine

from .test_chat import FakeChat, _ask, _source, _subject, _thread
from .test_flashcards import FakeCardLLM, fake  # noqa: F401  (fixture)

H = dict[str, str]
TEXT = "\n\n".join(
    f"Párrafo {i}: la arquitectura número {i} define componentes, conectores y restricciones"
    f" que guían la evolución del sistema durante años de mantenimiento continuado {i}."
    for i in range(6)
)


class FakeAnthropic:
    """Servidor HTTP que imita /v1/messages en streaming y responde como FakeCardLLM."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.brain = FakeCardLLM()
        self.reply: str | None = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.bodies.append({"path": self.path, "headers": dict(self.headers), **body})
                text = outer.answer(body)
                events = [
                    ("message_start", {"type": "message_start", "message": {
                        "id": "msg_1", "type": "message", "role": "assistant",
                        "model": body["model"], "content": [], "stop_reason": None,
                        "stop_sequence": None, "usage": {"input_tokens": 1000, "output_tokens": 1},
                    }}),
                    ("content_block_start", {"type": "content_block_start", "index": 0,
                                             "content_block": {"type": "text", "text": ""}}),
                    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                             "delta": {"type": "text_delta", "text": text}}),
                    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                    ("message_delta", {"type": "message_delta",
                                       "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                       "usage": {"output_tokens": 500}}),
                    ("message_stop", {"type": "message_stop"}),
                ]  # fmt: skip
                data = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(data.encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def answer(self, body: dict[str, Any]) -> str:
        if self.reply is not None:
            return self.reply
        msgs = [Message("system", body.get("system") or "")] + [
            Message(m["role"], m["content"]) for m in body["messages"]
        ]
        schema = ((body.get("output_config") or {}).get("format") or {}).get("schema")
        return self.brain.chat(ChatRequest(body["model"], msgs, schema=schema)).text


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeAnthropic]:
    f = FakeAnthropic()
    t = threading.Thread(target=f.server.serve_forever, daemon=True)
    t.start()
    monkeypatch.setattr(engine, "API_BASE_URL", f.url)
    yield f
    f.server.shutdown()


def _enable(client: TestClient, auth: H, key: bool = True, **extra: Any) -> dict[str, Any]:
    if key:
        r = client.put(
            "/api/v1/cloud/api-key", headers=auth, json={"key": "sk-ant-test-" + "x" * 30}
        )
        assert r.status_code == 200, r.text
    r = client.put("/api/v1/cloud/settings", headers=auth, json={"enabled": True, **extra})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def _consent(client: TestClient, auth: H, mode: str = "once", **body: Any) -> str:
    r = client.post("/api/v1/cloud/consents", headers=auth, json={"mode": mode, **body})
    assert r.status_code == 201, r.text
    cid: str = r.json()["id"]
    return cid


def _deck(client: TestClient, auth: H, subject: str, **body: Any) -> dict[str, Any]:
    import time

    r = client.post(f"/api/v1/subjects/{subject}/decks", headers=auth, json={"count": 5, **body})
    assert r.status_code == 202, r.text
    did = r.json()["id"]
    for _ in range(400):
        d: dict[str, Any] = client.get(f"/api/v1/decks/{did}", headers=auth).json()
        if d["status"] not in ("queued", "running"):
            return d
        time.sleep(0.02)
    raise AssertionError("el mazo no terminó")


def _requests(settings: Settings) -> list[dict[str, Any]]:
    db = connect(settings.db_path)
    try:
        return [dict(r) for r in db.execute("SELECT * FROM cloud_requests ORDER BY id")]
    finally:
        db.close()


@pytest.fixture
def subject(client: TestClient, auth: H, fake: FakeCardLLM) -> str:  # noqa: F811
    sid = _subject(client, auth, "Redes")
    _source(client, auth, sid, "Tema 1", TEXT)
    return sid


# ------------------------------------------------------------------ sin consentimiento, nada sale
def test_disabled_by_default_and_nothing_leaves_without_consent(
    client: TestClient, auth: H, api: FakeAnthropic, subject: str, settings: Settings
) -> None:
    st = client.get("/api/v1/cloud/status", headers=auth).json()
    assert st["enabled"] is False and st["via"] is None and st["model"] == "claude-sonnet-5-5"
    assert st["limits"] == {"api": 5.0, "plan": 5.0}
    deck = _deck(client, auth, subject)  # desactivada: local
    assert deck["status"] == "ready" and api.bodies == [], deck["error_message"]

    _enable(client, auth)
    deck = _deck(client, auth, subject)  # activada pero sin consentimiento: local
    assert deck["status"] == "ready" and deck["model"] == "qwen3.5:9b"
    deck = _deck(client, auth, subject, consent_id="no-existe")  # consentimiento inventado
    assert deck["status"] == "ready" and api.bodies == [] and _requests(settings) == []


def test_preview_shows_exact_text_cost_and_limits(
    client: TestClient, auth: H, api: FakeAnthropic, subject: str
) -> None:
    body = {"kind": "deck", "subject_id": subject, "count": 10}
    p = client.post("/api/v1/cloud/preview", headers=auth, json=body).json()
    assert p["cloud"] is False and p["reason"] == "disabled" and p["est_cost_usd"] == 0
    _enable(client, auth)
    p = client.post("/api/v1/cloud/preview", headers=auth, json=body).json()
    assert p["cloud"] is True and p["via"] == "api" and p["tasks"] == ["generate", "review"]
    assert "la arquitectura número 0 define" in p["text"] and p["chars"] == len(p["text"])
    assert [s["title"] for s in p["sources"]] == ["Tema 1"] and p["fragments"] == 6
    assert 0 < p["est_cost_usd"] < 0.5 and p["limit_usd"] == 5.0 and p["spent_usd"] == 0
    assert p["session_consent_id"] is None
    assert api.bodies == []  # la vista previa no envía nada


def test_consented_deck_goes_to_claude_with_same_logic_and_audit(
    client: TestClient,
    auth: H,
    api: FakeAnthropic,
    subject: str,
    settings: Settings,
    fake: FakeCardLLM,  # noqa: F811
) -> None:
    _enable(client, auth)
    local = _deck(client, auth, subject)
    cid = _consent(client, auth, kind="deck", subject_id=subject, count=5)
    calls_before = len(fake.requests)
    remote = _deck(client, auth, subject, consent_id=cid)
    assert remote["status"] == "ready" and len(fake.requests) == calls_before  # nada en local

    # Misma lógica de negocio: mismas tarjetas con Claude que en local.
    def fronts(d: dict[str, Any]) -> list[str]:
        cards = client.get(f"/api/v1/decks/{d['id']}", headers=auth).json()["cards"]
        return sorted(c["front"] for c in cards)

    assert fronts(remote) == fronts(local) and remote["model"] == "claude-sonnet-5-5"
    first = api.bodies[0]
    assert first["path"].startswith("/v1/messages") and first["model"] == "claude-sonnet-5-5"
    headers = {k.lower(): v for k, v in first["headers"].items()}
    assert headers["authorization"].startswith("Bearer sk-ant-test-")  # la clave del Keychain
    assert first["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert "temperature" not in first  # Sonnet 5.5 no acepta temperatura
    rows = _requests(settings)
    assert {r["task"] for r in rows} == {"cards:generate", "cards:judge"}
    assert all(r["status"] == "ok" and r["via"] == "api" and r["cost_usd"] > 0 for r in rows)
    assert all(r["chars_sent"] > 0 for r in rows)
    st = client.get("/api/v1/cloud/status", headers=auth).json()
    assert st["spent"]["api"] == pytest.approx(sum(r["cost_usd"] for r in rows), abs=1e-3)
    audit = client.get("/api/v1/cloud/requests", headers=auth).json()
    assert len(audit) == len(rows) and "text" not in audit[0]  # sin contenido

    # Un consentimiento «una vez» no sirve para otro mazo.
    n = len(api.bodies)
    again = _deck(client, auth, subject, consent_id=cid)
    assert again["status"] == "ready" and len(api.bodies) == n and again["model"] == "qwen3.5:9b"


def test_review_only_sends_just_the_judge(
    client: TestClient, auth: H, api: FakeAnthropic, subject: str, settings: Settings
) -> None:
    _enable(client, auth, tasks={"generate": False})
    p = client.post(
        "/api/v1/cloud/preview", headers=auth, json={"kind": "deck", "subject_id": subject}
    ).json()
    assert p["tasks"] == ["review"] and "review_only" in p["notes"]
    cid = _consent(client, auth, kind="deck", subject_id=subject)
    deck = _deck(client, auth, subject, consent_id=cid)
    assert deck["status"] == "ready" and deck["model"] == "qwen3.5:9b + claude-sonnet-5-5"
    assert {r["task"] for r in _requests(settings)} == {"cards:judge"}


def test_consent_only_covers_the_previewed_sources(
    client: TestClient, auth: H, api: FakeAnthropic, subject: str
) -> None:
    _enable(client, auth)
    cid = _consent(client, auth, kind="deck", subject_id=subject)
    _source(
        client, auth, subject, "Tema 2", TEXT.replace("arquitectura", "topología")
    )  # nueva fuente
    deck = _deck(client, auth, subject, consent_id=cid)
    assert deck["status"] == "ready" and api.bodies == []  # no se aprobó «Tema 2»: local


def test_session_consent_lasts_until_restart_and_can_be_revoked(
    client: TestClient, auth: H, api: FakeAnthropic, subject: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(client, auth)
    body = {"kind": "deck", "subject_id": subject}
    cid = _consent(client, auth, mode="session", **body)
    p = client.post("/api/v1/cloud/preview", headers=auth, json=body).json()
    assert p["session_consent_id"] == cid
    assert _deck(client, auth, subject, consent_id=cid)["model"] == "claude-sonnet-5-5"
    assert _deck(client, auth, subject, consent_id=cid)["model"] == "claude-sonnet-5-5"
    st = client.get("/api/v1/cloud/status", headers=auth).json()
    assert [c["id"] for c in st["session_consents"]] == [cid]
    # Cambiar el modelo invalida lo aprobado.
    _enable(client, auth, key=False, model="claude-opus-5-5")
    assert (
        client.post("/api/v1/cloud/preview", headers=auth, json=body).json()["session_consent_id"]
        is None
    )
    _enable(client, auth, key=False, model="claude-sonnet-5-5")
    # Reiniciar la app (otro arranque) también.
    boot = cloud.BOOT_ID
    monkeypatch.setattr(cloud, "BOOT_ID", "otro-arranque")
    assert (
        client.post("/api/v1/cloud/preview", headers=auth, json=body).json()["session_consent_id"]
        is None
    )
    monkeypatch.setattr(cloud, "BOOT_ID", boot)
    assert client.delete("/api/v1/cloud/consents", headers=auth).status_code == 204
    n = len(api.bodies)
    assert _deck(client, auth, subject, consent_id=cid)["model"] == "qwen3.5:9b"
    assert len(api.bodies) == n


# ------------------------------------------------------------------ límites y sin conexión
def test_monthly_limit_blocks_and_continues_locally(
    client: TestClient, auth: H, api: FakeAnthropic, subject: str, settings: Settings
) -> None:
    _enable(client, auth)
    cid = _consent(client, auth, kind="deck", subject_id=subject)
    _enable(client, auth, key=False, limit_api=0.0001)  # el límite baja tras consentir
    deck = _deck(client, auth, subject, consent_id=cid)
    assert deck["status"] == "ready" and api.bodies == [] and deck["model"] == "qwen3.5:9b"
    assert deck["stats"] is not None
    rows = _requests(settings)
    assert rows and rows[0]["status"] == "blocked" and rows[0]["chars_sent"] == 0
    p = client.post(
        "/api/v1/cloud/preview", headers=auth, json={"kind": "deck", "subject_id": subject}
    ).json()
    assert p["cloud"] is True  # aún no se ha gastado nada
    db = connect(settings.db_path)
    db.execute(
        "INSERT INTO cloud_requests(owner_id, kind, task, via, model, status, cost_usd)"
        " SELECT id, 'deck', 'x', 'api', 'claude-sonnet-5-5', 'ok', 1 FROM users LIMIT 1"
    )
    db.close()
    p = client.post(
        "/api/v1/cloud/preview", headers=auth, json={"kind": "deck", "subject_id": subject}
    ).json()
    assert p["cloud"] is False and p["reason"] == "limit"
    r = client.post(
        "/api/v1/cloud/consents", headers=auth, json={"kind": "deck", "subject_id": subject}
    )
    assert r.status_code == 409


def test_offline_falls_back_to_local(
    client: TestClient, auth: H, subject: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "API_BASE_URL", "http://127.0.0.1:9")  # puerto cerrado
    _enable(client, auth)
    cid = _consent(client, auth, kind="deck", subject_id=subject)
    deck = _deck(client, auth, subject, consent_id=cid)
    assert deck["status"] == "ready" and deck["model"] == "qwen3.5:9b"
    rows = _requests(settings)
    assert len(rows) == 1 and rows[0]["status"] == "failed" and rows[0]["error"] == "cloud_offline"
    db = connect(settings.db_path)
    stats = json.loads(
        db.execute("SELECT stats_json FROM decks WHERE id = ?", (deck["id"],)).fetchone()[0]
    )
    db.close()
    assert stats["cloud"]["stopped"] == "Sin conexión con Claude"


# ------------------------------------------------------------------ asistente
def test_chat_sends_exactly_the_previewed_fragments(
    client: TestClient,
    auth: H,
    api: FakeAnthropic,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    f = FakeChat()
    from app.resources import manager
    from app.services import llm

    monkeypatch.setattr(llm, "provider", lambda: f)
    monkeypatch.setattr(manager, "available_mb", lambda: 10_000)
    sid = _subject(client, auth, "Biología")
    _source(client, auth, sid, "Célula", "La mitocondria produce la energía de la célula.")
    _enable(client, auth)
    tid = _thread(client, auth, subject_id=sid)
    q = "¿Qué produce la mitocondria?"
    p = client.post(
        "/api/v1/cloud/preview", headers=auth, json={"kind": "chat", "thread_id": tid, "text": q}
    ).json()
    assert p["cloud"] and p["fragments"] == 1 and "La mitocondria produce" in p["text"]
    cid = _consent(client, auth, kind="chat", thread_id=tid, text=q)
    api.reply = "La mitocondria produce la energía [A0]."
    r = client.post(
        f"/api/v1/chat/threads/{tid}/messages", headers=auth, json={"text": q, "consent_id": cid}
    )
    assert r.status_code == 202
    import time

    for _ in range(300):
        m = client.get(f"/api/v1/chat/messages/{r.json()['id']}", headers=auth).json()
        if m["status"] not in ("queued", "streaming"):
            break
        time.sleep(0.02)
    assert m["status"] == "done" and m["model"] == "claude-sonnet-5-5" and m["citations"]
    sent = api.bodies[-1]["messages"][-1]["content"]
    assert "La mitocondria produce la energía de la célula." in sent and f.requests == []
    # Una pregunta sin nada que buscar ni crear: «no encontrado» sin enviar nada.
    p = client.post(
        "/api/v1/cloud/preview",
        headers=auth,
        json={"kind": "chat", "thread_id": tid, "text": "Kubernetes"},
    ).json()
    assert p["cloud"] is False and p["sends"] is False
    assert _ask(client, auth, tid, "Kubernetes")["status"] == "not_found"
    assert len(_requests(settings)) == 1


# ------------------------------------------------------------------ clave y plan
def test_api_key_lives_in_keychain_not_in_db(
    client: TestClient, auth: H, settings: Settings, no_real_cloud: Any
) -> None:
    st = _enable(client, auth)
    assert st["api_key"] == "…xxxx" and st["via"] == "api"
    assert any("sk-ant-test-" in v for v in no_real_cloud.items.values())
    db = connect(settings.db_path)
    dump = "\n".join(db.iterdump())
    db.close()
    assert "sk-ant-test-" not in dump
    assert (
        client.put(
            "/api/v1/cloud/api-key", headers=auth, json={"key": "no-es-clave-de-anthropic"}
        ).status_code
        == 422
    )
    st = client.delete("/api/v1/cloud/api-key", headers=auth).json()
    assert st["api_key"] is None and st["via"] is None and not no_real_cloud.items


FAKE_CLAUDE = """#!{python}
import json, os, sys
log = {log!r}
if sys.argv[1:3] == ["auth", "status"]:
    print(json.dumps({{"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro",
                      "email": "secreto@ejemplo.com"}}))
    sys.exit(0)
prompt = sys.stdin.read()
with open(log, "a") as f:
    env = sorted(k for k in os.environ if k.startswith("ANTHROPIC"))
    f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "prompt": prompt,
                        "env": env}}) + "\\n")
import re
ids = re.findall(r"\\[([A-Z]\\d+)\\]", prompt)
text = f"La mitocondria produce energía [{{ids[0]}}]."
print(json.dumps({{"type": "stream_event", "event": {{"type": "content_block_delta",
                  "delta": {{"type": "text_delta", "text": text}}}}}}))
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": text,
                  "total_cost_usd": 0.0123, "usage": {{"input_tokens": 900, "output_tokens": 40}},
                  "modelUsage": {{"claude-sonnet-5-5": {{}}}}}}))
"""


def test_plan_via_runs_claude_code_without_tools_or_credentials(
    client: TestClient,
    auth: H,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = tmp_path / "claude.log"
    binary = tmp_path / "claude"
    binary.write_text(FAKE_CLAUDE.format(python=sys.executable, log=str(log)))
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(claude_code, "find_binary", lambda: str(binary))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-del-entorno")
    f = FakeChat()
    from app.resources import manager
    from app.services import llm

    monkeypatch.setattr(llm, "provider", lambda: f)
    monkeypatch.setattr(manager, "available_mb", lambda: 10_000)
    sid = _subject(client, auth, "Biología")
    _source(client, auth, sid, "Célula", "La mitocondria produce la energía de la célula.")
    st = _enable(client, auth, key=False)
    assert st["via"] == "plan" and st["plan"] == {
        "installed": True,
        "logged_in": True,
        "plan": "pro",
    }
    assert "secreto" not in json.dumps(st)  # solo se leen campos no secretos
    tid = _thread(client, auth, subject_id=sid)
    q = "¿Qué produce la mitocondria?"
    assert _ask(client, auth, tid, q)["model"] == "qwen3.5:9b"  # sin consentimiento: local
    assert not log.exists()
    cid = _consent(client, auth, kind="chat", thread_id=tid, text=q)
    r = client.post(
        f"/api/v1/chat/threads/{tid}/messages", headers=auth, json={"text": q, "consent_id": cid}
    )
    import time

    for _ in range(300):
        m = client.get(f"/api/v1/chat/messages/{r.json()['id']}", headers=auth).json()
        if m["status"] not in ("queued", "streaming"):
            break
        time.sleep(0.02)
    assert m["status"] == "done" and m["model"] == "claude-sonnet-5-5" and m["citations"]
    call = json.loads(log.read_text().splitlines()[-1])
    argv = call["argv"]
    assert argv[argv.index("--tools") + 1] == "" and "--strict-mcp-config" in argv
    assert argv[argv.index("--setting-sources") + 1] == "" and "--disable-slash-commands" in argv
    assert (
        "--no-session-persistence" in argv
        and argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    )
    assert call["env"] == [] and "La mitocondria produce" in call["prompt"]
    assert not os.path.exists(call["cwd"])  # carpeta temporal ya borrada
    rows = _requests(settings)
    assert rows[-1]["via"] == "plan" and rows[-1]["cost_usd"] == pytest.approx(0.0123)
    assert client.get("/api/v1/cloud/status", headers=auth).json()["spent"][
        "plan"
    ] == pytest.approx(0.0123)


def test_prompt_never_starts_with_a_slash_command() -> None:
    assert claude_code.render_prompt([{"role": "user", "content": "/login"}]).startswith("Mensaje:")
