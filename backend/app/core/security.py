"""Autenticación de cada petición con el token de sesión que entrega el proceso Rust.

Escuchar en un Unix socket con permisos 0600 ya limita quién puede conectarse, pero no
confiamos solo en eso (defensa en profundidad): toda petición debe traer el token.
"""

import hmac
import json

from starlette.types import ASGIApp, Receive, Scope, Send


class TokenAuthMiddleware:
    def __init__(self, app: ASGIApp, token: str) -> None:
        if len(token) < 32:
            raise ValueError("token de sesión demasiado corto")
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        provided = dict(scope["headers"]).get(b"authorization", b"")
        if not hmac.compare_digest(provided, self.expected):
            await _error(send, 401, "unauthorized", "No autorizado")
            return
        await self.app(scope, receive, send)


class BodyLimitMiddleware:
    """Rechaza cuerpos demasiado grandes antes de leerlos (Fase 9). El proxy de Rust siempre
    envía `Content-Length`; un cuerpo sin longitud declarada (chunked) no es legítimo."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            length = headers.get(b"content-length")
            if length is None and b"transfer-encoding" in headers:
                await _error(send, 411, "length_required", "Falta la longitud de la petición")
                return
            if length is not None and (not length.isdigit() or int(length) > self.max_bytes):
                await _error(send, 413, "too_large", "La petición es demasiado grande")
                return
        await self.app(scope, receive, send)


async def _error(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
