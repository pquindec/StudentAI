"""Interfaz común de los modelos de lenguaje (ADR-005).

La lógica de negocio solo conoce `LLMProvider`. Implementaciones: Ollama (local), la API de Claude
con clave (`claude_api`) y Claude Code con el plan del usuario (`claude_code`). Los proveedores de
la nube solo se crean desde `services/engine.py`, tras validar el consentimiento (ARCHITECTURE §10).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """Error con código estable y mensaje en español apto para la UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LLMCancelled(Exception):
    pass


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass
class ChatRequest:
    model: str
    messages: list[Message]
    schema: dict[str, Any] | None = None  # salida estructurada (JSON Schema)
    num_ctx: int = 8192
    max_tokens: int = 1500
    temperature: float = 0.2
    keep_alive: str = "2m"


@dataclass
class ChatResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int
    cost_usd: float | None = None  # solo en la nube (con el plan: coste equivalente)
    model: str | None = None  # modelo que respondió de verdad (la nube puede usar uno de respaldo)


@dataclass
class LoadedModel:
    name: str
    size_mb: int


@dataclass
class RuntimeInfo:
    running: bool
    version: str | None = None
    models: list[str] = field(default_factory=list)


class LLMProvider(Protocol):
    name: str

    def info(self) -> RuntimeInfo: ...

    def loaded(self) -> list[LoadedModel]: ...

    def unload(self, model: str) -> None: ...

    def chat(
        self,
        req: ChatRequest,
        on_token: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ChatResult:
        """Genera en streaming. `on_token` recibe el número de tokens generados hasta ahora y
        `on_text` el texto acumulado; `cancelled` se consulta durante la generación y, si es
        cierto, se corta (LLMCancelled)."""
        ...

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Vectores (embeddings) de los textos, en el mismo orden."""
        ...
