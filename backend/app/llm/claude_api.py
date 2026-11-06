"""Claude por la API de Anthropic con la clave del usuario (Fase 8).

Solo se crea desde `services/engine.py` después de validar el consentimiento. La clave llega del
Keychain y se pasa explícita: el cliente nunca toma credenciales del entorno.
"""

import copy
import time
from collections.abc import Callable
from typing import Any

import anthropic

from app.llm.base import ChatRequest, ChatResult, LLMCancelled, LLMError, LoadedModel, RuntimeInfo

# Precio por millón de tokens (entrada, salida). Fuente: tabla de modelos de Anthropic, 2026-10.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
CACHE_WRITE = 1.25  # la escritura en caché cuesta 1,25 veces la entrada
CACHE_READ = 0.10  # y la lectura, una décima parte
THINKING_ROOM = 8000  # el razonamiento del modelo cuenta dentro de max_tokens
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def price(model: str) -> tuple[float, float]:
    """Precio del modelo; uno desconocido (p. ej. de respaldo) se cuenta como el más caro."""
    return PRICES.get(model, max(PRICES.values()))


def cost(model: str, usage: Any) -> float:
    pin, pout = price(model)
    inp = getattr(usage, "input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return (inp * pin + write * pin * CACHE_WRITE + read * pin * CACHE_READ + out * pout) / 1e6


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """La salida estructurada de Claude exige `additionalProperties: false` en cada objeto."""
    out = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(out)
    return out


def split_messages(req: ChatRequest) -> tuple[str, list[dict[str, str]]]:
    system = "\n\n".join(m.content for m in req.messages if m.role == "system")
    msgs = [
        {"role": m.role, "content": m.content}
        for m in req.messages
        if m.role in ("user", "assistant")
    ]
    return system, msgs


def _error(e: Exception) -> LLMError:
    if isinstance(e, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return LLMError("cloud_auth", "La clave de API de Claude no es válida o no tiene permiso")
    if isinstance(e, anthropic.RateLimitError):
        return LLMError("cloud_busy", "Claude está limitando las peticiones; prueba más tarde")
    if isinstance(e, anthropic.APIConnectionError):  # incluye el tiempo de espera agotado
        return LLMError("cloud_offline", "Sin conexión con Claude")
    if isinstance(e, anthropic.APIStatusError):
        return LLMError("cloud_error", f"Claude devolvió un error ({e.status_code})")
    return LLMError("cloud_error", "Error al llamar a Claude")


class ClaudeApiProvider:
    name = "claude_api"

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self.model = model
        self._client = anthropic.Anthropic(
            api_key=api_key, base_url=base_url, timeout=600.0, max_retries=2
        )

    def info(self) -> RuntimeInfo:
        return RuntimeInfo(running=True, version=anthropic.__version__, models=[self.model])

    def loaded(self) -> list[LoadedModel]:
        return []

    def unload(self, model: str) -> None:
        pass

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        raise LLMError("unsupported", "Los vectores de búsqueda siempre se calculan en local")

    def chat(
        self,
        req: ChatRequest,
        on_token: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ChatResult:
        system, msgs = split_messages(req)
        extra: dict[str, Any] = {"effort": "medium"}
        if req.schema is not None:
            extra["format"] = {"type": "json_schema", "schema": strict_schema(req.schema)}
        t0 = time.monotonic()
        text, n = "", 0
        try:
            with self._client.beta.messages.stream(
                model=self.model,
                max_tokens=req.max_tokens + THINKING_ROOM,
                system=system,
                messages=msgs,  # type: ignore[arg-type]
                output_config=extra,  # type: ignore[arg-type]
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                for chunk in stream.text_stream:
                    if cancelled and cancelled():
                        raise LLMCancelled
                    text += chunk
                    n += 1
                    if on_text:
                        on_text(text)
                    if on_token:
                        on_token(n)
                final = stream.get_final_message()
        except LLMCancelled:
            raise
        except anthropic.AnthropicError as e:
            raise _error(e) from e
        if final.stop_reason == "refusal":
            raise LLMError("cloud_refusal", "Claude no ha querido responder a esta petición")
        text = "".join(b.text for b in final.content if b.type == "text")
        used = str(final.model)
        return ChatResult(
            text=text,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            duration_ms=int((time.monotonic() - t0) * 1000),
            cost_usd=cost(used, final.usage),
            model=used,
        )
