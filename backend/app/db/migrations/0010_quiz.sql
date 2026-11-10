-- Modo concurso de la sala en vivo: todos ven la misma pregunta a la vez, con cuenta atrás;
-- puntos por acierto y rapidez y clasificación tras cada pregunta. Una sala en modo concurso
-- se guarda con mode = 'practice' (entrada directa, sin nota) y quiz = 1.

ALTER TABLE live_sessions ADD COLUMN quiz INTEGER NOT NULL DEFAULT 0 CHECK (quiz IN (0, 1));
ALTER TABLE live_sessions ADD COLUMN question_s INTEGER
    CHECK (question_s IS NULL OR question_s BETWEEN 5 AND 120);  -- segundos por pregunta
ALTER TABLE live_sessions ADD COLUMN quiz_json TEXT NOT NULL DEFAULT '{}'
    CHECK (json_valid(quiz_json));                                -- orden de las preguntas
ALTER TABLE live_sessions ADD COLUMN quiz_index INTEGER;          -- pregunta actual (desde 0)
ALTER TABLE live_sessions ADD COLUMN quiz_opens_at TEXT;          -- se abre tras la cuenta atrás
ALTER TABLE live_sessions ADD COLUMN quiz_closes_at TEXT;         -- se cierra (tiempo o todos)

CREATE TABLE live_quiz_answers (
    participant_id TEXT NOT NULL REFERENCES live_participants (id) ON DELETE CASCADE,
    question_id    TEXT NOT NULL REFERENCES exam_questions (id) ON DELETE CASCADE,
    choice_json    TEXT NOT NULL CHECK (json_valid(choice_json)),
    correct        INTEGER NOT NULL CHECK (correct IN (0, 1)),
    points         INTEGER NOT NULL CHECK (points BETWEEN 0 AND 1000),
    answer_ms      INTEGER NOT NULL CHECK (answer_ms >= 0),  -- medido en el Mac, no en el teléfono
    answered_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (participant_id, question_id)
);
CREATE INDEX idx_live_quiz_answers_question ON live_quiz_answers (question_id);
