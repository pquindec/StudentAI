"""Catálogo y descarga verificada de modelos de transcripción.

Los modelos se descargan solo cuando el usuario lo pide, desde una URL fija de Hugging Face, y
solo se dan por instalados si el tamaño y el SHA-256 coinciden con los publicados (en la Fase 0.5
una descarga fallida dejó una página HTML de 92 bytes con nombre de modelo).
"""

import hashlib
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal, cast

HF = "https://huggingface.co"
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ModelSpec:
    id: str
    kind: Literal["stt", "vad"]
    label: str
    description: str
    file: str
    url: str
    size: int
    sha256: str
    ram_mb: int


CATALOG: dict[str, ModelSpec] = {
    m.id: m
    for m in (
        ModelSpec(
            "large-v3-turbo-q5_0",
            "stt",
            "Whisper large-v3-turbo (recomendado)",
            "La mejor precisión medida en este Mac: ~3 s por minuto de audio y"
            " hasta 1,7 GB de memoria.",
            "ggml-large-v3-turbo-q5_0.bin",
            f"{HF}/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin",
            574041195,
            "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
            1700,
        ),
        ModelSpec(
            "small",
            "stt",
            "Whisper small (ligero)",
            "Algo menos preciso; útil con poca memoria libre o con batería.",
            "ggml-small.bin",
            f"{HF}/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
            487601967,
            "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
            1000,
        ),
        ModelSpec(
            "silero-v5.1.2",
            "vad",
            "Detector de voz (Silero VAD)",
            "Necesario: salta los silencios y evita texto inventado en ellos.",
            "ggml-silero-v5.1.2.bin",
            f"{HF}/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin",
            885098,
            "29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf",
            50,
        ),
    )
}
DEFAULT_STT = "large-v3-turbo-q5_0"
VAD = "silero-v5.1.2"


class DownloadError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DownloadCancelled(Exception):
    pass


def models_dir(data_dir: Path) -> Path:
    return data_dir / "models" / "whisper"


def model_path(data_dir: Path, model_id: str) -> Path:
    return models_dir(data_dir) / CATALOG[model_id].file


def is_installed(data_dir: Path, model_id: str) -> bool:
    """Comprobación rápida (tamaño). El hash se verifica al descargar."""
    p = model_path(data_dir, model_id)
    return p.is_file() and p.stat().st_size == CATALOG[model_id].size


def download(
    data_dir: Path,
    model_id: str,
    on_progress: Callable[[float], None],
    cancelled: Callable[[], bool],
    opener: Callable[[str], IO[bytes]] | None = None,
) -> Path:
    spec = CATALOG[model_id]
    dest = model_path(data_dir, model_id)
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    received = 0
    try:
        open_url = opener or (
            lambda url: cast(IO[bytes], urllib.request.urlopen(url, timeout=60))  # noqa: S310
        )
        try:
            resp = open_url(spec.url)
        except OSError as e:
            raise DownloadError(
                "network", "No se pudo conectar para descargar el modelo. Revisa tu conexión."
            ) from e
        with resp as r, open(tmp, "wb") as out:
            os.chmod(tmp, 0o600)
            while True:
                if cancelled():
                    raise DownloadCancelled
                try:
                    block = r.read(CHUNK)
                except OSError as e:
                    raise DownloadError("network", "La descarga se interrumpió.") from e
                if not block:
                    break
                received += len(block)
                if received > spec.size:
                    raise DownloadError("bad_size", "El archivo descargado no es el esperado.")
                digest.update(block)
                out.write(block)
                on_progress(received / spec.size)
        if received != spec.size:
            raise DownloadError("bad_size", "La descarga está incompleta. Vuelve a intentarlo.")
        if digest.hexdigest() != spec.sha256:
            raise DownloadError(
                "bad_hash", "El archivo descargado no coincide con el original (SHA-256)."
            )
        tmp.replace(dest)
        return dest
    finally:
        tmp.unlink(missing_ok=True)
