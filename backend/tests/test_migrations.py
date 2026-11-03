import sqlite3
import stat
from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.connection import connect
from app.db.migrate import available, migrate

LATEST = max(v for v, _ in available())
NEXT = f"{LATEST + 1:04d}"


def _copy_real_migrations(dest: Path) -> None:
    dest.mkdir()
    for _, f in available():
        (dest / f.name).write_text(f.read_text())


def test_migrate_is_idempotent(settings: Settings) -> None:
    assert migrate(settings.db_path, settings.backups_dir) == LATEST
    assert migrate(settings.db_path, settings.backups_dir) == LATEST


def test_db_file_is_private(settings: Settings) -> None:
    assert stat.S_IMODE(settings.db_path.stat().st_mode) == 0o600


def test_local_user_exists(settings: Settings) -> None:
    conn = connect(settings.db_path)
    assert conn.execute("SELECT role FROM users WHERE id='local'").fetchone()[0] == "owner"


def test_backup_before_new_migration(settings: Settings, tmp_path: Path) -> None:
    mig = tmp_path / "migs"
    _copy_real_migrations(mig)
    (mig / f"{NEXT}_extra.sql").write_text("CREATE TABLE extra (id INTEGER PRIMARY KEY);")
    assert migrate(settings.db_path, settings.backups_dir, mig) == LATEST + 1
    backups = list(settings.backups_dir.glob(f"app-*-pre-{NEXT}.db"))
    assert len(backups) == 1


def test_failed_migration_rolls_back(settings: Settings, tmp_path: Path) -> None:
    mig = tmp_path / "migs"
    _copy_real_migrations(mig)
    (mig / f"{NEXT}_bad.sql").write_text("CREATE TABLE half (id INTEGER); SELECT * FROM nope;")
    with pytest.raises(sqlite3.Error):
        migrate(settings.db_path, settings.backups_dir, mig)
    conn = connect(settings.db_path)
    assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == LATEST
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "half" not in tables


def _subject(conn: sqlite3.Connection, sid: str) -> None:
    conn.execute("INSERT INTO subjects(id, owner_id, name) VALUES (?, 'local', ?)", (sid, sid))


def test_unit_parent_must_be_same_subject(settings: Settings) -> None:
    conn = connect(settings.db_path)
    _subject(conn, "s1")
    _subject(conn, "s2")
    conn.execute(
        "INSERT INTO units(id, subject_id, kind, title) VALUES ('c1','s1','course','Curso')"
    )
    conn.execute(
        "INSERT INTO units(id, subject_id, parent_id, kind, title) "
        "VALUES ('t1','s1','c1','topic','Tema')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="parent_unit_other_subject"):
        conn.execute(
            "INSERT INTO units(id, subject_id, parent_id, kind, title) "
            "VALUES ('t2','s2','c1','topic','Tema')"
        )


def test_unit_cannot_be_own_parent(settings: Settings) -> None:
    conn = connect(settings.db_path)
    _subject(conn, "s1")
    conn.execute("INSERT INTO units(id, subject_id, kind, title) VALUES ('u1','s1','topic','T')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE units SET parent_id='u1' WHERE id='u1'")


def test_deleting_subject_cascades(settings: Settings) -> None:
    conn = connect(settings.db_path)
    _subject(conn, "s1")
    conn.execute("INSERT INTO units(id, subject_id, kind, title) VALUES ('u1','s1','topic','T')")
    conn.execute(
        "INSERT INTO sessions(id, subject_id, unit_id, kind, title) "
        "VALUES ('x1','s1','u1','class','Clase 1')"
    )
    conn.execute("DELETE FROM subjects WHERE id='s1'")
    assert conn.execute("SELECT COUNT(*) FROM units").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
