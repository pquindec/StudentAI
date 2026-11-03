"""Proveedor local: Ollama (app oficial) en 127.0.0.1. Solo HTTP a localhost: nada sale del Mac."""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.client import HTTPResponse
from typing import Any

from app.llm.base import (
    ChatRequest,
    ChatResult,
    LLMCancelled,
    LLMError,
    LoadedModel,
    RuntimeInfo,
)

DEFAULT_URL = "http://127.0.0.1:11434"


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 600) -> None:
        if not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("Ollama debe ser local")  # nunca un host remoto
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @contextmanager
    def _open(
        self, path: str, body: dict[str, Any] | None, timeout: float
    ) -> Iterator[HTTPResponse]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(  # noqa: S310 - URL local fija, validada en __init__
            self.base_url + path,
            data=data,
            method="POST" if data is not None else "GET",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                yield resp
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 501 or "structured output is unavailable" in detail:
                raise LLMError(
                    "structured_unavailable",
                    "Este Ollama no admite salida estructurada. Instala la app oficial desde"
                    " ollama.com (la versión de Homebrew no sirve).",
                ) from e
            if e.code == 404 and "not found" in detail:
                raise LLMError("model_missing", "El modelo no está descargado en Ollama") from e
            raise LLMError("llm_http", f"Ollama respondió con un error ({e.code})") from e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise LLMError(
                "llm_unavailable", "Ollama no está en marcha. Abre la app de Ollama."
            ) from e

    def _get(self, path: str) -> dict[str, Any]:
        with self._open(path, None, timeout=5) as resp:
            data: dict[str, Any] = json.loads(resp.read())
            return data

    def info(self) -> RuntimeInfo:
        try:
            version = self._get("/api/version").get("version")
            tags = self._get("/api/tags").get("models", [])
        except LLMError:
            return RuntimeInfo(running=False)
        return RuntimeInfo(running=True, version=version, models=sorted(m["name"] for m in tags))

    def loaded(self) -> list[LoadedModel]:
        try:
            models = self._get("/api/ps").get("models", [])
        except LLMError:
            return []
        return [LoadedModel(m["name"], int(m.get("size", 0)) // 2**20) for m in models]

    def unload(self, model: str) -> None:
        with self._open("/api/generate", {"model": model, "keep_alive": 0}, timeout=30) as r:
            r.read()

    def chat(
        self,
        req: ChatRequest,
        on_token: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": req.model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "stream": True,
            "think": False,
            "keep_alive": req.keep_alive,
            "options": {
                "num_ctx": req.num_ctx,
                "num_predict": req.max_tokens,
                "temperature": req.temperature,
            },
        }
        if req.schema is not None:
            body["format"] = req.schema
        start = time.monotonic()
        parts: list[str] = []
        produced = 0
        final: dict[str, Any] = {}
        with self._open("/api/chat", body, timeout=self.timeout) as resp:
            for raw in resp:
                if cancelled and cancelled():
                    raise LLMCancelled  # al cerrar la conexión, Ollama deja de generar
                line = raw.strip()
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise LLMError("llm_error", f"Ollama: {str(chunk['error'])[:200]}")
                parts.append(chunk.get("message", {}).get("content", ""))
                produced += 1
                if on_token and produced % 16 == 0:
                    on_token(produced)
                if chunk.get("done"):
                    final = chunk
                    break
        if final.get("done_reason") == "length":
            raise LLMError("llm_truncated", "La respuesta del modelo se cortó por longitud")
        return ChatResult(
            text="".join(parts),
            input_tokens=final.get("prompt_eval_count"),
            output_tokens=final.get("eval_count", produced),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
