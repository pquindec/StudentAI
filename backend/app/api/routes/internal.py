"""Endpoints que SOLO invoca el núcleo Rust (el proxy de la UI rechaza `/api/v1/internal/`).

Importar por ruta de archivo es una capacidad sensible: Rust solo la usa con rutas que el
usuario eligió explícitamente (diálogo de Finder o arrastrar y soltar).
"""

import sqlite3
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, StringConstraints

from app.api.deps import AppSettings, Db, UserId
from app.api.routes.sources import SourceOut, enqueue_processing, to_out
from app.core import limits
from app.core.errors import AppError, conflict
from app.db.connection import tx
from app.pipelines import files
from app.services import sources as svc
from app.services import subjects as subj

CORE_HEADER = "x-core-caller"


def require_core(request: Request) -> None:
    """Defensa en profundidad: el proxy de la UI nunca añade esta cabecera (la UI no puede
    fijar cabeceras), solo los comandos propios del núcleo Rust."""
    if request.headers.get(CORE_HEADER) != "1":
        raise AppError(403, "forbidden", "Operación no permitida")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    include_in_schema=False,
    dependencies=[Depends(require_core)],
)


class ImportFileIn(BaseModel):
    path: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    subject_id: str
    unit_ids: Annotated[list[str], Field(max_length=200)] = []
    session_ids: Annotated[list[str], Field(max_length=200)] = []


@router.post("/sources/import-file", response_model=SourceOut, status_code=201)
def import_file(
    body: ImportFileIn, request: Request, db: Db, user: UserId, settings: AppSettings
) -> SourceOut:
    subj.get_subject(db, user, body.subject_id)
    path = Path(body.path)
    name = path.name[:255]
    info = files.inspect(path, name)
    sources_dir = settings.data_dir / "sources"
    tmp, sha, size = files.store_copy(path, sources_dir, limits.MAX_BYTES[info.kind])
    try:
        dup = db.execute(
            "SELECT id, title FROM sources WHERE subject_id = ? AND sha256 = ?",
            (body.subject_id, sha),
        ).fetchone()
        if dup:
            raise conflict(
                "duplicate",
                f"«{name}» ya está en esta asignatura como «{dup['title']}»",
                source_id=dup["id"],
            )
        sid = str(uuid.uuid4())
        stored = files.finalize(tmp, sources_dir, sid, info.ext)
        kind = "audio" if info.kind == "audio" else info.kind
        try:
            with tx(db):
                svc.check_link_targets(db, body.subject_id, body.unit_ids, body.session_ids)
                db.execute(
                    "INSERT INTO sources(id, subject_id, kind, title, original_name, stored_path,"
                    " sha256, mime, size_bytes) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        sid,
                        body.subject_id,
                        kind,
                        Path(name).stem[:300] or name,
                        name,
                        str(stored.relative_to(settings.data_dir)),
                        sha,
                        info.mime,
                        size,
                    ),
                )
                svc.set_links(db, sid, body.unit_ids, body.session_ids)
                enqueue_processing(db, kind, sid)
        except (AppError, sqlite3.Error):
            subj.remove_source_dir(settings.data_dir, sid)
            raise
    finally:
        tmp.unlink(missing_ok=True)
    request.app.state.scheduler.wake()
    return to_out(db, svc.get_source(db, user, sid))
