-- 0001: tablas base (usuarios, ajustes, asignaturas, unidades, sesiones)
-- Fechas en ISO-8601 UTC. IDs: UUID en texto.

CREATE TABLE users (
    id            TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    email         TEXT UNIQUE,
    password_hash TEXT,
    role          TEXT NOT NULL DEFAULT 'owner' CHECK (role IN ('owner', 'member')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Escritorio: un único usuario local (ver ADR-009).
INSERT INTO users (id, display_name, role) VALUES ('local', 'Usuario local', 'owner');

CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL CHECK (json_valid(value_json)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE subjects (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name        TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 200),
    description TEXT,
    color       TEXT,
    term        TEXT,
    archived_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_subjects_owner ON subjects (owner_id, archived_at);

-- Árbol flexible: Asignatura → Curso → Módulo → Tema (niveles intermedios opcionales).
CREATE TABLE units (
    id         TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    parent_id  TEXT REFERENCES units (id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('course', 'module', 'topic')),
    title      TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (parent_id IS NULL OR parent_id <> id)
);
CREATE INDEX idx_units_subject ON units (subject_id, parent_id, position);

CREATE TRIGGER units_parent_same_subject_ins
BEFORE INSERT ON units
WHEN NEW.parent_id IS NOT NULL
 AND (SELECT subject_id FROM units WHERE id = NEW.parent_id) IS NOT NEW.subject_id
BEGIN
    SELECT RAISE(ABORT, 'parent_unit_other_subject');
END;

CREATE TRIGGER units_parent_same_subject_upd
BEFORE UPDATE OF parent_id, subject_id ON units
WHEN NEW.parent_id IS NOT NULL
 AND (SELECT subject_id FROM units WHERE id = NEW.parent_id) IS NOT NEW.subject_id
BEGIN
    SELECT RAISE(ABORT, 'parent_unit_other_subject');
END;

CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,
    subject_id  TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    unit_id     TEXT REFERENCES units (id) ON DELETE SET NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('class', 'study')),
    title       TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
    held_at     TEXT,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_sessions_subject ON sessions (subject_id, held_at);

CREATE TRIGGER sessions_unit_same_subject
BEFORE INSERT ON sessions
WHEN NEW.unit_id IS NOT NULL
 AND (SELECT subject_id FROM units WHERE id = NEW.unit_id) IS NOT NEW.subject_id
BEGIN
    SELECT RAISE(ABORT, 'session_unit_other_subject');
END;

CREATE TRIGGER sessions_unit_same_subject_upd
BEFORE UPDATE OF unit_id, subject_id ON sessions
WHEN NEW.unit_id IS NOT NULL
 AND (SELECT subject_id FROM units WHERE id = NEW.unit_id) IS NOT NEW.subject_id
BEGIN
    SELECT RAISE(ABORT, 'session_unit_other_subject');
END;
