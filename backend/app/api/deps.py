import sqlite3
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.db.connection import get_db

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def current_user() -> str:
    """Escritorio: un único usuario local. El modo web (ADR-009) lo obtendrá de la sesión."""
    return "local"


UserId = Annotated[str, Depends(current_user)]


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(get_settings)]
