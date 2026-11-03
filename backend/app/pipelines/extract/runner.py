"""Ejecuta un extractor en un SUBPROCESO aislado: si un archivo malicioso o dañado provoca un
fallo en código nativo (pdfium, lxml) o un bucle infinito, solo muere el subproceso."""

import json
import resource
import subprocess
import sys
from pathlib import Path

from app.core import limits
from app.pipelines.extract.document import Extraction

# El hijo recibe sys.path por stdin para funcionar igual en desarrollo y empaquetado (-I).
_BOOT = (
    "import sys, json; sys.path[:0] = json.loads(sys.stdin.readline()); "
    "from app.pipelines.extract.runner import child_main; child_main()"
)


class ExtractFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def run_isolated(kind: str, path: Path, timeout: float = limits.EXTRACT_TIMEOUT_S) -> Extraction:
    paths = [p for p in sys.path if p]
    try:
        proc = subprocess.run(  # noqa: S603 — ejecutable y argumentos controlados
            [sys.executable, "-I", "-c", _BOOT, kind, str(path)],
            input=json.dumps(paths) + "\n",
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractFailed("timeout", "El archivo tardó demasiado en procesarse") from exc
    if proc.returncode == 0:
        return Extraction.from_json(json.loads(proc.stdout))
    if proc.returncode == 2:
        err = json.loads(proc.stdout)
        raise ExtractFailed(err["code"], err["message"])
    raise ExtractFailed(
        "crashed", "No se pudo leer el archivo: puede estar dañado o tener un formato no compatible"
    )


def child_main() -> None:
    from app.pipelines.extract.extractors import EXTRACTORS, ExtractionError

    # Límite de CPU (segundos): defensa extra frente a bucles patológicos.
    resource.setrlimit(resource.RLIMIT_CPU, (limits.EXTRACT_TIMEOUT_S, limits.EXTRACT_TIMEOUT_S))
    kind, path = sys.argv[1], Path(sys.argv[2])
    try:
        result = EXTRACTORS[kind](path)
    except ExtractionError as e:
        sys.stdout.write(json.dumps({"code": e.code, "message": e.message}))
        sys.exit(2)
    sys.stdout.write(json.dumps(result.to_json(), ensure_ascii=False))
