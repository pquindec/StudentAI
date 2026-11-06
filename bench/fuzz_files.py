"""Fase 9 — fuzzing de archivos malformados.

Muta archivos válidos (PDF, DOCX, RTF, CSV, TXT, MD y audio) y los pasa por el mismo camino
que una importación real: `inspect` (firma y límites), el extractor en subproceso aislado y,
para el audio, `ffprobe`. Comprueba que cada archivo termina en «leído» o en un error controlado
con mensaje, sin colgarse, sin excepciones inesperadas y sin tumbar el proceso principal.

    cd backend && uv run python ../bench/fuzz_files.py [--n 150] [--seed 9]

Escribe el resumen en bench/results/fuzz_files.json. Solo datos sintéticos.
"""

import argparse
import io
import json
import random
import resource
import sys
import tempfile
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))

from app.core.errors import AppError  # noqa: E402
from app.pipelines import audio  # noqa: E402
from app.pipelines.extract.runner import ExtractFailed, run_isolated  # noqa: E402
from app.pipelines.files import inspect  # noqa: E402
from tests.factories import make_audio, make_docx, make_pdf  # noqa: E402

TIMEOUT_S = 60  # en la app son 300 s; aquí basta para detectar cuelgues

TEXT = "Tema 1: Arquitectura\n\nLa arquitectura define componentes, conectores y restricciones.\n"
SEEDS_TEXT = {
    "txt": TEXT.encode(),
    "md": b"# Tema\n\n- punto *uno*\n- punto [dos](http://x)\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    "csv": "concepto;definición\nOCP;abierto/cerrado\nSRP;responsabilidad única\n".encode(),
    "rtf": rb"{\rtf1\ansi{\fonttbl\f0 Arial;}\f0\pard Tema {\b uno}\par Arquitectura\'e9\par}",
}


def seeds(tmp: Path) -> dict[str, bytes]:
    out = dict(SEEDS_TEXT)
    out["pdf"] = make_pdf(tmp / "s.pdf", [["Tema 1", "Componentes y conectores"], ["Tema 2"]]).read_bytes()
    out["docx"] = make_docx(tmp / "s.docx").read_bytes()
    wav = make_audio(tmp / "s.wav", seconds=2)
    if wav is not None:
        out["wav"] = wav.read_bytes()
    return out


def mutate(data: bytes, rng: random.Random) -> bytes:
    b = bytearray(data)
    for _ in range(rng.randint(1, 4)):
        op = rng.choice(["flip", "insert", "delete", "truncate", "dup", "junk", "magic"])
        if not b:
            b = bytearray(b"x")
        i = rng.randrange(len(b))
        if op == "flip":
            for _ in range(rng.randint(1, 32)):
                j = rng.randrange(len(b))
                b[j] ^= 1 << rng.randrange(8)
        elif op == "insert":
            b[i:i] = rng.randbytes(rng.randint(1, 512))
        elif op == "delete":
            del b[i : i + rng.randint(1, 512)]
        elif op == "truncate":
            del b[max(8, i) :]
        elif op == "dup":
            j = rng.randrange(len(b))
            b[i:i] = b[j : j + rng.randint(1, 4096)] * rng.randint(1, 50)
        elif op == "junk":
            b[i:i] = rng.choice([b"\x00" * 4096, b"\xff" * 4096, b"(" * 2000, b"<<" * 2000,
                                 b"obj " * 1000, b"{\\" * 2000, b'"' * 3000, b";" * 5000])  # fmt: skip
        else:  # números extremos donde suelen ir tamaños y longitudes
            b[i:i] = rng.choice([b"99999999999", b"-1", b"4294967295", b"0", b"/Length 999999999"])
    return bytes(b)


def mutate_docx(data: bytes, rng: random.Random) -> bytes:
    """Muta el XML de dentro del zip (además de mutar el zip entero, que cubre `mutate`)."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        target = rng.choice(zin.namelist())
        for name in zin.namelist():
            raw = zin.read(name)
            zout.writestr(name, mutate(raw, rng) if name == target else raw)
    return buf.getvalue()


def run_one(kind: str, ext: str, data: bytes, path: Path) -> tuple[str, float]:
    path.write_bytes(data)
    t0 = time.monotonic()
    try:
        info = inspect(path, path.name)
        if info.kind == "audio":
            audio.probe(path)
            outcome = "ok"
        else:
            run_isolated(info.kind, path, timeout=TIMEOUT_S)
            outcome = "ok"
    except AppError as e:
        assert e.body()["error"]["message"], "error sin mensaje"
        outcome = f"rechazado:{e.body()['error']['code']}"
    except ExtractFailed as e:
        assert e.message, "error sin mensaje"
        outcome = f"fallo:{e.code}"
    return outcome, time.monotonic() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150, help="mutaciones por formato")
    ap.add_argument("--seed", type=int, default=9)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    tmp = Path(tempfile.mkdtemp(prefix="fuzz-"))
    base = seeds(tmp)

    cases: list[tuple[str, str, bytes]] = []
    for kind, data in base.items():
        ext = "." + kind
        for _ in range(args.n):
            fn = mutate_docx if kind == "docx" and rng.random() < 0.5 else mutate
            cases.append((kind, ext, fn(data, rng)))

    results: dict[str, Counter[str]] = {k: Counter() for k in base}
    unexpected: list[dict[str, str]] = []
    slowest: dict[str, float] = {k: 0.0 for k in base}

    def work(i: int, case: tuple[str, str, bytes]) -> None:
        kind, ext, data = case
        try:
            outcome, dt = run_one(kind, ext, data, tmp / f"c{i}{ext}")
        except Exception as e:  # cualquier otra cosa es un hallazgo
            (tmp / "fallos").mkdir(exist_ok=True)
            (tmp / "fallos" / f"c{i}{ext}").write_bytes(data)
            unexpected.append({"kind": kind, "case": f"c{i}{ext}", "error": repr(e)[:300]})
            return
        results[kind][outcome.split(":")[0] if outcome == "ok" else outcome] += 1
        slowest[kind] = max(slowest[kind], dt)
        if dt >= TIMEOUT_S:
            unexpected.append({"kind": kind, "case": f"c{i}{ext}", "error": "timeout"})
        (tmp / f"c{i}{ext}").unlink(missing_ok=True)

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda a: work(*a), enumerate(cases)))
    child_peak_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // (1024 * 1024)

    summary = {
        "seed": args.seed,
        "per_format": args.n,
        "cases": len(cases),
        "duration_s": round(time.monotonic() - t0, 1),
        "outcomes": {k: dict(v) for k, v in results.items()},
        "slowest_s": {k: round(v, 2) for k, v in slowest.items()},
        "child_peak_rss_mb": child_peak_mb,
        "unexpected": unexpected,
        "kept_failures_in": str(tmp / "fallos") if unexpected else None,
    }
    out = ROOT / "results" / "fuzz_files.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
