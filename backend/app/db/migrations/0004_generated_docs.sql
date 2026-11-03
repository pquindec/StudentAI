-- 0004: apuntes y resúmenes generados por IA local, con citas trazables a segmentos concretos
-- (versión de la fuente + ordinal), y registro de cada ejecución de un modelo.

CREATE TABLE generated_docs (
    id            TEXT PRIMARY KEY,
    subject_id    TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('notes', 'summary')),
    detail        TEXT NOT NULL CHECK (detail IN ('brief', 'medium', 'detailed')),
    title         TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 300),
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'running', 'ready', 'failed', 'cancelled')),
    -- Documento estructurado: apartados → puntos → referencias de cita (ver generation/).
    content_json  TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(content_json)),
    model         TEXT,
    job_id        TEXT REFERENCES jobs (id) ON DELETE SET NULL,
    error_code    TEXT,
    error_message TEXT,
    -- Métricas de validación: citas propuestas por el modelo que no existían (se descartan).
    stats_json    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_generated_docs_subject ON generated_docs (subject_id, created_at);

-- Fuentes usadas (todas de la misma asignatura que el documento).
CREATE TABLE generated_doc_sources (
    doc_id     TEXT NOT NULL REFERENCES generated_docs (id) ON DELETE CASCADE,
    source_id  TEXT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES source_versions (id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    PRIMARY KEY (doc_id, source_id)
);

CREATE TRIGGER generated_doc_sources_same_subject
BEFORE INSERT ON generated_doc_sources
WHEN (SELECT subject_id FROM sources WHERE id = NEW.source_id) IS NOT
     (SELECT subject_id FROM generated_docs WHERE id = NEW.doc_id)
BEGIN
    SELECT RAISE(ABORT, 'doc_source_other_subject');
END;

-- Cada cita apunta a un segmento existente. `ref` es el número que se muestra ([1], [2]…).
CREATE TABLE generated_doc_citations (
    doc_id     TEXT NOT NULL REFERENCES generated_docs (id) ON DELETE CASCADE,
    ref        INTEGER NOT NULL,
    segment_id INTEGER NOT NULL REFERENCES segments (id) ON DELETE CASCADE,
    PRIMARY KEY (doc_id, ref)
);

CREATE TABLE model_runs (
    id            INTEGER PRIMARY KEY,
    job_id        TEXT REFERENCES jobs (id) ON DELETE SET NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    task          TEXT NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    duration_ms   INTEGER NOT NULL,
    loaded_mb     INTEGER,          -- tamaño del modelo cargado según el runtime (/api/ps)
    cloud         INTEGER NOT NULL DEFAULT 0 CHECK (cloud IN (0, 1)),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_model_runs_created ON model_runs (created_at);
