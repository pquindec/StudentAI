-- Fase 3: transcripción reanudable.
-- checkpoint_json guarda el avance de trabajos largos (p. ej. hasta qué milisegundo se ha
-- transcrito) para continuar tras un cierre inesperado sin repetir el trabajo hecho.
ALTER TABLE jobs ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}'
    CHECK (json_valid(checkpoint_json));

-- Un solo trabajo de transcripción activo por fuente.
CREATE UNIQUE INDEX idx_jobs_one_active_transcription ON jobs (source_id)
    WHERE type = 'transcribe' AND status IN ('queued', 'running');

-- Audios importados en la Fase 2 (antes de existir la transcripción): quedan a la espera del
-- modelo y se transcriben en cuanto esté instalado.
UPDATE sources
SET metadata_json = json_set(metadata_json, '$.transcription', 'needs_model')
WHERE kind IN ('audio', 'recording')
  AND json_extract(metadata_json, '$.transcription') = 'pending';
