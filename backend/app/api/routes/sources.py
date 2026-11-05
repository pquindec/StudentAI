import json
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field, StringConstraints

from app.api.deps import AppSettings, Db, UserId
from app.core import limits
from app.core.errors import AppError, bad_request, conflict
from app.db.connection import tx
from app.jobs import queue
from app.pipelines.extract.document import segment
from app.services import audio_files, transcription
from app.services import sources as svc
from app.services import subjects as subj
from app.services.subjects import remove_source_dir
from app.stt.transcript import to_srt, to_txt

router = APIRouter(tags=["sources"])

SourceKind = Literal[
    "recording", "audio", "pdf", "docx", "txt", "md", "rtf", "csv", "paste", "note"
]
SourceStatus = Literal["pending", "processing", "ready", "failed", "cancelled"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
IdList = Annotated[list[str], Field(max_length=200)]


class SourceOut(BaseModel):
    id: str
    subject_id: str
    kind: SourceKind
    title: str
    original_name: str | None
    mime: str | None
    size_bytes: int | None
    duration_ms: int | None
    page_count: int | None
    language: str | None
    status: SourceStatus
    error_code: str | None
    error_message: str | None
    needs_review: bool
    metadata: dict[str, Any]
    imported_at: str
    processed_at: str | None
    unit_ids: list[str]
    session_ids: list[str]
    version: int | None
    char_count: int | None


class SourceListOut(BaseModel):
    items: list[SourceOut]
    total: int


class TextSourceIn(BaseModel):
    subject_id: str
    kind: Literal["paste", "note"] = "paste"
    title: Title
    text: Annotated[str, StringConstraints(min_length=1, max_length=limits.MAX_PASTED_CHARS)]
    unit_ids: IdList = []
    session_ids: IdList = []


class SourcePatch(BaseModel):
    title: Title | None = None
    unit_ids: IdList | None = None
    session_ids: IdList | None = None


class SegmentOut(BaseModel):
    ordinal: int
    kind: Literal["heading", "paragraph", "table", "list"]
    level: int | None
    text: str
    page: int | None
    section_path: str | None
    start_ms: int | None
    end_ms: int | None
    char_start: int
    char_end: int


class VersionInfo(BaseModel):
    version: int
    origin: Literal["extracted", "transcribed", "user_edit", "pasted"]
    char_count: int
    created_at: str


class SourceContentOut(BaseModel):
    version: int
    origin: str
    text: str
    segments: list[SegmentOut]
    versions: list[VersionInfo]


class ContentIn(BaseModel):
    text: Annotated[str, StringConstraints(min_length=1, max_length=limits.MAX_PASTED_CHARS)]
    base_version: int = Field(ge=1)


def to_out(db: Db, row: dict[str, Any]) -> SourceOut:
    units, sessions = svc.links(db, row["id"])
    v = db.execute(
        "SELECT version, char_count FROM source_versions WHERE source_id = ?"
        " ORDER BY version DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    data = {k: val for k, val in row.items() if k in SourceOut.model_fields}
    data["needs_review"] = bool(row["needs_review"])
    return SourceOut(
        **data,
        metadata=json.loads(row["metadata_json"] or "{}"),
        unit_ids=units,
        session_ids=sessions,
        version=v["version"] if v else None,
        char_count=v["char_count"] if v else None,
    )


@router.get("/sources", response_model=SourceListOut)
def list_sources(
    db: Db,
    user: UserId,
    subject_id: str | None = None,
    unit_id: str | None = None,
    kind: SourceKind | None = None,
    status: SourceStatus | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SourceListOut:
    where = ["s.owner_id = ?"]
    args: list[Any] = [user]
    if subject_id:
        where.append("x.subject_id = ?")
        args.append(subject_id)
    if unit_id:
        where.append("x.id IN (SELECT source_id FROM source_links WHERE unit_id = ?)")
        args.append(unit_id)
    if kind:
        where.append("x.kind = ?")
        args.append(kind)
    if status:
        where.append("x.status = ?")
        args.append(status)
    if q:
        where.append("(x.title LIKE ? ESCAPE '\\' OR x.original_name LIKE ? ESCAPE '\\')")
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args += [pattern, pattern]
    base = f"FROM sources x JOIN subjects s ON s.id = x.subject_id WHERE {' AND '.join(where)}"
    total = db.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
    rows = db.execute(
        f"SELECT x.* {base} ORDER BY x.imported_at DESC LIMIT ? OFFSET ?",
        (*args, limit, offset),
    ).fetchall()
    return SourceListOut(items=[to_out(db, dict(r)) for r in rows], total=total)


@router.post("/sources/text", response_model=SourceOut, status_code=201)
def create_text_source(body: TextSourceIn, db: Db, user: UserId) -> SourceOut:
    subj.get_subject(db, user, body.subject_id)
    if not body.text.strip():
        raise bad_request("empty_text", "El texto está vacío")
    sid = svc.create_text_source(
        db,
        body.subject_id,
        body.kind,
        body.title,
        body.text.strip(),
        body.unit_ids,
        body.session_ids,
    )
    return to_out(db, svc.get_source(db, user, sid))


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: str, db: Db, user: UserId) -> SourceOut:
    return to_out(db, svc.get_source(db, user, source_id))


@router.patch("/sources/{source_id}", response_model=SourceOut)
def update_source(source_id: str, body: SourcePatch, db: Db, user: UserId) -> SourceOut:
    src = svc.get_source(db, user, source_id)
    with tx(db):
        if body.title is not None:
            db.execute("UPDATE sources SET title = ? WHERE id = ?", (body.title, source_id))
        if body.unit_ids is not None or body.session_ids is not None:
            cur_units, cur_sessions = svc.links(db, source_id)
            units = body.unit_ids if body.unit_ids is not None else cur_units
            sessions = body.session_ids if body.session_ids is not None else cur_sessions
            svc.check_link_targets(db, src["subject_id"], units, sessions)
            svc.set_links(db, source_id, units, sessions)
    return to_out(db, svc.get_source(db, user, source_id))


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str, db: Db, user: UserId, settings: AppSettings) -> Response:
    svc.get_source(db, user, source_id)
    with tx(db):
        db.execute(
            "UPDATE jobs SET cancel_requested = 1 WHERE source_id = ? AND status = 'running'",
            (source_id,),
        )
        db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    remove_source_dir(settings.data_dir, source_id)
    return Response(status_code=204)


@router.get("/sources/{source_id}/content", response_model=SourceContentOut)
def get_content(
    source_id: str, db: Db, user: UserId, version: Annotated[int | None, Query(ge=1)] = None
) -> SourceContentOut:
    svc.get_source(db, user, source_id)
    if version is None:
        v = svc.current_version(db, source_id)
    else:
        row = db.execute(
            "SELECT * FROM source_versions WHERE source_id = ? AND version = ?",
            (source_id, version),
        ).fetchone()
        v = dict(row) if row else None
    if v is None:
        raise AppError(404, "no_content", "Esta fuente aún no tiene texto")
    segs = db.execute(
        "SELECT * FROM segments WHERE version_id = ? ORDER BY ordinal", (v["id"],)
    ).fetchall()
    versions = db.execute(
        "SELECT version, origin, char_count, created_at FROM source_versions"
        " WHERE source_id = ? ORDER BY version DESC",
        (source_id,),
    ).fetchall()
    return SourceContentOut(
        version=v["version"],
        origin=v["origin"],
        text=v["text"],
        segments=[SegmentOut(**{k: s[k] for k in SegmentOut.model_fields}) for s in segs],
        versions=[VersionInfo(**dict(x)) for x in versions],
    )


@router.put("/sources/{source_id}/content", response_model=SourceContentOut)
def update_content(source_id: str, body: ContentIn, db: Db, user: UserId) -> SourceContentOut:
    """Guarda una edición como versión NUEVA (la anterior se conserva)."""
    svc.get_source(db, user, source_id)
    with tx(db, immediate=True):
        cur = svc.current_version(db, source_id)
        if cur is None:
            raise AppError(409, "no_content", "Esta fuente aún no tiene texto")
        if cur["version"] != body.base_version:
            raise conflict(
                "version_conflict",
                "El texto cambió mientras lo editabas. Recarga y vuelve a aplicar tus cambios.",
                current_version=cur["version"],
            )
        if body.text.strip() == cur["text"].strip():
            raise bad_request("no_changes", "No hay cambios que guardar")
        svc.add_version(db, source_id, body.text.strip(), "user_edit")
        db.execute("UPDATE sources SET needs_review = 0 WHERE id = ?", (source_id,))
    return get_content(source_id, db, user)


@router.post("/sources/{source_id}/retry", response_model=SourceOut)
def retry(
    source_id: str, request: Request, db: Db, user: UserId, settings: AppSettings
) -> SourceOut:
    src = svc.get_source(db, user, source_id)
    if src["status"] not in ("failed", "cancelled"):
        raise bad_request(
            "not_retryable", "Solo se pueden reintentar fuentes fallidas o canceladas"
        )
    if src["stored_path"] is None:
        raise bad_request("not_retryable", "Esta fuente no tiene archivo que procesar")
    # Audio ya transcrito antes: el original se borró y se reintenta desde la copia ligera.
    audio_state = (
        audio_files.state(settings.data_dir, src)[0]
        if src["kind"] in audio_files.AUDIO_KINDS
        else "full"
    )
    if audio_state == "deleted":
        raise _audio_deleted()
    with tx(db):
        db.execute(
            "UPDATE sources SET status = 'pending', error_code = NULL, error_message = NULL"
            " WHERE id = ?",
            (source_id,),
        )
        if audio_state == "light":
            transcription.enqueue(db, source_id)
        else:
            enqueue_processing(db, src["kind"], source_id)
    request.app.state.scheduler.wake()
    return to_out(db, svc.get_source(db, user, source_id))


class TranscribeIn(BaseModel):
    language: Literal["auto", "es", "en"] | None = None


@router.post("/sources/{source_id}/transcribe", response_model=SourceOut, status_code=202)
def transcribe_source(
    source_id: str,
    body: TranscribeIn,
    request: Request,
    db: Db,
    user: UserId,
    settings: AppSettings,
) -> SourceOut:
    """(Re)transcribe un audio ya preparado. La transcripción anterior se conserva como versión."""
    src = svc.get_source(db, user, source_id)
    if src["kind"] not in ("audio", "recording"):
        raise bad_request("not_audio", "Solo se pueden transcribir audios y grabaciones")
    if src["status"] in ("pending", "processing"):
        raise conflict("busy", "Este audio se está procesando todavía")
    if not audio_files.light_path(settings.data_dir, source_id).exists():
        if audio_files.state(settings.data_dir, src)[0] == "deleted":
            raise _audio_deleted()
        raise bad_request("not_prepared", "Reintenta el procesamiento del audio primero")
    if not transcription.ready(db, settings.data_dir):
        raise bad_request("needs_model", "Descarga el modelo de transcripción para continuar")
    with tx(db):
        db.execute(
            "UPDATE sources SET status = 'pending', error_code = NULL, error_message = NULL"
            " WHERE id = ?",
            (source_id,),
        )
        transcription.enqueue(db, source_id, body.language)
    request.app.state.scheduler.wake()
    return to_out(db, svc.get_source(db, user, source_id))


def _audio_deleted() -> AppError:
    return bad_request(
        "audio_deleted",
        "El audio de esta clase se borró para liberar espacio. La transcripción se conserva.",
    )


class AudioOut(BaseModel):
    state: Literal["full", "light", "deleted"]
    bytes: int
    expires_at: str | None  # cuándo se borrará solo (None: nunca o aún sin transcribir)
    deletable: bool  # transcrita y sin trabajos en curso


def _audio_out(db: Db, data_dir: Path, src: dict[str, Any]) -> AudioOut:
    if src["kind"] not in audio_files.AUDIO_KINDS:
        raise bad_request("not_audio", "Esta fuente no tiene audio")
    st, size = audio_files.state(data_dir, src)
    ok = st != "deleted" and audio_files.deletable(db, src)
    return AudioOut(
        state=st,
        bytes=size,
        expires_at=audio_files.expires_at(db, src) if st != "deleted" else None,
        deletable=ok,
    )


@router.get("/sources/{source_id}/audio", response_model=AudioOut)
def get_audio(source_id: str, db: Db, user: UserId, settings: AppSettings) -> AudioOut:
    return _audio_out(db, settings.data_dir, svc.get_source(db, user, source_id))


@router.delete("/sources/{source_id}/audio", response_model=AudioOut)
def delete_audio(source_id: str, db: Db, user: UserId, settings: AppSettings) -> AudioOut:
    """Borra el audio de una clase ya transcrita. La transcripción no se toca."""
    src = svc.get_source(db, user, source_id)
    if src["kind"] not in audio_files.AUDIO_KINDS:
        raise bad_request("not_audio", "Esta fuente no tiene audio")
    if not audio_files.deletable(db, src):
        raise conflict(
            "not_transcribed",
            "Solo se puede borrar el audio de una clase ya transcrita y sin tareas en curso",
        )
    audio_files.delete_now(db, settings.data_dir, src)
    return _audio_out(db, settings.data_dir, svc.get_source(db, user, source_id))


class ExportOut(BaseModel):
    filename: str
    content: str


@router.get("/sources/{source_id}/export", response_model=ExportOut)
def export_source(
    source_id: str, db: Db, user: UserId, format: Literal["txt", "srt"] = "txt"
) -> ExportOut:
    src = svc.get_source(db, user, source_id)
    version = svc.current_version(db, source_id)
    if version is None:
        raise bad_request("no_content", "Este material todavía no tiene texto")
    segs = segment(version["text"])
    if format == "srt":
        if not any(x.start_ms is not None for x in segs):
            raise bad_request("no_timestamps", "Este texto no tiene marcas de tiempo")
        content = to_srt(segs, src["duration_ms"])
    else:
        content = to_txt(version["text"])
    stem = "".join(c for c in src["title"] if c.isalnum() or c in " -_").strip()[:80]
    return ExportOut(filename=f"{stem or 'transcripcion'}.{format}", content=content)


def enqueue_processing(db: Db, kind: str, source_id: str) -> str:
    if kind in ("audio", "recording"):
        return queue.enqueue(db, "prepare_audio", "media", source_id)
    return queue.enqueue(db, "extract_document", "io", source_id)
