"""Generadores de archivos de prueba (válidos y maliciosos)."""

import shutil
import subprocess
import zipfile
from pathlib import Path


def _pdf_escape(line: str) -> bytes:
    raw = line.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make_pdf(path: Path, pages: list[list[str]]) -> Path:
    """PDF mínimo válido; cada página es una lista de líneas (vacía = página escaneada)."""
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    objs.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    for i, lines in enumerate(pages):
        cid = 5 + 2 * i
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>".encode()
        )
        body = b"BT /F1 11 Tf 72 740 Td 15 TL "
        for ln in lines:
            body += b"(" + _pdf_escape(ln) + b") Tj T* "
        body += b"ET"
        objs.append(b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for k, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    return path


def make_docx(path: Path) -> Path:
    import docx

    d = docx.Document()
    d.add_heading("Tema 2: Patrones de diseño", 1)
    d.add_paragraph("El patrón Observer define una relación de uno a muchos entre objetos.")
    d.add_heading("Patrones estructurales", 2)
    d.add_paragraph("Adapter convierte una interfaz en otra que espera el cliente.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Patrón", "Familia"
    t.cell(1, 0).text, t.cell(1, 1).text = "Singleton", "Creacional"
    d.save(str(path))
    return path


def make_zip_bomb(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", b"\x00" * (60 * 1024 * 1024))
    return path


def make_audio(path: Path, seconds: int = 3) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            str(path),
        ],
        check=True,
    )
    return path


RTF = (
    rb"{\rtf1\ansi\ansicpg1252 {\fonttbl\f0 Helvetica;}\f0 Arquitectura de software\par"
    rb" La \'e1rbol de decisiones\par}"
)
