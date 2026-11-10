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
| 7 — Flashcards y seguimiento | ✅ Aprobada por el usuario (2026-11-06) — en transcripciones 30 % de tarjetas dudosas: limitación aceptada, a mejorar en la Fase 8 con Claude (ver BENCHMARKS §8) |
| 8 — Cloud y optimización | ✅ Aprobada por el usuario (2026-11-06) |
| 9 — QA y seguridad | ✅ Aprobada por el usuario (2026-11-07) |
| 9.5 — Examen en vivo en el aula | 🔄 En curso (aprobada para empezar el 2026-11-07) |
| 10 — Empaquetado | ⏳ No iniciada |

### Ajustes tras la prueba del usuario (2026-11-05)
- [x] Copiar texto en resúmenes, apuntes y asistente; resúmenes proporcionales al material (0.6.1)
- [x] Grabaciones guardadas filtradas por la asignatura elegida (0.6.2)
- [x] Retención del audio: el original se borra al transcribir; la copia ligera, a los 7/30 días o nunca; botón «Borrar audio ahora». La transcripción nunca se borra (0.6.2)
- [x] Asistente: crea ejemplos, ejercicios y preguntas de opción múltiple a partir de las fuentes (con citas); si el tema no está en ellas, con conocimiento general y marcado «sin respaldo» (0.7.2)
- [x] Modo concurso en la sala en vivo: misma pregunta para todos, puntos por acierto y rapidez (sin rachas), vista para proyectar y teléfonos, avance automático, apodo a elegir, podio (decidido con el usuario, 2026-11-09)
- [ ] Probar el concurso en el aula con el proyector y varios teléfonos (usuario)
- [x] Exámenes escritos a mano: editor de preguntas (opción múltiple, V/F, corta con respuesta modelo y puntos clave), explicación, dificultad y fuente opcionales; listo al guardar; editable hasta que tenga intentos o salas, después «Duplicar para editar» (petición del usuario, 2026-11-09)
- [ ] Comprobar en la app: crear un examen a mano y usarlo en una sala en vivo (usuario)
- [ ] Comprobar en la app: copiar texto, filtro de grabaciones, borrado del audio y peticiones de crear en el asistente (usuario)

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
- [x] Prueba en la app (usuario)
- **Criterio de aceptación:** estudiar tarjetas durante varios días simulados y ver que las fechas y las estadísticas evolucionan correctamente (pruebas con reloj simulado).

## Fase 8 — Cloud y optimización
- [x] Dos vías detrás de `LLMProvider`: clave API (SDK `anthropic`, clave en el Keychain) y tu plan de Claude mediante el binario oficial de Claude Code (`claude -p`, sin leer sus credenciales). «Automática»: la clave si hay; si no, el plan
- [x] Enrutado por tarea (asistente, apuntes/resúmenes, generar, revisar), consentimiento con vista previa del texto exacto (por envío o para la sesión), auditoría sin contenido, coste estimado y límite mensual (5 $ por vía; con el plan, coste equivalente)
- [x] Modo offline verificado: si Claude falla o no hay conexión, el trabajo sigue en local (`test_offline_falls_back_to_local`)
- [x] Resource Manager revisado con métricas reales (104 llamadas del 9B: pico 8.460 MB, presupuesto 8.500 MB nunca superado): no requiere cambios
- [x] Revisor de tarjetas y preguntas con Claude (tarea «revisar»; se puede activar sola, sin enviar la generación)
- [ ] Medir con material real cuánto baja el 30 % de tarjetas dudosas con el revisor de Claude (necesita tu consentimiento; usuario)
- [ ] Probar en la app: Configuración › Claude, ventana de consentimiento y un envío real (usuario)
- **Criterio de aceptación:** cambiar una tarea entre local y cloud no modifica la lógica de negocio; sin consentimiento no sale ningún byte (verificado con un proxy de red en las pruebas); sin conexión, todo lo local sigue funcionando.

## Fase 9 — QA y seguridad
- [x] Pruebas unitarias, de integración y E2E (Playwright + WebKit, 7 flujos contra el backend real)
- [x] SAST (Semgrep, Bandit), SCA (pip-audit, npm audit, cargo audit, Trivy), Gitleaks
- [x] DAST de la API local (pruebas propias: token, aislamiento ruta a ruta, entradas hostiles, tamaño)
- [x] Fuzzing de archivos malformados; batería de prompt injection; revisión de capabilities de Tauri
- [x] Pruebas de rendimiento y estabilidad (audio de 3 h en 11,6 min; 500 documentos sin fallos)
- [x] Informe `QA_REPORT.md`: 0 críticos/altos; 3 medios y 6 bajos/informativos corregidos
- **Criterio de aceptación:** informe con hallazgos, evidencias, severidad y estado; 0 críticos/altos abiertos.

## Fase 9.5 — Examen en vivo en el aula (decidido con el usuario el 2026-11-07; diseño: ADR-012)
Contexto: en el aula, con la Wi-Fi de la universidad, 15–20 personas, para **practicar** y para **exámenes con nota**. Los participantes usan el navegador de su teléfono (Android/iOS) o de su ordenador; no instalan nada.

**0. Comprobación previa (bloqueante)**
- [x] Herramienta de prueba de red lista (`cd backend && uv run python -m app.live.netcheck`): QR, latencia, tiempo real (SSE) y reconexión; probada en la Wi-Fi de casa con un iPhone simulado (WebKit) → 4/4 correcto
- [x] Prueba en casa con un Android real: Chrome ✓ (46,5 ms, tiempo real 15/15); Samsung Internet ✗ (probable HTTPS forzado; la herramienta lo detecta)
- [ ] Confirmar la causa con Samsung Internet y decidir cómo soportarlo (decisión del usuario)
- [ ] **Prueba en el aula (usuario):** ejecutarla con 2–3 teléfonos reales (Android e iPhone) en la Wi-Fi de la universidad. *Plan original:* la app abre temporalmente una página de prueba con su QR; desde 2–3 teléfonos en la Wi-Fi de la universidad se comprueba si llegan al Mac (muchas redes aíslan los dispositivos). Si no llegan → decidir alternativa (router de viaje propio sin internet, o túnel con consentimiento) antes de seguir

**1. Servidor de la sala**
- [x] Servidor aparte y mínimo, solo en la red local y solo mientras haya una sala abierta; ofrece únicamente las rutas del participante. La API principal sigue sin puerto de red (Unix socket)
- [x] Código de sala aleatorio que caduca, límite de participantes, límite de peticiones por dispositivo y bloqueo ante códigos erróneos repetidos
- [x] Migración nueva `0009_live.sql`: sesiones en vivo y participantes; las respuestas reutilizan los intentos de examen (todo filtrado por `owner_id`)
- [x] El Mac no se suspende mientras la sala está abierta
- [x] Puerto 80 por defecto (el que menos redes filtran; 2026-11-10, la página no abría en la Wi-Fi de la universidad con 8765). Solo atiende lo que llega por la IP de la Wi-Fi; si no se puede, 8765. **Resultado 2026-11-10:** tampoco abre con el 80. El teléfono da `ERR_ADDRESS_UNREACHABLE` y no llega ninguna conexión al Mac: la Wi-Fi de la universidad aísla a los dispositivos (no era el puerto). Decidir alternativa (usuario)
- [x] **Acceso por internet con Cloudflare** (elegido por el usuario el 2026-11-10 tras probar un túnel manual que funcionó en la universidad): botón «Compartir por internet» en la sala, con aviso de consentimiento cada vez; el QR y el enlace pasan a `https://….trycloudflare.com`; se cierra al cerrar la sala o la app. Límites por IP real del teléfono a través del túnel
- [ ] Probar el botón en el aula con varios teléfonos (usuario). Decidir si `cloudflared` se incluye en el `.dmg` o se sigue instalando aparte (`brew install cloudflared`)

**2. En la app (tú)**
- [x] Botón «Compartir en vivo» en un examen: modo **Práctica** o **Con nota**
- [x] Sala de espera: código, **QR** y enlace; lista en tiempo real de quién entra; Admitir, Expulsar, Cerrar la sala, **Iniciar** y Terminar
- [x] Con nota: **admisión manual** de cada persona; un token por dispositivo y nombre único en la sala (desde otro dispositivo no se puede reutilizar el nombre)
- [ ] Lista de clase opcional (pegar o CSV) — no construida; la admisión manual la cubre. Decidir si hace falta
- [ ] Cambio de dispositivo aprobado por ti (hoy: expulsar y que vuelva a entrar, perdiendo lo respondido)
- [x] Durante el examen: quién responde, quién entregó, desconexiones, salidas de la página (informativo) y tiempo restante
- [x] Preguntas con respuesta correcta, justificación y fuente en la sala (solo en la app; petición del usuario tras la primera prueba con 1 teléfono, 2026-11-07)
- [x] Resultados: corrección automática (opción múltiple, V/F) y por IA local (respuestas cortas, marcada «Corregida por IA»); **revisas y ajustas** las notas antes de publicarlas; estadística por pregunta; exportar CSV

**3. En el teléfono (participantes)**
- [x] Página web ligera en español, sin recursos externos: nombre → «Esperando a que se inicie…» → examen
- [x] Empieza para todos a la vez; el tiempo lo controla tu Mac; respuestas guardadas al momento; si se bloquea el teléfono o se corta la Wi-Fi, vuelve donde estaba
- [x] Orden de preguntas y opciones distinto por persona; las respuestas correctas **nunca** llegan al teléfono antes de que publiques los resultados
- [x] Práctica: nota y explicaciones al entregar (si lo permites). Con nota: solo cuando publiques

**4. Privacidad y seguridad**
- [x] Se guardan solo nombre, dispositivo, respuestas y nota, en tu Mac; borrado manual («Borrar datos de la sala»); aviso en la página de entrada
- [ ] Borrado automático (plazo a decidir por el usuario; propuesta: 1 año con nota, 30 días práctica)
- [x] Ampliar `THREAT_MODEL.md` (T20–T25) y pruebas: DAST del servidor de la sala desde «otro dispositivo», fuerza bruta del código, suplantación, acceso a la API principal desde la red (debe ser imposible), sala cerrada → puerto cerrado

**Criterio de aceptación:**
- E2E con **20 participantes simulados** (navegadores móviles WebKit y Chromium): entrar, esperar, iniciar, desconexión y reconexión, entregar, corregir, publicar y exportar.
- Prueba real en el aula con al menos **3 teléfonos reales (Android e iOS)** en la Wi-Fi de la universidad.
- Ningún participante puede ver las respuestas correctas antes de publicarlas; desde la red no se alcanza nada salvo la sala abierta; al cerrar la sala no queda ningún puerto abierto.

**Estado del criterio (2026-11-07):** 20 teléfonos simulados a la vez por HTTP contra el servidor real ✓ (`test_twenty_phones_at_once`); E2E con la app real y 3 navegadores móviles (iPhone/WebKit y Android/Pixel) ✓: entrar, admitir, iniciar, responder, recargar y recuperar respuestas, entregar, corregir, publicar y cerrar. Sin cubrir en el E2E: exportar CSV (probado en unidad) y un corte real de Wi-Fi. **Pendiente: prueba real en el aula.**

## Fase 10 — Empaquetado
- [ ] `.app` + `.dmg`, Python embebido, binarios de ffmpeg (LGPL) y whisper incluidos
- [ ] Firma y notarización (requiere Apple Developer ID)
- [ ] Actualizador de Tauri (opcional)
- [ ] Prueba de instalación limpia en un usuario de macOS nuevo
- **Criterio de aceptación:** se instala y funciona en un Mac Apple Silicon limpio, con Ollama instalado mediante el asistente.
