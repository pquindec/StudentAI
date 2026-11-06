"""Extractores por formato. Se ejecutan en un subproceso aislado (ver runner.py): reciben
contenido NO confiable y nunca deben tumbar el backend."""

import csv
import io
import re
import zipfile
from collections.abc import Sequence
from pathlib import Path

from charset_normalizer import from_bytes

from app.core import limits
from app.pipelines.extract.document import Block, Extraction, clean, table_to_markdown


class ExtractionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- texto
# Caracteres no ASCII habituales en textos en español/inglés/europeo occidental.
_WESTERN = frozenset(
    "áéíóúüñçàèìòùâêîôûäëïöÁÉÍÓÚÜÑÇÀÈÌÒÙÂÊÎÔÛÄËÏÖ¿¡ºª°«»€£§©®·\u2013\u2014\u2018\u2019\u201c\u201d\u2026\u2022\u00a0"
)


def _western(data: bytes) -> str | None:
    """Windows-1252 si encaja limpiamente: el detector falla con textos cortos en español."""
    try:
        text = data.decode("cp1252")
    except UnicodeDecodeError:
        return None
    if all(c in _WESTERN for c in text if ord(c) > 127):
        return text
    return None


def decode_text(data: bytes) -> tuple[str, str]:
    """Devuelve (texto, codificación). Rechaza contenido binario."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    western = _western(data)
    if western is not None:
        return western, "cp1252"
    best = from_bytes(data[: 2 * limits.MB]).best()
    if best is None or best.encoding is None:
        raise ExtractionError("binary", "El archivo no parece contener texto legible")
    text = data.decode(best.encoding, errors="replace")
    control = sum(1 for c in text[:100_000] if ord(c) < 32 and c not in "\n\r\t")
    if control > len(text[:100_000]) * 0.01:
        raise ExtractionError("binary", "El archivo no parece contener texto legible")
    return text, best.encoding


def paragraphs(text: str, page: int | None = None) -> list[Block]:
    out: list[Block] = []
    for chunk in re.split(r"\n\s*\n", text):
        c = clean(chunk)
        if c:
            out.append(Block("paragraph", c, page=page))
    return out


def extract_txt(path: Path) -> Extraction:
    text, enc = decode_text(path.read_bytes())
    return Extraction(paragraphs(text), metadata={"encoding": enc})


def extract_md(path: Path) -> Extraction:
    text, enc = decode_text(path.read_bytes())
    blocks: list[Block] = []
    for chunk in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        c = chunk.strip()
        if not c:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", c)
        if m and "\n" not in c:
            blocks.append(Block("heading", m.group(2), level=len(m.group(1))))
        elif all(ln.lstrip().startswith("|") for ln in c.split("\n")):
            blocks.append(Block("table", c))
        else:
            blocks.append(Block("paragraph", c))
    return Extraction(blocks, metadata={"encoding": enc})


def extract_rtf(path: Path) -> Extraction:
    from striprtf.striprtf import rtf_to_text

    raw = path.read_bytes().decode("latin-1")
    m = re.search(r"\\ansicpg(\d+)", raw[:2000])
    encoding = f"cp{m.group(1)}" if m else "cp1252"
    try:
        text = rtf_to_text(raw, encoding=encoding, errors="replace")  # type: ignore[no-untyped-call]
    except Exception as exc:
        raise ExtractionError("corrupt", "El archivo RTF está dañado") from exc
    return Extraction(paragraphs(text), metadata={"encoding": encoding})


def extract_csv(path: Path) -> Extraction:
    text, enc = decode_text(path.read_bytes())
    sample = text[:20_000]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows: list[list[str]] = []
    truncated = False
    # newline="": el lector de csv reconoce \r, \n y \r\n (CSV de Mac antiguos, saltos dentro
    # de celdas entre comillas). Celdas enormes o comillas imposibles → error controlado.
    try:
        for i, row in enumerate(csv.reader(io.StringIO(text, newline=""), dialect)):
            if i >= limits.CSV_MAX_ROWS:
                truncated = True
                break
            rows.append(row)
    except csv.Error as exc:
        raise ExtractionError("corrupt", "El CSV está dañado o tiene un formato no válido") from exc
    if not rows:
        raise ExtractionError("empty", "El CSV está vacío")
    header, body = rows[0], rows[1:]
    # Tablas de 50 filas repitiendo la cabecera: cada trozo se entiende por sí solo.
    blocks = [
        Block("table", table_to_markdown([list(header), *body[i : i + 50]]))
        for i in range(0, max(len(body), 1), 50)
    ]
    warnings = ["truncated"] if truncated else []
    meta = {"encoding": enc, "rows": len(body), "columns": len(header)}
    return Extraction(blocks, metadata=meta, warnings=warnings)


# ---------------------------------------------------------------- DOCX
def check_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > limits.DOCX_MAX_ENTRIES:
                raise ExtractionError("too_complex", "El documento tiene demasiados elementos")
            total = 0
            for i in infos:
                total += i.file_size
                big = i.file_size > 10 * limits.MB
                if big and i.file_size > max(i.compress_size, 1) * limits.DOCX_MAX_RATIO:
                    raise ExtractionError(
                        "zip_bomb",
                        "El documento parece malicioso (compresión anómala)",
                    )
            if total > limits.DOCX_MAX_UNCOMPRESSED:
                raise ExtractionError("too_large", "El documento descomprimido es demasiado grande")
            if "word/document.xml" not in z.namelist():
                raise ExtractionError("corrupt", "No es un documento de Word válido")
    except zipfile.BadZipFile as exc:
        raise ExtractionError("corrupt", "El documento de Word está dañado") from exc


def extract_docx(path: Path) -> Extraction:
    check_zip(path)
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        doc = docx.Document(str(path))
    except Exception as exc:
        raise ExtractionError("corrupt", "El documento de Word está dañado") from exc

    blocks: list[Block] = []
    for el in doc.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, doc)
            text = clean(p.text)
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.match(r"^(?:Heading|Título|Titulo)\s*(\d)", style, re.I)
            if m:
                blocks.append(Block("heading", text, level=int(m.group(1))))
            elif style.lower() in ("title", "título", "titulo"):
                blocks.append(Block("heading", text, level=1))
            elif el.find(".//{*}numPr") is not None or "list" in style.lower():
                blocks.append(Block("list", f"- {text}"))
            else:
                blocks.append(Block("paragraph", text))
        elif tag == "tbl":
            t = Table(el, doc)
            md = table_to_markdown([[c.text for c in row.cells] for row in t.rows])
            if md:
                blocks.append(Block("table", md))
    blocks = merge_lists(blocks)
    props = doc.core_properties
    meta = {k: v for k, v in {"title": props.title, "author": props.author}.items() if v}
    return Extraction(blocks, metadata=meta)


def merge_lists(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for b in blocks:
        if b.kind == "list" and out and out[-1].kind == "list" and out[-1].page == b.page:
            out[-1].text += "\n" + b.text
        else:
            out.append(b)
    return out


# ---------------------------------------------------------------- PDF
NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s+\S")


def pdf_page_blocks(text: str, page: int) -> list[Block]:
    """Reconstruye párrafos y títulos a partir de las líneas de una página."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [clean(ln) for ln in text.split("\n")]
    blocks: list[Block] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            blocks.append(Block("paragraph", " ".join(buf), page=page))
            buf.clear()

    for ln in lines:
        if not ln:
            flush()
            continue
        num = NUMBERED.match(ln)
        is_heading = (
            len(ln) <= 90
            and not ln.endswith((".", ",", ";", ":"))
            and (num is not None or (ln.isupper() and len(ln) > 3))
        )
        if is_heading:
            flush()
            level = num.group(1).count(".") + 1 if num else 1
            blocks.append(Block("heading", ln, level=min(level, 6), page=page))
        elif re.match(r"^[-•*]\s+", ln):
            flush()
            blocks.append(Block("list", "- " + ln.lstrip("-•* ").strip(), page=page))
        else:
            buf.append(ln)
            if ln.endswith((".", "?", "!", ":")) and len(ln) < 60:
                flush()
    flush()
    return merge_lists(blocks)


def extract_pdf(path: Path) -> Extraction:
    import pdfplumber
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise ExtractionError("encrypted", "El PDF está protegido con contraseña") from exc
        raise ExtractionError("corrupt", "El PDF está dañado o no es válido") from exc

    n = len(pdf)
    if n == 0:
        raise ExtractionError("empty", "El PDF no tiene páginas")
    if n > limits.MAX_PDF_PAGES:
        raise ExtractionError(
            "too_large", f"El PDF tiene {n} páginas (máximo {limits.MAX_PDF_PAGES})"
        )

    meta_raw = pdf.get_metadata_dict()
    blocks: list[Block] = []
    empty_pages: list[int] = []
    total_chars = 0
    with pdfplumber.open(str(path)) as plumb:
        for i in range(n):
            page_no = i + 1
            text = pdf[i].get_textpage().get_text_bounded()
            total_chars += len(text.strip())
            if len(text.strip()) < 20:
                empty_pages.append(page_no)
                continue
            # Páginas con tablas: texto fuera de las tablas + tablas en Markdown (sin duplicar).
            tables = []
            try:
                p = plumb.pages[i]
                tables = p.find_tables() if text.count("\n") > 5 else []
                if tables:
                    bboxes = [t.bbox for t in tables]

                    def outside(
                        obj: dict[str, float], bb: Sequence[Sequence[float]] = bboxes
                    ) -> bool:
                        return not any(
                            obj.get("x0", 0) >= b[0]
                            and obj.get("x1", 0) <= b[2]
                            and obj.get("top", 0) >= b[1]
                            and obj.get("bottom", 0) <= b[3]
                            for b in bb
                        )

                    text = p.filter(outside).extract_text() or ""
            except Exception:
                tables = []
            blocks.extend(pdf_page_blocks(text, page_no))
            for t in tables:
                md = table_to_markdown(t.extract())
                if md:
                    blocks.append(Block("table", md, page=page_no))

    if total_chars < 25 * n and len(empty_pages) == n:
        raise ExtractionError(
            "no_text",
            "Este PDF no contiene texto seleccionable (probablemente es un escaneo). "
            "El reconocimiento de texto (OCR) llegará como módulo opcional.",
        )
    warnings = ["empty_pages"] if empty_pages else []
    meta = {k.lower(): v for k, v in meta_raw.items() if k in ("Title", "Author") and v}
    if empty_pages:
        meta["empty_pages"] = empty_pages[:200]
    return Extraction(blocks, page_count=n, metadata=meta, warnings=warnings)


EXTRACTORS = {
    "pdf": extract_pdf,
    "docx": extract_docx,
    "txt": extract_txt,
    "md": extract_md,
    "rtf": extract_rtf,
    "csv": extract_csv,
}
