-- 0002: fuentes de conocimiento, versiones de texto, segmentos localizables, vínculos y cola
-- de trabajos persistente.

CREATE TABLE sources (
    id             TEXT PRIMARY KEY,
    subject_id     TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN (
                       'recording', 'audio', 'pdf', 'docx', 'txt', 'md', 'rtf', 'csv',
                       'paste', 'note')),
    title          TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 300),
    original_name  TEXT,
    stored_path    TEXT,          -- relativo a la carpeta de datos; NULL para texto pegado
    sha256         TEXT,
    mime           TEXT,
    size_bytes     INTEGER,
    duration_ms    INTEGER,
    page_count     INTEGER,
    language       TEXT,
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'processing', 'ready', 'failed', 'cancelled')),
    error_code     TEXT,
    error_message  TEXT,
    needs_review   INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0, 1)),
    metadata_json  TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    imported_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    processed_at   TEXT,
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_sources_subject ON sources (subject_id, status, imported_at);
-- El mismo archivo no se importa dos veces en la misma asignatura.
CREATE UNIQUE INDEX uq_sources_subject_sha ON sources (subject_id, sha256) WHERE sha256 IS NOT NULL;

-- Una fuente se vincula a N unidades (curso/módulo/tema) o sesiones de SU asignatura.
CREATE TABLE source_links (
    id         INTEGER PRIMARY KEY,
    source_id  TEXT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    unit_id    TEXT REFERENCES units (id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions (id) ON DELETE CASCADE,
    CHECK ((unit_id IS NULL) <> (session_id IS NULL))
);
CREATE UNIQUE INDEX uq_source_links_unit ON source_links (source_id, unit_id) WHERE unit_id IS NOT NULL;
CREATE UNIQUE INDEX uq_source_links_session ON source_links (source_id, session_id) WHERE session_id IS NOT NULL;
CREATE INDEX idx_source_links_unit ON source_links (unit_id);
CREATE INDEX idx_source_links_session ON source_links (session_id);

CREATE TRIGGER source_links_same_subject
BEFORE INSERT ON source_links
WHEN (NEW.unit_id IS NOT NULL AND
      (SELECT subject_id FROM units WHERE id = NEW.unit_id) IS NOT
      (SELECT subject_id FROM sources WHERE id = NEW.source_id))
  OR (NEW.session_id IS NOT NULL AND
      (SELECT subject_id FROM sessions WHERE id = NEW.session_id) IS NOT
      (SELECT subject_id FROM sources WHERE id = NEW.source_id))
BEGIN
    SELECT RAISE(ABORT, 'link_other_subject');
END;

-- Cada extracción o edición del usuario crea una versión nueva (nunca se sobrescribe).
CREATE TABLE source_versions (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    version     INTEGER NOT NULL CHECK (version >= 1),
    origin      TEXT NOT NULL CHECK (origin IN ('extracted', 'transcribed', 'user_edit', 'pasted')),
    text        TEXT NOT NULL,
    char_count  INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_id, version)
);

-- Unidad mínima localizable: título, párrafo o tabla con su página/sección/tiempo.
CREATE TABLE segments (
    id            INTEGER PRIMARY KEY,
    version_id    TEXT NOT NULL REFERENCES source_versions (id) ON DELETE CASCADE,
    ordinal       INTEGER NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('heading', 'paragraph', 'table', 'list')),
    level         INTEGER,
    text          TEXT NOT NULL,
    page          INTEGER,
    section_path  TEXT,
    start_ms      INTEGER,
    end_ms        INTEGER,
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    UNIQUE (version_id, ordinal)
);

CREATE TABLE jobs (
    id               TEXT PRIMARY KEY,
    type             TEXT NOT NULL,
    resource_class   TEXT NOT NULL CHECK (resource_class IN ('io', 'media', 'stt', 'llm', 'embed')),
    priority         INTEGER NOT NULL DEFAULT 50,
    status           TEXT NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
    source_id        TEXT REFERENCES sources (id) ON DELETE CASCADE,
    payload_json     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
    progress         REAL NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
    message          TEXT,
    attempts         INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    error_code       TEXT,
    error_message    TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at       TEXT,
    finished_at      TEXT
);
CREATE INDEX idx_jobs_queue ON jobs (status, priority DESC, created_at);
CREATE INDEX idx_jobs_source ON jobs (source_id);
