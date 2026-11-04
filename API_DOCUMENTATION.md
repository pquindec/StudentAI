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
| POST | `/api/v1/sources/{id}/retry` | Reprocesar una fuente fallida o cancelada |
| GET | `/api/v1/stt` | whisper.cpp disponible, modelos (instalado, descarga en curso), modelo e idioma elegidos |
| PUT | `/api/v1/stt/settings` | `{model?, language?: auto\|es\|en}` |
| POST | `/api/v1/stt/models/{id}/download` | Descarga explícita (202); también descarga el VAD si falta |
| POST | `/api/v1/sources/{id}/transcribe` | `{language?}` — (re)transcribir un audio; la versión anterior se conserva |
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
