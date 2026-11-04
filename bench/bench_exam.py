"""Aceptación de la Fase 6: examen de 20 preguntas con el modelo local y el pipeline real.

Uso (desde la raíz): backend/.venv/bin/python bench/bench_exam.py [--real DB]
- Corpus: los 24 párrafos de Ingeniería de Software, un documento por tema.
- --real: además, un examen sobre la fuente más larga de esa BD (copiada en solo lectura a una
  BD temporal; nada sale del Mac). Las preguntas reales NO se guardan en bench/results.
Comprueba que el 100 % de las preguntas guardadas tiene evidencia literal y vuelca las preguntas
para revisarlas a mano.
"""

import json
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))

from app.db.connection import connect  # noqa: E402
from app.db.migrate import migrate  # noqa: E402
from app.generation.exam import ExamConfig  # noqa: E402
from app.jobs import handlers  # noqa: E402
from app.rag.scope import Scope  # noqa: E402
from app.services import exams as exams_svc  # noqa: E402
from app.services import sources as src_svc  # noqa: E402

CORPUS = json.loads((ROOT / "corpus" / "es_corpus.json").read_text())
CFG = ExamConfig(count=20, types=["single", "true_false", "short"], difficulty="mixed", options=4)


def run_exam(db: sqlite3.Connection, data_dir: Path, subject: str) -> dict:
    eid = exams_svc.create_exam(db, "local", subject, "Bench", CFG, Scope(subject_id=subject))
    job = dict(db.execute("SELECT j.* FROM jobs j JOIN exams e ON e.job_id = j.id WHERE e.id = ?",
                          (eid,)).fetchone())
    db.execute("UPDATE jobs SET status = 'done' WHERE type = 'index_source'")
    t0 = time.monotonic()
    while True:
        try:
            handlers.generate_exam(handlers.JobContext(job=job, db=db, data_dir=data_dir))
            break
        except handlers.Yielded:
            job = dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone())
    seconds = round(time.monotonic() - t0)
    exam = dict(db.execute("SELECT * FROM exams WHERE id = ?", (eid,)).fetchone())
    qs = exams_svc.questions(db, eid, kept_only=False)
    ev = exams_svc.evidence(db, [q["id"] for q in qs])
    literal = 0
    out = []
    for q in qs:
        rows = db.execute(
            "SELECT e.quote, e.char_start, e.char_end, g.text FROM exam_question_evidence e"
            " JOIN segments g ON g.id = e.segment_id WHERE e.question_id = ?", (q["id"],)
        ).fetchall()
        ok = bool(rows) and all(r["text"][r["char_start"]:r["char_end"]] == r["quote"] for r in rows)
        literal += ok
        out.append({
            "kept": bool(q["kept"]),
            "type": q["type"],
            "difficulty": q["difficulty"],
            "stem": q["stem"],
            "options": json.loads(q["options_json"]),
            "answer": json.loads(q["answer_json"]),
            "rubric": json.loads(q["rubric_json"]),
            "justification": q["justification"],
            "evidence": [e["quote"] for e in ev[q["id"]]],
            "source": ev[q["id"]][0]["source_title"] if ev[q["id"]] else None,
            "literal": ok,
        })
    stats = json.loads(exam["stats_json"])
    calls = db.execute(
        "SELECT task, COUNT(*), SUM(duration_ms), MAX(loaded_mb) FROM model_runs"
        " WHERE job_id = ? GROUP BY task", (job["id"],)
    ).fetchall()
    return {
        "status": exam["status"],
        "available": exam["available"],
        "saved": len(qs),
        "kept": sum(q["kept"] for q in qs),
        "literal_evidence": f"{literal}/{len(qs)}",
        "seconds": seconds,
        "stats": {k: stats.get(k) for k in ("batches", "batches_used", "proposed", "valid", "rejected")},
        "calls": {r[0]: {"n": r[1], "ms": r[2], "max_loaded_mb": r[3]} for r in calls},
        "types": {t: sum(1 for q in out if q["kept"] and q["type"] == t) for t in CFG.types},
        "questions": out,
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        migrate(data_dir / "b.db", data_dir / "backups")
        db = connect(data_dir / "b.db")
        db.execute("INSERT INTO subjects(id, owner_id, name) VALUES ('A', 'local', 'Ingeniería')")
        by_topic: dict[str, list[str]] = defaultdict(list)
        for p in CORPUS["paragraphs"]:
            by_topic[p["topic"]].append(p["text"])
        for topic, paras in by_topic.items():
            src_svc.create_text_source(db, "A", "paste", topic, f"# {topic}\n\n" + "\n\n".join(paras), [], [])
        result = {"corpus": run_exam(db, data_dir, "A")}
        print("corpus:", json.dumps({k: v for k, v in result["corpus"].items() if k != "questions"},
                                     ensure_ascii=False))
        (ROOT / "results" / "exam.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        if "--real" in sys.argv:
            src = sqlite3.connect(f"file:{sys.argv[sys.argv.index('--real') + 1]}?mode=ro", uri=True)
            kind, title, text = src.execute(
                """SELECT s.kind, s.title, v.text FROM sources s JOIN source_versions v
                   ON v.source_id = s.id AND v.version = (SELECT MAX(version) FROM source_versions
                   WHERE source_id = s.id) WHERE s.kind = 'recording' ORDER BY v.char_count DESC
                   LIMIT 1"""
            ).fetchone()
            src.close()
            db.execute("INSERT INTO subjects(id, owner_id, name) VALUES ('R', 'local', 'Real')")
            src_svc.create_text_source(db, "R", kind, title, text, [], [])
            real = run_exam(db, data_dir, "R")
            print("real:", json.dumps({k: v for k, v in real.items() if k != "questions"},
                                       ensure_ascii=False))
            # Contenido de las clases del usuario: solo en el scratchpad, nunca en el repositorio.
            Path(sys.argv[sys.argv.index("--out") + 1]).write_text(
                json.dumps(real, ensure_ascii=False, indent=2)
            )
        db.close()


if __name__ == "__main__":
    main()
