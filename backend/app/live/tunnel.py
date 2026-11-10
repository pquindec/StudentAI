"""Acceso a la sala por internet con un túnel rápido de Cloudflare (`cloudflared`, Apache-2.0).

Solo para cuando la Wi-Fi del aula no deja que los teléfonos lleguen al Mac (aislamiento entre
dispositivos). Lo activa el usuario en cada sala, tras un aviso: el tráfico de la sala (nombres,
preguntas y respuestas) pasa por Cloudflare. No necesita cuenta; la dirección
`https://….trycloudflare.com` es aleatoria y cambia cada vez. `cloudflared` no va incluido en la
app: se instala aparte (`brew install cloudflared`).
"""

import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)

CANDIDATES = (Path("/opt/homebrew/bin/cloudflared"), Path("/usr/local/bin/cloudflared"))
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
READY = "Registered tunnel connection"
START_TIMEOUT_S = 45

# Si el backend muere de golpe (p. ej. al reiniciar la app en desarrollo), `cloudflared` no debe
# quedarse abierto: un `sh` vigila el proceso padre y lo cierra.
WATCH = (
    'p=$1; shift; "$@" & c=$!; trap \'kill "$c" 2>/dev/null; exit 0\' TERM INT; '
    'while kill -0 "$p" 2>/dev/null && kill -0 "$c" 2>/dev/null; do sleep 1; done; '
    'kill "$c" 2>/dev/null; wait "$c"'
)


def find() -> Path | None:
    """Ruta de `cloudflared` (Homebrew o PATH); None si no está instalado."""
    for p in CANDIDATES:
        if p.is_file() and os.access(p, os.X_OK):
            return p
    found = shutil.which("cloudflared")
    return Path(found) if found else None


class Tunnel:
    """Un `cloudflared tunnel --url <sala local>`. Estado: starting → on, o error."""

    def __init__(self, exe: Path, target: str, parent_pid: int | None = None) -> None:
        self.target = target
        self.url: str | None = None
        self.error: str | None = None
        self.ready = threading.Event()
        self._stopping = False
        cmd = [str(exe), "tunnel", "--no-autoupdate", "--protocol", "http2", "--url", target]
        # http2: en la red de la universidad QUIC (UDP) está bloqueado; http2 va por el 443.
        # Binario localizado por `find` y argumentos propios (la URL es la de la sala local).
        self.proc = subprocess.Popen(  # noqa: S603
            ["/bin/sh", "-c", WATCH, "sh", str(parent_pid or os.getpid()), *cmd],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(target=self._read, daemon=True, name="tunel").start()
        timer = threading.Timer(START_TIMEOUT_S, self._timeout)
        timer.daemon = True
        timer.start()

    def _read(self) -> None:
        if self.proc.stdout is None:
            return
        for line in self.proc.stdout:
            if self.url is None and (m := URL_RE.search(line)):
                self.url = m.group(0)
            if READY in line and self.url:
                self.ready.set()
        self.proc.wait()
        if not self._stopping and self.error is None:
            self.error = "El túnel de Cloudflare se cerró. Vuelve a activarlo."
            log.warning("Túnel de Cloudflare cerrado (código %s)", self.proc.returncode)

    def _timeout(self) -> None:
        if not self.ready.is_set() and not self._stopping and self.proc.poll() is None:
            self.error = "Cloudflare no respondió. Comprueba que el Mac tiene internet."
            self.stop()
            self._stopping = False  # el error se mantiene visible

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.ready.is_set() and self.proc.poll() is None:
            return "on"
        return "starting"

    @property
    def public_base(self) -> str | None:
        return self.url if self.status == "on" else None

    def stop(self) -> None:
        self._stopping = True
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
