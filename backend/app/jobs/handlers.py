"""Manejadores de trabajos. Se ejecutan en un hilo; cada uno abre su propia conexión."""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.connection import tx
from app.jobs import queue
from app.pipelines import audio
from app.pipelines.extract.document import to_markdown
from app.pipelines.extract.runner import ExtractFailed, run_isolated
from app.services import sources as src_svc


class JobFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class JobContext:
    job: dict[str, Any]
    db: sqlite3.Connection
    data_dir: Path

    @property
    def source_id(self) -> str:
        sid = self.job["source_id"]
        if not isinstance(sid, str):
            raise JobFailed("no_source", "El trabajo no tiene fuente asociada")
        return sid

    def report(self, value: float, message: str | None = None) -> None:
        queue.progress(self.db, self.job["id"], value, message)

    def cancelled(self) -> bool:
        return queue.cancel_requested(self.db, self.job["id"])

    def source(self) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM sources WHERE id = ?", (self.source_id,)).fetchone()
        if row is None:
            raise audio.Cancelled  # la fuente se borró mientras esperaba
        return dict(row)


def extract_document(ctx: JobContext) -> None:
    src = ctx.source()
    ctx.report(0.1, "Extrayendo texto")
    path = ctx.data_dir / src["stored_path"]
    try:
        result = run_isolated(src["kind"], path)
    except ExtractFailed as e:
        raise JobFailed(e.code, e.message) from e
    if ctx.cancelled():
        raise audio.Cancelled
    ctx.report(0.8, "Guardando")
    text = to_markdown(result.blocks)
    if not text.strip():
        raise JobFailed("no_text", "No se encontró texto en el documento")
    with tx(ctx.db):
        src_svc.add_version(ctx.db, ctx.source_id, text, "extracted")
        src_svc.merge_metadata(
            ctx.db, ctx.source_id, {**result.metadata, "warnings": result.warnings}
        )
        ctx.db.execute(
            "UPDATE sources SET status = 'ready', processed_at = now_iso(), page_count = ?,"
            " needs_review = ?, error_code = NULL, error_message = NULL WHERE id = ?",
            (result.page_count, 1 if result.warnings else 0, ctx.source_id),
        )


def prepare_audio(ctx: JobContext) -> None:
    src = ctx.source()
    path = ctx.data_dir / src["stored_path"]
    ctx.report(0.02, "Analizando audio")
    try:
        info = audio.probe(path)
        if ctx.cancelled():
            raise audio.Cancelled
        with tx(ctx.db):
            src_svc.merge_metadata(ctx.db, ctx.source_id, info)
            ctx.db.execute(
                "UPDATE sources SET duration_ms = ? WHERE id = ?",
                (info["duration_ms"], ctx.source_id),
            )
        ctx.report(0.05, "Convirtiendo a formato de transcripción")
        audio.normalize(
            path,
            path.parent / "normalized.wav",
            info["duration_ms"],
            on_progress=lambda p: ctx.report(0.05 + p * 0.95),
            cancelled=ctx.cancelled,
        )
    except audio.AudioError as e:
        raise JobFailed(e.code, e.message) from e
    # Transcripción: Fase 3. De momento el audio queda listo y pendiente de transcribir.
    ctx.db.execute(
        "UPDATE sources SET status = 'ready', processed_at = now_iso(), error_code = NULL,"
        " error_message = NULL WHERE id = ?",
        (ctx.source_id,),
    )
    src_svc.merge_metadata(ctx.db, ctx.source_id, {"transcription": "pending"})


HANDLERS: dict[str, Callable[[JobContext], None]] = {
    "extract_document": extract_document,
    "prepare_audio": prepare_audio,
}


def set_source_status(
    db: sqlite3.Connection,
    source_id: str | None,
    status: str,
    code: str | None = None,
    message: str | None = None,
) -> None:
    if source_id:
        db.execute(
            "UPDATE sources SET status = ?, error_code = ?, error_message = ? WHERE id = ?",
            (status, code, message, source_id),
        )


def payload(job: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(job.get("payload_json") or "{}")
    return data
