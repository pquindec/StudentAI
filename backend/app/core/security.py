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
            body = json.dumps(
                {"error": {"code": "unauthorized", "message": "No autorizado"}}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
