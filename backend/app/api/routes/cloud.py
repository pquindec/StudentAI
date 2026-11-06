"""Claude en la nube (Fase 8): ajustes, clave en el Keychain, vista previa, consentimiento y
registro de envíos. Nada de esto envía datos: solo prepara y autoriza lo que harán los trabajos."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, StringConstraints

from app.api.deps import Db, UserId
from app.api.routes.exams import ExamScopeIn
from app.core import secrets
from app.core.errors import bad_request, conflict
from app.llm.claude_api import PRICES
from app.rag.scope import Scope
from app.services import cloud
from app.services import cloud_preview as preview_svc
from app.services import subjects as subj

router = APIRouter(tags=["cloud"])

Kind = Literal["chat", "docs", "deck", "exam"]
Task = Literal["chat", "docs", "generate", "review"]
Via = Literal["api", "plan"]
Id = Annotated[str, StringConstraints(max_length=64)]
MODEL_LABELS = {
    "claude-opus-5-5": "Claude Opus 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
}


class CloudModelOut(BaseModel):
    id: str
    label: str
    input_usd: float  # por millón de tokens
    output_usd: float


class PlanOut(BaseModel):
    installed: bool
    logged_in: bool
    plan: str | None


class ViaAmountsOut(BaseModel):
    api: float
    plan: float


class SessionConsentOut(BaseModel):
    id: str
    kind: Kind
    tasks: list[Task]
    via: Via
    model: str
    created_at: str


class CloudStatusOut(BaseModel):
    enabled: bool
    via_pref: Literal["auto", "api", "plan"]
    via: Via | None  # la que se usará ahora (None: ninguna disponible)
    model: str
    models: list[CloudModelOut]
    tasks: dict[Task, bool]
    api_key: str | None  # solo los 4 últimos caracteres
    plan: PlanOut
    limits: ViaAmountsOut
    spent: ViaAmountsOut  # este mes (con el plan: coste equivalente)
    session_consents: list[SessionConsentOut]


class CloudSettingsIn(BaseModel):
    enabled: bool | None = None
    via: Literal["auto", "api", "plan"] | None = None
    model: Literal["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] | None = None
    tasks: dict[Task, bool] | None = None
    limit_api: float | None = Field(None, ge=0, le=1000)
    limit_plan: float | None = Field(None, ge=0, le=1000)


class ApiKeyIn(BaseModel):
    key: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=20, max_length=300, pattern=r"^sk-ant-\S+$"
        ),
    ]


class PreviewIn(BaseModel):
    kind: Kind
    subject_id: Id | None = None  # docs, deck, exam
    source_ids: list[Id] = Field([], max_length=50)  # docs
    scope: ExamScopeIn = ExamScopeIn()  # deck, exam
    count: int = Field(20, ge=1, le=100)  # deck, exam
    thread_id: Id | None = None  # chat
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None


class ConsentIn(PreviewIn):
    mode: Literal["once", "session"] = "once"


class PreviewSourceOut(BaseModel):
    id: str
    title: str
    kind: str


class PreviewOut(BaseModel):
    cloud: bool  # False: se hará en local (ver `reason`)
    reason: Literal["disabled", "task_local", "no_via", "limit"] | None
    tasks: list[Task]
    via: Via | None
    model: str
    sources: list[PreviewSourceOut]
    fragments: int
    chars: int
    text: str  # texto exacto (hasta 200.000 caracteres)
    truncated: bool
    sends: bool  # False: no hay nada que enviar
    notes: list[str]  # review_only | creative | general | not_found
    est_cost_usd: float
    spent_usd: float
    limit_usd: float
    session_consent_id: str | None


class ConsentOut(BaseModel):
    id: str
    mode: Literal["once", "session"]


class CloudRequestOut(BaseModel):
    id: int
    kind: str
    task: str
    via: Via
    model: str
    status: Literal["ok", "failed", "blocked"]
    chars_sent: int
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float
    error: str | None
    created_at: str


def _status(db: Db, user: str) -> CloudStatusOut:
    cfg = cloud.settings(db)
    return CloudStatusOut(
        enabled=cfg["enabled"],
        via_pref=cfg["via"],
        via=cloud.resolve_via(db),  # type: ignore[arg-type]
        model=cfg["model"],
        models=[
            CloudModelOut(id=m, label=MODEL_LABELS.get(m, m), input_usd=p[0], output_usd=p[1])
            for m, p in PRICES.items()
        ],
        tasks=cfg["tasks"],
        api_key=cloud.api_key_hint(),
        plan=PlanOut(**cloud.plan_status()),
        limits=ViaAmountsOut(**cfg["limits"]),
        spent=ViaAmountsOut(**{v: round(cloud.spent(db, user, v), 4) for v in cloud.VIAS}),
        session_consents=[SessionConsentOut(**c) for c in cloud.session_consents(db, user)],
    )


@router.get("/cloud/status", response_model=CloudStatusOut)
def cloud_status(db: Db, user: UserId, refresh: bool = False) -> CloudStatusOut:
    if refresh:
        cloud.plan_status(refresh=True)
    return _status(db, user)


@router.put("/cloud/settings", response_model=CloudStatusOut)
def update_settings(body: CloudSettingsIn, db: Db, user: UserId) -> CloudStatusOut:
    cloud.put_settings(db, **body.model_dump())
    return _status(db, user)


@router.put("/cloud/api-key", response_model=CloudStatusOut)
def set_api_key(body: ApiKeyIn, db: Db, user: UserId) -> CloudStatusOut:
    try:
        secrets.put(secrets.ANTHROPIC_KEY, body.key)
    except Exception as e:  # el Keychain puede negarse (p. ej. el usuario cancela el permiso)
        raise conflict("keychain_error", "No se pudo guardar la clave en el llavero") from e
    return _status(db, user)


@router.delete("/cloud/api-key", response_model=CloudStatusOut)
def delete_api_key(db: Db, user: UserId) -> CloudStatusOut:
    secrets.delete(secrets.ANTHROPIC_KEY)
    return _status(db, user)


def _preview(db: Db, user: str, body: PreviewIn, r: cloud.Route) -> preview_svc.Preview:
    if body.kind == "chat":
        if not body.thread_id or not body.text:
            raise bad_request("invalid_preview", "Falta la conversación o la pregunta")
        return preview_svc.for_chat(db, user, body.thread_id, body.text)
    if not body.subject_id:
        raise bad_request("invalid_preview", "Falta la asignatura")
    subj.get_subject(db, user, body.subject_id)
    if body.kind == "docs":
        return preview_svc.for_docs(db, user, body.subject_id, body.source_ids)
    scope = Scope(subject_id=body.subject_id, **body.scope.model_dump())
    return preview_svc.for_material(db, user, scope, review_only=r.tasks == ["review"])


@router.post("/cloud/preview", response_model=PreviewOut)
def preview(body: PreviewIn, db: Db, user: UserId) -> PreviewOut:
    r = cloud.route(db, user, body.kind)
    if not r.cloud:  # va en local: no hace falta preparar el texto
        return PreviewOut(
            cloud=False, reason=r.reason, tasks=r.tasks, via=r.via, model=r.model,  # type: ignore[arg-type]
            sources=[], fragments=0, chars=0, text="", truncated=False, sends=False, notes=[],
            est_cost_usd=0.0, spent_usd=round(r.spent_usd, 4), limit_usd=r.limit_usd,
            session_consent_id=None,
        )  # fmt: skip
    p = _preview(db, user, body, r)
    return PreviewOut(
        cloud=r.cloud and p.sends,
        reason=r.reason,  # type: ignore[arg-type]
        tasks=r.tasks,  # type: ignore[arg-type]
        via=r.via,  # type: ignore[arg-type]
        model=r.model,
        sources=[PreviewSourceOut(**s) for s in p.sources],
        fragments=p.fragments,
        chars=p.chars,
        text=p.text[: preview_svc.MAX_PREVIEW_CHARS],
        truncated=p.chars > preview_svc.MAX_PREVIEW_CHARS,
        sends=p.sends,
        notes=p.notes,
        est_cost_usd=cloud.estimate(r.model, r.tasks, p.chars, body.count) if r.cloud else 0.0,
        spent_usd=round(r.spent_usd, 4),
        limit_usd=r.limit_usd,
        session_consent_id=cloud.session_consent(db, user, body.kind) if r.cloud else None,
    )


@router.post("/cloud/consents", response_model=ConsentOut, status_code=201)
def give_consent(body: ConsentIn, db: Db, user: UserId) -> ConsentOut:
    """Registra el consentimiento para lo que se ha mostrado en la vista previa."""
    r = cloud.route(db, user, body.kind)
    if not r.cloud:
        raise conflict("cloud_unavailable", "Claude no está disponible para esta tarea")
    p = _preview(db, user, body, r)
    if not p.sends:
        raise conflict("nothing_to_send", "No hay nada que enviar a Claude")
    est = cloud.estimate(r.model, r.tasks, p.chars, body.count)
    cid = cloud.create_consent(db, user, body.kind, r, body.mode, p.scope, p.chars, est)
    return ConsentOut(id=cid, mode=body.mode)


@router.delete("/cloud/consents", status_code=204)
def revoke_session_consents(db: Db, user: UserId) -> Response:
    cloud.revoke(db, user)
    return Response(status_code=204)


@router.delete("/cloud/consents/{consent_id}", status_code=204)
def revoke_consent(consent_id: str, db: Db, user: UserId) -> Response:
    cloud.revoke(db, user, consent_id)
    return Response(status_code=204)


@router.get("/cloud/requests", response_model=list[CloudRequestOut])
def list_requests(
    db: Db, user: UserId, limit: Annotated[int, Query(ge=1, le=500)] = 50
) -> list[CloudRequestOut]:
    return [
        CloudRequestOut(**{k: r[k] for k in CloudRequestOut.model_fields})
        for r in cloud.requests(db, user, limit)
    ]
