"""Representación común del contenido extraído.

Todos los extractores producen bloques → `to_markdown()` los convierte en texto Markdown con
marcas de página (`--- Página N ---`). `segment()` vuelve a dividir CUALQUIER texto (extraído,
pegado o editado por el usuario) en segmentos con su posición exacta, página y sección. Así las
ediciones conservan la trazabilidad hacia la fuente original.
"""

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BlockKind = Literal["heading", "paragraph", "table", "list"]

PAGE_MARK = re.compile(r"^--- Página (\d+) ---$")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d{1,3}[.)])\s+")


@dataclass
class Block:
    kind: BlockKind
    text: str
    level: int | None = None
    page: int | None = None


@dataclass
class Segment:
    ordinal: int
    kind: BlockKind
    text: str
    char_start: int
    char_end: int
    level: int | None = None
    page: int | None = None
    section_path: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass
class Extraction:
    blocks: list[Block]
    page_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "blocks": [asdict(b) for b in self.blocks],
            "page_count": self.page_count,
            "metadata": self.metadata,
            "warnings": self.warnings,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Extraction":
        return Extraction(
            blocks=[Block(**b) for b in data["blocks"]],
            page_count=data.get("page_count"),
            metadata=data.get("metadata") or {},
            warnings=data.get("warnings") or [],
        )


def clean(text: str) -> str:
    """Normaliza espacios y elimina caracteres de control (salvo saltos de línea y tabuladores)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub("[ \t\u00a0]+", " ", text)
    return text.strip()


def table_to_markdown(raw: Sequence[Sequence[str | None]]) -> str:
    rows = [[clean(c or "").replace("\n", " ").replace("|", "\\|") for c in r] for r in raw]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def to_markdown(blocks: list[Block]) -> str:
    parts: list[str] = []
    page: int | None = None
    for b in blocks:
        if not b.text.strip():
            continue
        if b.page is not None and b.page != page:
            page = b.page
            parts.append(f"--- Página {page} ---")
        if b.kind == "heading":
            parts.append(f"{'#' * min(max(b.level or 1, 1), 6)} {b.text.strip()}")
        else:
            parts.append(b.text.strip())
    return "\n\n".join(parts)


def segment(text: str) -> list[Segment]:
    """Divide texto Markdown en segmentos con offsets exactos sobre `text`."""
    segments: list[Segment] = []
    page: int | None = None
    sections: list[tuple[int, str]] = []  # pila (nivel, título)

    # Recorre "bloques" separados por líneas en blanco, guardando su posición real.
    for m in re.finditer(r"(?:[^\n]*\S[^\n]*(?:\n|$))+", text):
        raw = m.group(0)
        start = m.start() + (len(raw) - len(raw.lstrip()))
        body = raw.strip()
        if not body:
            continue
        end = start + len(body)
        lines = body.split("\n")

        pm = PAGE_MARK.match(lines[0].strip())
        if pm:
            page = int(pm.group(1))
            if len(lines) == 1:
                continue
            # Marca de página seguida de texto en el mismo bloque.
            offset = body.index("\n") + 1
            start += offset
            body = body[offset:].strip()
            lines = body.split("\n")

        hm = HEADING.match(lines[0]) if len(lines) == 1 else None
        kind: BlockKind
        level: int | None = None
        if hm:
            kind = "heading"
            level = len(hm.group(1))
            sections = [s for s in sections if s[0] < level] + [(level, hm.group(2).strip())]
        elif all(ln.lstrip().startswith("|") for ln in lines):
            kind = "table"
        elif all(LIST_ITEM.match(ln) for ln in lines if ln.strip()):
            kind = "list"
        else:
            kind = "paragraph"

        segments.append(
            Segment(
                ordinal=len(segments),
                kind=kind,
                text=body,
                char_start=start,
                char_end=end,
                level=level,
                page=page,
                section_path=" \u203a ".join(t for _, t in sections) or None,
            )
        )
    return segments
