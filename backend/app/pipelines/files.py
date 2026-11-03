"""Validación y almacenamiento de archivos importados.

- El tipo se decide por extensión Y contenido (magic bytes): una extensión falsa se rechaza.
- El original se copia, nunca se mueve ni se modifica. La copia vive en
  `sources/<uuid>/original.<ext>`: el nombre original jamás se usa como ruta.
"""

import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core import limits
from app.core.errors import AppError

DOC_EXT = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".rtf": "rtf",
    ".csv": "csv",
}
AUDIO_EXT = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".webm",
    ".aiff",
    ".aif",
    ".wma",
    ".m4b",
    ".mp4",
}
MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
    "rtf": "application/rtf",
    "csv": "text/csv",
}
KIND_LABEL = {
    "pdf": "un PDF",
    "docx": "un documento de Word",
    "rtf": "un archivo RTF",
    "txt": "un archivo de texto",
    "md": "un archivo Markdown",
    "csv": "un CSV",
    "audio": "un archivo de audio",
}


@dataclass(frozen=True)
class Inspected:
    kind: str  # pdf | docx | txt | md | rtf | csv | audio
    ext: str
    mime: str
    size: int


def _audio_signature(head: bytes) -> str | None:
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio/mpeg"  # MP3 o AAC ADTS
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[4:8] == b"ftyp":
        return "audio/mp4"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "audio/aiff"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    if head.startswith(b"\x30\x26\xb2\x75\x8e\x66\xcf\x11"):
        return "audio/x-ms-wma"
    return None


def _looks_textual(head: bytes) -> bool:
    if head.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        return True
    return b"\x00" not in head


def inspect(path: Path, display_name: str) -> Inspected:
    """Valida un archivo indicado por el usuario. `display_name` solo se usa en mensajes."""
    if not path.is_absolute():
        raise AppError(400, "invalid_path", "Ruta de archivo no válida")
    try:
        st = path.stat()  # sigue enlaces: Finder puede dar alias; validamos el destino
    except OSError as exc:
        raise AppError(404, "file_not_found", f"No se encuentra «{display_name}»") from exc
    if not stat.S_ISREG(st.st_mode):
        raise AppError(400, "not_a_file", f"«{display_name}» no es un archivo")
    if st.st_size == 0:
        raise AppError(400, "empty_file", f"«{display_name}» está vacío")

    ext = path.suffix.lower()
    if ext in DOC_EXT:
        kind = DOC_EXT[ext]
    elif ext in AUDIO_EXT:
        kind = "audio"
    else:
        raise AppError(
            415,
            "unsupported_type",
            f"El formato de «{display_name}» no es compatible. Usa PDF, DOCX, TXT, MD, RTF, CSV "
            "o audio (MP3, WAV, M4A, AAC, FLAC, OGG…)",
        )
    if st.st_size > limits.MAX_BYTES[kind]:
        mb = limits.MAX_BYTES[kind] // limits.MB
        raise AppError(413, "too_large", f"«{display_name}» supera el tamaño máximo ({mb} MB)")

    try:
        with path.open("rb") as f:
            head = f.read(8192)
    except OSError as exc:
        raise AppError(403, "unreadable", f"No se puede leer «{display_name}»") from exc

    ok: bool
    mime = MIME.get(kind, "")
    if kind == "pdf":
        ok = b"%PDF-" in head[:1024]
    elif kind == "docx":
        ok = head.startswith(b"PK\x03\x04")
    elif kind == "rtf":
        ok = head.lstrip().startswith(b"{\\rtf")
    elif kind == "audio":
        sig = _audio_signature(head)
        ok, mime = sig is not None, sig or ""
    else:
        ok = _looks_textual(head)
    if not ok:
        raise AppError(
            415,
            "content_mismatch",
            f"«{display_name}» no es {KIND_LABEL[kind]} válido: su contenido no coincide con la "
            "extensión o el archivo está dañado",
        )
    return Inspected(kind=kind, ext=ext, mime=mime, size=st.st_size)


def store_copy(src: Path, sources_dir: Path, max_bytes: int) -> tuple[Path, str, int]:
    """Copia el archivo a una carpeta temporal privada calculando SHA-256.
    Devuelve (ruta temporal, sha256, bytes). El llamador la mueve a su sitio definitivo."""
    incoming = sources_dir / ".incoming"
    incoming.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = incoming / f"{uuid.uuid4()}.part"
    h = hashlib.sha256()
    size = 0
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with src.open("rb") as fin, os.fdopen(fd, "wb") as fout:
            while chunk := fin.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:  # el archivo creció durante la copia
                    raise AppError(413, "too_large", "El archivo supera el tamaño máximo")
                h.update(chunk)
                fout.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, h.hexdigest(), size


def finalize(tmp: Path, sources_dir: Path, source_id: str, ext: str) -> Path:
    dest_dir = sources_dir / source_id
    dest_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    dest = dest_dir / f"original{ext}"
    tmp.rename(dest)
    dest.chmod(0o400)  # inmutable: solo lectura
    return dest
