"""Texto de transcripción con marcas de tiempo y exportación a TXT/SRT."""

from dataclasses import dataclass

from app.pipelines.extract.document import TIME_MARK, Segment, format_time_mark

PARAGRAPH_PAUSE_MS = 2000  # una pausa así abre un párrafo nuevo
PARAGRAPH_MAX_MS = 90_000  # y, en cualquier caso, como mucho cada minuto y medio


@dataclass
class Piece:
    start_ms: int
    end_ms: int
    text: str


def build_text(pieces: list[Piece]) -> str:
    """Una línea por frase con su marca `[mm:ss]`; párrafos separados por pausas."""
    paragraphs: list[list[str]] = []
    para_start = 0
    prev_end: int | None = None
    for p in pieces:
        text = " ".join(p.text.split())
        if not text:
            continue
        # Una línea transcrita no puede parecer una marca de tiempo propia.
        text = TIME_MARK.sub("", text) or text
        new_para = (
            prev_end is None
            or p.start_ms - prev_end >= PARAGRAPH_PAUSE_MS
            or p.start_ms - para_start >= PARAGRAPH_MAX_MS
        )
        if new_para:
            paragraphs.append([])
            para_start = p.start_ms
        paragraphs[-1].append(f"{format_time_mark(p.start_ms)} {text}")
        prev_end = p.end_ms
    return "\n\n".join("\n".join(lines) for lines in paragraphs)


def _srt_time(ms: int) -> str:
    h, rem = divmod(max(ms, 0), 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[Segment], duration_ms: int | None) -> str:
    timed = [s for s in segments if s.start_ms is not None]
    blocks = []
    for i, s in enumerate(timed, start=1):
        start = s.start_ms or 0
        end = s.end_ms or duration_ms or start + 5000
        end = max(end, start + 500)
        text = " ".join(s.text.split())
        blocks.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    return "\n".join(blocks)


def to_txt(text: str) -> str:
    """Texto limpio, sin marcas de tiempo, para leer o pegar en otro sitio."""
    paragraphs = []
    for block in text.split("\n\n"):
        lines = [TIME_MARK.sub("", ln).strip() for ln in block.split("\n")]
        joined = " ".join(ln for ln in lines if ln)
        if joined:
            paragraphs.append(joined)
    return "\n\n".join(paragraphs) + "\n"
