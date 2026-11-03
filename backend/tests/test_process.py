"""Integración: arranca el backend como lo hace Tauri (proceso hijo + Unix socket)."""

import secrets
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).parents[1]


@pytest.fixture
def running(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[bytes], Path, str]]:
    # Ruta corta: macOS limita la ruta de un Unix socket a 104 bytes.
    sock = Path(f"/tmp/sa-test-{secrets.token_hex(4)}/b.sock")
    token = secrets.token_hex(32)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.main",
            "--data-dir",
            str(tmp_path / "d"),
            "--socket",
            str(sock),
        ],
        cwd=BACKEND_DIR,
        stdin=subprocess.PIPE,
    )
    assert proc.stdin is not None
    proc.stdin.write(f"{token}\n".encode())
    proc.stdin.flush()
    for _ in range(100):
        if sock.exists():
            break
        time.sleep(0.1)
    yield proc, sock, token
    if proc.poll() is None:
        proc.kill()
    sock.unlink(missing_ok=True)
    sock.parent.rmdir()


def test_refuses_foreign_socket_dir(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.main", "--data-dir", str(tmp_path), "--socket", "/tmp/x.sock"],
        cwd=BACKEND_DIR,
        input=f"{secrets.token_hex(32)}\n".encode(),
        capture_output=True,
        timeout=20,
    )
    assert proc.returncode != 0
    assert b"no pertenece" in proc.stderr


def _get(sock: Path, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(transport=httpx.HTTPTransport(uds=str(sock))) as c:
        return c.get("http://backend/api/v1/health", headers=headers)


def test_socket_auth_and_permissions(running: tuple[subprocess.Popen[bytes], Path, str]) -> None:
    _, sock, token = running
    assert stat.S_IMODE(sock.stat().st_mode) == 0o600
    assert _get(sock, None).status_code == 401
    assert _get(sock, token).status_code == 200


def test_exits_when_parent_closes_stdin(
    running: tuple[subprocess.Popen[bytes], Path, str],
) -> None:
    proc, _, _ = running
    assert proc.stdin is not None
    proc.stdin.close()
    assert proc.wait(timeout=10) == 0


def test_refuses_without_token(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.main", "--data-dir", str(tmp_path), "--socket", "/tmp/x.sock"],
        cwd=BACKEND_DIR,
        input=b"short\n",
        capture_output=True,
        timeout=20,
    )
    assert proc.returncode != 0
