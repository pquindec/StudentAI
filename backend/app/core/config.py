"""Configuración del proceso backend (inmutable durante la ejecución)."""

import os
from dataclasses import dataclass
from pathlib import Path

APP_VERSION = "0.1.0"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    socket_path: Path
    token: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def prepare_dirs(self) -> None:
        """Crea los directorios de datos y del socket, solo accesibles por el usuario (0700).

        Nunca cambia permisos de un directorio ajeno: si existe y no es del usuario actual,
        se aborta (evita, p. ej., colocar el socket en /tmp compartido).
        """
        for d in (self.data_dir, self.backups_dir, self.logs_dir, self.socket_path.parent):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = d.stat()
            if info.st_uid != os.getuid():
                raise SystemExit(f"El directorio {d} no pertenece al usuario actual")
            if info.st_mode & 0o077:
                d.chmod(0o700)
