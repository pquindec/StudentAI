from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, StringConstraints

from app.api.deps import AppSettings, Db, UserId
from app.db.connection import tx
from app.services import subjects as svc

router = APIRouter(tags=["subjects"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
UnitKind = Literal["course", "module", "topic"]
SessionKind = Literal["class", "study"]


class SubjectIn(BaseModel):
    name: Name
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    color: Color | None = None
    term: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None


class SubjectPatch(BaseModel):
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    color: Color | None = None
    term: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    archived: bool | None = None


class SubjectOut(BaseModel):
    id: str
    name: str
    description: str | None
    color: str | None
    term: str | None
    archived_at: str | None
    created_at: str
    updated_at: str
    source_count: int = 0
    unit_count: int = 0


class UnitIn(BaseModel):
    kind: UnitKind
    title: Name
    parent_id: str | None = None
    position: int = Field(default=0, ge=0, le=100_000)


class UnitPatch(BaseModel):
    title: Name | None = None
    parent_id: str | None = None
    position: int | None = Field(default=None, ge=0, le=100_000)


class UnitOut(BaseModel):
    id: str
    subject_id: str
    parent_id: str | None
    kind: UnitKind
    title: str
    position: int


class SessionIn(BaseModel):
    kind: SessionKind
    title: Name
    unit_id: str | None = None
    held_at: str | None = Field(default=None, max_length=40)
    duration_ms: int | None = Field(default=None, ge=0)
    notes: Annotated[str, StringConstraints(max_length=10_000)] | None = None


class SessionPatch(BaseModel):
    title: Name | None = None
    unit_id: str | None = None
    held_at: str | None = Field(default=None, max_length=40)
    notes: Annotated[str, StringConstraints(max_length=10_000)] | None = None


class SessionOut(BaseModel):
    id: str
    subject_id: str
    unit_id: str | None
    kind: SessionKind
    title: str
    held_at: str | None
    duration_ms: int | None
    notes: str | None


class SubjectDetailOut(SubjectOut):
    units: list[UnitOut]
    sessions: list[SessionOut]


# ---------- asignaturas ----------
@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(db: Db, user: UserId, archived: bool = Query(False)) -> list[SubjectOut]:
    return [SubjectOut(**r) for r in svc.list_subjects(db, user, archived)]


@router.post("/subjects", response_model=SubjectOut, status_code=201)
def create_subject(body: SubjectIn, db: Db, user: UserId) -> SubjectOut:
    sid = svc.new_id()
    db.execute(
        "INSERT INTO subjects(id, owner_id, name, description, color, term) VALUES (?,?,?,?,?,?)",
        (sid, user, body.name, body.description, body.color, body.term),
    )
    return SubjectOut(**svc.get_subject(db, user, sid))


@router.get("/subjects/{subject_id}", response_model=SubjectDetailOut)
def get_subject(subject_id: str, db: Db, user: UserId) -> SubjectDetailOut:
    s = svc.get_subject(db, user, subject_id)
    units = db.execute(
        "SELECT * FROM units WHERE subject_id = ? ORDER BY position, title COLLATE NOCASE",
        (subject_id,),
    ).fetchall()
    sessions = db.execute(
        "SELECT * FROM sessions WHERE subject_id = ? ORDER BY held_at DESC, created_at DESC",
        (subject_id,),
    ).fetchall()
    counts = db.execute(
        "SELECT (SELECT COUNT(*) FROM sources WHERE subject_id = ?),"
        " (SELECT COUNT(*) FROM units WHERE subject_id = ?)",
        (subject_id, subject_id),
    ).fetchone()
    return SubjectDetailOut(
        **s,
        source_count=counts[0],
        unit_count=counts[1],
        units=[UnitOut(**dict(u)) for u in units],
        sessions=[SessionOut(**dict(x)) for x in sessions],
    )


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(subject_id: str, body: SubjectPatch, db: Db, user: UserId) -> SubjectOut:
    svc.get_subject(db, user, subject_id)
    fields = body.model_dump(exclude_unset=True)
    archived = fields.pop("archived", None)
    sets = [f"{k} = ?" for k in fields]
    values: list[object] = list(fields.values())
    if archived is not None:
        sets.append("archived_at = " + ("now_iso()" if archived else "NULL"))
    if sets:
        db.execute(
            f"UPDATE subjects SET {', '.join(sets)}, updated_at = now_iso() WHERE id = ?",  # noqa: S608
            (*values, subject_id),
        )
    return SubjectOut(**svc.get_subject(db, user, subject_id))


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_subject(subject_id: str, db: Db, user: UserId, settings: AppSettings) -> Response:
    svc.get_subject(db, user, subject_id)
    ids = [r[0] for r in db.execute("SELECT id FROM sources WHERE subject_id = ?", (subject_id,))]
    db.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
    svc.delete_subject_files(settings.data_dir, ids)
    return Response(status_code=204)


# ---------- unidades ----------
@router.post("/subjects/{subject_id}/units", response_model=UnitOut, status_code=201)
def create_unit(subject_id: str, body: UnitIn, db: Db, user: UserId) -> UnitOut:
    svc.get_subject(db, user, subject_id)
    uid = svc.new_id()
    with tx(db):
        svc.check_unit_parent(db, subject_id, body.kind, body.parent_id, None)
        db.execute(
            "INSERT INTO units(id, subject_id, parent_id, kind, title, position)"
            " VALUES (?,?,?,?,?,?)",
            (uid, subject_id, body.parent_id, body.kind, body.title, body.position),
        )
    return UnitOut(**svc.get_unit(db, user, uid))


@router.patch("/units/{unit_id}", response_model=UnitOut)
def update_unit(unit_id: str, body: UnitPatch, db: Db, user: UserId) -> UnitOut:
    unit = svc.get_unit(db, user, unit_id)
    fields = body.model_dump(exclude_unset=True)
    with tx(db):
        if "parent_id" in fields:
            svc.check_unit_parent(
                db, unit["subject_id"], unit["kind"], fields["parent_id"], unit_id
            )
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            db.execute(
                f"UPDATE units SET {sets}, updated_at = now_iso() WHERE id = ?",  # noqa: S608
                (*fields.values(), unit_id),
            )
    return UnitOut(**svc.get_unit(db, user, unit_id))


@router.delete("/units/{unit_id}", status_code=204)
def delete_unit(unit_id: str, db: Db, user: UserId) -> Response:
    svc.get_unit(db, user, unit_id)
    # Las subunidades se borran en cascada; las fuentes NO (solo pierden el vínculo).
    db.execute("DELETE FROM units WHERE id = ?", (unit_id,))
    return Response(status_code=204)


# ---------- sesiones ----------
@router.post("/subjects/{subject_id}/sessions", response_model=SessionOut, status_code=201)
def create_session(subject_id: str, body: SessionIn, db: Db, user: UserId) -> SessionOut:
    svc.get_subject(db, user, subject_id)
    svc.check_unit_in_subject(db, subject_id, body.unit_id)
    xid = svc.new_id()
    db.execute(
        "INSERT INTO sessions(id, subject_id, unit_id, kind, title, held_at, duration_ms, notes)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            xid,
            subject_id,
            body.unit_id,
            body.kind,
            body.title,
            body.held_at,
            body.duration_ms,
            body.notes,
        ),
    )
    return SessionOut(**svc.get_session(db, user, xid))


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def update_session(session_id: str, body: SessionPatch, db: Db, user: UserId) -> SessionOut:
    x = svc.get_session(db, user, session_id)
    fields = body.model_dump(exclude_unset=True)
    if "unit_id" in fields:
        svc.check_unit_in_subject(db, x["subject_id"], fields["unit_id"])
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        db.execute(
            f"UPDATE sessions SET {sets}, updated_at = now_iso() WHERE id = ?",  # noqa: S608
            (*fields.values(), session_id),
        )
    return SessionOut(**svc.get_session(db, user, session_id))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, db: Db, user: UserId) -> Response:
    svc.get_session(db, user, session_id)
    db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return Response(status_code=204)
