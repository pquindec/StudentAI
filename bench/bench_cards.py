"""Calidad de las tarjetas (Fase 7): mazo de 20 con el modelo local y el pipeline real.

Uso (desde la raíz): backend/.venv/bin/python bench/bench_cards.py [--real DB --out FICHERO]
- Corpus: los párrafos de Ingeniería de Software (un documento por tema).
- --real: además, un mazo sobre la grabación más larga de esa BD (leída en solo lectura y copiada
  a una BD temporal). Las tarjetas reales se guardan solo en --out, NUNCA en bench/results.
Comprueba que el 100 % de las tarjetas guardadas tiene evidencia literal y vuelca las tarjetas
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
from app.generation.docs import Yielded  # noqa: E402
from app.jobs import handlers  # noqa: E402
from app.rag.scope import Scope  # noqa: E402
from app.services import flashcards as cards_svc  # noqa: E402
from app.services import sources as src_svc  # noqa: E402

CORPUS = json.loads((ROOT / "corpus" / "es_corpus.json").read_text())
COUNT = 20


def run_deck(db: sqlite3.Connection, data_dir: Path, subject: str) -> dict:
    did = cards_svc.create_deck(db, "local", subject, "Bench", COUNT, Scope(subject_id=subject))
    job = dict(db.execute("SELECT j.* FROM jobs j JOIN decks d ON d.job_id = j.id WHERE d.id = ?",
                          (did,)).fetchone())
    db.execute("UPDATE jobs SET status = 'done' WHERE type = 'index_source'")
    t0 = time.monotonic()
    while True:
        try:
            handlers.generate_deck(handlers.JobContext(job=job, db=db, data_dir=data_dir))
            break
        except Yielded:
            job = dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone())
    seconds = round(time.monotonic() - t0)
    deck = dict(db.execute("SELECT * FROM decks WHERE id = ?", (did,)).fetchone())
    rows = db.execute(
        "SELECT f.front, f.back, f.quote, f.char_start, f.char_end, g.text FROM flashcards f"
        " JOIN segments g ON g.id = f.segment_id WHERE f.deck_id = ? ORDER BY f.position", (did,)
    ).fetchall()
    cards = [
        {"front": r["front"], "back": r["back"], "evidence": r["quote"],
         "literal": r["text"][r["char_start"]:r["char_end"]] == r["quote"]}
        for r in rows
    ]
    stats = json.loads(deck["stats_json"])
    calls = db.execute(
        "SELECT task, COUNT(*), SUM(duration_ms), MAX(loaded_mb) FROM model_runs"
        " WHERE job_id = ? GROUP BY task", (job["id"],)
    ).fetchall()
    return {
        "status": deck["status"],
        "error": deck["error_message"],
        "saved": len(cards),
        "literal_evidence": f"{sum(c['literal'] for c in cards)}/{len(cards)}",
        "seconds": seconds,
        "stats": {k: stats.get(k) for k in ("batches", "batches_used", "proposed", "valid", "rejected")},
        "calls": {r[0]: {"n": r[1], "ms": r[2], "max_loaded_mb": r[3]} for r in calls},
        "cards": cards,
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
        result = {"corpus": run_deck(db, data_dir, "A")}
        print("corpus:", json.dumps({k: v for k, v in result["corpus"].items() if k != "cards"},
                                     ensure_ascii=False), flush=True)
        (ROOT / "results" / "cards.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
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
            real = run_deck(db, data_dir, "R")
            print("real:", json.dumps({k: v for k, v in real.items() if k != "cards"},
                                       ensure_ascii=False), flush=True)
            # Contenido de las clases del usuario: solo en el scratchpad, nunca en el repositorio.
            Path(sys.argv[sys.argv.index("--out") + 1]).write_text(
                json.dumps(real, ensure_ascii=False, indent=2)
            )
        db.close()


if __name__ == "__main__":
    main()
