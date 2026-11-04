"""Fase 5: troceo, índice (FTS + vectores), ámbito y búsqueda híbrida."""

import hashlib
import math
import re
import sqlite3
import uuid
from collections.abc import Iterator

import pytest

from app.core.config import Settings
from app.db.connection import connect, tx
from app.llm.base import LLMError, LoadedModel, RuntimeInfo
from app.rag import index, search
from app.rag.chunking import MAX, chunk_segments
from app.rag.scope import Scope
from app.services import sources as src_svc

WORD = re.compile(r"\w+")
DIM = 128


def bow(text: str) -> list[float]:
    """Vector de bolsa de palabras: textos con palabras en común quedan cerca (coseno)."""
    v = [0.0] * DIM
    for w in WORD.findall(text.lower()):
        if len(w) > 3:
            v[int(hashlib.md5(w[:6].encode()).hexdigest(), 16) % DIM] += 1.0  # noqa: S324
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeEmbedder:
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def info(self) -> RuntimeInfo:
        return RuntimeInfo(running=True, version="t", models=[index.EMBED_MODEL])

    def loaded(self) -> list[LoadedModel]:
        return []

    def unload(self, model: str) -> None:
        pass

    def chat(self, *a: object, **k: object) -> object:
        raise AssertionError("chat no esperado")

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise LLMError("llm_unavailable", "Ollama no responde")
        self.calls.append(texts)
        return [bow(t.removeprefix(index.QUERY_PREFIX)) for t in texts]


@pytest.fixture
def db(settings: Settings) -> Iterator[sqlite3.Connection]:
    conn = connect(settings.db_path)
    yield conn
    conn.close()


def make_subject(db: sqlite3.Connection, name: str, owner: str = "local") -> str:
    sid = str(uuid.uuid4())
    db.execute("INSERT INTO subjects(id, owner_id, name) VALUES (?,?,?)", (sid, owner, name))
    return sid


def make_unit(db: sqlite3.Connection, subject: str, parent: str | None = None) -> str:
    uid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO units(id, subject_id, parent_id, kind, title) VALUES (?,?,?, 'topic', 'T')",
        (uid, subject, parent),
    )
    return uid


def add(db: sqlite3.Connection, subject: str, title: str, text: str, units: list[str] = []) -> str:  # noqa: B006
    return src_svc.create_text_source(db, subject, "paste", title, text, units, [])


def run_index(db: sqlite3.Connection, provider: object, memory: int = 99_999) -> None:
    for (sid,) in db.execute(
        "SELECT json_extract(payload_json, '$.source_id') FROM jobs"
        " WHERE type = 'index_source' AND status = 'queued'"
    ).fetchall():
        index.index_source(db, sid, provider, memory=lambda: memory)  # type: ignore[arg-type]
    db.execute("UPDATE jobs SET status = 'done' WHERE type = 'index_source'")


def ids(db: sqlite3.Connection, res: search.SearchResult) -> set[str]:
    return {h.source_id for h in res.hits}


# ------------------------------------------------------------------ troceo
def seg(o: int, text: str, kind: str = "paragraph", **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "ordinal": o,
        "kind": kind,
        "text": text,
        "page": None,
        "start_ms": None,
        "end_ms": None,
        "section_path": None,
    }
    return {**base, **kw}


def test_chunks_keep_location_and_break_at_headings() -> None:
    segs = [
        seg(0, "Tema 1", "heading", page=1, section_path="Tema 1"),
        seg(1, "a" * 600, page=1, section_path="Tema 1"),
        seg(2, "b" * 600, page=2, section_path="Tema 1"),
        seg(3, "Tema 2", "heading", page=3, section_path="Tema 2"),
        seg(4, "c" * 300, page=3, section_path="Tema 2"),
    ]
    chunks = chunk_segments(segs)
    assert [(c.seg_from, c.seg_to) for c in chunks] == [(0, 2), (3, 4)]
    assert (chunks[0].page_from, chunks[0].page_to) == (1, 2)
    assert chunks[1].text.startswith("Tema 2")  # el título va con su contenido
    assert chunks[1].section_path == "Tema 2"


def test_chunks_limit_size_and_audio_span() -> None:
    long = [seg(i, "x" * 500) for i in range(10)]
    assert all(len(c.text) <= MAX for c in chunk_segments(long))
    speech = [
        seg(i, f"frase {i}", start_ms=i * 30_000, end_ms=i * 30_000 + 29_000) for i in range(10)
    ]
    chunks = chunk_segments(speech)
    assert len(chunks) > 1
    assert all(c.end_ms - c.start_ms <= 150_000 for c in chunks)  # type: ignore[operator]
    assert chunks[0].start_ms == 0 and chunks[-1].end_ms == 9 * 30_000 + 29_000


def test_empty_segments_are_skipped() -> None:
    assert chunk_segments([seg(0, "   "), seg(1, "")]) == []


# ------------------------------------------------------------------ índice
def test_new_version_is_indexed_and_old_one_replaced(db: sqlite3.Connection) -> None:
    s = make_subject(db, "Bio")
    sid = add(db, s, "Célula", "La mitocondria produce energía para la célula.")
    run_index(db, FakeEmbedder())
    st = db.execute("SELECT * FROM source_index WHERE source_id = ?", (sid,)).fetchone()
    assert (st["status"], st["chunks"], st["embedded"]) == ("ready", 1, 1)

    with tx(db):
        src_svc.add_version(db, sid, "El ribosoma fabrica proteínas.", "user_edit")
    run_index(db, FakeEmbedder())
    texts = [r[0] for r in db.execute("SELECT text FROM chunks WHERE source_id = ?", (sid,))]
    assert texts == ["El ribosoma fabrica proteínas."]
    # El índice de palabras sigue al contenido (triggers): lo viejo ya no se encuentra.
    assert search.search(db, "local", Scope(), "mitocondria", None).hits == []
    assert ids(db, search.search(db, "local", Scope(), "ribosoma", None)) == {sid}


def test_enqueue_is_deduplicated(db: sqlite3.Connection) -> None:
    s = make_subject(db, "Bio")
    sid = add(db, s, "A", "uno")
    with tx(db):
        src_svc.add_version(db, sid, "dos", "user_edit")
    n = db.execute("SELECT COUNT(*) FROM jobs WHERE type = 'index_source'").fetchone()[0]
    assert n == 1
    job = db.execute("SELECT source_id FROM jobs WHERE type = 'index_source'").fetchone()
    assert job["source_id"] is None  # indexar no cambia el estado visible de la fuente


def test_without_embeddings_search_by_words(db: sqlite3.Connection) -> None:
    s = make_subject(db, "Bio")
    sid = add(db, s, "A", "La fotosíntesis ocurre en los cloroplastos.")
    run_index(db, FakeEmbedder(fail=True))
    st = db.execute("SELECT * FROM source_index WHERE source_id = ?", (sid,)).fetchone()
    assert (st["status"], st["embedded"]) == ("ready", 0)
    assert "solo búsqueda por palabras" in st["error"]
    res = search.search(db, "local", Scope(), "¿Dónde ocurre la fotosintesis?", FakeEmbedder(True))
    assert ids(db, res) == {sid} and res.mode == "fts" and res.relevant


def test_low_memory_skips_vectors(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(index, "MAX_WAIT_S", 0.0)
    s = make_subject(db, "Bio")
    sid = add(db, s, "A", "texto de prueba")
    emb = FakeEmbedder()
    run_index(db, emb, memory=100)
    assert emb.calls == []
    st = db.execute(
        "SELECT embedded, error FROM source_index WHERE source_id = ?", (sid,)
    ).fetchone()
    assert st["embedded"] == 0 and "memoria" in st["error"]


def test_delete_source_cascades_to_index(db: sqlite3.Connection) -> None:
    s = make_subject(db, "Bio")
    sid = add(db, s, "A", "La meiosis produce gametos.")
    run_index(db, FakeEmbedder())
    db.execute("DELETE FROM sources WHERE id = ?", (sid,))
    assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] == 0
    fts = db.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'meiosis'")
    assert fts.fetchone()[0] == 0


def test_chunk_cannot_belong_to_other_subject(db: sqlite3.Connection) -> None:
    a, b = make_subject(db, "A"), make_subject(db, "B")
    sid = add(db, a, "A", "texto")
    ver = db.execute("SELECT id FROM source_versions WHERE source_id = ?", (sid,)).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="chunk_other_subject"):
        db.execute(
            "INSERT INTO chunks(source_id, version_id, subject_id, ordinal, text, seg_from,"
            " seg_to) VALUES (?,?,?,99,'x',0,0)",
            (sid, ver, b),
        )


def test_backfill_finds_missing_and_stale(db: sqlite3.Connection) -> None:
    s = make_subject(db, "Bio")
    a = add(db, s, "A", "uno")
    b = add(db, s, "B", "dos")
    run_index(db, FakeEmbedder())
    assert index.backfill(db) == 0
    db.execute("DELETE FROM source_index WHERE source_id = ?", (a,))
    db.execute("UPDATE source_index SET status = 'indexing' WHERE source_id = ?", (b,))
    assert index.backfill(db) == 2


# ------------------------------------------------------------------ ámbito y búsqueda
@pytest.fixture
def library(db: sqlite3.Connection) -> dict[str, str]:
    bio, his = make_subject(db, "Biología"), make_subject(db, "Historia")
    other_user = "intruso"
    db.execute("INSERT INTO users(id, display_name) VALUES (?, 'Otro')", (other_user,))
    foreign = make_subject(db, "Ajena", owner=other_user)
    t1 = make_unit(db, bio)
    t1a = make_unit(db, bio, parent=t1)
    out = {
        "bio": bio,
        "his": his,
        "t1": t1,
        "cell": add(db, bio, "Célula", "La mitocondria produce la energía de la célula.", [t1a]),
        "dna": add(db, bio, "ADN", "El ADN se replica antes de la división celular."),
        "rev": add(db, his, "Revolución", "La revolución francesa empezó en 1789 con la toma."),
        "secret": add(db, foreign, "Privado", "La mitocondria secreta del otro usuario."),
    }
    run_index(db, FakeEmbedder())
    return out


def test_scope_subject_never_leaks(db: sqlite3.Connection, library: dict[str, str]) -> None:
    emb = FakeEmbedder()
    for q in ("mitocondria energía", "revolución francesa 1789", "ADN división"):
        found = ids(db, search.search(db, "local", Scope(subject_id=library["his"]), q, emb))
        assert found <= {library["rev"]}
        found = ids(db, search.search(db, "local", Scope(subject_id=library["bio"]), q, emb))
        assert found <= {library["cell"], library["dna"]}


def test_scope_never_crosses_users(db: sqlite3.Connection, library: dict[str, str]) -> None:
    emb = FakeEmbedder()
    res = search.search(db, "local", Scope(), "mitocondria secreta usuario", emb)
    assert library["secret"] not in ids(db, res)
    # Ni pidiendo su asignatura o su fuente explícitamente.
    foreign = db.execute("SELECT subject_id FROM sources WHERE id = ?", (library["secret"],))
    scope = Scope(subject_id=foreign.fetchone()[0], source_ids=[library["secret"]])
    assert search.search(db, "local", scope, "mitocondria", emb).hits == []


def test_scope_sources_units_and_exclusions(
    db: sqlite3.Connection, library: dict[str, str]
) -> None:
    emb = FakeEmbedder()
    q = "célula"
    by_unit = search.search(db, "local", Scope(unit_ids=[library["t1"]]), q, emb)
    assert ids(db, by_unit) == {library["cell"]}  # vinculada a una subunidad del tema
    only = search.search(db, "local", Scope(source_ids=[library["dna"]]), q, emb)
    assert ids(db, only) == {library["dna"]}
    excl = Scope(subject_id=library["bio"], exclude_source_ids=[library["cell"]])
    assert library["cell"] not in ids(db, search.search(db, "local", excl, q, emb))


def test_hybrid_ranks_and_flags_irrelevant(db: sqlite3.Connection, library: dict[str, str]) -> None:
    emb = FakeEmbedder()
    res = search.search(db, "local", Scope(), "¿Qué produce la mitocondria?", emb)
    assert res.mode == "hybrid" and res.relevant
    assert res.hits[0].source_id == library["cell"]
    assert res.hits[0].fts_rank == 1 and res.hits[0].vec_rank == 1
    off = search.search(db, "local", Scope(), "pingüinos antárticos nadando", emb)
    assert not off.relevant


def test_fts_query_is_safe() -> None:
    assert search.fts_query("¿Qué es la célula?") == '"celula"'
    assert search.fts_query("de la que") is None
    q = search.fts_query('mitocondrias" OR 1=1) NEAR(* -- ')
    assert q is not None and '""' not in q and "NEAR" not in q


def test_short_unknown_words_are_also_searched_as_acronyms(
    db: sqlite3.Connection, library: dict[str, str]
) -> None:
    # «adn» existe en las fuentes (no cambia); «vuca» no aparece tal cual → posible sigla.
    assert search.acronym_variant(db, "¿qué es vuca y el adn?") == "¿qué es VUCA y el adn?"
    assert search.acronym_variant(db, "Vuca") == "VUCA"
    assert search.acronym_variant(db, "VUCA") == "VUCA"

    class CaseSensitive(FakeEmbedder):
        """Como el modelo real: la sigla en minúsculas no se parece a su texto."""

        def embed(self, model: str, texts: list[str]) -> list[list[float]]:
            q = [t.removeprefix(index.QUERY_PREFIX) for t in texts]
            return [bow("biuca volatilidad" if t.isupper() else "zzzz qqqq") for t in q]

    s = make_subject(db, "Economía")
    sid = add(db, s, "Entorno", "La palabra biuca: volatilidad, incertidumbre, complejidad.")
    run_index(db, FakeEmbedder())
    res = search.search(db, "local", Scope(subject_id=s), "vuca", CaseSensitive())
    assert ids(db, res) == {sid} and "acronym_variant" in res.notes
