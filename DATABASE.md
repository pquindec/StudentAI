# Base de datos

El modelo de datos completo y su justificación están en `ARCHITECTURE.md §5`. **El esquema real es el de las migraciones** en `backend/app/db/migrations/`.

## Estado
| Versión | Migración | Contenido |
|---|---|---|
| 1 | `0001_init.sql` | `users` (usuario `local`), `settings`, `subjects`, `units` (course/module/topic), `sessions` |
| 7 | `0007_flashcards.sql` | `decks` (mazos: ámbito, estado de generación, métricas), `flashcards` (anverso, reverso, cita literal + offsets en el segmento; la fuente borrada deja la evidencia en NULL; misma asignatura que su mazo por trigger), `card_states` (estado FSRS: `new/learning/review/relearning`, paso, estabilidad, dificultad, `due_at`, repasos y fallos), `card_reviews` (historial: valoración 1–4, hora, duración, estado previo, días transcurridos y programados). Ajuste `settings['srs.new_per_day']` |
| 6 | `0006_exams.sql` | `exams` (configuración y ámbito en JSON, estado `queued/running/insufficient/ready/failed/cancelled`, pedidas/disponibles, métricas de validación), `exam_questions` (enunciado, opciones, respuesta, justificación, rúbrica, `kept` = entra en el examen; las sobrantes validadas se conservan para aceptar menos), `exam_question_evidence` (cita literal + offsets en el segmento; se borra con él), `exam_attempts` (intentos: estado, hora límite impuesta por el backend, nota), `attempt_answers` (respuesta, marcada, comprobada, puntos, `graded_by` auto/ai, comentario) |
| 5 | `0005_rag_chat.sql` | `chunks` (trozos de ~1.000 caracteres de la versión actual con segmentos, página y tiempo; misma asignatura que su fuente por trigger), `chunks_fts` (FTS5 de contenido externo, sin acentos, sincronizado por triggers), `chunk_vectors` (float32 por modelo, tabla normal con borrado en cascada), `source_index` (estado del índice por fuente), `chat_threads` (ámbito en `scope_json`), `chat_messages` (estado y métricas), `chat_message_citations` (ref → segmento) |
| 4 | `0004_generated_docs.sql` | `generated_docs` (apuntes/resúmenes: contenido estructurado, estado, modelo, métricas de validación), `generated_doc_sources` (fuentes y versión fijada, misma asignatura por trigger), `generated_doc_citations` (ref → segmento), `model_runs` (tokens, duración, tamaño cargado) |
| 3 | `0003_transcription.sql` | `jobs.checkpoint_json` (avance de trabajos largos), índice único: una transcripción activa por fuente; audios de la Fase 2 pasan a `transcription = needs_model` |
| 2 | `0002_sources_jobs.sql` | `sources` (material importado), `source_links` (N:M con unidad **o** sesión), `source_versions` (texto por versión: extraído, transcrito, pegado, editado), `segments` (bloques con página, sección, offsets y timestamps), `jobs` (cola persistente) |

## Reglas
- SQLite en modo **WAL**, `foreign_keys=ON`, `busy_timeout=5000`. Una conexión por petición.
- IDs en texto (UUID); fechas ISO-8601 UTC.
- Integridad en la propia BD: `CHECK` de longitudes y enumerados; triggers que impiden que una unidad o sesión apunte a una unidad de otra asignatura; una unidad no puede ser su propio padre; borrado en cascada desde `subjects`.
- Ciclos más largos en el árbol de unidades (A→B→A) y el orden curso → módulo → tema se validan en el servicio (`services/subjects.py::check_unit_parent`).
- `source_links` exige exactamente uno de `unit_id`/`session_id`, y un trigger impide vincular a una unidad o sesión de otra asignatura.
- Los archivos viven en `sources/<uuid>/original.<ext>` (solo lectura); `stored_path` es relativo a la carpeta de datos. Borrar una fuente o asignatura borra también su carpeta.
- Audio ya transcrito (0.6.2, sin migración): el original y luego `normalized.wav` se borran según `settings['audio.keep_days']` (0/7/30); `stored_path` se conserva como referencia y `metadata_json.audio_cleaned_at` registra la limpieza. El estado real se calcula mirando el disco.
- Las ediciones nunca sobrescriben: crean una versión nueva y se re-segmentan.
- Solo se indexa la **versión actual** de cada fuente: guardar una versión encola `index_source`, que sustituye sus chunks (los triggers mantienen FTS5 al día y los vectores se borran en cascada).
- `sqlite-vec` se carga solo en las conexiones que buscan (`vec_distance_cosine` sobre `chunk_vectors`); el esquema no depende de la extensión, así que borrar o migrar funciona sin ella.

## Migraciones
- Archivo nuevo `NNNN_nombre.sql` (4 dígitos, minúsculas). Nunca editar uno aplicado.
- Cada migración se aplica en **una transacción**; si falla, se revierte entera.
- Antes de migrar una BD existente se crea `backups/app-<fecha>-pre-NNNN.db` (se conservan 5).
- Archivos de BD y copias con permisos `0600`.
