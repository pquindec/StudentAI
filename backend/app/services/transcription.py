"""Reglas de cuándo y con qué modelo se transcribe."""

import sqlite3
from pathlib import Path

from app.jobs import queue
from app.services import settings as prefs
from app.services import sources as src_svc
from app.stt import models

LANGUAGES = ("auto", "es", "en")


def chosen_model(db: sqlite3.Connection) -> str:
    model = prefs.get(db, "stt.model", models.DEFAULT_STT)
    return (
        model
        if model in models.CATALOG and models.CATALOG[model].kind == "stt"
        else models.DEFAULT_STT
    )


def default_language(db: sqlite3.Connection) -> str:
    lang = prefs.get(db, "stt.language", "auto")
    return lang if lang in LANGUAGES else "auto"


def ready(db: sqlite3.Connection, data_dir: Path) -> bool:
    return models.is_installed(data_dir, chosen_model(db)) and models.is_installed(
        data_dir, models.VAD
    )


def enqueue(db: sqlite3.Connection, source_id: str, language: str | None = None) -> str | None:
    """Encola la transcripción (prioridad alta: el usuario espera su clase). Si ya hay una
    activa para esta fuente, no duplica."""
    active = db.execute(
        "SELECT id FROM jobs WHERE source_id = ? AND type = 'transcribe'"
        " AND status IN ('queued', 'running')",
        (source_id,),
    ).fetchone()
    if active:
        return str(active[0])
    src_svc.merge_metadata(db, source_id, {"transcription": "queued"})
    return queue.enqueue(
        db,
        "transcribe",
        "stt",
        source_id,
        {"language": language or default_language(db), "model": chosen_model(db)},
        priority=queue.PRIORITY["recording"],
    )


def enqueue_waiting(db: sqlite3.Connection, data_dir: Path) -> int:
    """Tras instalar un modelo: transcribe los audios que lo estaban esperando."""
    if not ready(db, data_dir):
        return 0
    rows = db.execute(
        "SELECT id FROM sources WHERE kind IN ('audio', 'recording')"
        " AND json_extract(metadata_json, '$.transcription') = 'needs_model'"
    ).fetchall()
    for r in rows:
        db.execute("UPDATE sources SET status = 'pending' WHERE id = ?", (r[0],))
        enqueue(db, r[0])
    return len(rows)
