"""Registro de procesos hijos (ffmpeg, whisper) para no dejar huérfanos al salir."""

import contextlib
import subprocess
import threading

_lock = threading.Lock()
_children: set[subprocess.Popen[str]] = set()


def register(p: subprocess.Popen[str]) -> None:
    with _lock:
        _children.add(p)


def unregister(p: subprocess.Popen[str]) -> None:
    with _lock:
        _children.discard(p)


def kill_all() -> None:
    with _lock:
        procs = list(_children)
    for p in procs:
        with contextlib.suppress(OSError):
            p.kill()
