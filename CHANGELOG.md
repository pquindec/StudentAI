# Changelog

## [0.5.1] — 2026-11-04 · Ajustes del asistente tras la prueba
### Corregido
- Preguntar «vuca» o «Vuca» daba «no encontrado» y «VUCA» sí respondía. Había tres causas: la transcripción escribió la sigla como suena («biuca»), el modelo de embeddings distingue mayúsculas y la explicación ocupaba varios fragmentos seguidos. Ahora:
  - las palabras cortas que no aparecen tal cual en ninguna fuente se buscan también en mayúsculas (posibles siglas);
  - al fragmento más relevante se le añade el siguiente de la misma fuente;
  - se avisa al modelo de que las mayúsculas no importan y de que la transcripción puede escribir mal un término;
  - si el modelo responde sin ninguna cita, se le pide una vez que cite antes de dar «no encontrado».
- La lista de grabaciones se quedaba en «Procesando» al terminar la transcripción hasta cambiar de pantalla. Ahora se refresca sola mientras haya alguna en proceso.

## [0.5.0] — 2026-11-04 · Fase 5: búsqueda en tus fuentes y asistente
### Añadido
- Página **Asistente**: conversaciones que responden solo con tus fuentes. Cada frase lleva su cita (texto literal, página o minuto; «Abrir fuente» salta al momento del audio). Si la respuesta no está en las fuentes, lo dice («No he encontrado la respuesta…») en lugar de inventar.
- Ámbito de búsqueda por conversación: toda la biblioteca, una asignatura o algunas de sus fuentes (la API admite también temas con sus subtemas y exclusiones). Se aplica en la base de datos: una asignatura nunca ve fragmentos de otra.
- Respuesta en directo mientras se genera, botón «Detener» e historial de las últimas preguntas para repreguntar.
- Índice de búsqueda automático: cada fuente con texto se trocea (sin perder página, tiempo ni sección) y se indexa por palabras (FTS5) y por significado (`qwen3-embedding:0.6b`, sqlite-vec), con fusión RRF. Se reindexa al editar; al arrancar se indexa lo que falte. Sin el modelo de embeddings sigue funcionando por palabras.
- Estado del índice en el detalle de cada fuente.
- Migración `0005_rag_chat.sql` y dependencia `sqlite-vec` 0.1.9 (MIT/Apache-2.0).
### Corregido
- Error intermitente «database is locked» al guardar un documento mientras otro trabajo escribía en la base de datos (ahora más probable al indexar en paralelo). Las transacciones toman el bloqueo de escritura al empezar y esperan su turno.
### Seguridad
- Documentos con instrucciones maliciosas probados contra el asistente: se tratan como datos; citas inventadas descartadas; sin cita válida no se muestra la respuesta.

## [0.4.2] — 2026-11-04 · Grabar y generar a la vez
### Corregido
- El botón «Empezar a grabar» quedaba desactivado sin explicación cuando había varias asignaturas y ninguna elegida. Ahora la asignatura viene preseleccionada (la de la última grabación) y se indica si falta el título.
- La transcripción de una grabación esperaba a que terminara el resumen o los apuntes en curso. Ahora la generación cede el turno al terminar la parte que está leyendo, la transcripción va primero y la generación continúa sola desde donde iba (sin repetir partes). Si un documento espera, se indica el motivo («Esperando a que termine la transcripción»).

## [0.4.1] — 2026-11-04 · Resúmenes compactos
### Cambiado
- Los resúmenes ya no tienen el formato de los apuntes: ahora son un texto corrido corto (3, 6 o 10 frases según el nivel) más unas pocas ideas clave que lo complementan, todo con citas.
- Las ideas clave son conceptos para estudiar con su definición breve («VUCA: …»). La longitud del resumen y que las ideas clave no repitan sus frases se garantizan en el código, no solo en el prompt (el modelo copiaba las mismas frases en ambas partes).
- En clases transcritas se priorizan definiciones, conceptos centrales y lo que el profesor destaca; se ignoran saludos, avisos, bromas y repeticiones.
- Resúmenes de material largo más rápidos: cada parte aporta solo sus ideas más relevantes (salida corta) antes de redactar el resumen final.
- La barra de progreso avanza mientras el modelo escribe cada parte y muestra el tiempo restante estimado («quedan ~3 min»). Antes se quedaba en 0 % durante la primera parte y parecía bloqueada.

## [0.4.0] — 2026-11-03 · Fase 4: IA local, apuntes y resúmenes
### Añadido
- Proveedor `LLMProvider` + Ollama local (streaming, salida con JSON Schema, `keep_alive`, cancelación a mitad de respuesta). Solo se conecta a `127.0.0.1`.
- AI Resource Manager v1: mide la memoria disponible antes de cargar el modelo; si no llega para `qwen3.5:9b` usa `qwen3.5:4b`; si tampoco, espera mostrando «Esperando memoria libre» (máx. 10 min). Descarga los modelos que sobran y libera el LLM antes de cada transcripción.
- Apuntes y resúmenes (breve / intermedio / detallado) de una o varias fuentes, con map-reduce. Cada punto cita fragmentos concretos; las citas inexistentes se descartan y se cuentan.
- Contradicciones entre fuentes en los resúmenes, mostradas lado a lado sin resolverlas.
- Páginas Apuntes y Resúmenes, vista del documento con citas clicables (texto literal, página o minuto, «Abrir fuente» salta al momento del audio), botones rápidos en cada fuente y panel de estado de Ollama.
- Generación reanudable por bloques y registro de cada llamada en `model_runs`.
- Migración `0004_generated_docs.sql`.

 — 2026-11-03 · Fase 3: grabación y transcripción
### Añadido
- Grabador nativo en Rust (cpal + hound): micrófono elegible, nivel de entrada, pausa/reanudar, segmentos WAV de 60 s vaciados a disco cada segundo, manifiesto y límite de 6 h. Al parar se une y se importa como fuente `recording`.
- Recuperación de grabaciones interrumpidas (cabecera WAV reparada) al abrir la app.
- Indicador permanente de grabación (barra superior roja y título de la ventana).
- Transcripción con whisper.cpp por tramos de 5 min con checkpoint: tras un cierre continúa donde iba. VAD Silero, idioma automático (se fija tras el primer tramo) o manual.
- Gestor de modelos: descarga solo a petición del usuario, con verificación de tamaño y SHA-256.
- Texto transcrito con marcas `[mm:ss]` por frase: editable sin perder la sincronización.
- Reproductor con transcripción sincronizada (clic para saltar, frase actual resaltada); volver a transcribir conservando la versión anterior; exportar a TXT y SRT con el diálogo nativo.
- Migración `0003_transcription.sql` (`jobs.checkpoint_json`, una transcripción activa por fuente).

### Corregido durante la fase
- Las marcas de tiempo se truncaban al segundo (hasta 1,3 s de error) → se redondean (máx. 0,8 s medido).
- Sin permiso de micrófono, macOS entrega silencio sin error y la grabación parecía funcionar → la barra de grabación avisa si en 3 s no llega ningún sonido.
- Tras un `kill -9` del backend, whisper seguía vivo y podía coincidir con la reanudación → archivos temporales únicos por tramo, PID registrado y eliminación del huérfano al reanudar; al cerrar la app el backend mata sus procesos hijos.

## [0.2.0] — 2026-11-03 · Fase 2: asignaturas y fuentes
### Añadido
- Migración `0002_sources_jobs.sql`: `sources`, `source_links` (N:M con unidades o sesiones), `source_versions`, `segments`, `jobs`.
- API: CRUD de asignaturas, unidades y sesiones; biblioteca (`/sources` con filtros), texto pegado/nota, contenido versionado con control de concurrencia, reintento; trabajos (`/jobs`, cancelar).
- Importación de archivos: validación por extensión + *magic bytes*, límites por tipo, copia inmutable (`0400`) con nombre UUID, SHA-256 y deduplicación por asignatura.
- Extractores PDF, DOCX, TXT, MD, RTF y CSV en un subproceso aislado con timeout y límite de CPU; segmentos con página, sección y offsets exactos.
- Audio: `ffprobe` + normalización a WAV 16 kHz mono con progreso y cancelación (la transcripción llega en la Fase 3).
- Cola de trabajos persistente con clases de recurso, recuperación tras cierre y cancelación.
- Rust: comandos `pick_files` (selector nativo) e `import_files`; solo se importan rutas elegidas por el usuario (diálogo o arrastrar y soltar), de un solo uso y con caducidad. El proxy de la UI bloquea `/api/v1/internal/`.
- UI: Mis asignaturas, detalle con árbol de unidades y sesiones, Importar (soltar, elegir, pegar), Biblioteca con filtros, detalle de material con vista previa, edición y versiones, y panel "En proceso".

### Corregido durante la fase
- Textos cortos en Windows-1252/Latin-1 se decodificaban con una página de códigos equivocada (el detector elegía cp775/cp1250) → se prueba primero Windows-1252 si todos los caracteres no ASCII son letras o signos occidentales.
- `SourceOut` recibía `needs_review` dos veces (error 500 al consultar una fuente).
- Prueba manual: tras importar no quedaba claro que el archivo ya estaba guardado y el botón desactivado del formulario de texto pegado parecía el de guardar. Ahora se muestra un aviso «Archivo guardado en la biblioteca», el estado de cada archivo se actualiza solo hasta «Listo» y el formulario de texto pegado está plegado.

## [0.1.0] — 2026-11-03 · Fase 1: estructura y entorno
### Añadido
- Monorepo: `app/` (Tauri 2 + React 19 + TS 7 + Tailwind 4), `backend/` (FastAPI, Python 3.13 con uv), `scripts/`.
- Supervisor Rust del backend: token de sesión por stdin, espera a `/health`, evento `backend://status`, apagado ordenado.
- Proxy Rust → Unix socket con validación de método, ruta y tamaño. Comandos `api_request` y `backend_status` con capabilities mínimas.
- Backend: middleware de token, socket 0600, salida al cerrar stdin, errores sin trazas, `/api/v1/health` y `/api/v1/system/info`.
- SQLite (WAL) con migraciones transaccionales y copia previa; `0001_init.sql` con `users`, `settings`, `subjects`, `units`, `sessions`.
- Frontend: `ApiTransport` (Tauri | HTTP para el futuro modo web), cliente tipado desde OpenAPI, navegación lateral en español, panel de estado del sistema.
- Prueba de empaquetado: `.app` con Python standalone incluido (`scripts/build-backend-runtime.sh`).
- `scripts/check.sh` y documentación base.

### Corregido durante la fase
- uvicorn aplicaba chmod 0666 al socket → el socket se crea manualmente con 0600.
- Un error de arranque podía terminar con código 0 (carrera con la vigilancia de stdin).
- `prepare_dirs` cambiaba permisos de directorios ajenos → ahora aborta si el directorio no es del usuario.
- El proceso hijo se lanzaba fuera del runtime de tokio (pánico al arrancar).
- El script de empaquetado copiaba un enlace simbólico y recortaba la instalación original de Python de uv → resuelve la ruta real y aborta si detecta un enlace. La instalación afectada se restauró con `uv python install --reinstall`.

## [0.0.1] — 2026-11-03 · Fases 0 y 0.5
- Arquitectura (`ARCHITECTURE.md`), plan (`TASKS.md`) y benchmarks en el equipo (`BENCHMARKS.md`).
