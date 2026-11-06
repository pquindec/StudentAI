"""Búsqueda híbrida: palabras (FTS5 / BM25) + significado (vectores) fusionadas con RRF.

Ambas consultas llevan el filtro de ámbito en SQL, así que un resultado fuera del ámbito no
puede llegar ni siquiera a la fusión.
"""

import logging
import re
import sqlite3
from dataclasses import dataclass, field

from app.llm.base import LLMError, LLMProvider
from app.rag.index import EMBED_MODEL, QUERY_PREFIX, pack
from app.rag.scope import Scope, scope_sql

log = logging.getLogger(__name__)

RRF_K = 60
CANDIDATES = 30
TOP_K = 6
# Por encima de esta distancia coseno, un resultado solo por significado no cuenta como
# relevante (si además no coincide ninguna palabra, la respuesta es «no encontrado»).
VEC_GATE = 0.55

STOPWORDS = frozenset(
    """a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada cual cuales
    cuando cuanto como con contra cual de del desde donde dos el ella ellas ellos en entre era
    eres es esa esas ese eso esos esta estas este esto estos fue fueron ha han hasta hay la las
    le les lo los mas me mi mis mucho muy nada ni no nos o otra otras otro otros para pero poco
    por porque que quien quienes se sea segun ser si sin sobre son su sus tambien tan te tiene
    tienen todo todos tu tus un una unas uno unos ya y yo explica explicame dime cual cuales
    significa define definicion the of and to in is what""".split()  # noqa: SIM905
)
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Hit:
    chunk_id: int
    source_id: str
    score: float
    fts_rank: int | None = None
    vec_rank: int | None = None
    distance: float | None = None


@dataclass
class SearchResult:
    hits: list[Hit]
    mode: str  # hybrid | fts | none
    relevant: bool  # hay al menos un resultado que pasa el umbral
    notes: list[str] = field(default_factory=list)


def fold(text: str) -> str:
    table = str.maketrans("áéíóúüàèìòùñç", "aeiouuaeiounc")
    return text.lower().translate(table)


def fts_query(question: str) -> str | None:
    """Palabras significativas entre comillas unidas con OR; las largas, también por prefijo
    (plural, género: «célula» encuentra «células»)."""
    terms: list[str] = []
    for w in _WORD.findall(fold(question)):
        if w in STOPWORDS or (len(w) < 3 and not w.isdigit()):
            continue
        terms.append(f'"{w}"')
        if len(w) >= 7:
            terms.append(f'"{w[:-2]}"*')
    return " OR ".join(dict.fromkeys(terms)) or None


_SHORT = re.compile(r"\b[^\W\d_]{2,6}\b", re.UNICODE)


def acronym_variant(db: sqlite3.Connection, question: str) -> str:
    """El modelo de embeddings distingue mayúsculas: «vuca» y «VUCA» dan vectores distintos.
    Las palabras cortas que no aparecen tal cual en ninguna fuente (posibles siglas, o términos
    que la transcripción escribió de otra forma) se prueban también en mayúsculas."""

    def up(m: re.Match[str]) -> str:
        w = m.group(0)
        f = fold(w)
        if w.isupper() or f in STOPWORDS:
            return w
        found = db.execute(
            "SELECT 1 FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT 1", (f'"{f}"',)
        ).fetchone()
        return w if found else w.upper()

    return _SHORT.sub(up, question)


def load_vec(db: sqlite3.Connection) -> bool:
    """Carga sqlite-vec en esta conexión. False si no es posible (se busca solo por palabras)."""
    try:
        db.execute("SELECT vec_version()")
        return True
    except sqlite3.OperationalError:
        pass
    try:
        import sqlite_vec  # type: ignore[import-untyped]

        db.enable_load_extension(True)
        try:
            sqlite_vec.load(db)
        finally:
            db.enable_load_extension(False)
        return True
    except (AttributeError, ImportError, sqlite3.Error) as e:
        log.warning("sqlite-vec no disponible: %s", e)
        return False


def _fts(db: sqlite3.Connection, query: str, where: str, params: list[object]) -> list[int]:
    rows = db.execute(
        f"""SELECT c.id FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ? AND {where}
            ORDER BY bm25(chunks_fts) LIMIT {CANDIDATES}""",  # noqa: S608 (solo marcadores)
        [query, *params],
    ).fetchall()
    return [int(r[0]) for r in rows]


def _vec(
    db: sqlite3.Connection, vector: bytes, where: str, params: list[object]
) -> list[tuple[int, float]]:
    rows = db.execute(
        f"""SELECT c.id, vec_distance_cosine(v.embedding, ?) AS d
            FROM chunk_vectors v JOIN chunks c ON c.id = v.chunk_id
            WHERE v.model = ? AND {where}
            ORDER BY d LIMIT {CANDIDATES}""",  # noqa: S608 (solo marcadores)
        [vector, EMBED_MODEL, *params],
    ).fetchall()
    return [(int(r[0]), float(r[1])) for r in rows]


def search(
    db: sqlite3.Connection,
    owner: str,
    scope: Scope,
    question: str,
    provider: LLMProvider | None,
    top_k: int = TOP_K,
    use_fts: bool = True,
    use_vec: bool = True,
) -> SearchResult:
    where, params = scope_sql(scope, owner)
    notes: list[str] = []
    fts_ids: list[int] = []
    q = fts_query(question)
    if use_fts and q:
        fts_ids = _fts(db, q, where, params)

    vec_lists: list[list[tuple[int, float]]] = []
    if use_vec and provider is not None:
        if not load_vec(db):
            notes.append("vec_unavailable")
        else:
            queries = [question]
            variant = acronym_variant(db, question)
            if variant != question:
                queries.append(variant)
                notes.append("acronym_variant")
            try:
                vectors = provider.embed(EMBED_MODEL, [QUERY_PREFIX + q for q in queries])
                vec_lists = [_vec(db, pack(v), where, params) for v in vectors]
            except LLMError as e:
                notes.append(f"embed_failed:{e.code}")
    vec_hits = [h for lst in vec_lists for h in lst]

    hits: dict[int, Hit] = {}
    for rank, cid in enumerate(fts_ids, 1):
        hits[cid] = Hit(cid, "", 1 / (RRF_K + rank), fts_rank=rank)
    for lst in vec_lists:
        for rank, (cid, dist) in enumerate(lst, 1):
            h = hits.setdefault(cid, Hit(cid, "", 0.0))
            h.score += 1 / (RRF_K + rank)
            if h.distance is None or dist < h.distance:
                h.vec_rank, h.distance = rank, dist
    top = sorted(hits.values(), key=lambda h: -h.score)[:top_k]
    if top:
        marks = ",".join("?" * len(top))
        owners = dict(
            db.execute(
                f"SELECT id, source_id FROM chunks WHERE id IN ({marks})",  # noqa: S608
                [h.chunk_id for h in top],
            ).fetchall()
        )
        for h in top:
            h.source_id = owners[h.chunk_id]
    relevant = bool(fts_ids) or any(d <= VEC_GATE for _, d in vec_hits)
    mode = "hybrid" if vec_hits else ("fts" if fts_ids else "none")
    return SearchResult(top, mode, relevant and bool(top), notes)


def from_chunks(db: sqlite3.Connection, chunk_ids: list[int]) -> SearchResult:
    """Resultado fijado de antemano (los fragmentos aprobados en un consentimiento), en orden."""
    marks = ",".join("?" * len(chunk_ids)) or "NULL"
    src = dict(
        db.execute(
            f"SELECT id, source_id FROM chunks WHERE id IN ({marks})",  # noqa: S608
            chunk_ids,
        ).fetchall()
    )
    hits = [Hit(c, str(src[c]), 0.0) for c in chunk_ids if c in src]
    return SearchResult(hits, "approved", bool(hits), [])
