"""Preferencias del usuario en la tabla `settings` (clave → JSON)."""

import json
import sqlite3
from typing import Any


def get(db: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = db.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(db: sqlite3.Connection, key: str, value: Any) -> None:
    db.execute(
        "INSERT INTO settings(key, value_json) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
        (key, json.dumps(value)),
    )
