-- Fase 7: mazos de tarjetas generados desde las fuentes, estado de repaso (FSRS) y repasos.

CREATE TABLE decks (
    id            TEXT PRIMARY KEY,
    subject_id    TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    title         TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 300),
    scope_json    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(scope_json)),
    requested     INTEGER NOT NULL CHECK (requested BETWEEN 1 AND 100),
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'running', 'ready', 'failed', 'cancelled')),
    model         TEXT,
    job_id        TEXT REFERENCES jobs (id) ON DELETE SET NULL,
    stats_json    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)),
    error_code    TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_decks_subject ON decks (subject_id, created_at);

-- Cada tarjeta guarda la frase LITERAL de la fuente que la respalda. Si la fuente se borra, la
-- tarjeta se conserva y la evidencia queda como «fuente eliminada».
CREATE TABLE flashcards (
    id          TEXT PRIMARY KEY,
    deck_id     TEXT NOT NULL REFERENCES decks (id) ON DELETE CASCADE,
    subject_id  TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    front       TEXT NOT NULL CHECK (length(trim(front)) BETWEEN 1 AND 1000),
    back        TEXT NOT NULL CHECK (length(trim(back)) BETWEEN 1 AND 2000),
    source_id   TEXT REFERENCES sources (id) ON DELETE SET NULL,
    segment_id  INTEGER REFERENCES segments (id) ON DELETE SET NULL,
    quote       TEXT,
    char_start  INTEGER,
    char_end    INTEGER,
    suspended   INTEGER NOT NULL DEFAULT 0 CHECK (suspended IN (0, 1)),
    edited      INTEGER NOT NULL DEFAULT 0 CHECK (edited IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_flashcards_deck ON flashcards (deck_id, position);
CREATE INDEX idx_flashcards_subject ON flashcards (subject_id);

-- La tarjeta y su mazo son de la misma asignatura.
CREATE TRIGGER flashcards_same_subject BEFORE INSERT ON flashcards
WHEN (SELECT subject_id FROM decks WHERE id = NEW.deck_id) IS NOT NEW.subject_id
BEGIN
    SELECT RAISE(ABORT, 'flashcard subject mismatch');
END;

-- Estado de repaso. 'new' = nunca repasada. Fechas ISO-8601 UTC.
CREATE TABLE card_states (
    card_id        TEXT PRIMARY KEY REFERENCES flashcards (id) ON DELETE CASCADE,
    state          TEXT NOT NULL DEFAULT 'new'
                   CHECK (state IN ('new', 'learning', 'review', 'relearning')),
    step           INTEGER,
    stability      REAL,
    difficulty     REAL,
    due_at         TEXT NOT NULL,
    last_review_at TEXT,
    reps           INTEGER NOT NULL DEFAULT 0,
    lapses         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_card_states_due ON card_states (due_at);

-- Historial de repasos (estadísticas y, en el futuro, optimizar los parámetros de FSRS).
CREATE TABLE card_reviews (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id        TEXT NOT NULL REFERENCES flashcards (id) ON DELETE CASCADE,
    subject_id     TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    rating         INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
    reviewed_at    TEXT NOT NULL,
    duration_ms    INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
    state_before   TEXT NOT NULL,
    elapsed_days   REAL,
    scheduled_days REAL NOT NULL
);
CREATE INDEX idx_card_reviews_subject ON card_reviews (subject_id, reviewed_at);
CREATE INDEX idx_card_reviews_card ON card_reviews (card_id, reviewed_at);
