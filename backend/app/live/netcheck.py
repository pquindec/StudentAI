"""Prueba de red del aula (Fase 9.5, paso 0).

    cd backend && uv run python -m app.live.netcheck [--minutes 20] [--port 8765]

Abre un servidor de prueba en la IP de la Wi-Fi del Mac y muestra un QR. Desde cada teléfono se
escanea y la página comprueba: que llega al Mac, la latencia, la conexión en tiempo real (SSE) y
la reconexión tras bloquear el teléfono. Al terminar dice si la Wi-Fi sirve para el examen en vivo.

Solo sirve la página de prueba, en una ruta aleatoria, y se apaga sola. No accede a los datos de
la app. Guarda un resumen sin IPs en `bench/results/netcheck.json`.
"""

import argparse
import contextlib
import json
import secrets
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.live import lan

MAX_BODY = 2048
MAX_DEVICES = 50
RATE_PER_MIN = 600
SSE_TICKS = 15
PAGE = (Path(__file__).parent / "netcheck.html").read_text(encoding="utf-8")


class _HTTPServer(ThreadingHTTPServer):
    """Cola de conexiones amplia: la de por defecto (5) se desborda con varios teléfonos."""

    request_queue_size = 128
    daemon_threads = True


@dataclass
class Device:
    n: int
    kind: str
    browser: str
    rtt_median_ms: float | None = None
    rtt_p95_ms: float | None = None
    sse_received: int | None = None
    sse_expected: int = SSE_TICKS
    reconnect_ok: bool | None = None
    events: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"Dispositivo {self.n} ({self.kind} · {self.browser})"


def describe(ua: str) -> tuple[str, str]:
    """Tipo de dispositivo y navegador a partir del User-Agent (no se guarda el texto completo)."""
    if "iPhone" in ua:
        kind = "iPhone"
    elif "iPad" in ua or ("Macintosh" in ua and "Mobile" in ua):
        kind = "iPad"
    elif "Android" in ua:
        kind = "Android"
    elif "Macintosh" in ua:
        kind = "Mac"
    elif "Windows" in ua:
        kind = "Windows"
    else:
        kind = "otro"
    if "SamsungBrowser" in ua:
        browser = "Samsung Internet"
    elif "Firefox" in ua or "FxiOS" in ua:
        browser = "Firefox"
    elif "Edg" in ua:
        browser = "Edge"
    elif "Chrome" in ua or "CriOS" in ua:
        browser = "Chrome"
    elif "Safari" in ua:
        browser = "Safari"
    else:
        browser = "otro"
    return kind, browser


class Check:
    """Estado compartido de la prueba (lo usan los hilos del servidor)."""

    def __init__(self, token: str, on_event: Any = print) -> None:
        self.token = token
        self.devices: dict[int, Device] = {}
        self.lock = threading.Lock()
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.on_event = on_event
        self.https_attempts = 0

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= RATE_PER_MIN:
                return False
            q.append(now)
            return True

    def hello(self, ua: str) -> Device | None:
        with self.lock:
            if len(self.devices) >= MAX_DEVICES:
                return None
            kind, browser = describe(ua)
            d = Device(len(self.devices) + 1, kind, browser)
            self.devices[d.n] = d
        self.on_event(f"📱 {d.label}: ha llegado al Mac")
        return d

    def report(self, data: dict[str, Any]) -> bool:
        n = data.get("id")
        if not isinstance(n, int) or isinstance(n, bool):
            return False
        with self.lock:
            d = self.devices.get(n)
        if d is None:
            return False
        if data.get("type") == "reconnect":
            ok = data.get("ok") is True
            d.reconnect_ok = ok
            self.on_event(f"   {d.label}: reconexión tras bloquear {'✓' if ok else '✗'}")
            return True
        med, p95, sse = data.get("rtt_median_ms"), data.get("rtt_p95_ms"), data.get("sse_received")
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (med, p95, sse)):
            return False
        assert isinstance(med, int | float) and isinstance(p95, int | float)  # noqa: S101 (mypy)
        assert isinstance(sse, int | float)  # noqa: S101
        d.rtt_median_ms = round(min(max(float(med), 0), 60_000), 1)
        d.rtt_p95_ms = round(min(max(float(p95), 0), 60_000), 1)
        d.sse_received = int(min(max(sse, 0), SSE_TICKS))
        self.on_event(
            f"   {d.label}: latencia {d.rtt_median_ms} ms (p95 {d.rtt_p95_ms}) · "
            f"tiempo real {d.sse_received}/{SSE_TICKS} "
            f"{'✓' if d.sse_received == SSE_TICKS else '✗'}"
        )
        return True

    def https_attempt(self) -> None:
        """Un navegador habló HTTPS (TLS) con este servidor HTTP: p. ej. Samsung Internet."""
        with self.lock:
            self.https_attempts += 1
            first = self.https_attempts == 1
        if first:
            self.on_event(
                "🔒 Un navegador intentó conectar con HTTPS y no puede abrir la página "
                "(Samsung Internet lo hace). Abre el enlace en Chrome o desactiva su ajuste de "
                "conexiones seguras."
            )

    def verdict(self) -> tuple[bool, str]:
        ok, msg = self._verdict()
        if self.https_attempts:
            msg += (
                f" Además, {self.https_attempts} conexión(es) por HTTPS fallaron: algún navegador "
                "(p. ej. Samsung Internet) fuerza conexiones seguras."
            )
        return ok, msg

    def _verdict(self) -> tuple[bool, str]:
        ds = list(self.devices.values())
        if not ds:
            return False, (
                "Ningún dispositivo llegó al Mac. Si el QR abrió el enlace pero la página no "
                "cargó, "
                "la Wi-Fi aísla los dispositivos (o el cortafuegos bloqueó la conexión). Siguiente "
                "paso: decidir la alternativa (router de viaje propio o túnel)."
            )
        tested = [d for d in ds if d.sse_received is not None]
        if not tested:
            return False, "Los dispositivos llegaron, pero ninguno terminó la prueba: repítela."
        if any(d.sse_received != SSE_TICKS for d in tested):
            return False, (
                "Los dispositivos llegan, pero la conexión en tiempo real se corta. El examen en "
                "vivo es posible con consultas periódicas en lugar de tiempo real."
            )
        slow = [d for d in tested if (d.rtt_p95_ms or 0) > 500]
        extra = (
            " Hay latencias altas (p95 > 500 ms): conviene repetir con más dispositivos."
            if slow
            else ""
        )
        return (
            True,
            f"La Wi-Fi permite el examen en vivo: {len(tested)} dispositivo(s) correctos.{extra}",
        )


def make_handler(check: Check) -> type[BaseHTTPRequestHandler]:
    prefix = f"/t/{check.token}/"

    class Handler(BaseHTTPRequestHandler):
        server_version = "netcheck"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            return  # sin registros: no se guardan IPs ni rutas

        def send_error(
            self, code: int, message: str | None = None, explain: str | None = None
        ) -> None:
            # Un saludo TLS empieza por 0x16 0x03: el navegador intentó HTTPS en un puerto HTTP.
            if getattr(self, "raw_requestline", b"")[:2] == b"\x16\x03":
                check.https_attempt()
                self.close_connection = True
                return
            super().send_error(code, message, explain)

        def _send(self, status: int, body: bytes = b"", ctype: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _route(self) -> str | None:
            path = self.path.split("?", 1)[0]
            if not check.allow(self.client_address[0]):
                self._send(429)
                return None
            if not path.startswith(prefix):
                self._send(404)
                return None
            return path[len(prefix) :]

        def _json(self) -> dict[str, Any] | None:
            length = self.headers.get("Content-Length")
            if length is None or not length.isdigit():
                self._send(411)
                return None
            if int(length) > MAX_BODY:
                self._send(413)
                return None
            try:
                data = json.loads(self.rfile.read(int(length)) or b"{}")
            except ValueError:
                self._send(400)
                return None
            if not isinstance(data, dict):
                self._send(400)
                return None
            return data

        def do_GET(self) -> None:
            route = self._route()
            if route is None:
                return
            if route == "":
                nonce = secrets.token_urlsafe(12)
                body = PAGE.replace("{nonce}", nonce).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy",
                    f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                    "connect-src 'self'; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'none'",
                )
                self.end_headers()
                self.wfile.write(body)
            elif route == "ping":
                self._send(204)
            elif route == "events":
                self._events()
            else:
                self._send(404)

        def _events(self) -> None:
            ticks = SSE_TICKS
            if "short=1" in self.path:
                ticks = 3
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                for i in range(1, ticks + 1):
                    self.wfile.write(f"data: {i}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(1)
                self.wfile.write(b"event: done\ndata: end\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self) -> None:
            route = self._route()
            if route is None:
                return
            data = self._json()
            if data is None:
                return
            if route == "hello":
                d = check.hello(self.headers.get("User-Agent", "")[:400])
                if d is None:
                    self._send(503)
                    return
                self._send(200, json.dumps({"id": d.n, "label": d.label}).encode())
            elif route == "report":
                self._send(204 if check.report(data) else 400)
            else:
                self._send(404)

    return Handler


class Server:
    def __init__(self, ip: str, port: int, check: Check) -> None:
        try:
            self.httpd = _HTTPServer((ip, port), make_handler(check))
        except OSError:
            self.httpd = _HTTPServer((ip, 0), make_handler(check))  # puerto ocupado
        self.httpd.daemon_threads = True
        self.port = int(self.httpd.server_address[1])
        self.url = f"http://{ip}:{self.port}/t/{check.token}/"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def save(check: Check, ip: str, ok: bool, msg: str, out: Path) -> None:
    devices = [
        {k: v for k, v in asdict(d).items() if k != "events"} for d in check.devices.values()
    ]
    rtts = [d.rtt_median_ms for d in check.devices.values() if d.rtt_median_ms is not None]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "date": datetime.now(UTC).isoformat(timespec="seconds"),
                "private_network": lan.is_private(ip),
                "ok": ok,
                "verdict": msg,
                "devices": devices,
                "https_attempts": check.https_attempts,
                "rtt_median_ms_all": round(statistics.median(rtts), 1) if rtts else None,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Prueba de red del aula")
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ip", help="IP del Mac (por defecto, la de la Wi-Fi)")
    ap.add_argument("--no-open", action="store_true", help="no abrir el QR como imagen")
    a = ap.parse_args()

    ip = a.ip or lan.wifi_ip()
    if not ip or not lan.is_private(ip):
        sys.exit("No encuentro la IP de la Wi-Fi del Mac. ¿Estás conectado a la Wi-Fi?")
    fw = lan.firewall()
    check = Check(secrets.token_urlsafe(6))
    server = Server(ip, a.port, check)

    print("\nPrueba de red del aula — escanea el QR con 2 o 3 teléfonos (Android e iPhone)\n")
    print(lan.qr_terminal(server.url))
    print(f"   {server.url}\n")
    if not a.no_open:
        svg = lan.qr_svg(server.url, Path(tempfile.mkdtemp(prefix="netcheck-")) / "qr.svg")
        subprocess.run(["/usr/bin/open", str(svg)], check=False)  # noqa: S603
        print("   (El QR también se ha abierto como imagen grande: más fácil de escanear.)\n")
    print("1. Conecta los teléfonos a la MISMA Wi-Fi que el Mac (la de la universidad).")
    print("2. Escanea el QR con la cámara y abre el enlace. La prueba tarda unos 20 s.")
    print("3. Después, bloquea el teléfono 10 s, desbloquéalo y vuelve a la página.")
    if fw["block_all"]:
        print(
            "\n⚠️  El cortafuegos bloquea TODAS las conexiones entrantes: "
            "desactívalo para la prueba."
        )
    elif fw["enabled"]:
        print("\n⚠️  Cortafuegos activado: si macOS pregunta, pulsa «Permitir» para Python.")
    print(f"\nSe apaga sola en {a.minutes:g} min. Ctrl+C para terminar antes.\n")

    server.start()
    with contextlib.suppress(KeyboardInterrupt):
        time.sleep(a.minutes * 60)
    server.stop()
    ok, msg = check.verdict()
    out = Path(__file__).resolve().parents[3] / "bench" / "results" / "netcheck.json"
    save(check, ip, ok, msg, out)
    print(f"\n{'✅' if ok else '❌'} {msg}\nResumen (sin IPs): {out}")


if __name__ == "__main__":
    main()
