"""Acceso a la sala por internet (túnel de Cloudflare). Con un `cloudflared` falso que imprime lo
mismo que el real: en las pruebas no sale nada a internet."""

# ruff: noqa: F811, S310
# F811: `exam` es un fixture importado de test_live. S310: solo se abre http://127.0.0.1.

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.live import room, tunnel
from tests.test_live import Phone, _host, _open, exam  # noqa: F401

H = dict[str, str]
URL = "https://pruebas-falsas-de-sala.trycloudflare.com"

READY = f"""
import sys, time, pathlib
pathlib.Path(sys.argv[0] + ".pid").write_text(str(__import__("os").getpid()))
pathlib.Path(sys.argv[0] + ".args").write_text(" ".join(sys.argv[1:]))
print("INF Requesting new quick Tunnel on trycloudflare.com...", flush=True)
print("INF |  {URL}  |", flush=True)
print("INF Registered tunnel connection connIndex=0 protocol=http2", flush=True)
time.sleep(600)
"""
SILENT = "import time\ntime.sleep(600)\n"
DIES = f"print('{URL}', flush=True)\nraise SystemExit(1)\n"


def fake(tmp_path: Path, body: str, name: str = "cloudflared") -> Path:
    exe = tmp_path / name
    exe.write_text(f"#!{sys.executable}\n{body}")
    exe.chmod(0o755)
    return exe


def until(cond: Callable[[], bool], seconds: float = 10) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("no se cumplió a tiempo")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def get(url: str, cf_ip: str | None = None) -> int:
    headers = {"CF-Connecting-IP": cf_ip} if cf_ip else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return e.code


def test_tunnel_gives_phones_the_internet_address(
    client: TestClient,
    auth: H,
    exam: dict[str, Any],
    tmp_path: Path,
    room_on_loopback: room.Manager,
) -> None:
    s = _open(client, auth, exam["id"], mode="quiz")
    lid, local, local_qr = s["id"], s["url"], s["qr"]
    assert s["tunnel"] == {"status": "off", "url": None, "error": None}

    # Sin cloudflared instalado: se explica cómo instalarlo.
    room_on_loopback.find_cloudflared = lambda: None
    r = client.post(f"/api/v1/live/{lid}/tunnel", headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "tunnel_unavailable"
    assert "brew install cloudflared" in r.json()["error"]["message"]

    exe = fake(tmp_path, READY)
    room_on_loopback.find_cloudflared = lambda: exe
    _host(client, auth, lid, "tunnel")
    until(lambda: _host(client, auth, lid)["tunnel"]["status"] == "on")
    s = _host(client, auth, lid)
    assert s["tunnel"]["url"] == URL
    assert s["url"] == f"{URL}/s/{s['code']}/"  # el QR lleva a la dirección de internet
    assert s["qr"] and s["qr"] != local_qr  # se genera con esa dirección
    args = Path(f"{exe}.args").read_text()
    assert args.endswith(f"--protocol http2 --url {local.split('/s/')[0]}")
    pid = int(Path(f"{exe}.pid").read_text())

    # Activarlo otra vez no abre un segundo túnel.
    _host(client, auth, lid, "tunnel")
    assert int(Path(f"{exe}.pid").read_text()) == pid

    # Desactivarlo: vuelve la dirección local y el proceso se cierra.
    s = _host(client, auth, lid, "tunnel", method="DELETE")
    assert s["tunnel"]["status"] == "off" and s["url"] == local
    until(lambda: not alive(pid))

    # Cerrar la sala (la última abierta) también cierra el túnel.
    _host(client, auth, lid, "tunnel")
    until(lambda: _host(client, auth, lid)["tunnel"]["status"] == "on")
    pid = int(Path(f"{exe}.pid").read_text())
    _host(client, auth, lid, "close")
    until(lambda: not alive(pid))
    assert room_on_loopback.tunnel is None
    r = client.post(f"/api/v1/live/{lid}/tunnel", headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "live_closed"


def test_rate_limits_use_the_real_phone_ip_only_through_the_tunnel(
    client: TestClient,
    auth: H,
    exam: dict[str, Any],
    tmp_path: Path,
    room_on_loopback: room.Manager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(room, "RATE_PER_MIN", 3)
    s = _open(client, auth, exam["id"], mode="practice")
    page = s["url"]

    # Sin túnel, la cabecera no cuenta: alguien de la red no puede saltarse el límite con ella.
    assert [get(page, f"10.0.0.{i}") for i in range(4)] == [200, 200, 200, 429]

    exe = fake(tmp_path, READY)
    room_on_loopback.find_cloudflared = lambda: exe
    room_on_loopback.guard.hits.clear()
    _host(client, auth, s["id"], "tunnel")
    until(lambda: _host(client, auth, s["id"])["tunnel"]["status"] == "on")
    # Con el túnel, cada teléfono tiene su propio límite (no uno para toda la clase).
    for ip in ("203.0.113.5", "2001:db8::7", "198.51.100.9"):
        assert [get(page, ip) for _ in range(3)] == [200, 200, 200]
        assert get(page, ip) == 429
    assert get(page, "no-es-una-ip") == 200  # cabecera inválida: cuenta la conexión real
    assert Phone(page).join("Ana")[0] == 201  # sin cabecera: cuenta la conexión real


def test_tunnel_failures_are_reported(
    client: TestClient,
    auth: H,
    exam: dict[str, Any],
    tmp_path: Path,
    room_on_loopback: room.Manager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lid = _open(client, auth, exam["id"])["id"]

    # Cloudflare no responde a tiempo.
    monkeypatch.setattr(tunnel, "START_TIMEOUT_S", 0.5)
    room_on_loopback.find_cloudflared = lambda: fake(tmp_path, SILENT, "silencioso")
    _host(client, auth, lid, "tunnel")
    until(lambda: _host(client, auth, lid)["tunnel"]["status"] == "error")
    t = _host(client, auth, lid)["tunnel"]
    assert "no respondió" in t["error"] and _host(client, auth, lid)["url"].startswith("http://")

    # Se cierra solo: se avisa y se puede reintentar.
    monkeypatch.setattr(tunnel, "START_TIMEOUT_S", 45)
    room_on_loopback.find_cloudflared = lambda: fake(tmp_path, DIES, "muere")
    _host(client, auth, lid, "tunnel")
    until(lambda: _host(client, auth, lid)["tunnel"]["status"] == "error")
    assert "se cerró" in _host(client, auth, lid)["tunnel"]["error"]
    s = _host(client, auth, lid, "tunnel", method="DELETE")
    assert s["tunnel"] == {"status": "off", "url": None, "error": None}


def test_cloudflared_dies_with_the_backend(tmp_path: Path) -> None:
    """Si el backend muere de golpe, cloudflared no se queda abierto."""
    exe = fake(tmp_path, READY)
    parent = subprocess.Popen(["/bin/sleep", "60"])
    t = tunnel.Tunnel(exe, "http://127.0.0.1:9", parent_pid=parent.pid)
    try:
        until(lambda: t.status == "on")
        pid = int(Path(f"{exe}.pid").read_text())
        assert alive(pid)
        parent.kill()
        parent.wait()
        until(lambda: not alive(pid), seconds=5)
        until(lambda: t.status == "error")
    finally:
        t.stop()
