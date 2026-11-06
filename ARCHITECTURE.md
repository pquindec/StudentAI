# AI Study Assistant — Arquitectura (Fase 0)

> Estado: **PROPUESTA — pendiente de aprobación**. Fecha: 2026-11-03.
> No existe código de producción. Este documento es el entregable de la Fase 0 junto con `TASKS.md`.

---

## 0. Resumen ejecutivo

- **Viable en un MacBook M5 de 24 GB**, con una condición: **un solo modelo grande cargado a la vez** y una cola de trabajos que serialice transcripción y generación.
- **Stack confirmado** (Tauri 2 + React/TS + FastAPI + SQLite + whisper.cpp + Ollama), con cinco ajustes que recomiendo (ver §2):
  1. El backend Python **no escucha en un puerto TCP**: usa un *Unix domain socket* privado y la UI le habla a través de Rust.
  2. La **grabación se hace en Rust** (no en el navegador del webview), escribiendo segmentos en disco para poder recuperar grabaciones cortadas.
  3. whisper.cpp y FFmpeg se ejecutan como **procesos hijos** que se lanzan por trabajo: al terminar, la memoria se libera sola.
  4. RAG con **SQLite FTS5 + sqlite-vec** (búsqueda híbrida) en la misma base de datos: sin servidor vectorial adicional.
  5. Repetición espaciada con **FSRS** en lugar de SM-2 (justificado en §9).
- **Benchmarks hechos (Fase 0.5, ver `BENCHMARKS.md`).** Modelos elegidos: whisper **large-v3-turbo q5_0**, LLM **qwen3.5:9b**, embeddings **qwen3-embedding:0.6b** con búsqueda híbrida. Es obligatorio usar **Ollama oficial**: el de Homebrew no tiene salida estructurada.

---

## 1. Entorno verificado (2026-11-03)

| Elemento | Estado |
|---|---|
| CPU / RAM | Apple M5, 10 núcleos, 24 GB memoria unificada |
| macOS | 27.0.1 |
| Node | v26.11.0 · npm 12.2.1 |
| Python | 3.14.7 (sistema) — **recomiendo fijar 3.12/3.13 con `uv`**: varias librerías de PDF/ML publican *wheels* para 3.14 con retraso |
| Homebrew | 7.0.9 |
| git | 2.54.0 (el directorio aún **no** es un repositorio) |
| Rust / cargo | **No instalado** (obligatorio para Tauri) |
| FFmpeg, whisper.cpp, Ollama, Tesseract, Docker | **No instalados** |
| Memoria libre en el momento de la medición | ~41 % (≈10 GB) con las herramientas actuales abiertas |

Disponibilidad de modelos comprobada en la web (no descargados, no medidos):

| Modelo | Disponible en Ollama | Tamaño aprox. | Observaciones |
|---|---|---|---|
| Qwen3.5 9B | `qwen3.5:9b` (GGUF Q4_K_M ≈ 6.6 GB), `qwen3.5:9b-mlx` (NVFP4 ≈ 8.9 GB) | 6.6–8.9 GB | Candidato principal. La variante MLX es más rápida según benchmarks de terceros |
| Gemma 4 12B | `gemma4:12b` (≈ 7.7–8 GB, QAT ≈ 7.2 GB) | 7–8 GB + caché | Ventana de 256K (no la usaremos entera: el coste de memoria se dispara) |
| Qwen3.5 4B | Por confirmar en el benchmark | ~3 GB | Alternativa ligera / modo "batería" |

**Riesgo abierto:** el backend MLX de Ollama (preview desde marzo 2026) aparece en algunas fuentes con un requisito de **32 GB** y vuelve en silencio al backend Metal/GGUF si el modelo no es compatible. Hay que **medirlo en tu Mac**, no suponerlo.

---

## 2. Decisiones técnicas cuestionadas

Pediste que cuestionara el stack donde tuviera sentido. Mantengo todas las tecnologías que propusiste, pero cambio **cómo** se integran.

### ADR-001 · Mantener Python/FastAPI como backend (con condiciones)
- **Alternativa considerada:** todo en Rust dentro de Tauri (un solo binario, empaquetado trivial).
- **Por qué Python:** el ecosistema de extracción (PDF, DOCX, RTF), RAG, FSRS y los SDK de Ollama y Anthropic es mucho más maduro, y el equipo va más rápido.
- **Coste que aceptamos:** empaquetar Python dentro del `.app` (Fase 10) es la parte más delicada del proyecto. Lo mitigamos desde la Fase 1 con `uv`, un intérprete *standalone* fijado y una prueba temprana de empaquetado (*spike*) en la Fase 1, no en la 10.

### ADR-002 · Comunicación UI ↔ backend por Unix socket + proxy en Rust
- **Problema:** una API en `127.0.0.1:8000` está expuesta a cualquier proceso local y a ataques de *DNS rebinding* desde el navegador. "Escucha en localhost" **no** es una medida de seguridad.
- **Decisión:** Uvicorn escucha en un **Unix domain socket** dentro del directorio de datos de la app (permisos `0600`). El frontend llama a comandos de Tauri (`invoke`). Rust reenvía la llamada al socket añadiendo un **token aleatorio por sesión**, que el backend recibe por `stdin` al arrancar (nunca por argumentos ni por variables de entorno visibles).
- **Consecuencias:** no hace falta CORS (el webview no habla HTTP con el backend), la superficie de red es nula y el progreso y el *streaming* del chat viajan por **Tauri Channels**.
- **Coste:** una capa de proxy en Rust (~200 líneas).

### ADR-003 · Grabación en Rust nativo, no en el webview
- `MediaRecorder` en WKWebView no permite elegir el dispositivo con fiabilidad, pierde datos si el proceso se cierra y no sirve para el audio del sistema.
- **Decisión:** un módulo Rust con `cpal` (CoreAudio) que escribe **segmentos WAV de 60 s** (`rec_0001.wav`…) más un `manifest.json`. Si la app se cierra, al reabrirla detecta el manifiesto incompleto y ofrece recuperar la grabación (como mucho se pierden unos segundos).
- **Audio del sistema** (fase posterior, módulo independiente): Core Audio *Process Taps* (macOS 14.2+) o ScreenCaptureKit, mediante un plugin Swift. Tiene un permiso propio y nunca bloquea la grabación del micrófono.

### ADR-004 · whisper.cpp y FFmpeg como procesos hijos efímeros
- Un proceso por trabajo: **cancelar = terminar el proceso**, **descargar el modelo de memoria = el proceso termina**. Sin fugas de memoria en el backend.
- whisper.cpp se compila con **Metal + Core ML** (el *encoder* corre en el Neural Engine) y **VAD Silero** para cortar el audio en los silencios.

### ADR-005 · Ollama como runtime local, detrás de una interfaz `LLMProvider`
- Ventajas: gestiona descargas, cuantizaciones y `keep_alive` (permite descargar modelos de memoria), y ofrece **salida estructurada con JSON Schema**, clave para los exámenes.
- Riesgo: es una dependencia externa que el usuario debe instalar. Mitigación: un asistente de instalación en la app que lo detecta y la interfaz `LLMProvider`, que permitiría añadir `mlx-lm` o `llama.cpp` sin tocar la lógica de negocio.
- Configuración obligatoria: `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1` y `keep_alive` corto controlado por el Resource Manager.

### ADR-006 · RAG dentro de SQLite (FTS5 + sqlite-vec)
- **Alternativas:** Chroma, LanceDB o Qdrant. Implican más procesos, más memoria y más superficie de ataque, sin ventaja apreciable con el volumen esperado de un estudiante (decenas de miles de fragmentos).
- **Decisión:** búsqueda por palabras clave con BM25 (FTS5) más búsqueda vectorial (`sqlite-vec`), combinadas con **Reciprocal Rank Fusion**. Un solo archivo de base de datos, con transacciones y copias de seguridad sencillas.
- Revisión prevista si se superan ~500 k fragmentos o la latencia p95 pasa de 300 ms.

### ADR-007 · Licencias: evitar dependencias AGPL/GPL en lo que se distribuye
- **PyMuPDF es AGPL** → se descarta. Usaremos `pypdfium2` (Apache/BSD) para el texto y `pdfplumber` (MIT) para las tablas.
- **FFmpeg de Homebrew es GPL** → en desarrollo no importa, pero para distribuir necesitamos un build **LGPL** o decodificar con AVFoundation los formatos que macOS ya soporta. La decisión se cierra en la Fase 10.
- **OCR:** el framework **Vision de Apple** (local, gratuito, buen soporte de español) es preferible a Tesseract.

### ADR-008 · Cola de trabajos persistente en SQLite (sin Redis ni Celery)
- Una tabla `jobs` y un *scheduler* `asyncio` en el backend. Los trabajos sobreviven a reinicios y se reanudan. No añadimos infraestructura que un estudiante tendría que instalar.

### ADR-009 · Preparado para un futuro "modo web" para compañeros (decidido 2026-11-03)
**Contexto:** la app es de uso personal, pero se quiere poder ofrecer más adelante una interfaz web para algunos compañeros.
**Decisión:** no se construye ahora, pero se diseña para que sea posible sin reescribir nada:
1. **El backend sigue siendo una API REST independiente del transporte.** En el escritorio va por Unix socket y proxy en Rust (ADR-002). En modo web, el mismo backend se arranca con un *gateway* HTTPS que añade autenticación real.
2. **El frontend usa una interfaz `ApiTransport`** con dos implementaciones: `TauriTransport` (`invoke` + Channels) y `HttpTransport` (`fetch` + SSE). Ningún componente de la UI llama a `invoke` directamente.
3. **Modelo de datos multiusuario desde el día 1:** tabla `users` y `owner_id` en `subjects`. En el escritorio existe un único usuario local. Todas las consultas filtran por propietario (barato ahora, muy caro de añadir después).
4. **Las funciones exclusivas de escritorio** (grabación nativa en Rust, audio del sistema, Keychain) se detectan por capacidades. En la web, la grabación usaría `MediaRecorder` del navegador con subida por trozos.
**Requisitos del modo web (fase futura, no incluida en las fases 1–10):** HTTPS; contraseñas con Argon2id o *passkeys*; sesiones con cookie `HttpOnly`/`SameSite=Strict` + CSRF; aislamiento estricto por usuario; límites de subida y de peticiones por usuario; reparto justo de la cola (un Mac M5 atiende **un trabajo de IA a la vez**: con 3–4 usuarios simultáneos habrá esperas); acceso por **Tailscale o VPN**, nunca expuesto directamente a Internet.
**Privacidad:** si alojas datos de compañeros en tu Mac, pasas a ser responsable de esos datos (RGPD). Habrá que informarles y permitirles borrar su cuenta y sus datos.

### ADR-010 · Interfaz solo en español (decidido 2026-11-03)
- Los textos de la UI se centralizan en un único módulo `es.ts` (sin una librería de i18n completa). Si algún día hace falta otro idioma, se migra a `i18next` sin tocar los componentes.
- Los prompts de IA están en español. El contenido de las fuentes puede estar en español o en inglés, y los materiales generados salen en el idioma que elija el usuario (por defecto, español).

### ADR-011 · Repetición espaciada con FSRS (decidido 2026-11-03)
- Se elige **FSRS** (ver §9). SM-2 queda descartado como algoritmo principal; la interfaz `Scheduler` permite añadirlo si algún día se necesita.

---

## 3. Vista de procesos

```
┌──────────────────────────── AI Study Assistant.app ────────────────────────────┐
│                                                                                │
│  WebView (React + TS + Tailwind)                                               │
│     │  invoke() / Channels  (sin HTTP, CSP estricta)                           │
│     ▼                                                                          │
│  Rust core (Tauri 2)                                                           │
│   ├─ Supervisor del backend (arranque, health-check, reinicio, apagado)        │
│   ├─ Proxy HTTP → Unix socket (+ token de sesión)                              │
│   ├─ Recorder (cpal → segmentos WAV + manifest)                                │
│   ├─ Diálogos de archivo, drag&drop, Keychain (claves API)                     │
│   └─ [futuro] plugin Swift: audio del sistema / OCR Vision                     │
│     │  HTTP sobre UDS (0600)                                                   │
│     ▼                                                                          │
│  Backend Python (FastAPI / Uvicorn, 1 proceso)                                 │
│   ├─ API (routers por dominio, Pydantic v2)                                    │
│   ├─ Servicios de dominio (subjects, sources, exams, cards, chat…)             │
│   ├─ Job Scheduler + AI Resource Manager                                       │
│   ├─ Pipelines: ingest → extract → normalize → chunk → embed → index          │
│   ├─ Providers: LLM (Ollama | Anthropic), STT (whisper.cpp), Embeddings        │
│   └─ Repositorios (SQLite + FTS5 + sqlite-vec, migraciones)                    │
│        │ spawn                      │ HTTP localhost                           │
│        ▼                            ▼                                          │
│   ffmpeg · whisper-cli         Ollama daemon (instalado por el usuario)        │
└────────────────────────────────────────────────────────────────────────────────┘
          Anthropic API (opcional, solo con consentimiento explícito)
```

**Ubicación de los datos:** `~/Library/Application Support/<bundle-id>/`
- `app.db` (SQLite en modo WAL)
- `sources/<uuid>/original.<ext>` (copia inmutable del original) y `normalized.wav`
  - Retención del audio (`services/audio_files.py`, 0.6.2): al terminar bien una transcripción se borra el original del audio; `normalized.wav` (copia ligera para escuchar y retranscribir) se borra a los `audio.keep_days` días (7 por defecto; 30 o 0 = siempre) desde la última transcripción. La limpieza corre al arrancar y cada hora, y nunca toca audios sin transcribir, con transcripción vacía o con trabajos en curso. La transcripción y lo generado con ella no se borran nunca.
- `recordings/<uuid>/` (segmentos y manifiesto)
- `models/whisper/` (modelos ggml descargados bajo demanda)
- `backups/`, `logs/` (logs sin contenido de las fuentes)

---

## 4. Módulos del backend

```
backend/app/
  api/            # routers: subjects, units, sessions, sources, jobs, transcripts,
                  #          notes, summaries, exams, flashcards, chat, settings, stats
  domain/         # modelos Pydantic, reglas de negocio, sin I/O
  services/       # casos de uso (orquestan repos + providers + jobs)
  pipelines/
    extract/      # pdf.py, docx.py, text.py, rtf.py, csv.py, ocr.py
    audio/        # probe.py (ffprobe), normalize.py (16 kHz mono), transcribe.py
    chunking/     # estrategias por tipo de fuente
    indexing/     # embeddings + FTS + vec
  rag/            # scope resolver, hybrid retriever, RRF, context builder, citations
  generation/     # notes, summaries, exam generator + validator, flashcards, grader
  providers/
    llm/          # base.py (LLMProvider), ollama.py, anthropic.py
    stt/          # base.py, whisper_cpp.py
    embeddings/   # base.py, ollama.py
  resources/      # AI Resource Manager, métricas, políticas
  jobs/           # cola persistente, scheduler, workers, cancelación
  security/       # validación de archivos, rutas, sanitización, consentimiento cloud
  db/             # conexión, migraciones versionadas, repositorios
```

**Contratos:** OpenAPI generado por FastAPI → tipos TypeScript generados automáticamente (`openapi-typescript`). Así el frontend no puede desincronizarse del backend sin que falle la compilación.

---

## 5. Modelo de datos (inicial)

### 5.1 Jerarquía académica
Tu lista (asignatura, curso, módulo, tema, clase, sesión) mezcla **estructura** y **eventos**. Propongo:

- **Subject** (asignatura) = espacio de trabajo, con propietario (`owner_id`, ver ADR-009). Atributo opcional `term` (periodo académico, p. ej. "2026-27").
- **Unit** = árbol flexible (`parent_id`) con `kind ∈ {course, module, topic}`. **"Curso" es una unidad dentro de la asignatura** (decidido 2026-11-03), por ejemplo `Asignatura → Curso → Módulo → Tema`. Todos los niveles intermedios son opcionales: también vale `Asignatura → Tema`.
- **Session** = evento en el tiempo, `kind ∈ {class, study}`, asociado opcionalmente a una Unit.
- **Source** pertenece a **una** Subject y se vincula a **N** Units o Sessions (`source_links`).
- Regla de integridad: un `parent_id` siempre apunta a una Unit de la **misma** Subject (se valida en el servicio y con un *trigger*).

### 5.2 Tablas

```
users(id, display_name, email?, password_hash?, role, created_at)   -- escritorio: 1 usuario local
subjects(id, owner_id→users, name, description, color, term, archived_at, created_at, updated_at)
units(id, subject_id→subjects, parent_id→units, kind[course|module|topic], title, position, …)
sessions(id, subject_id, unit_id?, kind, title, held_at, duration_ms, notes)

sources(id, subject_id, kind[recording|audio_import|pdf|docx|txt|md|rtf|csv|paste|note|generated],
        title, original_name, stored_path, sha256, mime, size_bytes,
        duration_ms?, page_count?, language?,
        status[pending|processing|ready|failed|cancelled], error_code?, error_detail?,
        imported_at, processed_at?, indexed_at?, index_status, metadata_json, deleted_at?)
source_links(source_id, unit_id?, session_id?)                 -- N:M

source_versions(id, source_id, version, origin[extracted|transcribed|user_edit],
                model_run_id?, created_at)                     -- las ediciones crean versión
segments(id, source_version_id, ordinal, text,
         start_ms?, end_ms?, page?, section_path?, char_start, char_end)
         -- unidad mínima localizable (frase con timestamp, párrafo con página)

chunks(id, source_id, source_version_id, subject_id, ordinal, text, token_count,
       segment_from, segment_to, start_ms?, end_ms?, page_from?, page_to?, section_path?, content_hash)
chunks_fts   (FTS5, contenido externo = chunks.text, tokenizer unicode61 remove_diacritics 2)
chunk_vectors(vec0: chunk_id, embedding float[D])  + embedding_models(id, name, dim, active)

jobs(id, type, resource_class[stt|llm|embed|io], priority, status, payload_json,
     progress, checkpoint_json, attempts, cancel_requested, error, parent_job_id,
     created_at, started_at, finished_at)
model_runs(id, job_id?, provider, model, task, input_tokens, output_tokens,
           duration_ms, peak_mem_mb, est_cost, cloud bool, consent_id?)
cloud_consents(id, task, provider, source_ids_json, preview_hash, granted_at, expires_at)

generated_docs(id, subject_id, kind[notes|summary], detail[brief|medium|detailed],
               title, content_md, scope_json, status, model_run_id, created_at, edited_at)
generated_doc_citations(doc_id, anchor, chunk_id, quote)

exams(id, subject_id, title, config_json, scope_json, mode[practice|timed], status, created_at)
questions(id, exam_id, type, stem, options_json?, answer_json, justification,
          distractor_rationale_json?, difficulty, unit_id?, validation[passed|rejected], validation_notes)
question_evidence(question_id, chunk_id, quote, char_start, char_end)
exam_attempts(id, exam_id, started_at, finished_at?, time_spent_ms, score, max_score, state_json)
attempt_answers(attempt_id, question_id, answer_json, flagged, is_correct?, points, feedback, graded_by)

flashcards(id, subject_id, unit_id?, front, back, explanation?, chunk_id?, created_at)
card_states(card_id, stability, difficulty, reps, lapses, state, due_at, last_review_at)
card_reviews(id, card_id, rating, reviewed_at, elapsed_days, scheduled_days)

chat_threads(id, subject_id, scope_json, title, created_at)
chat_messages(id, thread_id, role, content, citations_json, model_run_id?, created_at)

study_events(id, subject_id, kind, ref_id, started_at, ended_at)   -- estadísticas
settings(key, value_json) · schema_migrations(version, applied_at)
```

**Índices clave:** `sources(subject_id, status)`, `chunks(subject_id)`, `chunks(source_id)`, `jobs(status, priority, created_at)`, `card_states(due_at)`, `source_links(unit_id)`.

**Borrado:** al eliminar una fuente se eliminan en cascada sus versiones, segmentos, chunks, vectores y entradas FTS, además de los archivos. Las citas de apuntes y exámenes que apuntaban a ella quedan marcadas como "fuente eliminada", no se borran en silencio.

**Migraciones:** archivos SQL numerados (`0001_init.sql`…), aplicados dentro de una transacción al arrancar, con copia de seguridad automática previa (`sqlite3 .backup`).

---

## 6. Flujos principales

### 6.1 Grabación
```
[UI] Grabar → Rust Recorder (cpal) → recordings/<id>/seg_NNNN.wav + manifest.json (cada 60 s)
  pausa/reanudar = cerrar/abrir segmento · indicador visible permanente + duración
[Stop] → Rust concatena → POST /sources (kind=recording) → job "transcribe" (prioridad ALTA)
[Crash] → al arrancar: manifest sin "closed" → "¿Recuperar grabación de 47 min?"
```

> **Implementado (F3):** segmentos de 60 s vaciados cada segundo (`hound` actualiza la cabecera); al parar Rust une los segmentos y los importa por el endpoint interno con `kind=recording`. La transcripción corta el WAV normalizado en tramos de 5 min (sin recodificar), repite el final de cada tramo desde la última frase completa (no corta frases) y guarda un checkpoint por tramo. Texto: una línea por frase con `[mm:ss]`.

### 6.2 Importación de audio (misma importancia que grabar)
```
Finder / drag&drop → Rust valida extensión+tamaño → copia a sources/<id>/original.ext (+sha256, dedupe)
→ job probe (ffprobe: duración, codec; detecta archivos dañados)
→ job normalize (ffmpeg → WAV 16 kHz mono)
→ job transcribe (whisper.cpp + VAD, por bloques de ~5 min con checkpoint)
→ job index
Cancelable en cualquier paso; el original nunca se modifica. Lotes = N jobs encadenados.
```

### 6.3 Importación de documentos y texto
```
PDF   → pypdfium2 (texto por página) + pdfplumber (tablas) → si <N caracteres/página: marcar "posible escaneo" → OCR opcional (Vision)
DOCX  → python-docx (títulos, párrafos, tablas → Markdown)
TXT/MD→ detección de codificación (charset-normalizer) · RTF → striprtf · CSV → tabla con límite de filas
Pegar / nota manual → source kind=paste|note
→ vista previa del texto extraído → el usuario puede editarlo (crea source_version) → job index
```

### 6.4 Indexación (RAG)
```
nueva versión de una fuente → index_source (clase embed, prioridad batch, deduplicado)
→ chunking sobre los segmentos (rag/chunking.py): ~1.000 caracteres (máx. 1.600), un título
  abre chunk nuevo, audio ≤ 120 s por chunk; conserva seg_from/to, páginas, ms y sección
→ chunks + FTS5 (triggers) en UNA transacción → vectores qwen3-embedding:0.6b por lotes de 16
  (si Ollama o el modelo faltan, o hay < 1,5 GB libres: solo palabras, embedded = 0)
→ source_index = ready. Al arrancar se encola lo que falte o quedara a medias.
```
Implementado en la Fase 5. Sin solapamiento entre chunks: la cita apunta a segmentos, no a chunks.

### 6.5 Consulta con el asistente
```
scope (UI) → ScopeResolver → conjunto de source_ids permitidos (filtrado en SQL, NUNCA confiado al prompt)
→ hybrid search (BM25 top-k + vector top-k → RRF) → [rerank opcional si mejora métricas]
→ context builder (presupuesto de tokens, fragmentos delimitados y numerados [S1]…[Sn])
→ LLM (streaming) → validación de citas (cada [Sx] debe existir en el contexto)
→ respuesta + referencias (documento, página, sección o timestamp con enlace al reproductor)
→ si la recuperación tiene baja puntuación: "No encuentro esto en tus fuentes"
```
Implementado (Fase 5): top 30 por BM25 y top 30 por coseno → RRF k=60 → 6 chunks. Si ninguna
palabra coincide y ningún vector está a distancia ≤ 0,55, no se llama al modelo («no encontrado»).
Los fragmentos son los segmentos de esos chunks con ids `A12`; se envían las 3 últimas preguntas
y respuestas (sin fragmentos). Una respuesta sin ninguna cita válida, o `NO_ENCONTRADO`, se
guarda como «no encontrado». Sin reranker: el Recall@5 ya es 1,0 (BENCHMARKS §6). Ajustes de la 0.5.1: búsqueda adicional en mayúsculas de las palabras cortas que no existen tal cual (siglas mal transcritas), chunk siguiente al más relevante y un reintento si la respuesta no trae ninguna cita.
Peticiones de crear (0.7.2, `rag/answer.py::is_creative`, por patrones: verbo de crear + objeto
—«hazme una pregunta», «dame un ejemplo»—, «opción múltiple», «ejercicio», o «otra» tras una
respuesta de crear): con fragmentos relevantes, prompt `CREATE_SYSTEM` (conceptos de los
fragmentos y citados; la situación o las opciones incorrectas pueden ser nuevas) → `kind=created`.
Si no hay fragmentos relevantes, el modelo responde `NO_ENCONTRADO` o no cita nada, se crea sin
fragmentos con `GENERAL_SYSTEM` → `kind=general`, sin citas y marcado en la UI como «sin respaldo
en tus fuentes». El tipo se guarda en `chat_messages.stats_json` (sin migración).

### 6.6 Generación de exámenes (funcionalidad crítica)
```
1. Plan:    reparto de preguntas por tema/fuente según los chunks disponibles en el scope
2. Generar: por lote de chunks, el LLM devuelve JSON validado contra un esquema
            {type, stem, options, answer, justification, distractor_rationale, difficulty,
             evidence:[{chunk_id, quote}]}
3. Validar (determinista):
     a) cada quote aparece LITERALMENTE (tras normalizar) en su chunk → si no, se descarta
     b) esquema completo; nº de opciones correcto; una sola respuesta correcta
     c) duplicados: similitud de embeddings entre enunciados > umbral → se descarta
4. Validar (LLM-juez, prompt separado): ¿la evidencia implica la respuesta?, ¿es ambigua?,
   ¿algún distractor también es correcto? → passed/rejected + motivo
5. Si las válidas < las solicitadas → informar: "Tus fuentes permiten 14 de las 20 preguntas. ¿Generar 14?"
6. Persistir preguntas + evidencias (con página o timestamp)
Corrección: objetivas = deterministas; abiertas o cortas = LLM con rúbrica + evidencia, marcadas "corregido por IA"
```
**Implementado (Fase 6):** `generation/exam.py`, `generation/grading.py`, `services/exams.py`, handlers `generate_exam` y `grade_attempt`. Detalles: lotes de fragmentos consecutivos (~1.800 caracteres) repartidos en proporción a cada fuente; se generan ~1,4 × las pedidas; la cita debe aparecer literalmente (mismas palabras en orden, sin importar mayúsculas ni signos, ≥ 4 palabras) y se guardan sus offsets; se rechazan «todas/ninguna de las anteriores», opciones repetidas y respuestas fuera de rango; duplicados por Jaccard ≥ 0,7 o coseno de embeddings ≥ 0,92; el juez (lotes de 5) solo deja pasar `supported` sin ambigüedad ni otro distractor correcto. Tipos: opción múltiple, V/F y respuesta corta. Trabajo reanudable con checkpoints y que cede el turno a la transcripción.

### 6.7 Apuntes y resúmenes
Estrategia *map-reduce* sobre los chunks del scope: resumen por fuente o sección con citas, y luego una síntesis global que conserva las citas. Detección de **contradicciones**: el LLM compara afirmaciones de fuentes distintas sobre el mismo concepto y las muestra lado a lado, **sin resolverlas**.

> **Implementado (F4):** la unidad citable es el **segmento** (párrafo con página o frase con tiempo) de la versión fijada de cada fuente; los chunks de RAG llegan en la F5. Cada segmento se presenta al modelo con un id corto (`A12` = fuente A, ordinal 12). Bloques de ~10.000 caracteres (8K de contexto); *map* por bloque con salida JSON Schema → *reduce* (jerárquico si no cabe). Las citas se validan contra los ids entregados en cada llamada y se numeran [1], [2]… al guardar (`generated_doc_citations` → `segments`). Contradicciones solo en resúmenes de ≥ 2 fuentes y solo si citan ≥ 2 fuentes distintas. Avance por bloque en `jobs.checkpoint_json`.

---

## 7. Modelos de IA y presupuesto de memoria

### 7.1 Presupuesto (24 GB)
| Consumidor | Estimación | Comentario |
|---|---|---|
| macOS + WindowServer | 4–5 GB | |
| VS Code + Claude Code + navegador | 4–7 GB | Tu escenario de desarrollo |
| Docker (si está abierto) | 2–4 GB | Hoy no está instalado |
| App (webview + Rust + Python) | 0.5–0.8 GB | |
| **Disponible para IA** | **≈ 8–10 GB de forma segura** | |

Consecuencias:
- **Qwen3.5 9B Q4 (6.6 GB + 1–2 GB de caché KV con 16K de contexto)** encaja. Es el **candidato por defecto**.
- **Gemma 4 12B (≈ 8 GB + caché)** está al límite si tienes las herramientas de desarrollo abiertas. Solo se usará si el benchmark demuestra mejor calidad y la memoria libre lo permite.
- La variante **MLX NVFP4 (8.9 GB)** es más rápida pero ocupa más. Hay que medir si compensa.
- **whisper large-v3-turbo** (≈ 1.5–2 GB en ejecución) **no** convive con el LLM por defecto: se serializa.
- **Embeddings:** modelo pequeño multilingüe (candidatos: `qwen3-embedding:0.6b`, `embeddinggemma`, `bge-m3`), ≈ 0.6–1.2 GB. Puede convivir con whisper, pero no con el LLM si la presión de memoria es alta.

> **Actualización tras la Fase 0.5 (medido):** la memoria disponible real con tus herramientas abiertas es menor que la estimada (había ~6,4 GB de swap antes de empezar). El 9B funciona pero deja ~2 GB libres; Gemma 12B añade +4,7 GB de swap → descartado. Valores por defecto: **contexto de 8K**, `keep_alive` ≤ 2 min y paso automático al 4B si quedan menos de ~3 GB libres. Ver `BENCHMARKS.md §4`.
>
> **Requisito nuevo:** al arrancar, el proveedor LLM ejecuta una comprobación de capacidades (salida estructurada, modelo presente, versión). El Ollama de Homebrew 0.40.14 no tiene `xgrammar` y no sirve para generar exámenes.

### 7.2 Benchmark realizado (Fase 0.5) — resultados en `BENCHMARKS.md`
| Prueba | Métrica |
|---|---|
| whisper base / small / medium / large-v3-turbo-q5 | RTF (segundos de proceso por minuto de audio), WER en un audio ES y otro EN de 5 min con transcripción de referencia, pico de memoria |
| Qwen3.5 9B (GGUF y MLX), Gemma 4 12B, Qwen3.5 4B | tokens/s de *prefill* y *decode* con 4K y 16K de contexto, pico de memoria, % de JSON válido en 20 generaciones de preguntas |
| Embeddings (3 candidatos) | ms/chunk, memoria y Recall@5 en 30 preguntas sobre documentos de prueba en español |
| Convivencia | ¿hay *swap* o presión de memoria "amarilla/roja" con VS Code y el navegador abiertos? |

Herramienta: un script `bench/` que registra `ps`/`vm_stat`/`powermetrics` (este último necesita `sudo`; si no se concede, se mide solo CPU y RAM) y guarda los resultados en `BENCHMARKS.md`. **Ningún modelo se elige sin estos números.**

---

## 8. AI Resource Manager

**Clases de recurso:** `stt`, `llm`, `embed`, `io`. **Regla base:** como mucho **un trabajo `stt` o `llm` pesado a la vez**. Los trabajos `io` (extracción, ffprobe) pueden ir en paralelo (2 a la vez).

**Prioridades (de mayor a menor):**
1. Interactivos (chat, corrección de una respuesta de examen): el usuario está esperando.
2. Transcripción de una grabación recién terminada.
3. Importaciones de audio, indexación.
4. Generación en lote (exámenes, apuntes, flashcards).

Un trabajo de prioridad baja en curso **no se interrumpe** (es caro), pero cede el turno entre lotes: los trabajos se dividen en pasos con *checkpoint*.

> **Implementado (F4):** la generación de apuntes/resúmenes comprueba entre partes si hay en cola un trabajo pesado más prioritario (la transcripción de una grabación); si lo hay, vuelve a la cola sin contar como intento y se reanuda desde su checkpoint. La grabación en sí nunca depende de la cola: la hace el núcleo nativo.

**Antes de lanzar un trabajo pesado:**
1. Lee la memoria disponible (`psutil` + `kern.memorystatus_level` / presión de memoria de macOS).
2. Si `disponible < requisito_medido_del_modelo + margen de 1.5 GB` → descarga el modelo inactivo (`keep_alive=0` en Ollama), espera y vuelve a comprobar.
3. Si aun así no cabe → el trabajo queda "en espera de memoria" (visible en la UI) o se ofrece el modelo ligero. **Nunca se fuerza.**

**Descarga de modelos:** el LLM se mantiene cargado 5 min tras el último uso (configurable) y luego se libera. whisper se libera al terminar su proceso.

**Métricas:** cada `model_run` guarda la duración, los tokens y el pico de memoria. Una pantalla de diagnóstico en Configuración muestra el modelo cargado, la cola y el consumo.

**Perfil "estoy desarrollando":** opción que reduce el contexto a 8K y usa el modelo 4B para tareas no críticas.

---

## 9. Flashcards: FSRS (decidido)

- SM-2 (1987) usa un único factor de facilidad y tiende a programar demasiados repasos. **FSRS** (usado por defecto en Anki desde 2023) modela estabilidad y dificultad, y con los mismos repasos consigue más retención.
- Hay una implementación open source mantenida (`py-fsrs`, MIT). La interfaz de valoración es la misma (Otra vez / Difícil / Bien / Fácil).
- Si prefieres SM-2 por motivos académicos (p. ej. para explicarlo en una memoria), el planificador queda detrás de una interfaz `Scheduler` y se pueden tener ambos.

**Implementación (Fase 7):**
- `srs/base.py` define `Scheduler` (`review`, `preview`) y `CardState`; `srs/fsrs_scheduler.py` lo implementa con `fsrs==6.3.2` (MIT, solo depende de `typing-extensions`), retención deseada 0,9, pasos de aprendizaje 1 y 10 min, reaprendizaje 10 min. Sin *fuzzing*: la fecha que muestra cada botón es la que se aplica y las pruebas son deterministas.
- Cola de repaso: aprendizaje vencido → repasos vencidos → nuevas (límite diario, 20 por defecto, contado por día local). Si no queda nada, se adelantan pasos de aprendizaje de los próximos 20 min.
- «Dominada» = en repaso con estabilidad ≥ 21 días.
- Generación de tarjetas con el mismo esquema que los exámenes (§6.6): lotes repartidos por fuentes, cita literal verificada, duplicados fuera y revisor separado (`generation/cards.py`).
- Estadísticas sin tabla `study_events`: se calculan de `card_reviews` (máx. 2 min por tarjeta) y de los intentos de examen (máx. su tiempo límite o 3 h). No mide el tiempo leyendo apuntes.
- Reloj inyectable: las rutas reciben la hora como dependencia (`api/deps.py::current_time`), y las pruebas simulan 60 días.

---

## 10. Proveedor cloud (Claude API)

- Desactivado por defecto. Se activa en Configuración con la clave API guardada en el **Keychain de macOS** (nunca en SQLite ni en archivos).
- Se elige qué tareas pueden ir a la nube (p. ej. solo "validar preguntas" o solo "resumen de asignatura completa").
- **Pantalla de consentimiento por envío** (o por sesión, si el usuario lo elige): muestra las fuentes, el número de fragmentos, una vista previa del texto exacto, el modelo y el coste estimado. El consentimiento se registra en `cloud_consents`.
- **Los audios nunca se envían**: solo texto (fragmentos recuperados).
- Límite de gasto mensual con bloqueo duro; el coste se registra en `model_runs`.
- Sin conexión, todo funciona en local; las tareas configuradas para la nube pasan a local o esperan, según prefieras.

---

## 11. Seguridad y privacidad (resumen; detalle en `THREAT_MODEL.md` en la Fase 1)

| Amenaza | Control |
|---|---|
| Otro proceso local llama a la API | Unix socket `0600` + token por sesión + sin puerto TCP (ADR-002) |
| XSS por contenido importado o generado por el LLM | React sin `dangerouslySetInnerHTML`; Markdown renderizado sin HTML crudo (`react-markdown` sin `rehype-raw`); CSP estricta en Tauri |
| Permisos Tauri excesivos | Capabilities mínimas; sin acceso libre a `fs` desde JS; Rust solo expone comandos concretos |
| Path traversal / symlinks | Los archivos se copian a rutas generadas con UUID; nunca se usa el nombre original como ruta; `realpath` + comprobación de prefijo |
| Archivos maliciosos o enormes (DoS, bombas zip en DOCX) | Límites de tamaño, de páginas, de duración y de ratio de descompresión; extracción en subproceso con *timeout* y límite de memoria |
| Prompt injection en documentos | El contenido va siempre delimitado como DATOS; el prompt de sistema lo declara no confiable; **el modelo no tiene herramientas ni acciones**; la salida se valida contra un esquema; el *scope* se aplica en SQL |
| Fuga entre asignaturas | `subject_id` es obligatorio en la recuperación; mezclar asignaturas requiere una acción explícita del usuario |
| Fuga hacia la nube | Consentimiento explícito con vista previa + registro de auditoría |
| Secretos | Keychain; Gitleaks en CI |
| Dependencias | `pip-audit`, `npm audit`, `cargo audit`, Trivy; versiones fijadas con *lockfiles* |
| Logs | Sin contenido de las fuentes; solo IDs y métricas |

Datos en reposo: se confía en **FileVault**. El cifrado de la base de datos (SQLCipher) queda como opción futura si lo pides (complica el uso de `sqlite-vec`).

---

## 12. Frontend

- React + TS + Vite + Tailwind; componentes accesibles con **Radix UI** (shadcn/ui); estado del servidor con **TanStack Query**; rutas con **TanStack Router** o React Router.
- La navegación lateral sigue tu lista. "Grabaciones" e "Importar" se unifican en un botón global **"Añadir fuente"** (grabar / audio / documento / pegar texto) accesible desde cualquier pantalla, para que el estudiante no tenga que pensar en qué sección está.
- Panel de **"Procesando"** global (cola de trabajos con progreso, cancelar, reintentar).
- Reproductor de audio sincronizado con la transcripción: al hacer clic en una cita con timestamp, el audio salta a ese punto.
- Modo claro y oscuro, navegación por teclado, mensajes de error en lenguaje no técnico.

---

## 13. Riesgos principales

| # | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | Empaquetar Python en el `.app` (firma y notarización) | Alta | Alto | *Spike* de empaquetado en la Fase 1; python-build-standalone + `uv` |
| R2 | El modelo de 9B genera preguntas pobres o mal fundamentadas | Media | Alto | Validación en dos capas (literal + LLM-juez); opción cloud para validar; benchmark de calidad con un conjunto de referencia |
| R3 | Presión de memoria con las herramientas de desarrollo abiertas | Media | Medio | Resource Manager + perfil ligero + serialización |
| R4 | El backend MLX de Ollama no funciona con 24 GB | Media | Bajo | Usar GGUF/Metal (más lento, estable) |
| R5 | Licencias GPL/AGPL (FFmpeg, PyMuPDF) | Alta si no se controla | Alto | ADR-007 |
| R6 | Captura del audio del sistema (APIs y permisos cambiantes) | Media | Medio | Módulo independiente y posterior |
| R7 | Calidad del OCR y de las tablas en PDF | Media | Medio | Vista previa + edición manual obligatoria antes de indexar si la calidad es baja |
| R8 | Python 3.14 sin *wheels* para algunas librerías | Media | Bajo | Fijar 3.12/3.13 |
| R9 | Contexto largo (asignatura completa) supera el contexto útil del modelo | Alta | Medio | Map-reduce; nunca "meter todo en el prompt" |

---

## 14. Plan

Ver **`TASKS.md`**: fases 0.5 a 10 con entregables y criterios de aceptación.

## 15. Decisiones

**Cerradas (2026-11-03):** arquitectura aprobada (ADR-001…008); Fase 0.5 ejecutada; FSRS (ADR-011); "Curso" = unidad dentro de la asignatura (§5.1); uso personal con un posible modo web futuro para compañeros (ADR-009); interfaz en español (ADR-010).

**Consecuencia del uso personal:** no hace falta firma ni notarización de Apple en la Fase 10 (basta una firma *ad-hoc* para tu Mac). Las restricciones de licencias (ADR-007) se mantienen por si se ofrece a compañeros.

**Pendientes:** ninguna que bloquee la Fase 1.
