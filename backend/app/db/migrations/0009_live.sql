-- 0009: examen en vivo en el aula (Fase 9.5, ADR-012).
-- Una sala comparte un examen con participantes de la red local. Cada participante admitido
-- tiene su propio intento (exam_attempts), así que la corrección es la de siempre.

CREATE TABLE live_sessions (
    id             TEXT PRIMARY KEY,
    exam_id        TEXT NOT NULL REFERENCES exams (id) ON DELETE CASCADE,
    owner_id       TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    mode           TEXT NOT NULL CHECK (mode IN ('practice', 'graded')),
    code           TEXT NOT NULL CHECK (length(code) BETWEEN 6 AND 16),
    status         TEXT NOT NULL DEFAULT 'lobby'
                   CHECK (status IN ('lobby', 'running', 'finished', 'closed')),
    locked         INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0, 1)),
    show_results   INTEGER NOT NULL DEFAULT 1 CHECK (show_results IN (0, 1)),
    published      INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0, 1)),
    time_limit_min INTEGER CHECK (time_limit_min IS NULL OR time_limit_min BETWEEN 1 AND 240),
    started_at     TEXT,
    ends_at        TEXT,
    finished_at    TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_live_sessions_owner ON live_sessions (owner_id, created_at);
-- Un código solo identifica una sala mientras está abierta.
CREATE UNIQUE INDEX idx_live_sessions_open_code ON live_sessions (code)
    WHERE status IN ('lobby', 'running', 'finished');

CREATE TABLE live_participants (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES live_sessions (id) ON DELETE CASCADE,
    name         TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 60),
    token_hash   TEXT NOT NULL UNIQUE,  -- SHA-256 del token del dispositivo (nunca el token)
    device       TEXT,                  -- p. ej. «Android · Chrome»; sin IP ni User-Agent completo
    status       TEXT NOT NULL CHECK (status IN ('pending', 'admitted', 'kicked')),
    attempt_id   TEXT REFERENCES exam_attempts (id) ON DELETE SET NULL,
    order_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(order_json)),
    left_count   INTEGER NOT NULL DEFAULT 0,  -- veces que salió de la página durante el examen
    last_seen_at TEXT,
    joined_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_live_participants_session ON live_participants (session_id, joined_at);
CREATE INDEX idx_live_participants_attempt ON live_participants (attempt_id);

-- Nota ajustada a mano por el profesor (prevalece sobre la corrección automática o de la IA).
ALTER TABLE attempt_answers ADD COLUMN adjusted INTEGER NOT NULL DEFAULT 0 CHECK (adjusted IN (0, 1));
