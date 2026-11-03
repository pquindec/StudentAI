"""Benchmark de embeddings + recuperación (semántica, BM25 e híbrida RRF).

Uso: .venv/bin/python bench_embed.py
"""
import json
import math
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).parent
OUT = ROOT / "results"
API = "http://localhost:11434/api"
client = httpx.Client(timeout=600)

CORPUS = json.loads((ROOT / "corpus" / "es_corpus.json").read_text())
DOCS = [(p["id"], p["text"]) for p in CORPUS["paragraphs"]]
# párrafos en inglés como ruido adicional
DOCS += [(f"en{i}", t) for i, t in enumerate((ROOT / "corpus" / "en_lecture.txt").read_text().split("\n\n"))]
QS = CORPUS["questions"]

MODELS = {
    "qwen3-embedding:0.6b": ("Instruct: Dada una pregunta de un estudiante, recupera el pasaje que la responde\nQuery: ", ""),
    "embeddinggemma": ("task: search result | query: ", "title: none | text: "),
    "bge-m3": ("", ""),
}
STOP = set("el la los las de del un una y o en que es por con para se su sus al lo como a no".split())


def tok(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [w for w in re.findall(r"\w+", s) if w not in STOP]


def bm25_rank(q, k1=1.5, b=0.75):
    docs = [tok(t) for _, t in DOCS]
    avg = sum(map(len, docs)) / len(docs)
    df = Counter(w for d in docs for w in set(d))
    n = len(docs)
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for w in tok(q):
            if w in tf:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return list(np.argsort(scores)[::-1])


def embed(model, texts):
    r = client.post(f"{API}/embed", json={"model": model, "input": texts, "keep_alive": "2m"})
    r.raise_for_status()
    v = np.array(r.json()["embeddings"], dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def rrf(*rankings, k=60):
    score = Counter()
    for rank in rankings:
        for pos, idx in enumerate(rank):
            score[idx] += 1 / (k + pos + 1)
    return [i for i, _ in score.most_common()]


def metrics(rankings):
    ids = [d for d, _ in DOCS]
    r1 = r3 = r5 = mrr = 0
    for q, rank in zip(QS, rankings):
        pos = [ids[i] for i in rank].index(q["answer"]) + 1
        r1 += pos <= 1
        r3 += pos <= 3
        r5 += pos <= 5
        mrr += 1 / pos
    n = len(QS)
    return {"recall@1": round(r1 / n, 3), "recall@3": round(r3 / n, 3), "recall@5": round(r5 / n, 3), "mrr": round(mrr / n, 3)}


if __name__ == "__main__":
    bm25 = [bm25_rank(q["q"]) for q in QS]
    results = {"docs": len(DOCS), "questions": len(QS), "bm25": metrics(bm25)}
    for model, (qp, dp) in MODELS.items():
        embed(model, ["calentamiento"])
        t0 = time.perf_counter()
        D = embed(model, [dp + t for _, t in DOCS])
        doc_ms = (time.perf_counter() - t0) * 1000 / len(DOCS)
        Q = embed(model, [qp + q["q"] for q in QS])
        ps = {m["name"]: m["size"] for m in client.get(f"{API}/ps").json()["models"]}
        sem = [list(np.argsort(Q[i] @ D.T)[::-1]) for i in range(len(QS))]
        results[model] = {
            "dim": int(D.shape[1]),
            "ms_per_chunk": round(doc_ms, 1),
            "mem_mb": round(next((v for k, v in ps.items() if k.startswith(model.split(":")[0])), 0) / 2**20),
            "semantic": metrics(sem),
            "hybrid_rrf": metrics([rrf(s, b) for s, b in zip(sem, bm25)]),
        }
        client.post(f"{API}/generate", json={"model": model, "keep_alive": 0})
        print(model, json.dumps(results[model]), flush=True)
    print("bm25", results["bm25"])
    (OUT / "embed.json").write_text(json.dumps(results, indent=2))
