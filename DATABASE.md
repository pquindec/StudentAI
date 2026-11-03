# Base de datos

El modelo de datos completo y su justificación están en `ARCHITECTURE.md §5`. **El esquema real es el de las migraciones** en `backend/app/db/migrations/`.

## Estado
| Versión | Migración | Contenido |
|---|---|---|
| 1 | `0001_init.sql` | `users` (usuario `local`), `settings`, `subjects`, `units` (course/module/topic), `sessions` |
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
- Las ediciones nunca sobrescriben: crean una versión nueva y se re-segmentan.

## Migraciones
- Archivo nuevo `NNNN_nombre.sql` (4 dígitos, minúsculas). Nunca editar uno aplicado.
- Cada migración se aplica en **una transacción**; si falla, se revierte entera.
- Antes de migrar una BD existente se crea `backups/app-<fecha>-pre-NNNN.db` (se conservan 5).
- Archivos de BD y copias con permisos `0600`.
