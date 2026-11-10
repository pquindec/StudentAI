"""Servidor de la sala en la red local (Fase 9.5, ADR-012).

Separado de la API principal (que sigue solo en el Unix socket): escucha en la IP de la Wi-Fi
mientras haya alguna sala abierta y solo ofrece las rutas del participante, bajo el código de su
sala (`/s/<CÓDIGO>/`). Cada petición abre su propia conexión a la BD.
"""

import ipaddress
import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.core.errors import AppError
from app.db.connection import connect
from app.live import lan, tunnel
from app.live.netcheck import describe
from app.services import live

log = logging.getLogger(__name__)
WEB_PORT = 80  # el de cualquier página web: el que menos redes filtran
PORT = 8765  # si el 80 no se puede usar
MAX_BODY = 20_000  # una respuesta corta de 4.000 caracteres en UTF-8 cabe con margen
RATE_PER_MIN = 600
BAD_CODES_PER_10_MIN = 30
IP_CACHE_S = 10
CAFFEINATE = Path("/usr/bin/caffeinate")
PAGE = (Path(__file__).parent / "room.html").read_text(encoding="utf-8")
ROUTE = re.compile(r"^/s/([A-Za-z0-9]{1,16})/(join|state|answer|submit|left)?$")
NOT_FOUND_PAGE = (
    "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
    "<title>Sala no encontrada</title><body style='font:17px system-ui;padding:24px'>"
    "<h1>Sala no encontrada</h1><p>El código no existe o la sala ya se cerró.</p>"
)


class Server(ThreadingHTTPServer):
    """Con 20 teléfonos escaneando a la vez, la cola por defecto (5 conexiones) se desborda y
    macOS rechaza el resto («connection reset»)."""

    request_queue_size = 128
    daemon_threads = True
    only_ip: str | None = None

    def verify_request(self, request: Any, client_address: Any) -> bool:
        # En el puerto 80 se escucha en todas las interfaces: solo se atiende lo que llega por la
        # IP de la Wi-Fi (ni localhost, ni VPN, ni cable).
        return self.only_ip is None or request.getsockname()[0] == self.only_ip


def bind(ip: str, handler: Callable[..., Any]) -> Server:
    """Primero el puerto 80, por si la red solo deja pasar el tráfico web. macOS solo lo deja usar
    sin ser administrador escuchando en todas las interfaces (0.0.0.0); por eso se filtra por IP
    en `verify_request`. Si no se puede, 8765 y, si está ocupado, uno libre."""
    if not ipaddress.ip_address(ip).is_loopback:  # en las pruebas, solo localhost
        try:
            httpd = Server(("0.0.0.0", WEB_PORT), handler)  # noqa: S104 (filtrado por IP)
            httpd.only_ip = ip
            return httpd
        except OSError:
            pass
    try:
        return Server((ip, PORT), handler)
    except OSError:
        return Server((ip, 0), handler)  # puerto ocupado


class Guard:
    """Límites por IP: peticiones por minuto y códigos de sala erróneos."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.bad: dict[str, deque[float]] = defaultdict(deque)
        self.https_attempts = 0
        self.forwarded = False  # con el túnel activo: la IP real llega en CF-Connecting-IP

    @staticmethod
    def _count(q: deque[float], window: float, now: float) -> int:
        while q and now - q[0] > window:
            q.popleft()
        return len(q)

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        with self.lock:
            if self._count(self.bad[ip], 600, now) >= BAD_CODES_PER_10_MIN:
                return False
            if self._count(self.hits[ip], 60, now) >= RATE_PER_MIN:
                return False
            self.hits[ip].append(now)
            return True

    def bad_code(self, ip: str) -> None:
        with self.lock:
            self.bad[ip].append(time.monotonic())

    def https(self) -> None:
        with self.lock:
            self.https_attempts += 1


def make_handler(db_path: Path, guard: Guard) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "sala"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            return  # sin registros de IPs ni rutas

        def send_error(
            self, code: int, message: str | None = None, explain: str | None = None
        ) -> None:
            if getattr(self, "raw_requestline", b"")[:2] == b"\x16\x03":  # saludo TLS
                guard.https()
                self.close_connection = True
                return
            super().send_error(code, message, explain)

        def _headers(self, status: int, ctype: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")

        def _json(self, status: int, body: Any = None) -> None:
            data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode()
            self._headers(status, "application/json; charset=utf-8", len(data))
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _error(self, status: int, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def _html(self, status: int, html: str, nonce: str | None = None) -> None:
            data = html.encode()
            self._headers(status, "text/html; charset=utf-8", len(data))
            # Con nonce: solo el script y el estilo de la página. Sin él (página de error): nada
            # de scripts y solo estilos en línea.
            src = (
                f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'"
                if nonce
                else "script-src 'none'; style-src 'unsafe-inline'"
            )
            self.send_header(
                "Content-Security-Policy",
                f"default-src 'none'; {src}; connect-src 'self'; base-uri 'none';"
                " form-action 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict[str, Any] | None:
            length = self.headers.get("Content-Length")
            if length is None or not length.isdigit():
                self._error(411, "length_required", "Falta la longitud de la petición")
                return None
            if int(length) > MAX_BODY:
                self._error(413, "too_large", "La respuesta es demasiado larga")
                return None
            try:
                data = json.loads(self.rfile.read(int(length)) or b"{}")
            except ValueError:
                self._error(400, "invalid_body", "Petición no válida")
                return None
            if not isinstance(data, dict):
                self._error(400, "invalid_body", "Petición no válida")
                return None
            return data

        def _client_ip(self) -> str:
            """Por el túnel, todos los teléfonos llegan desde `cloudflared`, que corre en este Mac
            y se conecta a la IP de la Wi-Fi: los límites irían a la vez para toda la clase. Solo
            entonces (y con el túnel activo) se usa la IP que indica Cloudflare. Un dispositivo de
            la red no puede conectarse con la IP del propio Mac, así que no puede falsearla."""
            ip = str(self.client_address[0])
            server: Any = self.server
            own = server.only_ip or server.server_address[0]
            fwd = self.headers.get("CF-Connecting-IP", "").strip()
            if guard.forwarded and ip == own and fwd:
                try:
                    return "cf:" + str(ipaddress.ip_address(fwd))
                except ValueError:
                    pass
            return ip

        def _dispatch(self, method: str) -> None:
            ip = self._client_ip()
            if not guard.allow(ip):
                self._error(429, "too_many", "Demasiadas peticiones: espera un momento")
                return
            m = ROUTE.match(self.path.split("?", 1)[0])
            if m is None:
                self._html(404, NOT_FOUND_PAGE)
                return
            code, action = m.group(1).upper(), m.group(2)
            db = connect(db_path)
            try:
                session = live.by_code(db, code)
                if session is None:
                    guard.bad_code(ip)
                    if action is None:
                        self._html(404, NOT_FOUND_PAGE)
                    else:
                        self._error(404, "room_not_found", "La sala no existe o ya se cerró")
                    return
                self._handle(db, session, method, action)
            except AppError as e:
                self._error(e.status, e.code, e.message)
            except sqlite3.Error:
                log.exception("Error de BD en la sala")
                self._error(503, "busy", "Ocupado: inténtalo de nuevo")
            finally:
                db.close()

        def _handle(
            self, db: sqlite3.Connection, session: dict[str, Any], method: str, action: str | None
        ) -> None:
            if action is None:
                if method != "GET":
                    self._error(405, "method_not_allowed", "Método no permitido")
                    return
                nonce = secrets.token_urlsafe(12)
                kind = "quiz" if session.get("quiz") else "exam"  # valor fijo, nunca del usuario
                self._html(200, PAGE.replace("{nonce}", nonce).replace("{kind}", kind), nonce)
                return
            expected = "GET" if action == "state" else "POST"
            if method != expected:
                self._error(405, "method_not_allowed", "Método no permitido")
                return
            body: dict[str, Any] = {}
            if method == "POST":
                parsed = self._body()
                if parsed is None:
                    return
                body = parsed
            if action == "join":
                kind, browser = describe(self.headers.get("User-Agent", "")[:400])
                joined, token = live.join(db, session, body.get("name"), f"{kind} · {browser}")
                self._json(201, {"token": token, "status": joined["status"]})
                return
            p = live.by_token(db, session, self.headers.get("X-Live-Token", ""))
            if p is None or p["status"] == "kicked":
                self._error(401, "not_joined", "Tienes que entrar de nuevo con tu nombre")
                return
            if action == "state":
                live.seen(db, session, p, left=False)
                self._json(200, live.state_for(db, session, p))
            elif action == "left":
                live.seen(db, session, p, left=True)
                self._json(204)
            elif action == "answer":
                live.answer(db, session, p, body.get("question_id"), body.get("value"))
                self._json(204)
            elif action == "submit":
                live.submit(db, session, p)
                self._json(204)

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PUT(self) -> None:
            self._dispatch("PUT")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

    return Handler


def keep_awake() -> subprocess.Popen[bytes] | None:
    """Evita que el Mac se suspenda mientras la sala está abierta (`caffeinate -i` de macOS).
    `-w` lo ata al backend: si este se cierra de golpe, caffeinate termina solo."""
    if not CAFFEINATE.exists():
        return None
    try:
        return subprocess.Popen(  # noqa: S603  (ruta fija del sistema, sin datos del usuario)
            [str(CAFFEINATE), "-i", "-w", str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        log.warning("No se pudo evitar la suspensión del Mac durante la sala")
        return None


class RoomServer:
    def __init__(self, ip: str, db_path: Path, guard: Guard) -> None:
        handler = make_handler(db_path, guard)
        self.httpd = bind(ip, handler)
        self.httpd.daemon_threads = True
        self.ip = ip
        self.port = int(self.httpd.server_address[1])
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="sala").start()
        self.awake = keep_awake()

    @property
    def base(self) -> str:
        return f"http://{self.ip}" + ("" if self.port == WEB_PORT else f":{self.port}")

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.awake:
            self.awake.terminate()
            self.awake.wait(timeout=5)


class Manager:
    """Un único servidor para el backend: se enciende con la primera sala abierta y se apaga
    cuando no queda ninguna. Si la IP de la Wi-Fi cambia, se vuelve a abrir en la nueva."""

    def __init__(self, resolve_ip: Callable[[], str | None] = lan.wifi_ip) -> None:
        self.resolve_ip = resolve_ip
        self.lock = threading.Lock()
        self.server: RoomServer | None = None
        self.guard = Guard()
        self._ip: tuple[float, str | None] = (0.0, None)
        self.tunnel: tunnel.Tunnel | None = None
        self.tunnel_error: str | None = None  # el último, para mostrarlo hasta que se reintente
        self.find_cloudflared: Callable[[], Path | None] = tunnel.find

    def _current_ip(self) -> str | None:
        t, ip = self._ip
        if time.monotonic() - t > IP_CACHE_S:
            ip = self.resolve_ip()
            self._ip = (time.monotonic(), ip)
        return ip

    def _ensure(self, db_path: Path) -> str | None:
        ip = self._current_ip()
        if self.server and self.server.ip != ip:
            had_tunnel = self.tunnel is not None
            self._stop_server()
            if had_tunnel:
                self.tunnel_error = "La red Wi-Fi cambió: vuelve a activar el acceso por internet."
        if ip is None:
            return None
        if self.server is None:
            self.server = RoomServer(ip, db_path, self.guard)
            log.info("Sala abierta en la red local, puerto %s", self.server.port)
        return self.server.base

    def ensure(self, db_path: Path) -> str | None:
        """URL base del servidor (lo enciende si hace falta); None si no hay red local."""
        with self.lock:
            return self._ensure(db_path)

    def public_base(self, db_path: Path) -> str | None:
        """La dirección que se da a los teléfonos: la del túnel si está activo, si no la local."""
        with self.lock:
            base = self._ensure(db_path)
            if base and self.tunnel and self.tunnel.public_base:
                return self.tunnel.public_base
            return base

    def start_tunnel(self, db_path: Path) -> None:
        """Abre el túnel hacia el servidor de la sala (no espera a que Cloudflare responda)."""
        with self.lock:
            if self.tunnel and self.tunnel.status != "error":
                return
            self._stop_tunnel()
            base = self._ensure(db_path)
            if base is None:
                raise AppError(409, "no_network", "No hay conexión de red en el Mac.")
            exe = self.find_cloudflared()
            if exe is None:
                raise AppError(
                    409,
                    "tunnel_unavailable",
                    "Falta cloudflared. Instálalo en Terminal con: brew install cloudflared",
                )
            self.tunnel_error = None
            self.tunnel = tunnel.Tunnel(exe, base)
            self.guard.forwarded = True
            log.info("Acceso por internet (Cloudflare) activado")

    def stop_tunnel(self) -> None:
        with self.lock:
            self.tunnel_error = None
            self._stop_tunnel()

    def _stop_tunnel(self) -> None:
        if self.tunnel:
            self.tunnel.stop()
            self.tunnel = None
            log.info("Acceso por internet (Cloudflare) desactivado")
        self.guard.forwarded = False

    def tunnel_state(self) -> dict[str, str | None]:
        with self.lock:
            t = self.tunnel
            if t is None:
                status = "error" if self.tunnel_error else "off"
                return {"status": status, "url": None, "error": self.tunnel_error}
            return {"status": t.status, "url": t.public_base, "error": t.error}

    def _stop_server(self) -> None:
        self._stop_tunnel()  # sin servidor, el túnel no lleva a ninguna parte
        if self.server:
            self.server.stop()
            self.server = None

    def stop_if_idle(self, db: sqlite3.Connection) -> None:
        with self.lock:
            if self.server and live.open_sessions(db) == 0:
                self._stop_server()
                self.tunnel_error = None
                log.info("Sin salas abiertas: servidor de la red local apagado")

    def stop(self) -> None:
        with self.lock:
            self._stop_server()

    @property
    def running(self) -> bool:
        return self.server is not None


manager = Manager()
