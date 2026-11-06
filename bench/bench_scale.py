"""Fase 9 — rendimiento y estabilidad a escala, con el pipeline real de la app.

    cd backend && uv run python ../bench/bench_scale.py library [--n 500]
    cd backend && uv run python ../bench/bench_scale.py audio [--hours 3]

- library: N documentos sintéticos distintos (texto pegado, PDF y Word) → importación,
  extracción, indexado con embeddings reales (Ollama) y, después, tiempos de la biblioteca
  (listado, filtros, búsqueda del asistente) y tamaño de la BD.
- audio: la grabación sintética de 1 h del corpus repetida hasta N horas → normalización,
  transcripción (whisper.cpp con puntos de control) e indexado; comprueba que no se pierde texto.

Carpeta temporal propia; no toca los datos del usuario. Los modelos de whisper se enlazan (solo
lectura) desde la instalación de la app. Resultados en bench/results/scale_<parte>.json.
"""

import argparse
import json
import random
import resource
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.app import create_app  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.db.migrate import migrate  # noqa: E402
from app.rag import search  # noqa: E402
from app.rag.scope import Scope  # noqa: E402
from app.services import llm  # noqa: E402
from app.stt import models as stt_models  # noqa: E402
from tests.factories import make_pdf  # noqa: E402

APP_DATA = Path.home() / "Library/Application Support/com.aistudyassistant.desktop"
WORDS = (
    "arquitectura sistema red protocolo memoria proceso hilo algoritmo complejidad grafo árbol"
    " tabla índice consulta transacción bloqueo caché latencia rendimiento seguridad cifrado"
    " clave certificado servidor cliente petición respuesta evento cola mensaje servicio"
    " contenedor despliegue prueba requisito diseño patrón interfaz módulo componente capa"
).split()


def rss_mb() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // (1024 * 1024)


def child_rss_mb() -> int:
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // (1024 * 1024)


def para(rng: random.Random, i: int) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(40, 90))]
    return f"Documento {i}. " + " ".join(words).capitalize() + "."


def timed(fn: Any, n: int = 20) -> dict[str, float]:
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    return {"p50_ms": round(statistics.median(ts), 1), "p95_ms": round(ts[int(len(ts) * 0.95) - 1], 1)}


def setup() -> tuple[Settings, dict[str, str], Path]:
    tmp = Path(tempfile.mkdtemp(prefix="scale-"))
    s = Settings(data_dir=tmp / "data", socket_path=tmp / "s.sock", token=secrets.token_hex(32))
    s.prepare_dirs()
    migrate(s.db_path, s.backups_dir)
    wdir = stt_models.models_dir(s.data_dir)
    wdir.mkdir(parents=True, exist_ok=True)
    for f in (APP_DATA / "models" / "whisper").glob("*.bin"):
        (wdir / f.name).symlink_to(f)
    return s, {"Authorization": f"Bearer {s.token}"}, tmp


def wait_all(c: TestClient, h: dict[str, str], timeout: float) -> float:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        jobs = c.get("/api/v1/jobs?limit=200", headers=h).json()
        if not jobs:
            return time.monotonic() - t0
        time.sleep(1)
    raise TimeoutError("quedan trabajos")


def library(n: int) -> dict[str, Any]:
    rng = random.Random(9)
    s, h, tmp = setup()
    files = tmp / "files"
    files.mkdir()
    out: dict[str, Any] = {"documents": n}
    with TestClient(create_app(s)) as c:
        subjects = [
            c.post("/api/v1/subjects", headers=h, json={"name": f"Asignatura {k}"}).json()["id"]
            for k in range(5)
        ]
        t0 = time.monotonic()
        kinds = {"paste": 0, "pdf": 0, "docx": 0}
        chars = 0
        for i in range(n):
            sid = subjects[i % 5]
            kind = "pdf" if i % 10 in (7, 8) else "docx" if i % 10 == 9 else "paste"
            kinds[kind] += 1
            if kind == "paste":
                text = "\n\n".join(para(rng, i) for _ in range(rng.randint(3, 60)))
                chars += len(text)
                r = c.post("/api/v1/sources/text", headers=h,
                           json={"subject_id": sid, "title": f"Apuntes {i}", "text": text})  # fmt: skip
            else:
                path = files / f"doc{i}.{kind}"
                if kind == "pdf":
                    pages = [[para(rng, i)[:90] for _ in range(20)] for _ in range(rng.randint(2, 15))]
                    make_pdf(path, pages)
                else:
                    import docx

                    d = docx.Document()
                    d.add_heading(f"Tema {i}", 1)
                    for _ in range(rng.randint(3, 40)):
                        d.add_paragraph(para(rng, i))
                    d.save(str(path))
                r = c.post("/api/v1/internal/sources/import-file", headers={**h, "x-core-caller": "1"},
                           json={"path": str(path), "subject_id": sid})  # fmt: skip
            assert r.status_code == 201, r.text
        out["import_requests_s"] = round(time.monotonic() - t0, 1)
        out["kinds"] = kinds
        out["pasted_chars"] = chars
        out["processing_and_index_s"] = round(wait_all(c, h, 3 * 3600), 1)
        total = c.get("/api/v1/sources?limit=1", headers=h).json()["total"]
        failed = c.get("/api/v1/sources?status=failed&limit=1", headers=h).json()["total"]
        rag = c.get("/api/v1/rag/status", headers=h).json()
        out.update(sources=total, failed=failed, rag=rag)

        out["list_page_50"] = timed(lambda: c.get("/api/v1/sources?limit=50", headers=h))
        out["list_last_page"] = timed(lambda: c.get(f"/api/v1/sources?limit=50&offset={n - 50}", headers=h))
        out["filter_text"] = timed(lambda: c.get("/api/v1/sources?q=Apuntes%2042&limit=50", headers=h))
        out["filter_subject_kind"] = timed(
            lambda: c.get(f"/api/v1/sources?subject_id={subjects[2]}&kind=pdf&limit=50", headers=h)
        )
        out["subjects"] = timed(lambda: c.get("/api/v1/subjects", headers=h))
        db = connect(s.db_path)
        prov = llm.provider()
        qs = [f"¿Qué relación hay entre {rng.choice(WORDS)} y {rng.choice(WORDS)}?" for _ in range(20)]
        it = iter(qs * 2)
        out["assistant_search_all"] = timed(lambda: search.search(db, "local", Scope(), next(it), prov), 20)
        it2 = iter(qs * 2)
        out["assistant_search_subject"] = timed(
            lambda: search.search(db, "local", Scope(subject_id=subjects[0]), next(it2), prov), 20
        )
        out["chunks"] = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        db.close()
    out["db_mb"] = round(sum(p.stat().st_size for p in s.data_dir.glob("app.db*")) / 2**20, 1)
    out["data_dir_mb"] = round(sum(p.stat().st_size for p in s.data_dir.rglob("*") if p.is_file()) / 2**20, 1)
    out["backend_peak_rss_mb"] = rss_mb()
    out["children_peak_rss_mb"] = child_rss_mb()
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def audio(hours: int) -> dict[str, Any]:
    s, h, tmp = setup()
    src = ROOT / "corpus" / "es_long.wav"
    long = tmp / f"clase_{hours}h.wav"
    subprocess.run(  # noqa: S603
        ["ffmpeg", "-v", "error", "-stream_loop", str(hours - 1), "-i", str(src), "-c", "copy", str(long)],
        check=True,
    )
    out: dict[str, Any] = {"hours": hours, "file_mb": round(long.stat().st_size / 2**20)}
    with TestClient(create_app(s)) as c:
        sid = c.post("/api/v1/subjects", headers=h, json={"name": "Clase larga"}).json()["id"]
        t0 = time.monotonic()
        r = c.post("/api/v1/internal/sources/import-file", headers={**h, "x-core-caller": "1"},
                   json={"path": str(long), "subject_id": sid})  # fmt: skip
        assert r.status_code == 201, r.text
        source = r.json()["id"]
        peak_free = []
        while True:
            jobs = c.get("/api/v1/jobs?limit=200", headers=h).json()
            if not jobs:
                break
            peak_free.append(c.get("/api/v1/ai/status", headers=h).json()["available_mb"])
            time.sleep(5)
        out["total_s"] = round(time.monotonic() - t0, 1)
        st = c.get(f"/api/v1/sources/{source}", headers=h).json()
        out["status"] = st["status"]
        t = time.perf_counter()
        body = c.get(f"/api/v1/sources/{source}/content", headers=h)
        out["content_ms"] = round((time.perf_counter() - t) * 1000)
        out["content_mb"] = round(len(body.content) / 2**20, 2)
        content = body.json()
        segs = content.get("segments", [])
        out["segments"] = len(segs)
        out["chars"] = len(content.get("text", ""))
        starts = [x["start_ms"] for x in segs if x.get("start_ms") is not None]
        out["last_timestamp_min"] = round(max(starts) / 60000, 1) if starts else None
        gaps = [(b - a) / 1000 for a, b in zip(starts, starts[1:], strict=False)]
        out["max_gap_s"] = round(max(gaps), 1) if gaps else None
        out["index"] = c.get(f"/api/v1/sources/{source}/index", headers=h).json()
        out["min_available_mb_during"] = min(peak_free) if peak_free else None
    out["children_peak_rss_mb"] = child_rss_mb()
    out["backend_peak_rss_mb"] = rss_mb()
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=["library", "audio"])
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--hours", type=int, default=3)
    a = ap.parse_args()
    res = library(a.n) if a.part == "library" else audio(a.hours)
    (ROOT / "results" / f"scale_{a.part}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
