"""Manejadores de trabajos. Se ejecutan en un hilo; cada uno abre su propia conexión."""

import dataclasses
import json
import logging
import shutil
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.connection import tx
from app.generation import grading
from app.generation.docs import Job as GenJob
from app.generation.docs import Yielded, number_citations
from app.jobs import queue
from app.llm.base import ChatRequest, ChatResult, LLMCancelled, LLMError
from app.pipelines import audio
from app.pipelines.extract.document import to_markdown
from app.pipelines.extract.runner import ExtractFailed, run_isolated
from app.rag import answer as rag_answer
from app.rag import index as rag_index
from app.rag import search as rag_search
from app.rag.scope import Scope
from app.resources import manager as res_manager
from app.resources.manager import ResourceManager, profile
from app.services import audio_files, transcription
from app.services import chat as chat_svc
from app.services import documents as docs_svc
from app.services import exams as exams_svc
from app.services import flashcards as cards_svc
from app.services import llm as llm_svc
from app.services import sources as src_svc
from app.stt import models
from app.stt.transcript import Piece, build_text
from app.stt.whisper_cpp import (
    SttError,
    kill_stale,
    slice_wav,
    transcribe_wav,
    wav_duration_ms,
)

log = logging.getLogger(__name__)


class JobFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class JobContext:
    job: dict[str, Any]
    db: sqlite3.Connection
    data_dir: Path

    @property
    def source_id(self) -> str:
        sid = self.job["source_id"]
        if not isinstance(sid, str):
            raise JobFailed("no_source", "El trabajo no tiene fuente asociada")
        return sid

    def report(self, value: float, message: str | None = None) -> None:
        queue.progress(self.db, self.job["id"], value, message)

    def cancelled(self) -> bool:
        return queue.cancel_requested(self.db, self.job["id"])

    def source(self) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM sources WHERE id = ?", (self.source_id,)).fetchone()
        if row is None:
            raise audio.Cancelled  # la fuente se borró mientras esperaba
        return dict(row)


def extract_document(ctx: JobContext) -> None:
    src = ctx.source()
    ctx.report(0.1, "Extrayendo texto")
    path = ctx.data_dir / src["stored_path"]
    try:
        result = run_isolated(src["kind"], path)
    except ExtractFailed as e:
        raise JobFailed(e.code, e.message) from e
    if ctx.cancelled():
        raise audio.Cancelled
    ctx.report(0.8, "Guardando")
    text = to_markdown(result.blocks)
    if not text.strip():
        raise JobFailed("no_text", "No se encontró texto en el documento")
    with tx(ctx.db):
        src_svc.add_version(ctx.db, ctx.source_id, text, "extracted")
        src_svc.merge_metadata(
            ctx.db, ctx.source_id, {**result.metadata, "warnings": result.warnings}
        )
        ctx.db.execute(
            "UPDATE sources SET status = 'ready', processed_at = now_iso(), page_count = ?,"
            " needs_review = ?, error_code = NULL, error_message = NULL WHERE id = ?",
            (result.page_count, 1 if result.warnings else 0, ctx.source_id),
        )


def prepare_audio(ctx: JobContext) -> None:
    src = ctx.source()
    path = ctx.data_dir / src["stored_path"]
    ctx.report(0.02, "Analizando audio")
    try:
        info = audio.probe(path)
        if ctx.cancelled():
            raise audio.Cancelled
        with tx(ctx.db):
            src_svc.merge_metadata(ctx.db, ctx.source_id, info)
            ctx.db.execute(
                "UPDATE sources SET duration_ms = ? WHERE id = ?",
                (info["duration_ms"], ctx.source_id),
            )
        ctx.report(0.05, "Convirtiendo a formato de transcripción")
        audio.normalize(
            path,
            path.parent / "normalized.wav",
            info["duration_ms"],
            on_progress=lambda p: ctx.report(0.05 + p * 0.95),
            cancelled=ctx.cancelled,
        )
    except audio.AudioError as e:
        raise JobFailed(e.code, e.message) from e
    with tx(ctx.db):
        if transcription.ready(ctx.db, ctx.data_dir):
            # Sigue "procesando": la transcripción se encadena con prioridad alta.
            transcription.enqueue(ctx.db, ctx.source_id, payload(ctx.job).get("language"))
        else:
            # El audio ya se puede escuchar; se transcribirá al instalar el modelo.
            ctx.db.execute(
                "UPDATE sources SET status = 'ready', processed_at = now_iso(),"
                " error_code = NULL, error_message = NULL WHERE id = ?",
                (ctx.source_id,),
            )
            src_svc.merge_metadata(ctx.db, ctx.source_id, {"transcription": "needs_model"})


CHUNK_MS = 5 * 60_000  # tramos de 5 min: como mucho se repite un tramo tras un cierre
EDGE_MS = 3000  # frases que acaban tan cerca del corte se repiten en el tramo siguiente
MIN_ADVANCE_MS = 30_000


def _parts_dir(ctx: JobContext) -> Path:
    return ctx.data_dir / "sources" / ctx.source_id / "transcript-parts"


def transcribe(ctx: JobContext) -> None:
    """Transcribe por tramos con checkpoint: tras un cierre continúa en el último tramo."""
    src = ctx.source()
    # whisper y el LLM no conviven en memoria (BENCHMARKS §4): se descarga el LLM inactivo.
    ResourceManager(llm_svc.provider()).release()
    wav = ctx.data_dir / "sources" / ctx.source_id / "normalized.wav"
    if not wav.exists():
        raise JobFailed("no_audio", "Falta el audio preparado. Reintenta el procesamiento.")
    p = payload(ctx.job)
    model_id = str(p.get("model") or models.DEFAULT_STT)
    model, vad = (
        models.model_path(ctx.data_dir, model_id),
        models.model_path(ctx.data_dir, models.VAD),
    )
    if not (
        models.is_installed(ctx.data_dir, model_id)
        and models.is_installed(ctx.data_dir, models.VAD)
    ):
        raise JobFailed("needs_model", "Descarga el modelo de transcripción para continuar.")

    cp: dict[str, Any] = json.loads(ctx.job.get("checkpoint_json") or "{}")
    next_ms = int(cp.get("next_ms", 0))
    language = str(cp.get("language") or p.get("language") or "auto")
    part = int(cp.get("parts", 0))
    total = wav_duration_ms(wav)
    parts = _parts_dir(ctx)
    parts.mkdir(exist_ok=True, mode=0o700)
    kill_stale(parts / "whisper.pid")  # whisper huérfano de un cierre brusco anterior
    src_svc.merge_metadata(ctx.db, ctx.source_id, {"transcription": "running"})
    if next_ms:
        ctx.report(next_ms / total, "Reanudando la transcripción")

    try:
        while next_ms < total:
            if ctx.cancelled():
                raise audio.Cancelled
            length = min(CHUNK_MS, total - next_ms)
            last = next_ms + length >= total
            ctx.report(next_ms / total, f"Transcribiendo {_clock(next_ms)} de {_clock(total)}")
            chunk = parts / f"chunk-{uuid.uuid4().hex}.wav"
            slice_wav(wav, chunk, next_ms, length)
            try:
                pieces, detected = transcribe_wav(
                    chunk, model, vad, language, next_ms, ctx.cancelled
                )
            finally:
                chunk.unlink(missing_ok=True)
            if language == "auto" and detected:
                language = detected  # el resto de la clase, en el mismo idioma
            end = next_ms + length
            if last:
                keep, new_next = pieces, total
            else:
                keep = [x for x in pieces if x.end_ms <= end - EDGE_MS]
                new_next = keep[-1].end_ms if keep else end
                if new_next - next_ms < MIN_ADVANCE_MS:
                    keep, new_next = pieces, end
            (parts / f"part_{part:05d}.json").write_text(
                json.dumps([x.__dict__ for x in keep], ensure_ascii=False), encoding="utf-8"
            )
            part += 1
            next_ms = new_next
            queue.save_checkpoint(
                ctx.db, ctx.job["id"], {"next_ms": next_ms, "language": language, "parts": part}
            )
    except SttError as e:
        raise JobFailed(e.code, e.message) from e

    ctx.report(0.99, "Guardando la transcripción")
    pieces = []
    for i in range(part):
        f = parts / f"part_{i:05d}.json"
        pieces += [Piece(**x) for x in json.loads(f.read_text(encoding="utf-8"))]
    text = build_text(pieces)
    with tx(ctx.db):
        if text.strip():
            src_svc.add_version(ctx.db, ctx.source_id, text, "transcribed")
        src_svc.merge_metadata(
            ctx.db,
            ctx.source_id,
            {"transcription": "done" if text.strip() else "empty", "stt_model": model_id},
        )
        ctx.db.execute(
            "UPDATE sources SET status = 'ready', processed_at = now_iso(), language = ?,"
            " duration_ms = COALESCE(duration_ms, ?), error_code = NULL, error_message = NULL"
            " WHERE id = ?",
            (language if language != "auto" else None, total, ctx.source_id),
        )
    shutil.rmtree(parts, ignore_errors=True)
    # Transcrita: el original pesado ya no hace falta (la copia ligera sigue unos días).
    audio_files.apply(ctx.db, ctx.data_dir, ctx.source(), own_job=ctx.job["id"])
    _ = src


def _clock(ms: int) -> str:
    s = ms // 1000
    return (
        f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    )


def download_model(ctx: JobContext) -> None:
    model_id = str(payload(ctx.job).get("model"))
    if model_id not in models.CATALOG:
        raise JobFailed("unknown_model", "Modelo desconocido")
    wanted = [m for m in (models.VAD, model_id) if not models.is_installed(ctx.data_dir, m)]
    sizes = sum(models.CATALOG[m].size for m in wanted) or 1
    done = 0
    try:
        for m in wanted:
            spec = models.CATALOG[m]
            base = done

            def progress(f: float, base: int = base, size: int = spec.size) -> None:
                ctx.report((base + f * size) / sizes, "Descargando modelo")

            models.download(ctx.data_dir, m, progress, ctx.cancelled)
            done += spec.size
    except models.DownloadCancelled as e:
        raise audio.Cancelled from e
    except models.DownloadError as e:
        raise JobFailed(e.code, e.message) from e
    transcription.enqueue_waiting(ctx.db, ctx.data_dir)


def generate_doc(ctx: JobContext) -> None:
    """Apuntes o resumen con map-reduce; el avance por bloque queda en el checkpoint."""
    doc_id = str(payload(ctx.job).get("doc_id"))
    doc = ctx.db.execute("SELECT * FROM generated_docs WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        raise audio.Cancelled  # se borró mientras esperaba
    docs_svc.set_status(ctx.db, doc_id, "running")
    try:
        _generate(ctx, dict(doc))
    except Yielded:
        docs_svc.set_status(ctx.db, doc_id, "queued")
        raise
    except (audio.Cancelled, LLMCancelled) as e:
        docs_svc.set_status(ctx.db, doc_id, "cancelled")
        raise audio.Cancelled from e
    except LLMError as e:
        docs_svc.set_status(ctx.db, doc_id, "failed", e.code, e.message)
        raise JobFailed(e.code, e.message) from e
    except JobFailed as e:
        docs_svc.set_status(ctx.db, doc_id, "failed", e.code, e.message)
        raise
    except Exception:
        docs_svc.set_status(ctx.db, doc_id, "failed", "internal_error", "Error inesperado")
        raise


def _generate(ctx: JobContext, doc: dict[str, Any]) -> None:
    prov = llm_svc.provider()
    info = prov.info()
    if not info.running:
        raise JobFailed("llm_unavailable", "Ollama no está en marcha. Abre la app de Ollama.")
    rm = ResourceManager(prov)
    choice = rm.acquire(
        llm_svc.chosen_model(ctx.db),
        llm_svc.light_model(ctx.db),
        info.models,
        report=lambda m: ctx.report(0, m),
        cancelled=ctx.cancelled,
    )
    material = docs_svc.load_material(ctx.db, doc["id"])
    segment_of = {f.id: f.segment_id for s in material for f in s.fragments}
    budget = profile(choice.model).budget_mb
    peak = {"mb": 0}

    def chat(
        req: ChatRequest, task: str, on_token: Callable[[int], None] | None = None
    ) -> ChatResult:
        res = prov.chat(req, on_token=on_token, cancelled=ctx.cancelled)
        loaded = rm.after_call(req.model)
        if loaded:
            peak["mb"] = max(peak["mb"], loaded)
            if loaded > budget:
                log.warning("%s ocupa %d MB (presupuesto %d MB)", req.model, loaded, budget)
        docs_svc.record_run(
            ctx.db,
            ctx.job["id"],
            req.model,
            f"{doc['kind']}:{task}",
            res.input_tokens,
            res.output_tokens,
            res.duration_ms,
            loaded,
        )
        return res

    job = GenJob(
        kind=doc["kind"],
        detail=doc["detail"],
        model=choice.model,
        keep_alive=llm_svc.keep_alive(ctx.db),
        sources=material,
        chat=chat,
        report=lambda v, m: ctx.report(v, m),
        checkpoint=json.loads(ctx.job.get("checkpoint_json") or "{}"),
        save_checkpoint=lambda data: queue.save_checkpoint(ctx.db, ctx.job["id"], data),
        should_yield=lambda: queue.higher_waiting(ctx.db, int(ctx.job["priority"])),
    )
    draft = job.run()
    content, cites = number_citations(draft, segment_of)
    if not content["sections"]:
        raise JobFailed(
            "empty_result", "El modelo no encontró contenido con respaldo en las fuentes"
        )
    stats = {
        **job.stats.__dict__,
        "fallback": choice.fallback,
        "available_mb": choice.available_mb,
        "peak_loaded_mb": peak["mb"],
        "budget_mb": budget,
    }
    docs_svc.save_result(ctx.db, doc["id"], content, cites, choice.model, stats)


def index_source(ctx: JobContext) -> None:
    """Chunks + vectores de la versión actual (la fuente va en el payload, no en el trabajo)."""
    sid = str(payload(ctx.job).get("source_id"))
    rag_index.index_source(
        ctx.db,
        sid,
        llm_svc.provider(),
        memory=lambda: res_manager.available_mb(),  # se resuelve al llamar (pruebas)
        report=ctx.report,
        cancelled=ctx.cancelled,
    )


def chat_answer(ctx: JobContext) -> None:
    """Respuesta del asistente: busca en el ámbito del hilo, genera en streaming y verifica las
    citas. Sin fragmentos relevantes no se llama al modelo («no encontrado»)."""
    data = payload(ctx.job)
    mid, qid = str(data.get("message_id")), str(data.get("question_id"))
    row = ctx.db.execute(
        "SELECT m.thread_id, t.owner_id, t.scope_json, q.content AS question"
        " FROM chat_messages m JOIN chat_threads t ON t.id = m.thread_id"
        " JOIN chat_messages q ON q.id = ? WHERE m.id = ?",
        (qid, mid),
    ).fetchone()
    if row is None:
        raise audio.Cancelled  # se borró la conversación mientras esperaba
    stats: dict[str, Any] = {}
    try:
        _answer(ctx, dict(row), mid, stats)
    except (audio.Cancelled, LLMCancelled) as e:
        ctx.db.execute(
            "UPDATE chat_messages SET status = 'cancelled', stats_json = ? WHERE id = ?",
            (json.dumps(stats), mid),
        )
        raise audio.Cancelled from e
    except LLMError as e:
        chat_svc.save_answer(ctx.db, mid, "failed", "", [], None, stats, e.message)
        raise JobFailed(e.code, e.message) from e
    except JobFailed as e:
        chat_svc.save_answer(ctx.db, mid, "failed", "", [], None, stats, e.message)
        raise
    except Exception:
        chat_svc.save_answer(ctx.db, mid, "failed", "", [], None, stats, "Error inesperado")
        raise


def _answer(ctx: JobContext, row: dict[str, Any], mid: str, stats: dict[str, Any]) -> None:
    prov = llm_svc.provider()
    info = prov.info()
    if not info.running:
        raise JobFailed("llm_unavailable", "Ollama no está en marcha. Abre la app de Ollama.")
    question = row["question"]
    history = chat_svc.history(ctx.db, row["thread_id"], mid)
    previous = chat_svc.last_kind(ctx.db, row["thread_id"], mid)
    creative = rag_answer.is_creative(question, previous in ("created", "general"))
    stats["kind"] = "created" if creative else "answer"
    ctx.report(0.1, "Buscando en tus fuentes")
    scope = Scope.model_validate(json.loads(row["scope_json"] or "{}"))
    embedder = prov if rag_index.embeddings_available(prov) is None else None
    t0 = time.monotonic()
    found = rag_search.search(ctx.db, row["owner_id"], scope, question, embedder)
    stats.update(
        search_ms=int((time.monotonic() - t0) * 1000),
        search_mode=found.mode,
        chunks=[h.chunk_id for h in found.hits],
        notes=found.notes,
    )
    if not found.relevant and not creative:
        chat_svc.save_answer(ctx.db, mid, "not_found", "", [], None, stats)
        return
    rm = ResourceManager(prov)
    choice = rm.acquire(
        llm_svc.chosen_model(ctx.db),
        llm_svc.light_model(ctx.db),
        info.models,
        report=lambda m: ctx.report(0.2, m),
        cancelled=ctx.cancelled,
    )
    keep = llm_svc.keep_alive(ctx.db)
    last_t, last_text = [0.0], [""]

    def on_text(raw: str) -> None:
        now = time.monotonic()
        shown = rag_answer.live_text(raw)
        if now - last_t[0] >= 0.25 and shown != last_text[0]:
            chat_svc.set_live(ctx.db, mid, shown)
            last_t[0], last_text[0] = now, shown

    def call(r: ChatRequest, task: str) -> ChatResult:
        out = prov.chat(r, cancelled=ctx.cancelled, on_text=on_text)
        loaded = rm.after_call(r.model)
        docs_svc.record_run(
            ctx.db,
            ctx.job["id"],
            r.model,
            task,
            out.input_tokens,
            out.output_tokens,
            out.duration_ms,
            loaded,
        )
        return out

    def save(res: ChatResult, content: str, cites: list[tuple[int, int]], **extra: Any) -> None:
        stats.update(
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
            duration_ms=res.duration_ms,
            fallback=choice.fallback,
            **extra,
        )
        status = "done" if content else "not_found"
        chat_svc.save_answer(ctx.db, mid, status, content, cites, choice.model, stats)

    if found.relevant:
        context = rag_answer.build_context(ctx.db, found.hits)
        step = "Creando a partir de tus fuentes" if creative else "Redactando la respuesta"
        ctx.report(0.3, step)
        req = ChatRequest(
            model=choice.model,
            messages=rag_answer.build_messages(question, history, context.block, creative),
            max_tokens=1200,
            temperature=0.3 if creative else 0.1,
            keep_alive=keep,
        )
        res = call(req, "chat:create" if creative else "chat:answer")
        final = rag_answer.finalize(res.text, context.segment_of)
        retried = False
        if not creative and not final.found and rag_answer.needs_citations(res.text):
            # Escribió una respuesta pero sin ninguna cita válida: se le pide una vez que cite.
            retried = True
            again = dataclasses.replace(
                req, messages=req.messages + rag_answer.cite_retry(res.text)
            )
            res = call(again, "chat:answer_retry")
            final = rag_answer.finalize(res.text, context.segment_of)
        cites = {"proposed_cites": final.proposed, "invented_cites": final.invented}
        if final.found or not creative:
            save(res, final.content, final.citations, retried=retried, **cites)
            return
        uncited = rag_answer.live_text(res.text)
        if uncited:  # creó algo pero sin citar de dónde sale: se muestra como «sin respaldo»
            stats["kind"] = "general"
            save(res, uncited, [], **cites)
            return
    # El tema no está en las fuentes: se crea con conocimiento general y se marca así.
    stats["kind"] = "general"
    ctx.report(0.3, "No está en tus fuentes: creando con conocimiento general")
    req = ChatRequest(
        model=choice.model,
        messages=rag_answer.general_messages(question, history),
        max_tokens=1200,
        temperature=0.4,
        keep_alive=keep,
    )
    res = call(req, "chat:create_general")
    save(res, rag_answer.live_text(res.text), [])


def generate_exam(ctx: JobContext) -> None:
    """Examen: preguntas con evidencia literal, duplicados fuera y LLM-juez (reanudable)."""
    exam_id = str(payload(ctx.job).get("exam_id"))
    row = ctx.db.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if row is None:
        raise audio.Cancelled
    exam = dict(row)
    owner = ctx.db.execute(
        "SELECT owner_id FROM subjects WHERE id = ?", (exam["subject_id"],)
    ).fetchone()[0]
    exams_svc.set_status(ctx.db, exam_id, "running")
    try:
        prov = llm_svc.provider()
        info = prov.info()
        if not info.running:
            raise JobFailed("llm_unavailable", "Ollama no está en marcha. Abre la app de Ollama.")
        rm = ResourceManager(prov)
        choice = rm.acquire(
            llm_svc.chosen_model(ctx.db),
            llm_svc.light_model(ctx.db),
            info.models,
            report=lambda m: ctx.report(0, m),
            cancelled=ctx.cancelled,
        )

        def chat(req: ChatRequest, task: str) -> ChatResult:
            res = prov.chat(req, cancelled=ctx.cancelled)
            loaded = rm.after_call(req.model)
            docs_svc.record_run(
                ctx.db,
                ctx.job["id"],
                req.model,
                task,
                res.input_tokens,
                res.output_tokens,
                res.duration_ms,
                loaded,
            )
            return res

        similarity = None
        if rag_index.embeddings_available(prov) is None:

            def similarity(stem: str, others: list[str]) -> list[float]:
                vecs = prov.embed(rag_index.EMBED_MODEL, [stem, *others])
                return [_cosine(vecs[0], v) for v in vecs[1:]]

        stats = exams_svc.run_generation(
            ctx.db,
            exam,
            chat,
            choice.model,
            llm_svc.keep_alive(ctx.db),
            owner,
            report=ctx.report,
            checkpoint=json.loads(ctx.job.get("checkpoint_json") or "{}"),
            save_checkpoint=lambda data: queue.save_checkpoint(ctx.db, ctx.job["id"], data),
            should_yield=lambda: queue.higher_waiting(ctx.db, int(ctx.job["priority"])),
            similarity=similarity,
        )
        log.info("Examen %s: %s", exam_id, {k: stats[k] for k in ("proposed", "valid")})
    except Yielded:
        exams_svc.set_status(ctx.db, exam_id, "queued")
        raise
    except (audio.Cancelled, LLMCancelled) as e:
        exams_svc.set_status(ctx.db, exam_id, "cancelled")
        raise audio.Cancelled from e
    except LLMError as e:
        exams_svc.set_status(ctx.db, exam_id, "failed", e.code, e.message)
        raise JobFailed(e.code, e.message) from e
    except JobFailed as e:
        exams_svc.set_status(ctx.db, exam_id, "failed", e.code, e.message)
        raise
    except Exception:
        exams_svc.set_status(ctx.db, exam_id, "failed", "internal_error", "Error inesperado")
        raise


def generate_deck(ctx: JobContext) -> None:
    """Mazo de tarjetas con evidencia literal y revisor (reanudable)."""
    deck_id = str(payload(ctx.job).get("deck_id"))
    row = ctx.db.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if row is None:
        raise audio.Cancelled
    deck = dict(row)
    owner = ctx.db.execute(
        "SELECT owner_id FROM subjects WHERE id = ?", (deck["subject_id"],)
    ).fetchone()[0]
    cards_svc.set_status(ctx.db, deck_id, "running")
    try:
        prov = llm_svc.provider()
        info = prov.info()
        if not info.running:
            raise JobFailed("llm_unavailable", "Ollama no está en marcha. Abre la app de Ollama.")
        rm = ResourceManager(prov)
        choice = rm.acquire(
            llm_svc.chosen_model(ctx.db),
            llm_svc.light_model(ctx.db),
            info.models,
            report=lambda m: ctx.report(0, m),
            cancelled=ctx.cancelled,
        )

        def chat(req: ChatRequest, task: str) -> ChatResult:
            res = prov.chat(req, cancelled=ctx.cancelled)
            loaded = rm.after_call(req.model)
            docs_svc.record_run(
                ctx.db, ctx.job["id"], req.model, task, res.input_tokens, res.output_tokens,
                res.duration_ms, loaded,
            )  # fmt: skip
            return res

        similarity = None
        if rag_index.embeddings_available(prov) is None:

            def similarity(text: str, others: list[str]) -> list[float]:
                vecs = prov.embed(rag_index.EMBED_MODEL, [text, *others])
                return [_cosine(vecs[0], v) for v in vecs[1:]]

        stats = cards_svc.run_generation(
            ctx.db,
            deck,
            chat,
            choice.model,
            llm_svc.keep_alive(ctx.db),
            owner,
            report=ctx.report,
            checkpoint=json.loads(ctx.job.get("checkpoint_json") or "{}"),
            save_checkpoint=lambda data: queue.save_checkpoint(ctx.db, ctx.job["id"], data),
            should_yield=lambda: queue.higher_waiting(ctx.db, int(ctx.job["priority"])),
            similarity=similarity,
        )
        log.info("Mazo %s: %s", deck_id, {k: stats[k] for k in ("proposed", "valid", "saved")})
    except Yielded:
        cards_svc.set_status(ctx.db, deck_id, "queued")
        raise
    except (audio.Cancelled, LLMCancelled) as e:
        cards_svc.set_status(ctx.db, deck_id, "cancelled")
        raise audio.Cancelled from e
    except LLMError as e:
        cards_svc.set_status(ctx.db, deck_id, "failed", e.code, e.message)
        raise JobFailed(e.code, e.message) from e
    except JobFailed as e:
        cards_svc.set_status(ctx.db, deck_id, "failed", e.code, e.message)
        raise
    except Exception:
        cards_svc.set_status(ctx.db, deck_id, "failed", "internal_error", "Error inesperado")
        raise


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def grade_attempt(ctx: JobContext) -> None:
    """Respuestas cortas corregidas por la IA con rúbrica y evidencia; luego, la nota."""
    aid = str(payload(ctx.job).get("attempt_id"))
    att = ctx.db.execute("SELECT * FROM exam_attempts WHERE id = ?", (aid,)).fetchone()
    if att is None:
        raise audio.Cancelled
    pending = ctx.db.execute(
        "SELECT q.*, a.answer_json AS given FROM attempt_answers a"
        " JOIN exam_questions q ON q.id = a.question_id"
        " WHERE a.attempt_id = ? AND q.type = 'short' AND a.graded_by IS NULL"
        " AND a.answer_json IS NOT NULL",
        (aid,),
    ).fetchall()
    prov = llm_svc.provider()
    info = prov.info()
    if not info.running:
        raise JobFailed("llm_unavailable", "Ollama no está en marcha. Abre la app de Ollama.")
    rm = ResourceManager(prov)
    choice = rm.acquire(
        llm_svc.chosen_model(ctx.db),
        llm_svc.light_model(ctx.db),
        info.models,
        report=lambda m: ctx.report(0, m),
        cancelled=ctx.cancelled,
    )
    ev = exams_svc.evidence(ctx.db, [q["id"] for q in pending])
    for i, q in enumerate(pending):
        ctx.report(i / max(1, len(pending)), f"Corrigiendo respuesta {i + 1} de {len(pending)}")
        req = ChatRequest(
            model=choice.model,
            messages=grading.grade_messages(
                dict(q), [e["quote"] for e in ev[q["id"]]], str(json.loads(q["given"]))
            ),
            schema=grading.GRADE_SCHEMA,
            max_tokens=400,
            temperature=0.0,
            keep_alive=llm_svc.keep_alive(ctx.db),
        )
        pts, feedback = 0.0, "No se pudo corregir automáticamente."
        for _ in range(2):
            res = prov.chat(req, cancelled=ctx.cancelled)
            try:
                pts, feedback = grading.parse_grade(res.text)
                break
            except (ValueError, json.JSONDecodeError):
                continue
        rm.after_call(choice.model)
        ctx.db.execute(
            "UPDATE attempt_answers SET points = ?, is_correct = ?, feedback = ?, graded_by = 'ai'"
            " WHERE attempt_id = ? AND question_id = ?",
            (pts, int(pts >= 1), feedback, aid, q["id"]),
        )
    exams_svc.finalize(ctx.db, aid)


HANDLERS: dict[str, Callable[[JobContext], None]] = {
    "generate_exam": generate_exam,
    "generate_deck": generate_deck,
    "grade_attempt": grade_attempt,
    "chat_answer": chat_answer,
    "generate_doc": generate_doc,
    "index_source": index_source,
    "extract_document": extract_document,
    "prepare_audio": prepare_audio,
    "transcribe": transcribe,
    "download_model": download_model,
}


def set_source_status(
    db: sqlite3.Connection,
    source_id: str | None,
    status: str,
    code: str | None = None,
    message: str | None = None,
) -> None:
    if source_id:
        db.execute(
            "UPDATE sources SET status = ?, error_code = ?, error_message = ? WHERE id = ?",
            (status, code, message, source_id),
        )


def payload(job: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(job.get("payload_json") or "{}")
    return data
