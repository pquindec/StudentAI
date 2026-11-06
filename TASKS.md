# TASKS — Plan de implementación

> Regla: no se avanza de fase sin aprobación expresa. Cada fase termina con un resumen (qué se hizo, archivos, pruebas, resultados, problemas, decisiones pendientes, siguiente paso).
> Arquitectura de referencia: `ARCHITECTURE.md`.

## Estado

| Fase | Estado |
|---|---|
| 0 — Investigación y arquitectura | ✅ Aprobada (2026-11-03) |
| 0.5 — Benchmarks en el equipo | ✅ Completada (2026-11-03) — ver `BENCHMARKS.md` |
| 1 — Estructura y entorno | ✅ Completada (2026-11-03) |
| 2 — Asignaturas y fuentes | ✅ Completada y verificada por el usuario (2026-11-03) |
| 3 — Grabación y transcripción | ✅ Aprobada por el usuario (2026-11-03) |
| 4 — IA local: apuntes y resúmenes | ✅ Aprobada por el usuario (2026-11-04) |
| 5 — RAG y asistente | ✅ Aprobada por el usuario (2026-11-04) |
| 6 — Exámenes | ✅ Completada (2026-11-04) — evidencia literal 100 %; en transcripciones 20 % de preguntas dudosas (limitación aceptada, ver BENCHMARKS §7) |
| 7 — Flashcards y seguimiento | 🔶 Implementada (2026-11-06), pendiente de aprobación — en transcripciones 30 % de tarjetas dudosas (ver BENCHMARKS §8) |
| 8–10 | ⏳ No iniciadas |

### Ajustes tras la prueba del usuario (2026-11-05)
- [x] Copiar texto en resúmenes, apuntes y asistente; resúmenes proporcionales al material (0.6.1)
- [x] Grabaciones guardadas filtradas por la asignatura elegida (0.6.2)
- [x] Retención del audio: el original se borra al transcribir; la copia ligera, a los 7/30 días o nunca; botón «Borrar audio ahora». La transcripción nunca se borra (0.6.2)
- [ ] Comprobar en la app: copiar texto, filtro de grabaciones y borrado del audio (usuario)

### Tareas nuevas surgidas de la Fase 0.5
- [x] (F1) Usar Ollama **oficial** en desarrollo (el de Homebrew no tiene salida estructurada); documentarlo en INSTALLATION.md
- [x] (F1) Tabla `users` y `owner_id` en el esquema inicial (ADR-009); interfaz `ApiTransport` en el frontend
- [ ] (F3) Sustituir `httpx` por `httpx2` en las pruebas cuando Starlette lo exija (sigue siendo solo un aviso)
- [x] (F2) Navegación entre pantallas: estado en memoria (`lib/nav.ts`), sin librería de rutas (una app de escritorio no necesita URLs)
- [ ] (F3) Gestor de modelos de whisper con verificación de tamaño y SHA-256
- [ ] (F3) Repetir el benchmark de transcripción con una **grabación real** de clase
- [ ] (F4) Comprobación de capacidades del proveedor LLM al arrancar
- [ ] (F6) Evaluación de calidad pedagógica de las preguntas con material real y revisión humana

---

## Fase 0.5 — Benchmarks en el equipo ✅
- [x] Instalar `rustup` (Rust 1.99.1), `uv`, `ffmpeg` 9.0.2, `whisper-cpp` 1.9.5 (Metal) y Ollama 0.40.14 (binario oficial en `bench/.ollama-official`)
- [x] Corpus de prueba: audio ES (4,4 min) + EN (3,5 min) sintéticos con ruido y referencia; 24 párrafos ES + 30 preguntas. *Desviación:* no se usaron PDF/DOCX (no hacía falta para comparar modelos; se prueban en la Fase 2) ni Core ML (el build de Homebrew solo trae Metal)
- [x] Scripts `bench/bench_whisper.py`, `bench_llm.py`, `bench_embed.py`
- [x] Comparación de los 4 whisper, 4 LLM y 3 embeddings + prueba de 1 h de audio
- [x] Prueba de convivencia (con las aplicaciones del usuario abiertas)
- **Criterio de aceptación:** `BENCHMARKS.md` con números reales y una elección justificada de los modelos por defecto (STT, LLM y embeddings).

## Fase 1 — Estructura y entorno ✅
- [x] Monorepo `app/`, `backend/`, `bench/`, `scripts/`; `git init` + `.gitignore`
- [x] Tauri 2 + React + TS + Vite + Tailwind; capabilities mínimas; CSP
- [x] Backend en Unix socket (0600); supervisor Rust; token por stdin; proxy `invoke` → socket; `/health` y `/system/info`
- [x] SQLite (WAL) + migraciones transaccionales + `0001_init.sql` + copia previa
- [x] Tipos TS generados desde OpenAPI (`npm run gen:api`)
- [x] ruff, mypy strict, oxlint (sustituye a ESLint, viene en la plantilla de Vite), prettier, clippy; pytest (21), vitest (4), cargo test (3)
- [x] Spike de empaquetado: `.app` con Python standalone (114 MB) funcionando fuera del repo
- [x] Docs: README, CLAUDE, PROJECT_CONTEXT, CHANGELOG, THREAT_MODEL v1, SECURITY, INSTALLATION, API_DOCUMENTATION, DATABASE, TESTING
- **Criterio de aceptación — cumplido:** la app abre en `tauri dev` y muestra el estado del backend obtenido por el socket; sin token → 401 (pytest + curl); el `.app` arranca su backend embebido fuera del entorno de desarrollo.

## Fase 2 — Asignaturas y fuentes ✅
- [x] CRUD de Subject, Unit (árbol) y Session
- [x] "Añadir fuente": selector nativo (Finder), arrastrar y soltar, pegar texto, nota manual
- [x] Validación de archivos (tipo real por *magic bytes*, tamaño, límites), copia inmutable, sha256 y deduplicación
- [x] Extractores: PDF (pypdfium2/pdfplumber), DOCX, TXT/MD, RTF, CSV + detección de "sin texto"
- [x] Vista previa y edición del texto extraído (versionado, conflicto de versiones)
- [x] Knowledge Library: lista, filtros, estado, vínculos N:M, borrado en cascada
- [x] Cola de trabajos persistente + panel "Procesando" (progreso y cancelación)
- [x] Importación de audio: probe y normalización (sin transcribir todavía)
- [x] Pruebas con archivos malformados (PDF corrupto, DOCX zip-bomb, extensión falsa, binario como .txt, vacío)
- [x] Verificación manual en la app (usuario, 2026-11-03): importación de PDF correcta; se mejoró la confirmación tras importar
- [x] Comprobar de nuevo la pantalla Importar con la mejora y el resto de formatos (usuario: «funciona bien»)
- **Criterio de aceptación:** crear una asignatura con temas e incorporar PDF, DOCX, TXT, MD, RTF, texto pegado y un MP3/M4A; todos aparecen con sus metadatos y una vista previa correcta; los archivos inválidos muestran un error comprensible.

## Fase 3 — Grabación y transcripción ✅
- [x] Recorder en Rust (cpal): selección de dispositivo, nivel de entrada, pausa/reanudar, segmentos de 60 s y manifiesto
- [x] Recuperación de grabaciones interrumpidas (al abrir la app: recuperar o descartar)
- [x] Permiso de micrófono (Info.plist), indicador permanente (barra roja + título de ventana)
- [x] Provider STT whisper.cpp: VAD, idioma automático o manual, tramos de 5 min con checkpoint, timestamps
- [x] Gestor de modelos: descarga explícita con verificación de tamaño y SHA-256
- [x] Editor de transcripción + reproductor sincronizado
- [x] Exportación a TXT y SRT
- [x] Aceptación (backend real como proceso): audio de 30 min, `kill -9` al 49 %, reapertura → transcripción completa, ordenada, sin duplicados, editable y exportable; timestamps dentro de ±1 s (máx. 0,8 s) frente a una pasada sin cortes
- [x] Prueba manual (usuario): grabación con micrófono (en desarrollo, lanzar desde Terminal.app: Termius no puede pedir el permiso)
- [ ] (F9) Empaquetar `whisper-cli` y `ffmpeg` dentro del `.app` (hoy se usan los de Homebrew)
- **Criterio de aceptación:** grabar 10 min (o importar un audio de 30 min), cerrar la app a la fuerza a mitad de proceso, reabrir y obtener una transcripción completa, editable, con timestamps correctos (±1 s) y exportable.

## Fase 4 — IA local: apuntes y resúmenes ✅
- [x] Interfaz `LLMProvider` + OllamaProvider (streaming, salida estructurada, keep_alive, solo localhost)
- [x] AI Resource Manager v1 (memoria disponible, modelo ligero si falta, espera visible, descarga del LLM antes de whisper)
- [x] Apuntes (breve / intermedio / detallado) con citas por punto
- [x] Resúmenes de una o varias fuentes con map-reduce y detección de contradicciones (mostradas sin resolver)
- [x] Prompts con el contenido delimitado como datos no confiables (delimitadores y ids falsos neutralizados)
- [x] Generación reanudable (checkpoint por bloque) y registro en `model_runs`
- [x] Revisión del usuario en la UI (resúmenes compactos y grabar mientras se genera, ajustados tras su prueba)
- **Criterio de aceptación:** apuntes y resumen de un documento y de una transcripción en los que cada apartado cita fragmentos existentes; 0 citas inventadas en el conjunto de prueba; la UI no se bloquea; la memoria no supera el presupuesto medido.

## Fase 5 — RAG y asistente
- [x] Chunking por tipo de fuente con trazabilidad (segmentos, página, tiempo, sección)
- [x] Embeddings + sqlite-vec + FTS5 + RRF; evaluación del reranker (no se incluye: Recall@5 = 1,0)
- [x] ScopeResolver (fuente / varias / tema con subtemas / asignatura / biblioteca, con exclusiones) aplicado en SQL
- [x] Chat con streaming, citas con enlace a página o timestamp, respuesta "no encontrado"
- [x] Pruebas de prompt injection (documentos con instrucciones maliciosas)
- [x] Revisión del usuario en la UI (siglas sin distinguir mayúsculas y lista de grabaciones, ajustadas tras su prueba)
- **Criterio de aceptación:** Recall@5 ≥ 0.8 en el conjunto de preguntas de prueba; todas las citas apuntan a fragmentos reales; una pregunta fuera del scope devuelve "no encontrado"; 0 fugas entre asignaturas en las pruebas.

## Fase 6 — Exámenes
- [x] Configuración (número, tipos, dificultad, temas, fuentes, tiempo, penalización, número de opciones, modo)
- [x] Generador + validación literal de la evidencia + deduplicación + LLM-juez
- [x] Aviso de "fuentes insuficientes"
- [x] Interfaz de examen (una pregunta a la vez, navegación, marcar, guardar progreso, temporizador)
- [x] Corrección automática y con rúbrica, explicaciones, temas débiles, material de repaso
- [x] Historial de intentos
- **Criterio de aceptación:** en un examen de 20 preguntas, el 100 % de las preguntas guardadas tiene una evidencia literal verificable; una revisión manual de una muestra confirma ≤ 5 % de preguntas ambiguas o incorrectas.

## Fase 7 — Flashcards y seguimiento
- [x] Generación de tarjetas con fuente (cita literal verificada, duplicados, revisor; por tandas hasta completar)
- [x] Planificador FSRS (`fsrs` 6.3.2, MIT) detrás de la interfaz `Scheduler`
- [x] Sesión de repaso (atajos 1–4 y espacio, intervalo en cada botón), dominio, próximas fechas, límite de nuevas al día
- [x] Edición, suspensión y borrado de tarjetas
- [x] Estadísticas (tiempo de estudio, repasos, retención, racha, exámenes, tarjetas, previsión) y «Para repasar hoy» en Inicio
- [x] Aceptación con reloj simulado: 62 días (`test_simulated_days_dates_and_stats_evolve`)
- [ ] Prueba en la app (usuario)
- **Criterio de aceptación:** estudiar tarjetas durante varios días simulados y ver que las fechas y las estadísticas evolucionan correctamente (pruebas con reloj simulado).

## Fase 8 — Cloud y optimización
- [ ] AnthropicProvider detrás de `LLMProvider`; clave en Keychain
- [ ] Enrutado por tarea, consentimiento con vista previa, auditoría, coste estimado y límite de gasto
- [ ] Modo offline verificado
- [ ] Ajustes del Resource Manager según las métricas reales
- **Criterio de aceptación:** cambiar una tarea entre local y cloud no modifica la lógica de negocio; sin consentimiento no sale ningún byte (verificado con un proxy de red en las pruebas); sin conexión, todo lo local sigue funcionando.

## Fase 9 — QA y seguridad
- [ ] Pruebas unitarias, de integración y E2E (Playwright sobre la UI de Tauri o WebDriver)
- [ ] SAST (Semgrep, Bandit), SCA (pip-audit, npm audit, cargo audit, Trivy), Gitleaks
- [ ] DAST de la API local (ZAP o pruebas propias sobre el socket)
- [ ] Fuzzing de archivos malformados; batería de prompt injection; revisión de capabilities de Tauri
- [ ] Pruebas de rendimiento y estabilidad (audio de 3 h, biblioteca de 500 documentos)
- **Criterio de aceptación:** informe con hallazgos, evidencias, severidad y estado; 0 críticos/altos abiertos.

## Fase 10 — Empaquetado
- [ ] `.app` + `.dmg`, Python embebido, binarios de ffmpeg (LGPL) y whisper incluidos
- [ ] Firma y notarización (requiere Apple Developer ID)
- [ ] Actualizador de Tauri (opcional)
- [ ] Prueba de instalación limpia en un usuario de macOS nuevo
- **Criterio de aceptación:** se instala y funciona en un Mac Apple Silicon limpio, con Ollama instalado mediante el asistente.
