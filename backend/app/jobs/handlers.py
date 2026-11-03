"""Manejadores de trabajos. Se ejecutan en un hilo; cada uno abre su propia conexión."""

import json
import shutil
import sqlite3
import uuid
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
from app.services import transcription
from app.stt import models
from app.stt.transcript import Piece, build_text
from app.stt.whisper_cpp import (
    SttError,
    kill_stale,
    slice_wav,
    transcribe_wav,
    wav_duration_ms,
)


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
    with tx(ctx.db):
        if transcription.ready(ctx.db, ctx.data_dir):
            # Sigue "procesando": la transcripción se encadena con prioridad alta.
            transcription.enqueue(ctx.db, ctx.source_id, payload(ctx.job).get("language"))
        else:
            # El audio ya se puede escuchar; se transcribirá al instalar el modelo.
            ctx.db.execute(
                "UPDATE sources SET status = 'ready', processed_at = now_iso(),"
                " error_code = NULL, error_message = NULL WHERE id = ?",
                (ctx.source_id,),
            )
            src_svc.merge_metadata(ctx.db, ctx.source_id, {"transcription": "needs_model"})


CHUNK_MS = 5 * 60_000  # tramos de 5 min: como mucho se repite un tramo tras un cierre
EDGE_MS = 3000  # frases que acaban tan cerca del corte se repiten en el tramo siguiente
MIN_ADVANCE_MS = 30_000


def _parts_dir(ctx: JobContext) -> Path:
    return ctx.data_dir / "sources" / ctx.source_id / "transcript-parts"


def transcribe(ctx: JobContext) -> None:
    """Transcribe por tramos con checkpoint: tras un cierre continúa en el último tramo."""
    src = ctx.source()
    wav = ctx.data_dir / "sources" / ctx.source_id / "normalized.wav"
    if not wav.exists():
        raise JobFailed("no_audio", "Falta el audio preparado. Reintenta el procesamiento.")
    p = payload(ctx.job)
    model_id = str(p.get("model") or models.DEFAULT_STT)
    model, vad = (
        models.model_path(ctx.data_dir, model_id),
        models.model_path(ctx.data_dir, models.VAD),
    )
    if not (
        models.is_installed(ctx.data_dir, model_id)
        and models.is_installed(ctx.data_dir, models.VAD)
    ):
        raise JobFailed("needs_model", "Descarga el modelo de transcripción para continuar.")

    cp: dict[str, Any] = json.loads(ctx.job.get("checkpoint_json") or "{}")
    next_ms = int(cp.get("next_ms", 0))
    language = str(cp.get("language") or p.get("language") or "auto")
    part = int(cp.get("parts", 0))
    total = wav_duration_ms(wav)
    parts = _parts_dir(ctx)
    parts.mkdir(exist_ok=True, mode=0o700)
    kill_stale(parts / "whisper.pid")  # whisper huérfano de un cierre brusco anterior
    src_svc.merge_metadata(ctx.db, ctx.source_id, {"transcription": "running"})
    if next_ms:
        ctx.report(next_ms / total, "Reanudando la transcripción")

    try:
        while next_ms < total:
            if ctx.cancelled():
                raise audio.Cancelled
            length = min(CHUNK_MS, total - next_ms)
            last = next_ms + length >= total
            ctx.report(next_ms / total, f"Transcribiendo {_clock(next_ms)} de {_clock(total)}")
            chunk = parts / f"chunk-{uuid.uuid4().hex}.wav"
            slice_wav(wav, chunk, next_ms, length)
            try:
                pieces, detected = transcribe_wav(
                    chunk, model, vad, language, next_ms, ctx.cancelled
                )
            finally:
                chunk.unlink(missing_ok=True)
            if language == "auto" and detected:
                language = detected  # el resto de la clase, en el mismo idioma
            end = next_ms + length
            if last:
                keep, new_next = pieces, total
            else:
                keep = [x for x in pieces if x.end_ms <= end - EDGE_MS]
                new_next = keep[-1].end_ms if keep else end
                if new_next - next_ms < MIN_ADVANCE_MS:
                    keep, new_next = pieces, end
            (parts / f"part_{part:05d}.json").write_text(
                json.dumps([x.__dict__ for x in keep], ensure_ascii=False), encoding="utf-8"
            )
            part += 1
            next_ms = new_next
            queue.save_checkpoint(
                ctx.db, ctx.job["id"], {"next_ms": next_ms, "language": language, "parts": part}
            )
    except SttError as e:
        raise JobFailed(e.code, e.message) from e

    ctx.report(0.99, "Guardando la transcripción")
    pieces = []
    for i in range(part):
        f = parts / f"part_{i:05d}.json"
        pieces += [Piece(**x) for x in json.loads(f.read_text(encoding="utf-8"))]
    text = build_text(pieces)
    with tx(ctx.db):
        if text.strip():
            src_svc.add_version(ctx.db, ctx.source_id, text, "transcribed")
        src_svc.merge_metadata(
            ctx.db,
            ctx.source_id,
            {"transcription": "done" if text.strip() else "empty", "stt_model": model_id},
        )
        ctx.db.execute(
            "UPDATE sources SET status = 'ready', processed_at = now_iso(), language = ?,"
            " duration_ms = COALESCE(duration_ms, ?), error_code = NULL, error_message = NULL"
            " WHERE id = ?",
            (language if language != "auto" else None, total, ctx.source_id),
        )
    shutil.rmtree(parts, ignore_errors=True)
    _ = src


def _clock(ms: int) -> str:
    s = ms // 1000
    return (
        f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    )


def download_model(ctx: JobContext) -> None:
    model_id = str(payload(ctx.job).get("model"))
    if model_id not in models.CATALOG:
        raise JobFailed("unknown_model", "Modelo desconocido")
    wanted = [m for m in (models.VAD, model_id) if not models.is_installed(ctx.data_dir, m)]
    sizes = sum(models.CATALOG[m].size for m in wanted) or 1
    done = 0
    try:
        for m in wanted:
            spec = models.CATALOG[m]
            base = done

            def progress(f: float, base: int = base, size: int = spec.size) -> None:
                ctx.report((base + f * size) / sizes, "Descargando modelo")

            models.download(ctx.data_dir, m, progress, ctx.cancelled)
            done += spec.size
    except models.DownloadCancelled as e:
        raise audio.Cancelled from e
    except models.DownloadError as e:
        raise JobFailed(e.code, e.message) from e
    transcription.enqueue_waiting(ctx.db, ctx.data_dir)


HANDLERS: dict[str, Callable[[JobContext], None]] = {
    "extract_document": extract_document,
    "prepare_audio": prepare_audio,
    "transcribe": transcribe,
    "download_model": download_model,
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
