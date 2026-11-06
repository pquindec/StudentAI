# Seguridad — controles implementados

Amenazas y riesgos: `THREAT_MODEL.md`. Este archivo lista **solo lo que está implementado y probado**.

| Control | Dónde | Prueba |
|---|---|---|
| Backend sin puerto TCP: Unix socket con permisos `0600` en directorio `0700` | `backend/app/main.py` (`bind_private_socket`) | `test_process.py::test_socket_auth_and_permissions` |
| El backend se niega a usar un directorio ajeno para el socket | `core/config.py::prepare_dirs` | `test_refuses_foreign_socket_dir` |
| Token de sesión aleatorio (32 bytes de `/dev/urandom`) entregado por stdin, nunca por argumentos ni entorno | `src-tauri/src/backend.rs` | manual (`ps` no lo muestra) |
| Toda petición exige token; comparación en tiempo constante | `core/security.py` | `test_security.py` (6 casos) |
| `/docs` y `/openapi.json` desactivados en ejecución | `api/app.py` | `test_docs_disabled` |
| Errores sin trazas ni detalles internos | `api/app.py` | — |
| Backend termina si la app muere (EOF en stdin) | `main.py` | `test_exits_when_parent_closes_stdin` + prueba manual con `kill -9` |
| Proxy Rust: lista blanca de métodos, ruta `/api/v1/*` saneada, límites de tamaño | `src-tauri/src/proxy.rs`, `lib.rs` | `cargo test` (3 pruebas) |
| Capabilities mínimas: solo `core:event:default` y los 2 comandos propios | `capabilities/default.json`, `build.rs` | — |
| CSP estricta (sin scripts externos ni `eval`), `freezePrototype` | `tauri.conf.json` | — |
| Proceso backend con entorno limpio (`env_clear`) | `backend.rs` | — |
| Backend empaquetado con `python -I` (ignora variables `PYTHON*` y site del usuario) | `build-backend-runtime.sh` | prueba manual del `.app` |
| Datos, BD y copias con permisos `0700`/`0600` | `config.py`, `migrate.py` | `test_db_file_is_private` |
| Importar solo rutas elegidas por el usuario (selector nativo o soltar), de un solo uso y con caducidad | `src-tauri/src/grants.rs`, `lib.rs` | `cargo test` (grants) |
| Endpoints internos bloqueados para la UI (incl. `%xx` y `//`) y exigencia de cabecera del núcleo en el backend | `proxy.rs`, `routes/internal.py` | `cargo test`, `test_internal_requires_core_header` |
| Tipo real del archivo por *magic bytes*; extensión falsa, binario como texto, vacío → rechazo con mensaje | `pipelines/files.py` | `test_rejected_on_import` (6 casos) |
| Límites de tamaño por tipo, páginas de PDF, duración de audio, filas CSV; zip-bomb en DOCX | `core/limits.py`, `extractors.py` | `test_fails_during_processing` |
| Copia inmutable (`0400`) con nombre UUID: el nombre original nunca se usa como ruta | `files.py` | `test_original_name_never_used_as_path` |
| Extracción en subproceso aislado (`python -I`), timeout y límite de CPU | `extract/runner.py` | PDF corrupto → `failed` sin afectar al backend |
| El contenido importado se muestra como texto (React escapa), nunca como HTML | `SourceDetail.tsx` | — |
| Modelos descargados solo a petición, URL fija HTTPS, tamaño y SHA-256 verificados antes de usarlos | `stt/models.py` | `test_download_verifies_hash` |
| Protocolo `asset` limitado a `$APPDATA/sources/*/normalized.wav` (ni BD, ni originales, ni modelos) | `tauri.conf.json` | — |
| Grabaciones: carpetas con nombre UUID validado (recuperar/descartar no aceptan rutas), permisos `0700` | `recorder.rs` | `ids_are_uuid_only` |
| Sin procesos huérfanos: whisper/ffmpeg registrados y terminados al salir; huérfano de un `kill -9` eliminado al reanudar | `core/children.py`, `whisper_cpp.kill_stale` | prueba E2E manual (registrada en TESTING.md) |
| Solo el núcleo marca un audio como `recording` (campo del endpoint interno) | `routes/internal.py` | `test_recording_import_kind` |
| El LLM solo se contacta en `127.0.0.1` (se rechaza cualquier otro host); sin herramientas ni acceso a red | `llm/ollama.py` | `test_ollama_only_local_and_down` |
| Contenido importado delimitado como datos; se neutralizan `</fuente>` y los ids de fragmento falsos `[A1]` del texto | `generation/prompts.py` | `test_untrusted_content_cannot_escape_delimiters` |
| Citas verificadas: solo ids entregados al modelo en esa llamada; las inventadas se descartan y se cuentan; un punto sin cita válida no se guarda | `generation/docs.py` | `test_validate_drops_invented_citations` |
| Documentos y sus fuentes, siempre de la misma asignatura y del mismo propietario (servicio + trigger) | `services/documents.py`, `0004` | `test_documents_respect_subject_and_owner` |
| Asistente: el ámbito se aplica en SQL en ambas búsquedas (palabras y vectores), siempre con el propietario; un chunk no puede pertenecer a otra asignatura (trigger) | `rag/scope.py`, `0005` | `test_scope_subject_never_leaks`, `test_scope_never_crosses_users`, `test_scope_isolation_in_answers` |
| Asistente: fuentes delimitadas como datos, respuesta solo con citas verificadas; sin cita válida → «no encontrado» (nunca se muestra texto sin respaldo); sin fragmentos relevantes no se llama al modelo. Excepción deliberada (0.7.2, decidida por el usuario): las peticiones de **crear** sin respaldo en las fuentes se responden con conocimiento general del modelo local, sin citas y con aviso visible «sin respaldo en tus fuentes»; en ese caso no se envía ningún fragmento al modelo | `rag/answer.py` | `test_injected_instructions_stay_as_data`, `test_not_found_when_model_says_so_or_cites_nothing`, `test_create_with_general_knowledge_when_not_in_sources`, `test_questions_still_answer_only_from_sources` |
| Exámenes: cada pregunta guardada tiene al menos una cita que aparece literalmente en su segmento (offsets verificados); id de fragmento inventado o cita parafraseada → descartada | `generation/exam.py::find_quote`, `check_question` | `test_find_quote_is_literal`, `test_exam_end_to_end_with_literal_evidence` |
| Flashcards: cada tarjeta guardada tiene su cita literal en el segmento (offsets verificados); cita inventada → descartada; revisor separado; fuentes delimitadas como datos | `generation/cards.py::check_card`, `judge_messages` | `test_check_card_requires_literal_quote`, `test_card_prompt_treats_sources_as_data`, `test_deck_end_to_end` |
| Flashcards y estadísticas: todo filtrado por propietario de la asignatura (mazo, tarjeta, cola de repaso, estadísticas) | `services/flashcards.py`, `services/stats.py` | `test_edit_suspend_delete_and_isolation` |
| Exámenes: la API no devuelve la respuesta correcta ni la evidencia antes de comprobar o entregar; la hora límite se impone en el backend | `routes/exams.py`, `services/exams.py` | `test_practice_attempt_hides_answers_until_checked`, `test_timed_attempt_closes_when_time_is_over` |
| Corrección por IA: la respuesta del estudiante va delimitada como datos (etiqueta neutralizada), salida con esquema (0 / 0,5 / 1) y marcada «Corregida por IA» | `generation/grading.py` | `test_student_answer_cannot_escape_delimiter`, `test_short_answers_are_graded_by_ai` |
| Consulta FTS construida solo con palabras entre comillas (sin operadores del usuario) | `rag/search.py::fts_query` | `test_fts_query_is_safe` |
| Vínculos solo dentro de la misma asignatura (servicio + trigger) | `services/sources.py`, `0002` | `test_links_must_be_same_subject` |
| Claude desactivado por defecto; ningún byte sale sin un consentimiento válido para esa tarea, vía y modelo | `services/cloud.py::authorize`, `services/engine.py` | `test_disabled_by_default_and_nothing_leaves_without_consent` |
| Consentimiento «una vez» ligado a un trabajo y a las fuentes/fragmentos mostrados; «sesión» ligado al arranque del backend; revocable | `services/cloud.py`, `services/cloud_preview.py` | `test_consent_only_covers_the_previewed_sources`, `test_session_consent_lasts_until_restart_and_can_be_revoked`, `test_chat_sends_exactly_the_previewed_fragments` |
| Límite mensual por vía comprobado antes de cada llamada; registro de envíos sin contenido | `services/cloud.py::Gate` | `test_monthly_limit_blocks_and_continues_locally` |
| Clave API solo en el Keychain; la API devuelve solo los 4 últimos caracteres | `core/secrets.py`, `routes/cloud.py` | `test_api_key_lives_in_keychain_not_in_db` |
| Plan de Claude: solo se ejecuta el binario oficial, sin herramientas, MCP ni ajustes, sin variables `ANTHROPIC_*`; nunca se leen sus credenciales; el prompt no puede ser un comando «/» | `llm/claude_code.py` | `test_plan_via_runs_claude_code_without_tools_or_credentials`, `test_prompt_never_starts_with_a_slash_command` |

## Pendiente (fases siguientes)
SAST/SCA/DAST, fuzzing y batería de prompt injection (Fase 9).

## Reportar un problema
Proyecto personal: abre una nota en `TASKS.md` con la etiqueta `[SEGURIDAD]`.
