"""Migraciones versionadas: archivos `NNNN_nombre.sql` aplicados en orden, cada uno en su
propia transacción. Antes de aplicar migraciones sobre una base existente se hace copia."""

import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.db.connection import connect

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
KEEP_BACKUPS = 5
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def available(migrations_dir: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    found = []
    for f in sorted(migrations_dir.iterdir()):
        m = _NAME.match(f.name)
        if m:
            found.append((int(m.group(1)), f))
    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise RuntimeError("Hay migraciones con el mismo número de versión")
    return found


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def backup(conn: sqlite3.Connection, backups_dir: Path, label: str) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backups_dir / f"app-{stamp}-{label}.db"
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    target.chmod(0o600)
    old = sorted(backups_dir.glob("app-*.db"))[:-KEEP_BACKUPS]
    for f in old:
        f.unlink()
    return target


def migrate(db_path: Path, backups_dir: Path, migrations_dir: Path = MIGRATIONS_DIR) -> int:
    """Aplica las migraciones pendientes y devuelve la versión final del esquema."""
    is_new = not db_path.exists()
    conn = connect(db_path)
    try:
        version = current_version(conn)
        pending = [(v, f) for v, f in available(migrations_dir) if v > version]
        if pending and not is_new and version > 0:
            path = backup(conn, backups_dir, f"pre-{pending[0][0]:04d}")
            log.info("Copia de seguridad antes de migrar: %s", path.name)
        for v, f in pending:
            sql = f.read_text(encoding="utf-8")
            now = datetime.now(UTC).isoformat()
            try:
                conn.executescript(
                    "BEGIN;\n"
                    f"{sql}\n"
                    f"INSERT INTO schema_migrations(version, name, applied_at) "
                    f"VALUES ({v}, '{f.stem}', '{now}');\n"
                    "COMMIT;"
                )
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.rollback()
                raise
            log.info("Migración aplicada: %s", f.name)
        if db_path.exists():
            db_path.chmod(0o600)
        return current_version(conn)
    finally:
        conn.close()
