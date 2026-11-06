"""Claude en la nube (Fase 8): ajustes, vía (clave o plan), consentimiento, límites y auditoría.

Reglas que se cumplen aquí y en `services/engine.py`:
- Desactivado por defecto. Nada sale sin un consentimiento válido para ESA tarea y ese contenido
  (o uno «de sesión», que dura hasta cerrar la app).
- Límite mensual por vía con bloqueo duro: antes de cada envío se comprueba que lo gastado este
  mes más lo que puede costar el envío no lo supera.
- Cada envío (o bloqueo) queda registrado en `cloud_requests`, sin el contenido.
"""

import json
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core import clock, secrets
from app.llm import claude_code
from app.llm.base import ChatRequest, ChatResult, LLMError
from app.llm.claude_api import PRICES, price
from app.services import settings as prefs
from app.services.flashcards import iso

KINDS = ("chat", "docs", "deck", "exam")
TASKS = ("chat", "docs", "generate", "review")
KIND_TASKS = {
    "chat": ("chat",),
    "docs": ("docs",),
    "deck": ("generate", "review"),
    "exam": ("generate", "review"),
}
VIAS = ("api", "plan")
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_LIMIT = 5.0
CHARS_PER_TOKEN = 3.0  # español: algo menos de 4 caracteres por token; se estima por lo alto
# Salida estimada por tarea (tokens), incluido el razonamiento del modelo.
OUT_TOKENS = {"chat": 2500, "docs": 9000, "generate": 1500, "review": 700}
BOOT_ID = uuid.uuid4().hex  # cambia en cada arranque: los consentimientos «de sesión» caducan

_plan_cache: dict[str, Any] = {"at": 0.0, "value": None}


# ------------------------------------------------------------------ ajustes
def settings(db: sqlite3.Connection) -> dict[str, Any]:
    tasks = prefs.get(db, "cloud.tasks", {}) or {}
    model = prefs.get(db, "cloud.model", DEFAULT_MODEL)
    via = prefs.get(db, "cloud.via", "auto")
    return {
        "enabled": bool(prefs.get(db, "cloud.enabled", False)),
        "via": via if via in ("auto", *VIAS) else "auto",
        "model": model if model in PRICES else DEFAULT_MODEL,
        "tasks": {t: bool(tasks.get(t, True)) for t in TASKS},
        "limits": {v: float(prefs.get(db, f"cloud.limit.{v}", DEFAULT_LIMIT)) for v in VIAS},
    }


def put_settings(db: sqlite3.Connection, **changes: Any) -> None:
    for key in ("enabled", "via", "model"):
        if changes.get(key) is not None:
            prefs.put(db, f"cloud.{key}", changes[key])
    if changes.get("tasks") is not None:
        current = settings(db)["tasks"]
        prefs.put(db, "cloud.tasks", {**current, **changes["tasks"]})
    for v in VIAS:
        if changes.get(f"limit_{v}") is not None:
            prefs.put(db, f"cloud.limit.{v}", float(changes[f"limit_{v}"]))


def api_key() -> str | None:
    return secrets.get(secrets.ANTHROPIC_KEY)


def api_key_hint() -> str | None:
    key = api_key()
    return f"…{key[-4:]}" if key else None


def plan_status(refresh: bool = False) -> dict[str, Any]:
    """¿Está Claude Code instalado y con sesión? Se consulta como mucho una vez por minuto."""
    if not refresh and _plan_cache["value"] and time.monotonic() - _plan_cache["at"] < 60:
        return dict(_plan_cache["value"])
    binary = claude_code.find_binary()
    value: dict[str, Any] = {"installed": binary is not None, "logged_in": False, "plan": None}
    if binary:
        st = claude_code.auth_status(binary)
        value.update(logged_in=st["logged_in"], plan=st.get("plan"))
    _plan_cache.update(at=time.monotonic(), value=value)
    return dict(value)


def resolve_via(db: sqlite3.Connection) -> str | None:
    """La vía que se usará: la elegida o, en «auto», la clave si hay y si no el plan."""
    pref = settings(db)["via"]
    has_key = api_key() is not None
    plan_ok = pref != "api" and plan_status()["logged_in"]
    if pref == "api":
        return "api" if has_key else None
    if pref == "plan":
        return "plan" if plan_ok else None
    return "api" if has_key else ("plan" if plan_ok else None)


# ------------------------------------------------------------------ gasto
def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent(db: sqlite3.Connection, owner: str, via: str, now: datetime | None = None) -> float:
    since = iso(month_start(now or clock.now()))
    row = db.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM cloud_requests"
        " WHERE owner_id = ? AND via = ? AND status = 'ok' AND created_at >= ?",
        (owner, via, since),
    ).fetchone()
    return float(row[0])


def estimate(model: str, tasks: tuple[str, ...] | list[str], chars: int, count: int = 1) -> float:
    """Coste estimado (USD) de enviar `chars` caracteres para estas tareas."""
    pin, pout = price(model)
    total = 0.0
    for t in tasks:
        inp = chars / CHARS_PER_TOKEN
        out = OUT_TOKENS[t]
        if t == "generate":  # varios lotes: salida proporcional a las tarjetas o preguntas
            out = OUT_TOKENS[t] * max(1, math.ceil(count / 5)) * 2
        elif t == "review":  # solo viajan las propuestas con su cita (una fracción del texto)
            inp = min(inp, 200 * count * 2)
            out = OUT_TOKENS[t] * max(1, math.ceil(count * 2 / 8))
        total += (inp * pin + out * pout) / 1e6
    return round(total, 4)


def call_estimate(model: str, req: ChatRequest) -> float:
    pin, pout = price(model)
    chars = sum(len(m.content) for m in req.messages)
    return (chars / CHARS_PER_TOKEN * pin + req.max_tokens * pout) / 1e6


# ------------------------------------------------------------------ enrutado
@dataclass
class Route:
    cloud: bool
    tasks: list[str] = field(default_factory=list)
    via: str | None = None
    model: str = DEFAULT_MODEL
    reason: str | None = None  # por qué va en local
    spent_usd: float = 0.0
    limit_usd: float = 0.0


def route(db: sqlite3.Connection, owner: str, kind: str, now: datetime | None = None) -> Route:
    cfg = settings(db)
    tasks = [t for t in KIND_TASKS[kind] if cfg["tasks"][t]]
    model = cfg["model"]
    if not cfg["enabled"]:
        return Route(False, model=model, reason="disabled")
    if not tasks:
        return Route(False, model=model, reason="task_local")
    via = resolve_via(db)
    if via is None:
        return Route(False, model=model, reason="no_via")
    used, limit = spent(db, owner, via, now), cfg["limits"][via]
    if used >= limit:
        return Route(False, tasks, via, model, "limit", used, limit)
    return Route(True, tasks, via, model, None, used, limit)


# ------------------------------------------------------------------ consentimientos
def create_consent(
    db: sqlite3.Connection,
    owner: str,
    kind: str,
    r: Route,
    mode: str,
    scope: dict[str, Any],
    chars: int,
    est: float,
) -> str:
    cid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO cloud_consents(id, owner_id, kind, tasks_json, mode, session_id, scope_json,"
        " via, model, chars, est_cost_usd, max_cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            cid,
            owner,
            kind,
            json.dumps(r.tasks),
            mode,
            BOOT_ID if mode == "session" else None,
            json.dumps(scope),
            r.via,
            r.model,
            chars,
            est,
            max(est * 2, 0.05),  # el gasto real puede pasar del estimado, pero no del doble
        ),
    )
    return cid


def session_consent(db: sqlite3.Connection, owner: str, kind: str) -> str | None:
    """Consentimiento «de sesión» vigente para este tipo de envío (con la vía y modelo actuales)."""
    r = route(db, owner, kind)
    if not r.cloud:
        return None
    row = db.execute(
        "SELECT id, tasks_json FROM cloud_consents WHERE owner_id = ? AND kind = ? AND"
        " mode = 'session' AND session_id = ? AND revoked_at IS NULL AND via = ? AND model = ?"
        " ORDER BY created_at DESC LIMIT 1",
        (owner, kind, BOOT_ID, r.via, r.model),
    ).fetchone()
    if row is None or not set(r.tasks) <= set(json.loads(row["tasks_json"])):
        return None
    return str(row["id"])


def session_consents(db: sqlite3.Connection, owner: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id, kind, tasks_json, via, model, created_at FROM cloud_consents"
        " WHERE owner_id = ? AND mode = 'session' AND session_id = ? AND revoked_at IS NULL"
        " ORDER BY created_at",
        (owner, BOOT_ID),
    ).fetchall()
    return [{**dict(r), "tasks": json.loads(r["tasks_json"])} for r in rows]


def revoke(db: sqlite3.Connection, owner: str, consent_id: str | None = None) -> int:
    """Revoca uno o, sin id, todos los consentimientos de sesión."""
    if consent_id:
        cur = db.execute(
            "UPDATE cloud_consents SET revoked_at = now_iso() WHERE id = ? AND owner_id = ?"
            " AND revoked_at IS NULL",
            (consent_id, owner),
        )
    else:
        cur = db.execute(
            "UPDATE cloud_consents SET revoked_at = now_iso() WHERE owner_id = ?"
            " AND mode = 'session' AND revoked_at IS NULL",
            (owner,),
        )
    return cur.rowcount


@dataclass
class Consent:
    id: str
    owner: str
    kind: str
    tasks: list[str]
    via: str
    model: str
    mode: str
    max_cost_usd: float
    scope: dict[str, Any]


def authorize(
    db: sqlite3.Connection,
    owner: str,
    consent_id: str | None,
    kind: str,
    job_id: str,
    source_ids: set[str] | None = None,
    chunk_ids: set[int] | None = None,
) -> Consent | None:
    """Consentimiento válido para este trabajo o None (y entonces todo se hace en local).

    «Una vez»: sirve a un solo trabajo (queda ligado al primero que lo usa) y solo para las
    fuentes o fragmentos que se mostraron. «Sesión»: hasta cerrar la app. En ambos casos, la nube
    tiene que seguir activada y con la misma vía y modelo que se aprobaron.
    """
    if not consent_id:
        return None
    row = db.execute(
        "SELECT * FROM cloud_consents WHERE id = ? AND owner_id = ? AND kind = ?"
        " AND revoked_at IS NULL",
        (consent_id, owner, kind),
    ).fetchone()
    if row is None:
        return None
    c = dict(row)
    r = route(db, owner, kind)
    if not r.cloud or r.via != c["via"] or r.model != c["model"]:
        return None
    scope = json.loads(c["scope_json"])
    if c["mode"] == "session":
        if c["session_id"] != BOOT_ID:
            return None
    else:
        if source_ids is not None and not source_ids <= set(scope.get("source_ids", [])):
            return None
        if chunk_ids is not None and not chunk_ids <= set(scope.get("chunk_ids", [])):
            return None
        bound = db.execute(
            "UPDATE cloud_consents SET job_id = ? WHERE id = ? AND (job_id IS NULL OR job_id = ?)",
            (job_id, consent_id, job_id),
        ).rowcount
        if not bound:
            return None
    tasks = [t for t in json.loads(c["tasks_json"]) if t in r.tasks]
    return Consent(
        c["id"], owner, kind, tasks, c["via"], c["model"], c["mode"], c["max_cost_usd"], scope
    )


# ------------------------------------------------------------------ control de cada envío
class Gate:
    """Comprueba los límites antes de cada envío y lo registra después."""

    def __init__(self, db: sqlite3.Connection, consent: Consent, job_id: str | None) -> None:
        self.db, self.consent, self.job_id = db, consent, job_id

    def _consent_spent(self) -> float:
        row = self.db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cloud_requests"
            " WHERE consent_id = ? AND status = 'ok'",
            (self.consent.id,),
        ).fetchone()
        return float(row[0])

    def check(self, req: ChatRequest, task: str) -> float:
        """Coste máximo que se permite a este envío; LLMError si superaría algún límite."""
        c = self.consent
        est = call_estimate(c.model, req)
        limit = settings(self.db)["limits"][c.via]
        room = float(limit) - spent(self.db, c.owner, c.via)
        if c.mode == "once":
            room = min(room, float(c.max_cost_usd) - self._consent_spent())
        if est > room:
            self.record(task, "blocked", req, None, "Límite de gasto")
            raise LLMError(
                "cloud_blocked", "Se alcanzó el límite de gasto de Claude: se continúa en local"
            )
        return room

    def record(
        self,
        task: str,
        status: str,
        req: ChatRequest,
        res: ChatResult | None,
        error: str | None = None,
    ) -> None:
        c = self.consent
        self.db.execute(
            "INSERT INTO cloud_requests(owner_id, consent_id, job_id, kind, task, via, model,"
            " status, chars_sent, input_tokens, output_tokens, cost_usd, error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                c.owner,
                c.id,
                self.job_id,
                c.kind,
                task,
                c.via,
                (res.model if res and res.model else c.model),
                status,
                0 if status == "blocked" else sum(len(m.content) for m in req.messages),
                res.input_tokens if res else None,
                res.output_tokens if res else None,
                (res.cost_usd or 0.0) if res else 0.0,
                error,
            ),
        )


def requests(db: sqlite3.Connection, owner: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM cloud_requests WHERE owner_id = ? ORDER BY id DESC LIMIT ?",
        (owner, limit),
    ).fetchall()
    return [dict(r) for r in rows]
