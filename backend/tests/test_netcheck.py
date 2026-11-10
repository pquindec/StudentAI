"""Prueba de red del aula (Fase 9.5, paso 0): servidor de prueba y veredicto."""

# ruff: noqa: S310 (solo se abre http://127.0.0.1)

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.live import lan, netcheck

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15"
    " Version/26.1 Mobile/15E148 Safari/604.1"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 16; Pixel 9) AppleWebKit/537.36 Chrome/142.0 Mobile Safari/537.36"
)


@pytest.fixture
def served() -> Iterator[tuple[netcheck.Server, list[str]]]:
    events: list[str] = []
    check = netcheck.Check("tok123", on_event=events.append)
    server = netcheck.Server("127.0.0.1", 0, check)
    server.start()
    yield server, events
    server.stop()


def call(
    url: str, data: Any = None, ua: str = IPHONE, raw: bytes | None = None
) -> tuple[int, dict[str, str], bytes]:
    body = raw if raw is not None else (None if data is None else json.dumps(data).encode())
    req = urllib.request.Request(
        url, data=body, headers={"User-Agent": ua, "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_only_the_secret_path_is_served(served: tuple[netcheck.Server, list[str]]) -> None:
    server, _ = served
    root = server.url.split("/t/")[0]
    for path in (
        "/",
        "/t/otro/",
        "/api/v1/subjects",
        "/t/tok123/../../etc/passwd",
        "/t/tok123/nada",
    ):
        assert call(root + path)[0] == 404
    status, headers, body = call(server.url)
    assert status == 200 and b"Prueba de red del aula" in body
    csp = headers["Content-Security-Policy"]
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in body.decode() and "default-src 'none'" in csp
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    assert "Server" not in headers or "Python" not in headers["Server"]


def test_full_device_flow_and_verdict(
    served: tuple[netcheck.Server, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    server, events = served
    monkeypatch.setattr(netcheck, "SSE_TICKS", 2)
    status, _, body = call(server.url + "hello", {}, ua=ANDROID)
    d = json.loads(body)
    assert status == 200 and d == {"id": 1, "label": "Dispositivo 1 (Android · Chrome)"}
    assert call(server.url + "ping")[0] == 204
    status, headers, body = call(server.url + "events")
    assert headers["Content-Type"] == "text/event-stream"
    assert body.decode().count("data: ") == 3 and "event: done" in body.decode()  # 2 + fin
    ok = {"id": 1, "rtt_median_ms": 12.3, "rtt_p95_ms": 30, "sse_received": 2}
    assert call(server.url + "report", ok)[0] == 204
    assert call(server.url + "report", {"id": 1, "type": "reconnect", "ok": True})[0] == 204
    assert any("ha llegado al Mac" in e for e in events) and any("reconexión" in e for e in events)


def test_reports_are_validated(served: tuple[netcheck.Server, list[str]]) -> None:
    server, _ = served
    call(server.url + "hello", {})
    bad = [
        {"id": 99, "rtt_median_ms": 1, "rtt_p95_ms": 1, "sse_received": 1},
        {"id": "1", "rtt_median_ms": 1, "rtt_p95_ms": 1, "sse_received": 1},
        {"id": True, "rtt_median_ms": 1, "rtt_p95_ms": 1, "sse_received": 1},
        {"id": 1, "rtt_median_ms": "x", "rtt_p95_ms": 1, "sse_received": 1},
        [1, 2],
    ]
    for data in bad:
        assert call(server.url + "report", data)[0] == 400
    assert call(server.url + "report", raw=b"{roto")[0] == 400
    assert call(server.url + "report", raw=b"x" * 5000)[0] == 413


def test_https_attempt_is_detected(served: tuple[netcheck.Server, list[str]]) -> None:
    server, events = served
    host, port = server.httpd.server_address[:2]
    hello = bytes.fromhex("160301") + b"\x00\x2a" + bytes(42) + b"\r\n"  # inicio de un saludo TLS
    with socket.create_connection((str(host), int(port)), timeout=5) as s:
        s.sendall(hello)
        assert s.recv(100) == b""  # se cierra sin responder HTTP
    assert any("HTTPS" in e for e in events)
    assert call(server.url + "ping")[0] == 204  # el servidor sigue funcionando


def test_rate_limit(
    served: tuple[netcheck.Server, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    server, _ = served
    monkeypatch.setattr(netcheck, "RATE_PER_MIN", 3)
    codes = [call(server.url + "ping")[0] for _ in range(5)]
    assert codes[:3] == [204] * 3 and codes[3:] == [429, 429]


def test_verdicts() -> None:
    c = netcheck.Check("t", on_event=lambda _: None)
    ok, msg = c.verdict()
    assert not ok and "aísla" in msg
    d = c.hello(IPHONE)
    assert d is not None and d.label == "Dispositivo 1 (iPhone · Safari)"
    assert not c.verdict()[0]  # llegó, pero no terminó
    c.report({"id": 1, "rtt_median_ms": 10, "rtt_p95_ms": 20, "sse_received": 7})
    ok, msg = c.verdict()
    assert not ok and "consultas periódicas" in msg
    c.report({"id": 1, "rtt_median_ms": 10, "rtt_p95_ms": 20, "sse_received": netcheck.SSE_TICKS})
    assert c.verdict() == (True, "La Wi-Fi permite el examen en vivo: 1 dispositivo(s) correctos.")


def test_qr_svg(tmp_path: Path) -> None:
    svg = lan.qr_svg("http://192.168.1.20:8765/t/abc/", tmp_path / "qr.svg").read_text()
    assert svg.startswith("<?xml") and "<svg" in svg and "#fff" in svg


def test_describe_and_private_ips() -> None:
    assert netcheck.describe(ANDROID) == ("Android", "Chrome")
    assert netcheck.describe(IPHONE) == ("iPhone", "Safari")
    assert (
        netcheck.describe("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Firefox/140.0")[0]
        == "Mac"
    )
    assert lan.is_private("192.168.1.20") and lan.is_private("10.20.0.5")
    assert lan.is_private("100.67.1.20")  # Wi-Fi de la universidad (RFC 6598)
    for ip in ("127.0.0.1", "8.8.8.8", "169.254.1.1", "100.128.0.1", "nada", "::1"):
        assert not lan.is_private(ip)
    qr = lan.qr_terminal("http://192.168.1.20:8765/t/abc/").splitlines()
    assert len(qr) > 10 and len({len(line) for line in qr if line}) == 1  # cuadrado
