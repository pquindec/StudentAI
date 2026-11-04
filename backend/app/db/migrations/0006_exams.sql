-- 0006: exámenes generados desde las fuentes, con evidencia literal verificada, e intentos.

CREATE TABLE exams (
    id            TEXT PRIMARY KEY,
    subject_id    TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    title         TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 300),
    config_json   TEXT NOT NULL CHECK (json_valid(config_json)),
    scope_json    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(scope_json)),
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'running', 'insufficient', 'ready', 'failed', 'cancelled')),
    requested     INTEGER NOT NULL CHECK (requested BETWEEN 1 AND 50),
    available     INTEGER NOT NULL DEFAULT 0,  -- preguntas válidas encontradas
    model         TEXT,
    job_id        TEXT REFERENCES jobs (id) ON DELETE SET NULL,
    stats_json    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)),
    error_code    TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_exams_subject ON exams (subject_id, created_at);

-- Solo se guardan preguntas que superaron toda la validación. `kept` = forma parte del examen
-- (si hay más válidas que las pedidas, o el usuario acepta menos, el resto queda en reserva).
CREATE TABLE exam_questions (
    id            TEXT PRIMARY KEY,
    exam_id       TEXT NOT NULL REFERENCES exams (id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    kept          INTEGER NOT NULL DEFAULT 1 CHECK (kept IN (0, 1)),
    type          TEXT NOT NULL CHECK (type IN ('single', 'true_false', 'short')),
    stem          TEXT NOT NULL,
    options_json  TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(options_json)),
    answer_json   TEXT NOT NULL CHECK (json_valid(answer_json)),  -- índice, booleano o texto modelo
    justification TEXT NOT NULL,
    rubric_json   TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(rubric_json)),
    difficulty    TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    source_id     TEXT REFERENCES sources (id) ON DELETE SET NULL,
    judge_notes   TEXT
);
CREATE INDEX idx_exam_questions_exam ON exam_questions (exam_id, kept, position);

-- Evidencia literal: la cita aparece tal cual en el segmento (offsets dentro de su texto).
CREATE TABLE exam_question_evidence (
    question_id TEXT NOT NULL REFERENCES exam_questions (id) ON DELETE CASCADE,
    segment_id  INTEGER NOT NULL REFERENCES segments (id) ON DELETE CASCADE,
    quote       TEXT NOT NULL,
    char_start  INTEGER NOT NULL,
    char_end    INTEGER NOT NULL,
    PRIMARY KEY (question_id, segment_id)
);

CREATE TABLE exam_attempts (
    id            TEXT PRIMARY KEY,
    exam_id       TEXT NOT NULL REFERENCES exams (id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'in_progress'
                  CHECK (status IN ('in_progress', 'grading', 'graded')),
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deadline_at   TEXT,  -- solo en modo cronometrado
    finished_at   TEXT,
    current_index INTEGER NOT NULL DEFAULT 0,
    score         REAL,
    max_score     REAL,
    job_id        TEXT REFERENCES jobs (id) ON DELETE SET NULL
);
CREATE INDEX idx_exam_attempts_exam ON exam_attempts (exam_id, started_at);

CREATE TABLE attempt_answers (
    attempt_id TEXT NOT NULL REFERENCES exam_attempts (id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES exam_questions (id) ON DELETE CASCADE,
    answer_json TEXT CHECK (answer_json IS NULL OR json_valid(answer_json)),
    flagged     INTEGER NOT NULL DEFAULT 0 CHECK (flagged IN (0, 1)),
    checked     INTEGER NOT NULL DEFAULT 0 CHECK (checked IN (0, 1)),  -- práctica: ya comprobada
    is_correct  INTEGER,
    points      REAL,
    feedback    TEXT,
    graded_by   TEXT CHECK (graded_by IS NULL OR graded_by IN ('auto', 'ai')),
    PRIMARY KEY (attempt_id, question_id)
);
