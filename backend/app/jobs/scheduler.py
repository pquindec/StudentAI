"""Planificador: toma trabajos de la cola respetando la concurrencia por clase de recurso.

Regla base (ARCHITECTURE §8): como mucho un trabajo pesado (stt/llm) a la vez; E/S en paralelo.
"""

import asyncio
import contextlib
import logging
from pathlib import Path

from app.core import children
from app.db.connection import connect
from app.jobs import queue
from app.jobs.handlers import HANDLERS, JobContext, JobFailed, set_source_status
from app.pipelines.audio import Cancelled
from app.services import transcription

log = logging.getLogger(__name__)

CONCURRENCY = {"io": 2, "media": 1, "stt": 1, "llm": 1, "embed": 1}
HEAVY = {"stt", "llm"}


class Scheduler:
    def __init__(self, db_path: Path, data_dir: Path, poll_interval: float = 0.3) -> None:
        self.db_path = db_path
        self.data_dir = data_dir
        self.poll_interval = poll_interval
        self.running: dict[str, int] = dict.fromkeys(CONCURRENCY, 0)
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._inflight: set[asyncio.Task[None]] = set()

    def start(self) -> None:
        db = connect(self.db_path)
        try:
            n = queue.recover_interrupted(db)
            if n:
                log.info("Reanudando %d trabajo(s) interrumpido(s)", n)
            # Audios que esperaban un modelo de transcripción que ya está instalado.
            n = transcription.enqueue_waiting(db, self.data_dir)
            if n:
                log.info("Encolando %d transcripción(es) pendiente(s)", n)
        finally:
            db.close()
        self._task = asyncio.create_task(self._loop(), name="job-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        children.kill_all()
        # Los trabajos en curso quedan 'running' y se reanudan al próximo arranque.

    def wake(self) -> None:
        self._wake.set()

    def _free_classes(self) -> list[str]:
        heavy_busy = any(self.running[c] for c in HEAVY)
        return [
            c
            for c, limit in CONCURRENCY.items()
            if self.running[c] < limit and not (c in HEAVY and heavy_busy)
        ]

    async def _loop(self) -> None:
        db = connect(self.db_path)
        try:
            while True:
                job = queue.claim_next(db, self._free_classes())
                if job is None:
                    self._wake.clear()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._wake.wait(), self.poll_interval)
                    continue
                self.running[job["resource_class"]] += 1
                t = asyncio.create_task(self._run(job))
                self._inflight.add(t)
                t.add_done_callback(self._inflight.discard)
        finally:
            db.close()

    async def _run(self, job: dict[str, object]) -> None:
        try:
            await asyncio.to_thread(self._execute, dict(job))
        finally:
            self.running[str(job["resource_class"])] -= 1
            self.wake()

    def _execute(self, job: dict[str, object]) -> None:
        db = connect(self.db_path)
        jid = str(job["id"])
        sid = job["source_id"] if isinstance(job["source_id"], str) else None
        try:
            handler = HANDLERS.get(str(job["type"]))
            if handler is None:
                queue.finish(db, jid, "failed", "unknown_job", "Tipo de trabajo desconocido")
                return
            set_source_status(db, sid, "processing")
            handler(JobContext(job=dict(job), db=db, data_dir=self.data_dir))
            queue.finish(db, jid, "done")
        except Cancelled:
            queue.finish(db, jid, "cancelled")
            set_source_status(db, sid, "cancelled", "cancelled", "Procesamiento cancelado")
        except JobFailed as e:
            queue.finish(db, jid, "failed", e.code, e.message)
            set_source_status(db, sid, "failed", e.code, e.message)
        except Exception:
            log.exception("Fallo inesperado en el trabajo %s", jid)
            msg = "Error inesperado al procesar el archivo"
            queue.finish(db, jid, "failed", "internal_error", msg)
            set_source_status(db, sid, "failed", "internal_error", msg)
        finally:
            db.close()
