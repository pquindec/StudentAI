"""Apuntes y resúmenes con map-reduce y citas verificadas.

1. El material se trocea en bloques que caben en el contexto (8K), sin partir fragmentos.
2. Map: cada bloque produce apartados → puntos con citas (ids de fragmento, p. ej. "A12").
3. Reduce: si hubo varios bloques, se unen los puntos en un único documento.
4. Validación: toda cita debe ser un id que se le dio al modelo en ese paso; las inventadas se
   descartan (y se cuentan) y un punto sin ninguna cita válida no se guarda.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from app.generation import prompts
from app.llm.base import ChatRequest, ChatResult, LLMError, Message

log = logging.getLogger(__name__)

BLOCK_CHARS = 10_000  # ≈ 3K tokens de datos: deja sitio a instrucciones y salida en 8K
REDUCE_CHARS = 12_000
# Salida máxima por llamada. Con 8K de contexto: ~3K de datos + instrucciones + salida.
MAX_TOKENS = {"brief": 1500, "medium": 2500, "detailed": 3500}
SHORTER = (
    "Tu respuesta anterior era demasiado larga y se cortó. Repítela con la mitad de puntos"
    " y frases más cortas."
)


@dataclass
class Fragment:
    id: str  # "A12": letra de la fuente + ordinal
    segment_id: int
    source: str  # letra
    where: str  # "p. 3" o "05:12"
    text: str


@dataclass
class SourceText:
    letter: str
    title: str
    fragments: list[Fragment]


@dataclass
class Stats:
    calls: int = 0
    proposed_cites: int = 0
    invented_cites: int = 0  # ids que no existían en lo que se le dio al modelo
    dropped_points: int = 0  # puntos sin ninguna cita válida
    dropped_contradictions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Draft:
    sections: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)


# Salida de las llamadas de un resumen: ideas de una parte, y el resumen final.
SUMMARY_MAP_TOKENS = 700
SUMMARY_TOKENS = {"brief": 1000, "medium": 1600, "detailed": 2400}


class Chat(Protocol):
    def __call__(
        self, req: ChatRequest, task: str, on_token: Callable[[int], None] | None = None
    ) -> ChatResult: ...


def blocks(sources: list[SourceText], budget: int = BLOCK_CHARS) -> list[list[SourceText]]:
    """Agrupa fragmentos en bloques de ~budget caracteres, en orden y sin partir fragmentos."""
    out: list[list[SourceText]] = []
    current: list[SourceText] = []
    size = 0
    for src in sources:
        piece: list[Fragment] = []
        for f in src.fragments:
            if size + len(f.text) > budget and (piece or current):
                if piece:
                    current.append(SourceText(src.letter, src.title, piece))
                out.append(current)
                current, piece, size = [], [], 0
            piece.append(f)
            size += len(f.text) + 8
        if piece:
            current.append(SourceText(src.letter, src.title, piece))
    if current:
        out.append(current)
    return out


def _render(block: list[SourceText]) -> str:
    return prompts.render_block(
        [(s.letter, s.title, [(f.id, f.where, f.text) for f in s.fragments]) for s in block]
    )


def _clean_points(raw: Any, allowed: set[str], stats: Stats) -> list[dict[str, Any]]:
    points = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict):
            continue
        text = str(p.get("text", "")).strip()
        cites = [str(c).strip().strip("[]") for c in p.get("cites") or []]
        stats.proposed_cites += len(cites)
        valid = list(dict.fromkeys(c for c in cites if c in allowed))
        stats.invented_cites += sum(1 for c in cites if c not in allowed)
        if not text or not valid:
            stats.dropped_points += 1
            continue
        points.append({"text": text, "cites": valid})
    return points


def validate(data: Any, allowed: set[str], stats: Stats, letter_of: Callable[[str], str]) -> Draft:
    if not isinstance(data, dict):
        raise LLMError("bad_output", "El modelo devolvió una respuesta no válida")
    draft = Draft()
    # Formas del resumen: texto corrido + ideas clave (final) o ideas sueltas (por parte).
    if "summary" in data or "key_points" in data:
        for key, title, prose in (
            ("summary", "Resumen", True),
            ("key_points", "Ideas clave", False),
        ):
            points = _clean_points(data.get(key), allowed, stats)
            if points:
                draft.sections.append({"title": title, "points": points, "prose": prose})
    elif "points" in data:
        points = _clean_points(data.get("points"), allowed, stats)
        if points:
            draft.sections.append({"title": "", "points": points})
    for s in data.get("sections") or []:
        if not isinstance(s, dict):
            continue
        points = _clean_points(s.get("points"), allowed, stats)
        title = str(s.get("title", "")).strip() or "Sin título"
        if points:
            draft.sections.append({"title": title, "points": points})
    for c in data.get("contradictions") or []:
        if not isinstance(c, dict):
            continue
        claims = _clean_points(c.get("claims"), allowed, stats)
        letters = {letter_of(x) for cl in claims for x in cl["cites"]}
        if len(claims) >= 2 and len(letters) >= 2:
            topic = str(c.get("topic", "")).strip() or "Contradicción"
            draft.contradictions.append({"topic": topic, "claims": claims})
        else:
            stats.dropped_contradictions += 1
    return draft


def _ask(
    chat: Chat,
    req: ChatRequest,
    task: str,
    allowed: set[str],
    stats: Stats,
    on_token: Callable[[int], None] | None = None,
) -> Draft:
    """Una llamada con salida estructurada; reintenta una vez si el JSON no es válido o si la
    respuesta se cortó por longitud (pidiendo entonces una versión más corta)."""
    for attempt in (1, 2):
        try:
            result = chat(req, task, on_token)
        except LLMError as e:
            if e.code != "llm_truncated" or attempt == 2:
                raise
            log.warning("Respuesta cortada por longitud: se pide una versión más corta")
            stats.calls += 1
            req = replace(req, messages=[*req.messages, Message("user", SHORTER)])
            continue
        stats.calls += 1
        stats.input_tokens += result.input_tokens or 0
        stats.output_tokens += result.output_tokens or 0
        try:
            data = json.loads(result.text)
        except json.JSONDecodeError:
            log.warning("JSON no válido del modelo (intento %d)", attempt)
            continue
        return validate(data, allowed, stats, lambda fid: fid.rstrip("0123456789"))
    raise LLMError("bad_output", "El modelo devolvió dos veces una respuesta no válida")


def _partials(drafts: list[Draft]) -> str:
    lines = []
    for d in drafts:
        for s in d.sections:
            if s["title"]:
                lines.append(f"## {prompts.neutralize(s['title'])}")
            for p in s["points"]:
                cites = "".join(f"[{c}]" for c in p["cites"])
                lines.append(f"- {prompts.neutralize(p['text'])} {cites}")
    return "\n".join(lines)


def _draft_cites(d: Draft) -> set[str]:
    return {c for s in d.sections for p in s["points"] for c in p["cites"]}


class Yielded(Exception):
    """El trabajo cede el turno a otro más prioritario; se reanuda desde el checkpoint."""


@dataclass
class Job:
    kind: str  # notes | summary
    detail: str
    model: str
    keep_alive: str
    sources: list[SourceText]
    chat: Chat
    report: Callable[[float, str], None]
    checkpoint: dict[str, Any]
    save_checkpoint: Callable[[dict[str, Any]], None]
    stats: Stats = field(default_factory=Stats)
    # Se consulta entre partes: si hay algo más urgente (transcribir una clase), se pausa.
    should_yield: Callable[[], bool] = lambda: False

    def _req(self, system: str, user: str, contradictions: bool, final: bool) -> ChatRequest:
        """final=False solo en las partes intermedias de un resumen (ideas sueltas, cortas)."""
        summary = self.kind == "summary"
        shape = ("summary" if final else "points") if summary else "sections"
        if summary:
            tokens = SUMMARY_TOKENS[self.detail] if final else SUMMARY_MAP_TOKENS
        else:
            tokens = MAX_TOKENS[self.detail]
        return ChatRequest(
            model=self.model,
            messages=[Message("system", system), Message("user", user)],
            schema=prompts.schema(contradictions, shape),
            max_tokens=tokens,
            keep_alive=self.keep_alive,
        )

    def _progress(self, start: float, span: float, label: str, limit: int) -> Callable[[int], None]:
        """Avance continuo mientras el modelo escribe (no solo al terminar cada parte)."""

        def on_token(n: int) -> None:
            self.report(start + span * min(n / max(limit, 1), 0.95), label)

        return on_token

    def run(self) -> Draft:
        parts = blocks(self.sources)
        if not parts:
            raise LLMError("no_content", "Las fuentes elegidas no tienen texto")
        contra = self.kind == "summary" and len(self.sources) > 1
        single = len(parts) == 1
        done: dict[str, Any] = self.checkpoint.setdefault("maps", {})
        stats0 = self.checkpoint.get("stats")
        if stats0:
            self.stats = Stats(**stats0)
        drafts: list[Draft] = []
        steps = len(parts) + (0 if single else 1)
        timings: list[float] = []
        for i, block in enumerate(parts):
            key = str(i)
            if key in done:  # hecho antes de un cierre: no se repite
                drafts.append(Draft(**done[key]))
                continue
            if self.should_yield():
                raise Yielded
            label = f"Leyendo la parte {i + 1} de {len(parts)}"
            if timings:  # estimación con lo que ya ha tardado cada parte
                left = sum(timings) / len(timings) * (steps - i)
                label += f" · quedan ~{max(1, round(left / 60))} min"
            self.report(i / steps, label)
            began = time.monotonic()
            allowed = {f.id for s in block for f in s.fragments}
            system = prompts.system_prompt(
                self.kind, self.detail, contra and single, partial=not single
            )
            user = prompts.map_user(_render(block), i + 1, len(parts))
            req = self._req(system, user, contra and single, final=single)
            draft = _ask(
                self.chat,
                req,
                "map",
                allowed,
                self.stats,
                self._progress(i / steps, 1 / steps, label, req.max_tokens),
            )
            timings.append(time.monotonic() - began)
            drafts.append(draft)
            done[key] = {"sections": draft.sections, "contradictions": draft.contradictions}
            self.checkpoint["stats"] = self.stats.__dict__
            self.save_checkpoint(self.checkpoint)
        if not single and self.should_yield():
            raise Yielded
        result = drafts[0] if single else self._reduce(drafts, contra)
        return finish_summary(result, self.detail) if self.kind == "summary" else result

    def _reduce(self, drafts: list[Draft], contra: bool) -> Draft:
        """Une los resultados parciales; si no caben juntos, por grupos (jerárquico)."""
        level = 0
        while True:
            groups: list[list[Draft]] = [[]]
            size = 0
            for d in drafts:
                n = len(_partials([d]))
                if groups[-1] and size + n > REDUCE_CHARS:
                    groups.append([])
                    size = 0
                groups[-1].append(d)
                size += n
            last = len(groups) == 1
            label = "Redactando el documento final" if last else "Uniendo resultados parciales"
            start = len(drafts) / (len(drafts) + 1)
            self.report(start, label)
            merged = []
            for g in groups:
                if len(g) == 1 and not last:
                    merged.append(g[0])
                    continue
                allowed = set().union(*(_draft_cites(d) for d in g))
                summary = self.kind == "summary"
                system = prompts.system_prompt(
                    self.kind, self.detail, contra and last, partial=summary and not last
                )
                user = prompts.reduce_user(_partials(g), summary=summary and last)
                req = self._req(system, user, contra and last, final=last or not summary)
                progress = self._progress(start, 1 - start, label, req.max_tokens)
                merged.append(_ask(self.chat, req, "reduce", allowed, self.stats, progress))
            if last:
                return merged[0]
            if len(merged) >= len(drafts):  # sin progreso: no debería ocurrir
                raise LLMError("too_long", "El material es demasiado largo para unirlo")
            drafts = merged
            level += 1


def _norm(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 3}


def _similar(a: str, b: str) -> bool:
    """Misma idea dicha casi igual: comparten la gran mayoría de las palabras con contenido."""
    wa, wb = _norm(a), _norm(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.7


def finish_summary(draft: Draft, detail: str) -> Draft:
    """Garantiza en código lo que el modelo no siempre respeta: la longitud del resumen y que
    las ideas clave no repitan sus frases."""
    sentences, keys, _ = prompts.SUMMARY_SIZE[detail]
    text = next((s for s in draft.sections if s.get("prose")), None)
    key = next((s for s in draft.sections if s["title"] == "Ideas clave"), None)
    sections = []
    if text:
        text["points"] = text["points"][:sentences]
        sections.append(text)
    if key:
        said = [p["text"] for p in text["points"]] if text else []
        fresh = [p for p in key["points"] if not any(_similar(p["text"], t) for t in said)]
        if fresh:
            key["points"] = fresh[:keys]
            sections.append(key)
    draft.sections = sections or draft.sections
    return draft


def number_citations(
    draft: Draft, segment_of: dict[str, int]
) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    """Sustituye los ids de fragmento por referencias numeradas [1], [2]… en orden de aparición.
    Devuelve el contenido final y la lista (ref, segment_id)."""
    refs: dict[str, int] = {}

    def conv(cites: list[str]) -> list[int]:
        out = []
        for c in cites:
            if c not in refs:
                refs[c] = len(refs) + 1
            out.append(refs[c])
        return out

    content = {
        "sections": [
            {
                "title": s["title"],
                "prose": bool(s.get("prose")),
                "points": [{"text": p["text"], "refs": conv(p["cites"])} for p in s["points"]],
            }
            for s in draft.sections
        ],
        "contradictions": [
            {
                "topic": c["topic"],
                "claims": [{"text": p["text"], "refs": conv(p["cites"])} for p in c["claims"]],
            }
            for c in draft.contradictions
        ],
    }
    return content, [(n, segment_of[c]) for c, n in refs.items()]
