# API — contrato UI ↔ backend

**Fuente de verdad:** el esquema OpenAPI generado (`app/src/lib/api/openapi.json`, regenerar con `npm run gen:api`). Este documento describe solo lo que el esquema no dice.

## Transporte
| Modo | Camino | Autenticación |
|---|---|---|
| Escritorio | `invoke('api_request', {request:{method, path, body}})` → Rust → HTTP/1.1 sobre Unix socket | Token de sesión (32 bytes) que Rust añade como `Authorization: Bearer …` |
| Web (futuro, ADR-009) | `fetch` HTTPS al mismo origen | Sesión con cookie `HttpOnly` + CSRF |

Restricciones del proxy Rust: métodos `GET POST PUT PATCH DELETE`; ruta que empiece por `/api/v1/`, ASCII imprimible, sin `..`, `#` ni `\`, ≤ 2048 caracteres; cuerpo JSON ≤ 1 MB; respuesta ≤ 32 MB. Los archivos **no** viajan por este canal (ver «Importar archivos»).

## Errores
Formato único:
```json
{ "error": { "code": "unauthorized", "message": "No autorizado" } }
```
`message` está en español y puede mostrarse al usuario. Nunca se devuelven trazas. Si el fallo ocurre en Rust (backend caído, ruta no permitida), la UI recibe `ApiError` con `code = "transport_error"`.

## Endpoints (v1)
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/health` | Estado, versión y versión del esquema de BD |
| GET | `/api/v1/system/info` | Versiones (Python, SQLite), FTS5, carpeta de datos, usuario local |
| GET/POST | `/api/v1/subjects` | Listar (`?archived=`) / crear asignatura |
| GET/PATCH/DELETE | `/api/v1/subjects/{id}` | Detalle con unidades y sesiones / editar (incl. `archived`) / borrar (borra también sus archivos) |
| POST | `/api/v1/subjects/{id}/units` · PATCH/DELETE `/api/v1/units/{id}` | Árbol curso → módulo → tema |
| POST | `/api/v1/subjects/{id}/sessions` · PATCH/DELETE `/api/v1/sessions/{id}` | Clases y sesiones de estudio |
| GET | `/api/v1/sources` | Biblioteca: `subject_id`, `unit_id`, `kind`, `status`, `q`, `limit`, `offset` → `{items, total}` |
| POST | `/api/v1/sources/text` | Texto pegado o nota propia (Markdown) |
| GET/PATCH/DELETE | `/api/v1/sources/{id}` | Detalle / renombrar y vínculos / borrar (cancela trabajos y borra archivos) |
| GET/PUT | `/api/v1/sources/{id}/content` | Texto y segmentos (`?version=`) / nueva versión con `base_version` (409 `version_conflict`, 400 `no_changes`) |
| POST | `/api/v1/sources/{id}/retry` | Reprocesar una fuente fallida o cancelada (audio sin original: retranscribe desde la copia ligera; sin audio: 400 `audio_deleted`) |
| GET | `/api/v1/stt` | whisper.cpp disponible, modelos (instalado, descarga en curso), modelo e idioma elegidos |
| PUT | `/api/v1/stt/settings` | `{model?, language?: auto\|es\|en, audio_keep_days?: 0\|7\|30}` (0 = conservar el audio siempre) |
| POST | `/api/v1/stt/models/{id}/download` | Descarga explícita (202); también descarga el VAD si falta |
| POST | `/api/v1/sources/{id}/transcribe` | `{language?}` — (re)transcribir un audio; la versión anterior se conserva. 400 `audio_deleted` si el audio ya se borró |
| GET | `/api/v1/sources/{id}/audio` | Audio en disco: `state` full (original + copia ligera) \| light (solo copia ligera) \| deleted, `bytes`, `expires_at` (cuándo se borra solo), `deletable` |
| DELETE | `/api/v1/sources/{id}/audio` | Borra el audio de una clase ya transcrita (409 `not_transcribed` si no lo está o hay tareas en curso). La transcripción no se toca |
| GET | `/api/v1/sources/{id}/export?format=txt\|srt` | `{filename, content}` (la UI lo guarda con el diálogo nativo) |
| GET | `/api/v1/ai/status` | Ollama (en marcha, versión), modelo elegido y ligero, `keep_alive`, modelos instalados, cargados y memoria disponible |
| PUT | `/api/v1/ai/settings` | `{model?, keep_alive?: 1m\|2m\|5m\|10m}` |
| POST | `/api/v1/subjects/{id}/documents` | `{kind: notes\|summary, detail: brief\|medium\|detailed, source_ids[1..20], title?}` → 202, se genera en segundo plano |
| GET | `/api/v1/subjects/{id}/documents` | Apuntes y resúmenes de la asignatura (con estado y progreso) |
| GET | `/api/v1/documents/{id}` | Apartados → puntos con `refs`, contradicciones, citas (texto literal, página o tiempo, fuente) y métricas |
| POST | `/api/v1/documents/{id}/retry` | Reintenta si falló o se canceló (409 si no) |
| DELETE | `/api/v1/documents/{id}` | Borra (y cancela si se está generando) |
| GET/POST | `/api/v1/chat/threads` | Conversaciones del asistente (más recientes primero) / crear `{scope?, title?}` → 201. `scope = {subject_id?, unit_ids[], source_ids[], exclude_source_ids[]}`; sin `subject_id` = toda la biblioteca. Los ids deben ser del usuario y de la asignatura (400 `invalid_scope`) |
| GET/PATCH/DELETE | `/api/v1/chat/threads/{id}` | Detalle con mensajes y citas / cambiar título o ámbito / borrar (cancela la respuesta en curso) |
| POST | `/api/v1/chat/threads/{id}/messages` | `{text}` → 202 con el mensaje de respuesta (`queued`); 409 `answer_in_progress` si aún responde |
| GET | `/api/v1/chat/messages/{id}` | Estado (`queued`, `streaming` con texto parcial, `done`, `not_found`, `failed`, `cancelled`), contenido con referencias `⟦n⟧`, citas y métricas. La UI lo consulta cada 400 ms mientras responde |
| POST | `/api/v1/chat/messages/{id}/cancel` | Detiene la respuesta |
| GET | `/api/v1/rag/status` | Modelo de embeddings y si está disponible, búsqueda por vectores, fuentes indexadas y pendientes |
| GET | `/api/v1/sources/{id}/index` | Estado del índice de una fuente (`none`, `queued`, `indexing`, `ready`, `failed`, chunks, con vector) |
| GET/POST | `/api/v1/subjects/{id}/exams` | Exámenes de la asignatura / crear `{title?, config, scope?}` → 202, se genera en segundo plano. `config = {count 1..50, types[single\|true_false\|short], difficulty easy\|medium\|hard\|mixed, options 3..5, mode practice\|timed, time_limit_min (obligatorio en timed), penalty 0..1}`; 400 `no_sources`, `invalid_scope` |
| GET/DELETE | `/api/v1/exams/{id}` | Estado, progreso, métricas de validación e intentos / borrar (cancela la generación) |
| POST | `/api/v1/exams/{id}/accept` | Con estado `insufficient`: aceptar las `available` preguntas válidas |
| POST | `/api/v1/exams/{id}/retry` | Reintentar si falló o se canceló |
| POST | `/api/v1/exams/{id}/attempts` | Empezar un intento (409 `exam_not_ready`). Nunca incluye las respuestas correctas |
| GET/DELETE | `/api/v1/attempts/{id}` | Intento con preguntas y respuestas; la solución, justificación y evidencia solo aparecen en preguntas comprobadas o tras la corrección. Si pasó la hora límite, se entrega al consultarlo |
| PUT | `/api/v1/attempts/{id}/answers/{qid}` | `{answer?, set_answer, flagged?, index?}` guarda progreso (409 `attempt_closed`, `time_over`, `already_checked`; 400 `invalid_answer`) |
| POST | `/api/v1/attempts/{id}/answers/{qid}/check` | Solo modo práctica: corrige esa pregunta y la bloquea |
| POST | `/api/v1/attempts/{id}/submit` | Entregar: test y V/F se corrigen al momento; las cortas, con la IA en segundo plano (`grading` → `graded`) |
| GET/POST | `/api/v1/subjects/{id}/decks` | Mazos de la asignatura con recuento (nuevas, aprendiendo, dominadas, suspendidas, pendientes, próximo repaso) / crear `{title?, count 5..100, scope?}` → 202, se genera en segundo plano; 400 `no_sources`, `invalid_scope` |
| GET/DELETE | `/api/v1/decks/{id}` | Mazo con sus tarjetas (estado de repaso y cita literal) / borrar (cancela la generación) |
| POST | `/api/v1/decks/{id}/retry` | Reintentar si falló o se canceló |
| PATCH/DELETE | `/api/v1/cards/{id}` | `{front?, back?, suspended?}` editar o suspender / borrar una tarjeta |
| GET | `/api/v1/study` | `?subject_id=` o `?deck_id=` (o nada: todo). Siguiente tarjeta que toca (aprendizaje vencido → repasos vencidos → nuevas hasta el límite diario; si no queda nada, adelanta pasos de aprendizaje de los próximos 20 min), fecha que pondría cada valoración, cuántas quedan y próximo repaso |
| POST | `/api/v1/cards/{id}/review` | `{rating 1..4 (Otra vez, Difícil, Bien, Fácil), duration_ms}` → estado nuevo (FSRS). 409 `suspended` |
| PUT | `/api/v1/study/settings` | `{new_per_day 0..200}` (20 por defecto) |
| GET | `/api/v1/stats` | `?subject_id=&days=7\|30\|90` tiempo de estudio por día (tarjetas, máx. 2 min cada una, + intentos de examen), repasos, retención, racha, días activos, tarjetas (reparto y previsión de 7 días), exámenes (intentos corregidos, nota media, últimos 10). Días locales |
| GET | `/api/v1/jobs` | Trabajos (`?active=true`) con progreso |
| POST | `/api/v1/jobs/{id}/cancel` | Cancelar (inmediato si está en cola; cooperativo si está en curso) |

Errores de dominio frecuentes: `not_found`, `invalid_hierarchy`, `invalid_link`, `duplicate` (con `details.source_id`), `content_mismatch`, `unsupported_type`, `empty_file`, `too_large`, `version_conflict`. Los fallos de extracción quedan en la fuente (`error_code`: `encrypted`, `corrupt`, `no_text`, `zip_bomb`, `crashed`, `timeout`…) con `error_message` en español.

## Importar archivos (solo escritorio)
1. La UI llama a `invoke('pick_files')` (selector nativo abierto desde Rust) o recibe rutas por el evento de arrastrar y soltar.
2. Rust registra esas rutas como **autorizadas** (un solo uso, caducan a los 10 min). Ninguna otra ruta se puede importar.
3. `invoke('import_files', {request:{subject_id, unit_ids, session_ids, paths}})` → por cada ruta autorizada Rust llama a `POST /api/v1/internal/sources/import-file` con la cabecera `x-core-caller: 1`. Devuelve `[{path, status, body}]`.

## Grabación (comandos Rust, solo escritorio)
`list_input_devices`, `recording_status`, `start_recording({device_id?, target:{subject_id, title, unit_ids, session_ids}})`, `pause_recording({resume})`, `stop_recording` → `{recording_id, status, body, warning}`, `list_recoverable_recordings`, `recover_recording({id})`, `discard_recording({id})`, `save_text_file({defaultName, content})`. Evento `recording://status` (~7 por segundo) con estado, duración y nivel.

Formato del texto transcrito: una línea por frase con marca `[mm:ss]` o `[h:mm:ss]`; una línea en blanco separa párrafos. `segments.start_ms/end_ms` salen de esas marcas.

`/api/v1/internal/*` no aparece en el esquema, el proxy de la UI lo rechaza (también con `%xx` o `//`) y el backend exige la cabecera del núcleo.

`/docs`, `/redoc` y `/openapi.json` están **desactivados** en ejecución.
