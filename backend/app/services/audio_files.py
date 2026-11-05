"""Retención del audio de clases ya transcritas. La transcripción (y todo lo generado con ella)
nunca se borra; solo los archivos de audio:

- `original.*`: el archivo grabado o importado, pesado (~385 MB/h en WAV). Se borra en cuanto la
  transcripción termina bien: ya no hace falta para nada.
- `normalized.wav`: copia ligera (16 kHz mono, ~115 MB/h) para escuchar la clase, saltar al
  minuto desde una cita y volver a transcribir. Se borra cuando pasan los días elegidos desde la
  última transcripción (`audio.keep_days`: 7 por defecto, 30 o 0 = conservar siempre).
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.db.connection import tx
from app.services import settings as prefs
from app.services import sources as src_svc

KEEP_DAYS_KEY = "audio.keep_days"
KEEP_CHOICES = (0, 7, 30)
DEFAULT_KEEP_DAYS = 7
AUDIO_KINDS = ("audio", "recording")

AudioState = Literal["full", "light", "deleted"]


def keep_days(db: sqlite3.Connection) -> int:
    days = prefs.get(db, KEEP_DAYS_KEY, DEFAULT_KEEP_DAYS)
    return days if days in KEEP_CHOICES else DEFAULT_KEEP_DAYS


def _dir(data_dir: Path, source_id: str) -> Path:
    return data_dir / "sources" / source_id


def original_path(data_dir: Path, row: dict[str, Any]) -> Path | None:
    return data_dir / row["stored_path"] if row.get("stored_path") else None


def light_path(data_dir: Path, source_id: str) -> Path:
    return _dir(data_dir, source_id) / "normalized.wav"


def _size(p: Path | None) -> int:
    try:
        return p.stat().st_size if p else 0
    except OSError:
        return 0


def state(data_dir: Path, row: dict[str, Any]) -> tuple[AudioState, int]:
    """Qué audio queda en disco y cuánto ocupa."""
    orig, light = _size(original_path(data_dir, row)), _size(light_path(data_dir, row["id"]))
    if orig:
        return "full", orig + light
    return ("light", light) if light else ("deleted", 0)


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def expires_at(db: sqlite3.Connection, row: dict[str, Any]) -> str | None:
    """Cuándo se borrará la copia ligera (None si no hay plazo o aún no está transcrita)."""
    days = keep_days(db)
    if not days or not _transcribed(row) or not row.get("processed_at"):
        return None
    when = _parse(row["processed_at"]) + timedelta(days=days)
    return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _transcribed(row: dict[str, Any]) -> bool:
    meta = json.loads(row.get("metadata_json") or "{}")
    return bool(row["status"] == "ready" and meta.get("transcription") == "done")


def _busy(db: sqlite3.Connection, source_id: str, own_job: str | None = None) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM jobs WHERE source_id = ? AND status IN ('queued', 'running')"
            " AND id IS NOT ?",
            (source_id, own_job),
        ).fetchone()
        is not None
    )


def deletable(db: sqlite3.Connection, row: dict[str, Any]) -> bool:
    return _transcribed(row) and not _busy(db, row["id"])


def _unlink(p: Path | None) -> int:
    size = _size(p)
    if p is not None:
        p.unlink(missing_ok=True)
    return size


def apply(
    db: sqlite3.Connection,
    data_dir: Path,
    row: dict[str, Any],
    now: datetime | None = None,
    own_job: str | None = None,
) -> int:
    """Aplica la política a una fuente. Devuelve los bytes liberados. Solo actúa sobre audios
    transcritos con texto y sin trabajos en curso (salvo `own_job`, el que llama)."""
    if row["kind"] not in AUDIO_KINDS or not _transcribed(row) or _busy(db, row["id"], own_job):
        return 0
    freed = _unlink(original_path(data_dir, row))
    exp = expires_at(db, row)
    if exp and _parse(exp) <= (now or datetime.now(UTC)):
        freed += _unlink(light_path(data_dir, row["id"]))
    if freed:
        _mark(db, row["id"])
    return freed


def delete_now(db: sqlite3.Connection, data_dir: Path, row: dict[str, Any]) -> int:
    """Borrado pedido por el usuario: todo el audio de una clase ya transcrita."""
    freed = _unlink(original_path(data_dir, row)) + _unlink(light_path(data_dir, row["id"]))
    _mark(db, row["id"])
    return freed


def _mark(db: sqlite3.Connection, source_id: str) -> None:
    with tx(db):
        src_svc.merge_metadata(
            db, source_id, {"audio_cleaned_at": datetime.now(UTC).isoformat(timespec="seconds")}
        )


def sweep(db: sqlite3.Connection, data_dir: Path, now: datetime | None = None) -> int:
    """Recorre todos los audios transcritos (al arrancar y cada hora)."""
    rows = db.execute(
        "SELECT * FROM sources WHERE kind IN ('audio', 'recording') AND status = 'ready'"
    ).fetchall()
    return sum(apply(db, data_dir, dict(r), now) for r in rows)
