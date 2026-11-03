"""Proveedor STT: whisper.cpp (`whisper-cli`) como proceso hijo efímero (ADR-004).

Se transcribe por tramos: cada tramo es un WAV temporal recortado del audio normalizado y los
tiempos se desplazan al tiempo absoluto. Al terminar el proceso, la memoria se libera.
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import time
import wave
from collections.abc import Callable
from pathlib import Path

from app.core import children
from app.pipelines.audio import Cancelled
from app.stt.transcript import Piece

CHUNK_TIMEOUT_S = 20 * 60


class SttError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def whisper_bin() -> str:
    path = shutil.which("whisper-cli")
    if path is None:
        raise SttError(
            "whisper_missing",
            "Falta whisper.cpp en este equipo. Instálalo con «brew install whisper-cpp»"
            " y reintenta.",
        )
    return path


def threads() -> int:
    return max(2, min(6, (os.cpu_count() or 4) - 2))


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as w:
        return int(w.getnframes() * 1000 / w.getframerate())


def slice_wav(src: Path, dst: Path, start_ms: int, duration_ms: int) -> None:
    """Copia un tramo de un WAV PCM (sin recodificar)."""
    with wave.open(str(src), "rb") as r:
        rate = r.getframerate()
        r.setpos(min(int(start_ms * rate / 1000), r.getnframes()))
        frames = r.readframes(int(duration_ms * rate / 1000))
        with wave.open(str(dst), "wb") as w:
            w.setnchannels(r.getnchannels())
            w.setsampwidth(r.getsampwidth())
            w.setframerate(rate)
            w.writeframes(frames)


def kill_stale(pidfile: Path) -> None:
    """Mata un whisper que quedó vivo tras un cierre brusco del backend (solo si es nuestro:
    mismo ejecutable y la carpeta de trabajo en su línea de comandos)."""
    try:
        pid = int(pidfile.read_text())
    except (OSError, ValueError):
        return
    ps = subprocess.run(  # noqa: S603
        ["/bin/ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
    )
    cmdline = ps.stdout
    if "whisper-cli" in cmdline and str(pidfile.parent) in cmdline:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
    pidfile.unlink(missing_ok=True)


def transcribe_wav(
    wav: Path,
    model: Path,
    vad_model: Path,
    language: str,
    offset_ms: int,
    cancelled: Callable[[], bool],
) -> tuple[list[Piece], str | None]:
    """Transcribe un WAV y devuelve (frases con tiempo absoluto, idioma detectado)."""
    prefix = wav.with_suffix("")
    out_json = prefix.with_suffix(".json")
    pidfile = wav.parent / "whisper.pid"
    cmd = [
        whisper_bin(),
        "-m", str(model),
        "-f", str(wav),
        "-l", language,
        "-t", str(threads()),
        "--vad", "-vm", str(vad_model),
        "-oj", "-of", str(prefix),
        "-np",
    ]  # fmt: skip
    proc = subprocess.Popen(  # noqa: S603
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    children.register(proc)
    pidfile.write_text(str(proc.pid))
    started = time.monotonic()
    try:
        while proc.poll() is None:
            if cancelled():
                proc.kill()
                raise Cancelled
            if time.monotonic() - started > CHUNK_TIMEOUT_S:
                proc.kill()
                raise SttError("timeout", "La transcripción tardó demasiado y se detuvo.")
            time.sleep(0.3)
        if proc.returncode != 0:
            err = (proc.stderr.read() if proc.stderr else "")[-300:]
            if "failed to load" in err or "invalid model" in err:
                raise SttError(
                    "model_error", "El modelo de transcripción está dañado. Vuelve a descargarlo."
                )
            raise SttError("stt_failed", "whisper.cpp no pudo transcribir este tramo de audio.")
        data = json.loads(out_json.read_text(encoding="utf-8"))
    finally:
        if proc.poll() is None:
            proc.kill()
        children.unregister(proc)
        pidfile.unlink(missing_ok=True)
        out_json.unlink(missing_ok=True)
    pieces = [
        Piece(
            start_ms=offset_ms + int(seg["offsets"]["from"]),
            end_ms=offset_ms + int(seg["offsets"]["to"]),
            text=str(seg.get("text", "")).strip(),
        )
        for seg in data.get("transcription", [])
        if str(seg.get("text", "")).strip()
    ]
    lang = data.get("result", {}).get("language")
    return pieces, lang if isinstance(lang, str) else None
