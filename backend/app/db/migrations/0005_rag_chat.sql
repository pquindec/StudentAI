-- 0005: búsqueda en las fuentes (RAG) y asistente.
-- Chunks: trozos de ~1.000 caracteres de la versión actual de cada fuente, con su localización.
-- FTS5 (palabras) y vectores (significado) se filtran por el mismo ámbito en SQL (ADR-006).

CREATE TABLE chunks (
    id           INTEGER PRIMARY KEY,
    source_id    TEXT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    version_id   TEXT NOT NULL REFERENCES source_versions (id) ON DELETE CASCADE,
    subject_id   TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    ordinal      INTEGER NOT NULL,
    text         TEXT NOT NULL,
    seg_from     INTEGER NOT NULL,   -- ordinales de los segmentos que abarca
    seg_to       INTEGER NOT NULL,
    page_from    INTEGER,
    page_to      INTEGER,
    start_ms     INTEGER,
    end_ms       INTEGER,
    section_path TEXT,
    UNIQUE (version_id, ordinal)
);
CREATE INDEX idx_chunks_subject ON chunks (subject_id);
CREATE INDEX idx_chunks_source ON chunks (source_id);

CREATE TRIGGER chunks_same_subject
BEFORE INSERT ON chunks
WHEN NEW.subject_id IS NOT (SELECT subject_id FROM sources WHERE id = NEW.source_id)
BEGIN
    SELECT RAISE(ABORT, 'chunk_other_subject');
END;

-- Índice de texto completo sin acentos (contenido externo: el texto vive en `chunks`).
CREATE VIRTUAL TABLE chunks_fts USING fts5 (
    text, content = 'chunks', content_rowid = 'id', tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER chunks_fts_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts (rowid, text) VALUES (NEW.id, NEW.text);
END;
CREATE TRIGGER chunks_fts_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', OLD.id, OLD.text);
END;

-- Vectores float32 (tabla normal: el borrado en cascada no depende de la extensión).
CREATE TABLE chunk_vectors (
    chunk_id  INTEGER PRIMARY KEY REFERENCES chunks (id) ON DELETE CASCADE,
    model     TEXT NOT NULL,
    embedding BLOB NOT NULL
);

-- Estado del índice por fuente.
CREATE TABLE source_index (
    source_id  TEXT PRIMARY KEY REFERENCES sources (id) ON DELETE CASCADE,
    version_id TEXT,
    status     TEXT NOT NULL CHECK (status IN ('queued', 'indexing', 'ready', 'failed')),
    chunks     INTEGER NOT NULL DEFAULT 0,
    embedded   INTEGER NOT NULL DEFAULT 0,  -- chunks con vector (0 = solo búsqueda por palabras)
    model      TEXT,
    error      TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Asistente: conversaciones con su ámbito, mensajes y citas a segmentos concretos.
CREATE TABLE chat_threads (
    id         TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    subject_id TEXT REFERENCES subjects (id) ON DELETE CASCADE,  -- NULL = toda la biblioteca
    title      TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 300),
    scope_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(scope_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_chat_threads_owner ON chat_threads (owner_id, updated_at);

CREATE TABLE chat_messages (
    id         TEXT PRIMARY KEY,
    thread_id  TEXT NOT NULL REFERENCES chat_threads (id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'done'
               CHECK (status IN ('queued', 'streaming', 'done', 'not_found', 'failed', 'cancelled')),
    error      TEXT,
    model      TEXT,
    job_id     TEXT REFERENCES jobs (id) ON DELETE SET NULL,
    stats_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_chat_messages_thread ON chat_messages (thread_id, created_at);

CREATE TABLE chat_message_citations (
    message_id TEXT NOT NULL REFERENCES chat_messages (id) ON DELETE CASCADE,
    ref        INTEGER NOT NULL,
    segment_id INTEGER NOT NULL REFERENCES segments (id) ON DELETE CASCADE,
    PRIMARY KEY (message_id, ref)
);
