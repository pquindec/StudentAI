"""AI Resource Manager v1 (ARCHITECTURE §8, umbrales medidos en BENCHMARKS §4).

- Un modelo pesado a la vez: el planificador ya serializa stt/llm; aquí, además, se descargan
  de Ollama los modelos que sobran antes de cargar otro o de lanzar whisper.
- Antes de cargar un LLM se mira la memoria disponible. Si no llega para el modelo preferido se
  usa el ligero; si tampoco, el trabajo espera (visible en la UI). Nunca se fuerza.
"""

import logging
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.llm.base import LLMCancelled, LLMError, LLMProvider

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelProfile:
    min_free_mb: int  # memoria disponible necesaria antes de cargarlo
    budget_mb: int  # tamaño cargado máximo esperado con 8K de contexto (medido)


# BENCHMARKS §2.1 y §4: 9B cargado 7,6 GB (~5K) → 8,3 GB (~15K); 4B 4,0 → 4,7 GB.
# Con menos de ~3 GB disponibles antes de cargar el 9B hubo presión de memoria → se usa el 4B.
PROFILES: dict[str, ModelProfile] = {
    "qwen3.5:9b": ModelProfile(min_free_mb=3000, budget_mb=8500),
    "qwen3.5:4b": ModelProfile(min_free_mb=1500, budget_mb=5000),
}
UNKNOWN = ModelProfile(min_free_mb=3000, budget_mb=9000)

# Medido en la Fase 4 (Ollama 0.40.14, motor MLX): el tamaño cargado crece ~250 MB por llamada
# aunque el contexto no cambie. Si la siguiente llamada superaría el presupuesto, se descarga
# el modelo y se vuelve a cargar limpio (~5 s).
GROWTH_MB = 300

WAIT_STEP_S = 5.0
MAX_WAIT_S = 600.0

_VM_LINE = re.compile(r"^Pages (free|inactive|speculative|purgeable):\s+(\d+)\.", re.M)


def available_mb() -> int:
    """Memoria que macOS puede entregar sin presión: libre + inactiva + especulativa + purgable."""
    out = subprocess.run(
        ["/usr/bin/vm_stat"], capture_output=True, text=True, timeout=5, check=True
    ).stdout
    page = re.search(r"page size of (\d+) bytes", out)
    size = int(page.group(1)) if page else 16384
    pages = sum(int(n) for _, n in _VM_LINE.findall(out))
    return pages * size // 2**20


def profile(model: str) -> ModelProfile:
    return PROFILES.get(model, UNKNOWN)


@dataclass
class Choice:
    model: str
    fallback: bool  # se usó el modelo ligero por falta de memoria
    available_mb: int


class ResourceManager:
    def __init__(
        self,
        provider: LLMProvider,
        memory: Callable[[], int] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.provider = provider
        # Se resuelven al llamar (no al definir) para poder sustituirlos en las pruebas.
        self.memory = memory or (lambda: available_mb())
        self.sleep = sleep or (lambda s: time.sleep(s))

    def release(self, keep: str | None = None) -> None:
        """Descarga de Ollama todos los modelos salvo `keep` (p. ej. antes de lanzar whisper)."""
        for m in self.provider.loaded():
            if m.name != keep:
                log.info("Descargando %s de la memoria", m.name)
                try:
                    self.provider.unload(m.name)
                except LLMError:
                    log.warning("No se pudo descargar %s", m.name)

    def after_call(self, model: str) -> int | None:
        """Tras cada llamada: devuelve el tamaño cargado y, si se acerca al presupuesto, descarga
        el modelo para que la memoria no siga creciendo."""
        size = next((m.size_mb for m in self.provider.loaded() if m.name == model), None)
        if size is not None and size + GROWTH_MB > profile(model).budget_mb:
            log.info("%s ocupa %d MB: se descarga para liberar memoria", model, size)
            try:
                self.provider.unload(model)
            except LLMError:
                log.warning("No se pudo descargar %s", model)
        return size

    def acquire(
        self,
        preferred: str,
        light: str | None,
        installed: list[str],
        report: Callable[[str], None],
        cancelled: Callable[[], bool],
    ) -> Choice:
        """Elige el modelo que cabe ahora mismo; si ninguno cabe, espera hasta MAX_WAIT_S."""
        candidates = [m for m in (preferred, light) if m and m in installed]
        if not candidates:
            raise LLMError(
                "model_missing",
                f"Falta el modelo {preferred} en Ollama. Descárgalo con «ollama pull {preferred}».",
            )
        loaded = {m.name for m in self.provider.loaded()}
        for m in candidates:
            if m in loaded:  # ya está en memoria: no hace falta más
                self.release(keep=m)
                return Choice(m, m != preferred, self.memory())
        self.release()
        waited = 0.0
        while True:
            free = self.memory()
            for m in candidates:
                if free >= profile(m).min_free_mb:
                    return Choice(m, m != preferred, free)
            if waited >= MAX_WAIT_S:
                raise LLMError(
                    "no_memory",
                    "No hay memoria libre suficiente para el modelo. Cierra alguna aplicación"
                    " y vuelve a intentarlo.",
                )
            report(f"Esperando memoria libre ({free / 1024:.1f} GB disponibles)")
            if cancelled():
                raise LLMCancelled
            self.sleep(WAIT_STEP_S)
            waited += WAIT_STEP_S
