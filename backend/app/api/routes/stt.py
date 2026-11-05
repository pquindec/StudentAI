"""Transcripción: estado de whisper.cpp y de los modelos, preferencias y descarga."""

import shutil
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.deps import AppSettings, Db
from app.core.errors import bad_request, not_found
from app.db.connection import tx
from app.jobs import queue
from app.services import audio_files, transcription
from app.services import settings as prefs
from app.stt import models

router = APIRouter(prefix="/stt", tags=["stt"])

Language = Literal["auto", "es", "en"]
KeepDays = Literal[0, 7, 30]  # días que se conserva el audio tras transcribir; 0 = siempre


class ModelOut(BaseModel):
    id: str
    kind: Literal["stt", "vad"]
    label: str
    description: str
    size_bytes: int
    installed: bool
    download_job_id: str | None
    download_progress: float | None


class SttStatusOut(BaseModel):
    whisper_available: bool
    ready: bool
    model: str
    language: Language
    audio_keep_days: KeepDays
    models: list[ModelOut]


class SttSettingsIn(BaseModel):
    model: str | None = None
    language: Language | None = None
    audio_keep_days: KeepDays | None = None


def _download_job(db: Db, model_id: str) -> tuple[str, float] | None:
    row = db.execute(
        "SELECT id, progress FROM jobs WHERE type = 'download_model'"
        " AND status IN ('queued', 'running') AND json_extract(payload_json, '$.model') = ?",
        (model_id,),
    ).fetchone()
    return (str(row[0]), float(row[1])) if row else None


def _status(db: Db, settings: AppSettings) -> SttStatusOut:
    out = []
    for m in models.CATALOG.values():
        job = _download_job(db, m.id)
        out.append(
            ModelOut(
                id=m.id,
                kind=m.kind,
                label=m.label,
                description=m.description,
                size_bytes=m.size,
                installed=models.is_installed(settings.data_dir, m.id),
                download_job_id=job[0] if job else None,
                download_progress=job[1] if job else None,
            )
        )
    return SttStatusOut(
        whisper_available=shutil.which("whisper-cli") is not None,
        ready=transcription.ready(db, settings.data_dir),
        model=transcription.chosen_model(db),
        language=transcription.default_language(db),  # type: ignore[arg-type]
        audio_keep_days=audio_files.keep_days(db),  # type: ignore[arg-type]
        models=out,
    )


@router.get("", response_model=SttStatusOut)
def stt_status(db: Db, settings: AppSettings) -> SttStatusOut:
    return _status(db, settings)


@router.put("/settings", response_model=SttStatusOut)
def update_settings(
    body: SttSettingsIn, request: Request, db: Db, settings: AppSettings
) -> SttStatusOut:
    with tx(db):
        if body.model is not None:
            spec = models.CATALOG.get(body.model)
            if spec is None or spec.kind != "stt":
                raise bad_request("unknown_model", "Modelo de transcripción desconocido")
            prefs.put(db, "stt.model", body.model)
        if body.language is not None:
            prefs.put(db, "stt.language", body.language)
        if body.audio_keep_days is not None:
            prefs.put(db, audio_files.KEEP_DAYS_KEY, body.audio_keep_days)
    if body.audio_keep_days is not None:
        request.app.state.scheduler.sweep_soon()
    return _status(db, settings)


@router.post("/models/{model_id}/download", response_model=SttStatusOut, status_code=202)
def download_model(model_id: str, request: Request, db: Db, settings: AppSettings) -> SttStatusOut:
    """Descarga explícita pedida por el usuario (única conexión a Internet de esta fase)."""
    if model_id not in models.CATALOG:
        raise not_found("Modelo")
    needed = not (
        models.is_installed(settings.data_dir, model_id)
        and models.is_installed(settings.data_dir, models.VAD)
    )
    if needed and _download_job(db, model_id) is None:
        queue.enqueue(db, "download_model", "io", None, {"model": model_id})
        request.app.state.scheduler.wake()
    return _status(db, settings)
