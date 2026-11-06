"""Motor de IA de un trabajo: local (Ollama + Resource Manager) o Claude, por tarea.

Los manejadores no saben dónde se ejecuta cada llamada: piden `Engine.chat(req, etiqueta)` y el
motor la envía a Claude solo si hay un consentimiento válido para esa tarea; si no, o si Claude
falla (sin conexión, límite de gasto, sesión caducada…), la hace en local. Cambiar una tarea entre
local y nube no cambia la lógica de negocio (criterio de aceptación de la Fase 8).
"""

import dataclasses
import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from app.llm.base import ChatRequest, ChatResult, LLMCancelled, LLMError, LLMProvider
from app.llm.claude_api import ClaudeApiProvider
from app.llm.claude_code import ClaudeCodeProvider
from app.resources.manager import Choice, ResourceManager, profile
from app.services import cloud
from app.services import documents as docs_svc
from app.services import llm as llm_svc

log = logging.getLogger(__name__)

API_BASE_URL: str | None = None  # None: api.anthropic.com (las pruebas apuntan a un servidor falso)

# Etiqueta de la llamada → tarea («cards:judge» es revisar; «cards:generate», generar).
REVIEW_SUFFIX = ":judge"


def task_of(kind: str, label: str) -> str:
    if kind in ("deck", "exam"):
        return "review" if label.endswith(REVIEW_SUFFIX) else "generate"
    return kind


def cloud_provider(via: str, model: str) -> LLMProvider:
    """Único sitio donde se crea un proveedor de la nube (llamado solo por `Engine`)."""
    if via == "api":
        key = cloud.api_key()
        if not key:
            raise LLMError("cloud_auth", "No hay clave de API de Claude guardada")
        return ClaudeApiProvider(key, model, base_url=API_BASE_URL)
    return ClaudeCodeProvider(model)


class Engine:
    def __init__(
        self,
        db: sqlite3.Connection,
        job_id: str | None,
        kind: str,
        consent: cloud.Consent | None,
        report: Callable[[float, str | None], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.db, self.job_id, self.kind, self.consent = db, job_id, kind, consent
        self._report, self._cancelled = report, cancelled
        self.local = llm_svc.provider()
        self._rm: ResourceManager | None = None
        self.choice: Choice | None = None
        self._cloud: LLMProvider | None = None
        self.gate = cloud.Gate(db, consent, job_id) if consent else None
        self.cloud_off: str | None = None  # motivo por el que se dejó de usar Claude
        self.used: dict[str, str] = {}  # tarea → modelo que la hizo
        self.peak_mb = 0
        self.cost_usd = 0.0

    # -------------------------------------------------------------- local
    def _ensure_local(self) -> tuple[ResourceManager, Choice]:
        if self._rm is None or self.choice is None:
            info = self.local.info()
            if not info.running:
                raise LLMError(
                    "llm_unavailable", "Ollama no está en marcha. Abre la app de Ollama."
                )
            rm = ResourceManager(self.local)
            self.choice = rm.acquire(
                llm_svc.chosen_model(self.db),
                llm_svc.light_model(self.db),
                info.models,
                report=lambda m: self._report(0, m) if self._report else None,
                cancelled=self._cancelled or (lambda: False),
            )
            self._rm = rm
        return self._rm, self.choice

    def _local_chat(
        self,
        req: ChatRequest,
        label: str,
        on_token: Callable[[int], None] | None,
        on_text: Callable[[str], None] | None,
    ) -> ChatResult:
        rm, choice = self._ensure_local()
        req = dataclasses.replace(req, model=choice.model)
        extra = {"on_text": on_text} if on_text else {}  # no todos los proveedores lo aceptan
        res = self.local.chat(req, on_token=on_token, cancelled=self._cancelled, **extra)
        loaded = rm.after_call(req.model)
        if loaded:
            self.peak_mb = max(self.peak_mb, loaded)
        docs_svc.record_run(
            self.db, self.job_id, req.model, label, res.input_tokens, res.output_tokens,
            res.duration_ms, loaded,
        )  # fmt: skip
        self.used.setdefault(task_of(self.kind, label), choice.model)
        return res

    # -------------------------------------------------------------- nube
    def uses_cloud(self, task: str) -> bool:
        return bool(self.consent and task in self.consent.tasks and not self.cloud_off)

    def _cloud_chat(
        self,
        req: ChatRequest,
        label: str,
        on_token: Callable[[int], None] | None,
        on_text: Callable[[str], None] | None,
    ) -> ChatResult:
        assert self.consent is not None and self.gate is not None  # noqa: S101
        c = self.consent
        room = self.gate.check(req, label)  # LLMError si superaría el límite
        if self._cloud is None:
            self._cloud = cloud_provider(c.via, c.model)
        if isinstance(self._cloud, ClaudeCodeProvider):
            self._cloud.max_cost_usd = max(room, 0.001)
        try:
            res = self._cloud.chat(
                dataclasses.replace(req, model=c.model),
                on_token=on_token,
                cancelled=self._cancelled,
                on_text=on_text,
            )
        except LLMCancelled:
            raise
        except LLMError as e:
            self.gate.record(label, "failed", req, None, e.code)
            raise
        self.gate.record(label, "ok", req, res)
        self.cost_usd += res.cost_usd or 0.0
        docs_svc.record_run(
            self.db, self.job_id, res.model or c.model, label, res.input_tokens,
            res.output_tokens, res.duration_ms, None, provider=f"claude_{c.via}",
        )  # fmt: skip
        self.used.setdefault(task_of(self.kind, label), res.model or c.model)
        return res

    # -------------------------------------------------------------- común
    def chat(
        self,
        req: ChatRequest,
        label: str,
        on_token: Callable[[int], None] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ChatResult:
        if self.uses_cloud(task_of(self.kind, label)):
            try:
                return self._cloud_chat(req, label, on_token, on_text)
            except LLMError as e:
                # Sin conexión, sin sesión, límite…: lo que queda del trabajo se hace en local.
                log.warning("Claude no disponible (%s): se continúa en local", e.code)
                self.cloud_off = e.message
        return self._local_chat(req, label, on_token, on_text)

    @property
    def model(self) -> str:
        """Modelo con el que se crean las peticiones (el motor lo sustituye por el real)."""
        return self.choice.model if self.choice else llm_svc.chosen_model(self.db)

    def model_label(self) -> str:
        """Modelos usados, para guardar en el resultado (p. ej. «qwen3.5:9b + claude-…»)."""
        names = list(dict.fromkeys(self.used.values()))
        return " + ".join(names) if names else self.model

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "fallback": bool(self.choice and self.choice.fallback),
            "available_mb": self.choice.available_mb if self.choice else None,
            "peak_loaded_mb": self.peak_mb,
            "budget_mb": profile(self.choice.model).budget_mb if self.choice else 0,
        }
        if self.consent:
            out["cloud"] = {
                "via": self.consent.via,
                "model": self.consent.model,
                "tasks": [t for t, m in self.used.items() if m.startswith("claude")],
                "cost_usd": round(self.cost_usd, 4),
                "stopped": self.cloud_off,
            }
        return out


def for_job(
    db: sqlite3.Connection,
    job: dict[str, Any],
    owner: str,
    kind: str,
    consent_id: str | None,
    report: Callable[[float, str | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    source_ids: set[str] | None = None,
    chunk_ids: set[int] | None = None,
) -> Engine:
    consent = cloud.authorize(
        db, owner, consent_id, kind, str(job["id"]), source_ids=source_ids, chunk_ids=chunk_ids
    )
    return Engine(db, str(job["id"]), kind, consent, report, cancelled)
