"""Análisis (ffprobe) y normalización (ffmpeg → WAV 16 kHz mono) de audio."""

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core import limits


class AudioError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Cancelled(Exception):
    pass


def tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise AudioError(
            "ffmpeg_missing",
            "Falta FFmpeg en este equipo. Instálalo con «brew install ffmpeg» y reintenta.",
        )
    return path


def probe(path: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(  # noqa: S603
            [
                tool("ffprobe"),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioError("timeout", "El análisis del audio tardó demasiado") from exc
    if proc.returncode != 0:
        raise AudioError("corrupt", "El archivo de audio está dañado o no es compatible")
    info = json.loads(proc.stdout or "{}")
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise AudioError("no_audio", "El archivo no contiene ninguna pista de audio")
    fmt = info.get("format", {})
    duration = float(fmt.get("duration") or streams[0].get("duration") or 0)
    if duration <= 0:
        raise AudioError(
            "corrupt", "No se pudo determinar la duración del audio (¿archivo dañado?)"
        )
    duration_ms = int(duration * 1000)
    if duration_ms > limits.MAX_AUDIO_MS:
        raise AudioError("too_long", "El audio dura más de 6 horas")
    s = streams[0]
    return {
        "duration_ms": duration_ms,
        "codec": s.get("codec_name"),
        "sample_rate": int(s.get("sample_rate") or 0) or None,
        "channels": s.get("channels"),
        "bit_rate": int(fmt.get("bit_rate") or 0) or None,
        "format": fmt.get("format_name"),
    }


def normalize(
    src: Path,
    dst: Path,
    duration_ms: int,
    on_progress: Callable[[float], None],
    cancelled: Callable[[], bool],
) -> None:
    """Convierte a WAV PCM 16 kHz mono (formato de whisper.cpp), con progreso y cancelación."""
    tmp = dst.with_suffix(".part.wav")
    cmd = [
        tool("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-progress",
        "pipe:1",
        str(tmp),
    ]
    proc = subprocess.Popen(  # noqa: S603
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if proc.stdout is None:
        raise AudioError("convert_failed", "No se pudo iniciar la conversión de audio")
    try:
        for line in proc.stdout:
            if cancelled():
                proc.kill()
                raise Cancelled
            if line.startswith("out_time_us=") and duration_ms > 0:
                try:
                    done_ms = int(line.split("=", 1)[1]) / 1000
                    on_progress(min(done_ms / duration_ms, 0.99))
                except ValueError:
                    pass
        code = proc.wait(timeout=60)
        if code != 0:
            raise AudioError("convert_failed", "No se pudo convertir el audio (archivo dañado)")
        tmp.rename(dst)
        dst.chmod(0o600)
    finally:
        if proc.poll() is None:
            proc.kill()
        tmp.unlink(missing_ok=True)
