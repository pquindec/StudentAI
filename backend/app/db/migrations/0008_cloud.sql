-- Fase 8: consentimientos para enviar datos a Claude y registro de cada envío (auditoría).
-- No se guarda el contenido enviado: solo qué se aprobó, cuánto texto salió y su coste.

CREATE TABLE cloud_consents (
    id           TEXT PRIMARY KEY,
    owner_id     TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('chat', 'docs', 'deck', 'exam')),
    tasks_json   TEXT NOT NULL CHECK (json_valid(tasks_json)),   -- tareas que irán a Claude
    mode         TEXT NOT NULL CHECK (mode IN ('once', 'session')),
    session_id   TEXT,                                           -- arranque del backend
    scope_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(scope_json)),
    via          TEXT NOT NULL CHECK (via IN ('api', 'plan')),
    model        TEXT NOT NULL,
    chars        INTEGER NOT NULL DEFAULT 0,
    est_cost_usd REAL NOT NULL DEFAULT 0,
    max_cost_usd REAL NOT NULL,                                  -- tope de este consentimiento
    job_id       TEXT,                                           -- «una vez»: el trabajo que lo usa
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revoked_at   TEXT
);
CREATE INDEX idx_cloud_consents_owner ON cloud_consents (owner_id, created_at);

CREATE TABLE cloud_requests (
    id            INTEGER PRIMARY KEY,
    owner_id      TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    consent_id    TEXT REFERENCES cloud_consents (id) ON DELETE SET NULL,
    job_id        TEXT,
    kind          TEXT NOT NULL,
    task          TEXT NOT NULL,          -- p. ej. cards:judge
    via           TEXT NOT NULL CHECK (via IN ('api', 'plan')),
    model         TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'blocked')),
    chars_sent    INTEGER NOT NULL DEFAULT 0,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL NOT NULL DEFAULT 0,
    error         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_cloud_requests_owner ON cloud_requests (owner_id, created_at);
