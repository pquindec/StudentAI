"""Punto de entrada del backend. Lo lanza y supervisa el proceso Rust de Tauri.

Protocolo con el proceso padre:
  1. Argumentos: --data-dir y --socket.
  2. Primera línea de stdin: token de sesión (nunca por argumentos ni variables de entorno).
  3. El padre mantiene stdin abierto; cuando se cierra (EOF), el backend termina.
"""

import argparse
import logging
import os
import socket
import stat
import sys
import threading
from pathlib import Path

import uvicorn

from app.api.app import create_app
from app.core import children
from app.core.config import Settings
from app.db.migrate import migrate

log = logging.getLogger("studyassistant")


def read_token() -> str:
    token = sys.stdin.readline().strip()
    if len(token) < 32:
        raise SystemExit("Token de sesión ausente o inválido")
    return token


def exit_when_parent_dies() -> None:
    def watch() -> None:
        sys.stdin.read()  # bloquea hasta EOF
        log.info("stdin cerrado: el proceso padre ha terminado, saliendo")
        children.kill_all()  # sin whisper/ffmpeg huérfanos
        os._exit(0)

    threading.Thread(target=watch, daemon=True, name="parent-watch").start()


def remove_stale_socket(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise SystemExit(f"{path} existe y no es un socket; no se elimina")
        path.unlink()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="studyassistant-backend")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    token = read_token()

    settings = Settings(data_dir=args.data_dir, socket_path=args.socket, token=token)
    settings.prepare_dirs()
    version = migrate(settings.db_path, backups_dir=settings.backups_dir)
    log.info("Base de datos lista (esquema v%d)", version)

    sock = bind_private_socket(settings.socket_path)
    # Se vigila al padre solo cuando el arranque ha ido bien: así los errores de arranque
    # no quedan ocultos por una salida "limpia".
    exit_when_parent_dies()
    config = uvicorn.Config(
        create_app(settings), log_level="warning", access_log=False, server_header=False
    )
    uvicorn.Server(config).run(sockets=[sock])


def bind_private_socket(path: Path) -> socket.socket:
    """Crea el Unix socket con permisos 0600. No se usa `uvicorn.run(uds=...)` porque uvicorn
    aplica chmod 0666 al socket."""
    remove_stale_socket(path)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)
    try:
        sock.bind(str(path))
    finally:
        os.umask(old_umask)
    path.chmod(0o600)
    return sock


if __name__ == "__main__":
    main()
