"""Claude con el plan del usuario, a través de Claude Code (`claude -p`) sin modificar (Fase 8).

Las condiciones de Anthropic permiten que el usuario use Claude Code con su propio plan; lo que
no permiten es que otra app lea o guarde sus credenciales. Por eso la app solo ejecuta el binario
oficial, nunca toca el token y le quita las variables de entorno de credenciales para que use la
sesión del plan. Se ejecuta sin herramientas, sin MCP, sin ajustes del usuario, sin comandos y
sin guardar la sesión, en una carpeta temporal vacía: el modelo solo puede devolver texto.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.llm.base import ChatRequest, ChatResult, LLMCancelled, LLMError, LoadedModel, RuntimeInfo
from app.llm.claude_api import split_messages, strict_schema

TIMEOUT_S = 900
# Una app de escritorio no hereda el PATH de la terminal: se buscan también las rutas habituales.
CANDIDATES = (
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
    str(Path.home() / ".local/bin/claude"),
    str(Path.home() / ".claude/local/claude"),
)
STRIP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE")


def find_binary() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    return next((c for c in CANDIDATES if os.access(c, os.X_OK)), None)


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in STRIP_ENV}


def auth_status(binary: str) -> dict[str, Any]:
    """Estado de la sesión (`claude auth status`): solo se leen campos no secretos."""
    try:
        out = subprocess.run(  # noqa: S603
            [binary, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=20,
            env=_env(),
            check=False,
        )
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"logged_in": False}
    return {
        "logged_in": bool(data.get("loggedIn")),
        "method": data.get("authMethod"),
        "plan": data.get("subscriptionType"),
    }


def render_prompt(msgs: list[dict[str, str]]) -> str:
    """`claude -p` recibe un solo mensaje: el historial va delante como texto."""
    if len(msgs) == 1:
        prompt = msgs[0]["content"]
    else:
        names = {"user": "Estudiante", "assistant": "Asistente"}
        past = "\n\n".join(f"[{names[m['role']]}]\n{m['content']}" for m in msgs[:-1])
        prompt = f"Conversación anterior:\n\n{past}\n\nMensaje actual:\n\n{msgs[-1]['content']}"
    # Un mensaje que empieza por «/» lo interpretaría Claude Code como un comando.
    return f"Mensaje:\n{prompt}" if prompt.lstrip().startswith("/") else prompt


class ClaudeCodeProvider:
    name = "claude_code"

    def __init__(self, model: str, binary: str | None = None, max_cost_usd: float = 1.0) -> None:
        self.model = model
        self.binary = binary or find_binary()
        self.max_cost_usd = max_cost_usd

    def info(self) -> RuntimeInfo:
        return RuntimeInfo(running=self.binary is not None, models=[self.model])

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
        if not self.binary:
            raise LLMError("cloud_unavailable", "Claude Code no está instalado")
        system, msgs = split_messages(req)
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="sa-claude-") as work:
            sys_file = Path(work) / "system.txt"
            sys_file.write_text(system or "Eres un asistente de estudio.", encoding="utf-8")
            args = [
                self.binary,
                "-p",
                "--system-prompt-file", str(sys_file),
                "--tools", "",
                "--strict-mcp-config",
                "--setting-sources", "",
                "--disable-slash-commands",
                "--no-session-persistence",
                "--model", self.model,
                "--effort", "medium",
                "--max-budget-usd", f"{self.max_cost_usd:.4f}",
                "--output-format", "stream-json",
                "--verbose",
                "--include-partial-messages",
            ]  # fmt: skip
            if req.schema is not None:
                args += ["--json-schema", json.dumps(strict_schema(req.schema))]
            result = self._run(args, work, render_prompt(msgs), on_text, on_token, cancelled)
        if result.get("is_error") or result.get("subtype") != "success":
            raise _result_error(result)
        structured = result.get("structured_output")
        text = json.dumps(structured) if structured is not None else str(result.get("result") or "")
        usage = result.get("usage") or {}
        models = list((result.get("modelUsage") or {}).keys())
        return ChatResult(
            text=text,
            input_tokens=_int(usage.get("input_tokens"))
            + _int(usage.get("cache_read_input_tokens"))
            + _int(usage.get("cache_creation_input_tokens")),
            output_tokens=_int(usage.get("output_tokens")),
            duration_ms=int((time.monotonic() - t0) * 1000),
            cost_usd=float(result.get("total_cost_usd") or 0.0),
            model=models[0] if models else self.model,
        )

    def _run(
        self,
        args: list[str],
        cwd: str,
        prompt: str,
        on_text: Callable[[str], None] | None,
        on_token: Callable[[int], None] | None,
        cancelled: Callable[[], bool] | None,
    ) -> dict[str, Any]:
        try:
            proc = subprocess.Popen(  # noqa: S603
                args,
                cwd=cwd,
                env=_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as e:
            raise LLMError("cloud_unavailable", "No se pudo ejecutar Claude Code") from e
        stop = threading.Event()
        stopped = {"cancel": False, "timeout": False}

        def watch() -> None:
            end = time.monotonic() + TIMEOUT_S
            while not stop.wait(0.2):
                if cancelled and cancelled():
                    stopped["cancel"] = True
                elif time.monotonic() > end:
                    stopped["timeout"] = True
                else:
                    continue
                proc.kill()
                return

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        result: dict[str, Any] = {}
        text, n = "", 0
        try:
            assert proc.stdin is not None and proc.stdout is not None  # noqa: S101
            proc.stdin.write(prompt)
            proc.stdin.close()
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "result":
                    result = ev
                elif ev.get("type") == "stream_event":
                    delta = (ev.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text += str(delta.get("text") or "")
                        n += 1
                        if on_text:
                            on_text(text)
                        if on_token:
                            on_token(n)
            proc.wait()
        except BrokenPipeError:
            proc.wait()
        finally:
            stop.set()
            watcher.join(1)
        if stopped["cancel"]:
            raise LLMCancelled
        if stopped["timeout"]:
            raise LLMError("cloud_offline", "Claude Code tardó demasiado en responder")
        if not result:
            raise LLMError("cloud_error", "Claude Code terminó sin respuesta")
        return result


def _int(v: Any) -> int:
    return int(v) if isinstance(v, int | float) else 0


def _result_error(result: dict[str, Any]) -> LLMError:
    msg = str(result.get("result") or "").lower()
    status = result.get("api_error_status")
    if "login" in msg or "authenticat" in msg or status in (401, 403):
        return LLMError("cloud_auth", "Claude Code no tiene la sesión iniciada (ejecuta «claude»)")
    if status == 429 or "limit" in msg:
        return LLMError("cloud_busy", "Se alcanzó el límite de uso de tu plan de Claude")
    if "budget" in msg:
        return LLMError("cloud_blocked", "La llamada superaría el coste máximo permitido")
    if "connect" in msg or "network" in msg or "offline" in msg:
        return LLMError("cloud_offline", "Sin conexión con Claude")
    return LLMError("cloud_error", "Claude Code devolvió un error")
