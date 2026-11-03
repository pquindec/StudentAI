import platform
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.config import APP_VERSION
from app.db.connection import get_db
from app.db.migrate import current_version

router = APIRouter(tags=["system"])
Db = Annotated[sqlite3.Connection, Depends(get_db)]


class HealthOut(BaseModel):
    status: str
    version: str
    schema_version: int


class SystemInfoOut(BaseModel):
    version: str
    python_version: str
    sqlite_version: str
    fts5_available: bool
    schema_version: int
    data_dir: str
    user_display_name: str


@router.get("/health", response_model=HealthOut)
def health(db: Db) -> HealthOut:
    return HealthOut(status="ok", version=APP_VERSION, schema_version=current_version(db))


@router.get("/system/info", response_model=SystemInfoOut)
def system_info(request: Request, db: Db) -> SystemInfoOut:
    options = {r[0] for r in db.execute("PRAGMA compile_options")}
    user = db.execute("SELECT display_name FROM users WHERE id = 'local'").fetchone()
    return SystemInfoOut(
        version=APP_VERSION,
        python_version=platform.python_version(),
        sqlite_version=sqlite3.sqlite_version,
        fts5_available="ENABLE_FTS5" in options,
        schema_version=current_version(db),
        data_dir=str(request.app.state.settings.data_dir),
        user_display_name=user["display_name"] if user else "",
    )
