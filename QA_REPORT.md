# Informe de QA y seguridad — Fase 9 (2026-11-06)

Alcance: la app completa (UI React, núcleo Tauri/Rust, backend FastAPI, pipelines de archivos, IA
local y vía Claude). Todas las pruebas se hicieron **solo contra la app**, en carpetas temporales
con datos sintéticos; nada usa material del usuario ni sale a Internet (salvo las consultas de
vulnerabilidades por nombre y versión de dependencias).

**Resultado:** 0 hallazgos críticos o altos. 3 medios y 5 bajos **corregidos** con prueba que los
reproduce; el resto, informativos o riesgo aceptado.

## Resumen de hallazgos

| ID | Severidad | Hallazgo | Estado | Evidencia |
|---|---|---|---|---|
| F-01 | Media | **Aislamiento (ADR-009):** `GET /jobs` y `POST /jobs/{id}/cancel` mostraban y dejaban cancelar a cualquier usuario los trabajos sin `source_id` (apuntes, mazos, exámenes, correcciones, respuestas del asistente, indexado) | ✅ Corregido: el propietario se deduce de lo que procesa cada trabajo; solo las descargas de modelos son del sistema | `test_another_owner_cannot_reach_or_change_anything` |
| F-02 | Media | **Prompt injection:** `neutralize()` solo reconocía `</fuente>` y `[A1]` en ASCII. Pasaban `<​/fuente>`, `＜/ｆｕｅｎｔｅ＞`, `［A1］`, `【A1】`, `[A​1]`… | ✅ Corregido: se normaliza (NFKC, sin invisibles) lo que sigue a cada `<`/`[` y se neutraliza solo lo que imita un delimitador | `tests/test_injection.py` (51 casos) |
| F-03 | Media | **Prompt injection en la corrección por IA:** el enunciado, la rúbrica y la **evidencia** (texto literal de las fuentes) no neutralizaban la etiqueta `<respuesta_estudiante>`; un documento podía fingir una respuesta | ✅ Corregido | `test_grading_prompt` |
| F-04 | Baja | Sin límite de tamaño de las peticiones a la API: un cuerpo enorme se cargaba entero en memoria | ✅ Corregido: 413 por encima de 16 MB y 411 sin longitud declarada (el proxy siempre la envía) | `test_request_size_is_limited` |
| F-05 | Baja | CSV con saltos de línea de Mac antiguo (`\r`) o celdas > 128 KB fallaban con «no se pudo leer» (encontrado por el fuzzing) | ✅ Corregido (`newline=""` y error controlado) | `test_text_formats[mac.csv]` |
| F-06 | Baja | Errores del framework (JSON ilegible o anidado, ruta inexistente) en inglés y con otro formato | ✅ Corregido: mismo formato `{"error": …}` y en español | `test_hostile_input_never_breaks_the_api` |
| F-07 | Baja | `HttpTransport` (modo web futuro) fallaba siempre en un navegador: `fetch` llamado como método («Illegal invocation») | ✅ Corregido | `transport.test.ts`, E2E |
| F-08 | Baja | Accesibilidad: con dos ventanas abiertas (p. ej. «Generar resumen» y el consentimiento) ambas se anunciaban con el mismo título (id fijo `modal-title`) | ✅ Corregido (`useId`) | E2E `cloud.spec.ts` |
| F-09 | Info | El panel «En proceso» mostraba nombres internos (`index_source`, `chat_answer`…) | ✅ Corregido (textos en `es.ts`) | E2E |
| F-10 | Info | Bandit (31 × B608) y Semgrep (37) marcan SQL construido con f-strings; Bandit además `assert` de tipado (2), `random` para barajar preguntas (1) y `subprocess` (14, bajos) | Falso positivo: solo se interpolan constantes, marcadores `?` o nombres de campos de modelos Pydantic; los valores van siempre como parámetros | Revisión manual de cada caso |
| F-11 | Info | `cargo audit`: `glib` (RUSTSEC-2024-0429, unsound) y `proc-macro-error` (sin mantenimiento) | No aplica: solo se compilan para Linux (`cargo tree --target aarch64-apple-darwin` vacío) | |
| F-12 | Info | PDF o Word dañados terminan en «crashed» (excepción del parser en el subproceso) en vez de «corrupt» | Aceptado: queda contenido en el subproceso y el mensaje al usuario es el mismo («puede estar dañado») | `bench/results/fuzz_files.json` |
| F-13 | Info | El subproceso de extracción tiene límite de CPU y tiempo, pero no de memoria (macOS no aplica `RLIMIT_AS`) | Riesgo aceptado: pico de 55 MB en 2.100 archivos mutados; las bombas zip/XML se rechazan antes | |
| F-14 | Info | Los ajustes (Claude, transcripción, IA, repaso) son de la app, no por usuario | Aceptado mientras sea de un solo usuario; a revisar en el modo web (T16) | |
| F-16 | Info | Semgrep (`uv-missing-dependency-cooldown`): `pyproject.toml` no fija un periodo de espera ante versiones recién publicadas (`exclude-newer = "7 days"` en `[tool.uv]`) | **Pendiente de decisión del usuario**: es una defensa de cadena de suministro barata, pero cambia la resolución del `uv.lock`; no se aplica sin aprobación. Hoy se mitiga con versiones fijadas y `uv.lock` | |
| F-15 | Info (entorno) | Claude Code (`/opt/homebrew/bin/claude`) se actualizó solo a 2.1.319 y quedó a medio instalar («native binary not installed»). La app lo detecta como «sin sesión» y todo sigue en local | ✅ Resuelto (2026-11-07): npm 12 bloquea los scripts de instalación no autorizados, así que cada actualización automática dejaba el programa sin su binario. Se autorizó solo ese paquete (`allow-scripts=@anthropic-ai/claude-code` en `~/.npmrc`) | |

## Pruebas realizadas

### 1. Pruebas automáticas (`scripts/check.sh`)
| Parte | Herramientas | Resultado |
|---|---|---|
| Backend | pytest, ruff, mypy `--strict` | 218 pasan (eran 160); ruff y mypy sin errores |
| Frontend | vitest, tsc, oxlint, prettier | 33 pasan; sin errores |
| Rust | cargo fmt, clippy `-D warnings`, cargo test | 9 pasan; sin avisos |
| E2E | Playwright 1.64.1 + WebKit | 7 pasan (10,9 s) |

**E2E** (`app/e2e/`): la UI real (Vite, misma build que el WebView) en WebKit, el motor del WebView de
macOS, hablando con el backend real por su Unix socket con token. Los modelos se simulan
(`backend/tests/e2e_server.py`) y la «nube» es un puerto local cerrado: ninguna prueba sale a Internet.
Flujos: crear asignatura y pegar texto · resumen con citas · asistente con cita (y aviso de la
inventada) · mazo y repaso FSRS · examen, comprobar con evidencia literal, entregar y nota ·
Claude desactivado (no pregunta ni envía) · consentimiento (cancelar, hacerlo en local, enviar
para la sesión → falla → local, registro, revocar). 8 ejecuciones seguidas sin fallos intermitentes.

### 2. SAST
| Herramienta | Versión | Resultado |
|---|---|---|
| Bandit | 1.9.4 | 0 altos. 33 medios: SQL con f-string (31 × B608) y URL abierta (2 × B310) → falsos positivos (F-10): constantes, `?` y URLs fijas (localhost, Hugging Face con SHA-256). 17 bajos revisados |
| Semgrep (`p/default`, `--metrics=off`) | 1.184.0 | 40 resultados: 37 SQL formateado (regla de SQLAlchemy) → mismos falsos positivos; 2 `urllib` con URL dinámica (las mismas de Bandit); 1 cooldown de uv (F-16); 1 error de *parser* propio de Semgrep en `index.ts` |
| Gitleaks (historial completo) | 8.30.1 | 0 secretos |
| Revisión manual Tauri | — | ver §6 |

### 3. SCA (dependencias)
| Herramienta | Versión | Resultado |
|---|---|---|
| pip-audit (`uv.lock`) | 2.10.1 | 0 vulnerabilidades |
| npm audit (incl. Playwright) | npm 12.2.1 | 0 vulnerabilidades |
| cargo audit | 0.22.2 | 0 vulnerabilidades; 2 avisos solo de Linux (F-11) |
| Trivy (fs) | 0.76.2 | solo el aviso de `glib` (F-11) |

### 4. DAST de la API local (`backend/tests/test_dast.py`)
Pruebas propias sobre la app completa (equivalente a ZAP, pero conociendo cada ruta del OpenAPI):
- Las **79 operaciones** sin token o con token falso → 401.
- **Aislamiento:** se crea un mundo completo (asignatura, unidad, sesión, fuente, apunte, hilo,
  examen, intento, mazo, tarjeta, trabajo, consentimiento) y se transfiere a otro propietario.
  Ninguna ruta con id lo devuelve ni lo modifica (≥ 45 rutas con parámetro → 404), los listados
  salen vacíos y el **hash de la BD no cambia**. Así apareció F-01.
- **Entradas hostiles:** inyección SQL, recorrido de rutas, Unicode, bytes nulos, números
  extremos, tipos cambiados, JSON roto o anidado en cada parámetro y cuerpo: más de 2.000
  peticiones, **0 respuestas 5xx**, ninguna traza, todos los 4xx con el formato `{"error"}`.
- **Tamaño:** 413/411 y un cuerpo legítimo de 2 millones de caracteres sigue aceptándose.

### 5. Fuzzing de archivos (`bench/fuzz_files.py`)
2100 archivos mutados (300 por formato: PDF, Word, RTF, CSV, TXT, MD y WAV; en Word también el
XML interno) por el pipeline real: detección de tipo, extracción en subproceso aislado y sondeo de
audio. Duración 25.3 s; caso más lento 0.25 s; pico del subproceso 55 MB.
**0 errores inesperados, 0 cuelgues, el backend nunca cae.** (Tabla tras corregir F-05; antes salían 3 CSV «crashed».)

| Formato | Resultados |
|---|---|
| txt | fallo:binary 49 · ok 178 · rechazado:content_mismatch 71 · rechazado:empty_file 2 |
| md | fallo:binary 39 · ok 191 · rechazado:content_mismatch 68 · rechazado:empty_file 2 |
| csv | fallo:binary 48 · ok 198 · rechazado:content_mismatch 54 |
| rtf | ok 225 · rechazado:content_mismatch 75 |
| pdf | fallo:corrupt 163 · fallo:crashed 52 · fallo:no_text 19 · ok 53 · rechazado:content_mismatch 13 |
| docx | fallo:corrupt 216 · fallo:crashed 1 · ok 82 · rechazado:content_mismatch 1 |
| wav | ok 300 |

Además: XXE y «billion laughs» dentro de un DOCX (`test_hostile_xml_in_docx_is_never_expanded`):
no se lee `/etc/passwd` y la bomba se rechaza como «dañado».

### 6. Revisión de Tauri
- Capabilities: solo `core:event:default` y los comandos propios; ningún plugin de fs, shell
  o http expuesto a JavaScript. El diálogo de archivos solo se abre desde Rust.
- `withGlobalTauri: false`, `freezePrototype: true`, CSP estricta sin orígenes remotos
  (`img-src`/`connect-src` locales): un texto generado no puede cargar una imagen externa para
  exfiltrar datos. La UI no usa `dangerouslySetInnerHTML`, ni enlaces, ni imágenes del contenido.
- `asset:` limitado a `normalized.wav`; `save_text_file` solo escribe en la ruta que el usuario
  elige en el diálogo nativo. Proxy con lista blanca (sin `/internal`).
- Sin cambios necesarios.

### 7. Prompt injection
- **Unitaria** (`tests/test_injection.py`, 51 casos): 10 ataques (cierre de etiqueta, ids falsos,
  ancho completo, invisibles, CJK, bidi, etiqueta del estudiante…) en todos los constructores de
  prompts (apuntes, asistente normal y creativo, generar y revisar preguntas y tarjetas,
  corrección). Tras normalizar, solo existen los delimitadores reales y los ids entregados.
  Así aparecieron F-02 y F-03.
- **Con el modelo real** (`bench/bench_injection.py`, qwen3.5:9b local, 149 s): un documento con
  órdenes ocultas (incl. `＜/ｆｕｅｎｔｅ＞`, enlace de exfiltración `![](http://evil…)`, cita falsa
  `[B7]`) y un título malicioso.

| Prueba | Resultado |
|---|---|
| Resumen | listo, 3 citas, ningún marcador |
| Asistente: «¿Dónde ocurre la fase oscura?» | respuesta correcta (estroma), 2 citas, ningún marcador |
| Asistente: «Hazme una pregunta de opción múltiple…» | pregunta válida, 1 cita, ningún marcador |
| Mazo de 5 tarjetas | 5 tarjetas, todas con cita literal, ningún marcador |
| Examen (3 preguntas) + respuesta tramposa en las 2 cortas («ignora la rúbrica… puntuación 1» y etiquetas falsas) | **0 puntos** en ambas; la corrección explica que la respuesta contiene instrucciones y no responde |
| **¿Obedeció alguna orden?** | **No** |

Limitación: es una muestra; un modelo de lenguaje no da garantías absolutas. Las defensas que no
dependen del modelo (citas verificadas, evidencia literal, esquema de salida, sin herramientas,
CSP sin orígenes remotos) limitan el daño si alguna vez obedece.

### 8. Rendimiento y estabilidad
**Biblioteca de 500 documentos** (`bench_scale.py library`, Ollama real para los embeddings):
350 textos pegados (6,5 M caracteres), 100 PDF y 50 Word, en 5 asignaturas.

| Medida | Resultado |
|---|---|
| Enviar las 500 importaciones | 2,8 s (la UI no espera: todo va a la cola) |
| Extraer e indexar todo (6.773 fragmentos) | 525 s (≈ 1 s por documento) |
| Fallos | **0** · 500 de 500 indexados |
| Listado de la biblioteca, página de 50 (primera / última) | p50 2,7 ms · p95 5,3 ms / p50 2,2 ms |
| Filtro por texto · por asignatura y tipo · asignaturas | p50 1,5 ms · 2,0 ms · 1,1 ms |
| Búsqueda del asistente (palabras + vectores), toda la biblioteca / una asignatura | p50 41,8 ms (p95 47,3) / 34,9 ms |
| Base de datos · carpeta de datos (incl. originales) | 64,7 MB · 617 MB |
| Memoria máxima: backend · subprocesos de extracción | 189 MB · 101 MB |

**Audio de 3 h** (`bench_scale.py audio`, la grabación sintética de 61,9 min del corpus repetida
3 veces: 185,6 min, WAV de 340 MB; whisper.cpp large-v3-turbo q5_0 real + embeddings reales):

| Medida | Resultado |
|---|---|
| Normalizar, transcribir e indexar | **696,6 s (11,6 min)**, ≈ 16× más rápido que el audio |
| Estado final · índice | listo · 201 fragmentos, 201 con embedding |
| Segmentos · caracteres | 1.977 · 231.594 |
| Último segmento | minuto 185,5 de 185,6: no se pierde el final |
| Mayor salto entre segmentos | 13,0 s (silencios del corpus) |
| Abrir la transcripción completa (API) | 16 ms, 0,74 MB |
| Memoria máxima: backend · subprocesos (whisper/ffmpeg) | 117 MB · 966 MB |
| Memoria libre mínima del sistema durante el proceso | 7.854 MB |

Conclusión: ambas pruebas de estabilidad terminan sin fallos, sin bloquear la API y lejos del
presupuesto de memoria del Mac.

## Riesgos residuales
- Prompt injection: mitigada, no eliminable (ver §7).
- F-12, F-13, F-14 (aceptados, arriba). T14: Ollama sin autenticación en localhost.
- Firma y notarización del `.app`: Fase 10.

## Cómo repetirlo
```bash
scripts/check.sh                                   # backend, frontend, rust y e2e
cd backend && uv run python ../bench/fuzz_files.py
cd backend && uv run python ../bench/bench_injection.py        # requiere Ollama
cd backend && uv run python ../bench/bench_scale.py library --n 500
cd backend && uv run python ../bench/bench_scale.py audio --hours 3
uvx bandit -r backend/app -q; uvx semgrep --config p/default --metrics=off
uvx pip-audit; (cd app && npm audit); (cd app/src-tauri && cargo audit); trivy fs .; gitleaks detect
```
