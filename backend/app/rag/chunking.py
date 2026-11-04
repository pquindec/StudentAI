"""Troceo de una versión de fuente en chunks para buscar, sin perder la trazabilidad.

Cada chunk agrupa segmentos consecutivos (párrafos con página, o frases con tiempo) hasta
~TARGET caracteres. Un título siempre abre un chunk nuevo (y se queda con su contenido), y en
transcripciones un chunk no abarca más de MAX_SPAN_MS de audio.
"""

from dataclasses import dataclass
from typing import Any

TARGET = 1000
MAX = 1600
MAX_SPAN_MS = 120_000


@dataclass
class Chunk:
    ordinal: int
    text: str
    seg_from: int
    seg_to: int
    page_from: int | None
    page_to: int | None
    start_ms: int | None
    end_ms: int | None
    section_path: str | None


def _make(ordinal: int, segs: list[dict[str, Any]]) -> Chunk:
    pages = [s["page"] for s in segs if s["page"] is not None]
    starts = [s["start_ms"] for s in segs if s["start_ms"] is not None]
    ends = [s["end_ms"] for s in segs if s["end_ms"] is not None]
    return Chunk(
        ordinal=ordinal,
        text="\n".join(s["text"] for s in segs),
        seg_from=segs[0]["ordinal"],
        seg_to=segs[-1]["ordinal"],
        page_from=min(pages) if pages else None,
        page_to=max(pages) if pages else None,
        start_ms=min(starts) if starts else None,
        end_ms=max(ends) if ends else (max(starts) if starts else None),
        section_path=next((s["section_path"] for s in segs if s["section_path"]), None),
    )


def chunk_segments(segments: list[dict[str, Any]]) -> list[Chunk]:
    """segments: dicts con ordinal, kind, text, page, start_ms, end_ms, section_path (en orden)."""
    out: list[Chunk] = []
    current: list[dict[str, Any]] = []
    size = 0
    for seg in segments:
        text = str(seg["text"]).strip()
        if not text:
            continue
        seg = {**seg, "text": text}
        heading = seg["kind"] == "heading"
        span_exceeded = (
            current
            and seg["start_ms"] is not None
            and current[0]["start_ms"] is not None
            and seg["start_ms"] - current[0]["start_ms"] > MAX_SPAN_MS
        )
        only_headings = all(s["kind"] == "heading" for s in current)
        if (
            current
            and not only_headings
            and (heading or size >= TARGET or size + len(text) > MAX or span_exceeded)
        ):
            out.append(_make(len(out), current))
            current, size = [], 0
        current.append(seg)
        size += len(text) + 1
    if current:
        out.append(_make(len(out), current))
    return out
