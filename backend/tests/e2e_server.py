"""Backend para las pruebas E2E de la interfaz (Fase 9): el backend real, con el mismo protocolo
de arranque que usa Tauri (token por stdin, Unix socket 0600), pero con modelos falsos y sin
Keychain ni Claude Code. Nunca toca los datos del usuario: la carpeta la elige la prueba.

    uv run python -m tests.e2e_server --data-dir DIR --socket SOCK   (token por stdin)
"""

import json
from pathlib import Path
from typing import Any

from app import main
from app.core import secrets
from app.live import room
from app.llm import claude_code
from app.llm.base import ChatRequest, ChatResult, LoadedModel, RuntimeInfo
from app.rag import index
from app.resources import manager
from app.services import engine, llm
from tests.conftest import MemoryKeyring
from tests.test_chat import FakeChat
from tests.test_exams import FakeExamLLM
from tests.test_flashcards import FakeCardLLM
from tests.test_generation import FakeLLM

MODELS = ["qwen3.5:9b", "qwen3.5:4b"]


class E2ELLM:
    """Reparte cada petición al modelo falso de su tarea según el esquema de salida."""

    name = "fake"

    def __init__(self) -> None:
        self.chat_fake = FakeChat()
        self.docs, self.exam, self.cards = FakeLLM(invent=False), FakeExamLLM(), FakeCardLLM()

    def info(self) -> RuntimeInfo:
        return RuntimeInfo(running=True, version="e2e", models=[*MODELS, index.EMBED_MODEL])

    def loaded(self) -> list[LoadedModel]:
        return []

    def unload(self, model: str) -> None:
        pass

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return self.chat_fake.embed(model, texts)

    def chat(self, req: ChatRequest, **kw: Any) -> ChatResult:
        props = (req.schema or {}).get("properties", {})
        user = req.messages[-1].content
        if "feedback" in props:  # corrección de respuestas cortas
            return ChatResult(json.dumps({"points": 1, "feedback": "Bien"}), 10, 5, 1)
        if "cards" in props or ("verdicts" in props and "Tarjeta 1" in user):
            return self.cards.chat(req, **kw)
        if "questions" in props or "verdicts" in props:
            return self.exam.chat(req, **kw)
        if props:
            return self.docs.chat(req, **kw)
        return self.chat_fake.chat(req, **kw)


def run() -> None:
    fake = E2ELLM()
    llm.provider = lambda: fake  # type: ignore[assignment]
    manager.available_mb = lambda: 10_000
    secrets._backend = MemoryKeyring()
    claude_code.find_binary = lambda: None  # type: ignore[assignment]
    # La «nube» de las pruebas es un puerto local cerrado: nada puede salir a Internet.
    engine.API_BASE_URL = "http://127.0.0.1:9"
    # La sala del examen en vivo, en 127.0.0.1: los «teléfonos» de las pruebas son navegadores
    # de este mismo Mac y nada se abre en la Wi-Fi real.
    room.manager = room.Manager(resolve_ip=lambda: "127.0.0.1")
    room.manager.find_cloudflared = fake_cloudflared  # nada sale a Cloudflare
    main.main()


def fake_cloudflared() -> Path:
    """Un `cloudflared` que imprime lo mismo que el real, sin conectarse a nada."""
    import sys
    import tempfile

    exe = Path(tempfile.mkdtemp(prefix="e2e-cloudflared-")) / "cloudflared"
    exe.write_text(
        f"#!{sys.executable}\n"
        "import time\n"
        "print('INF |  https://sala-de-pruebas-e2e.trycloudflare.com  |', flush=True)\n"
        "print('INF Registered tunnel connection connIndex=0 protocol=http2', flush=True)\n"
        "time.sleep(3600)\n"
    )
    exe.chmod(0o755)
    return exe


if __name__ == "__main__":
    run()
