# Changelog

## [0.8.0] — 2026-11-06 · Fase 8: Claude en la nube, solo con tu permiso
### Añadido
- **Configuración › Claude** (antes «Próximamente»): activar Claude (desactivado por defecto), vía, modelo (Sonnet 5.5 por defecto), tareas permitidas, límites mensuales, consentimientos de la sesión y registro de envíos.
- Dos vías:
  - **Clave API** de Anthropic, guardada en el **llavero de macOS** (nunca en la base de datos). Se muestran solo sus 4 últimos caracteres.
  - **Tu plan de Claude** (Pro/Max) mediante el programa oficial de Claude Code (`claude`), sin modificar. La app solo lo ejecuta; no lee ni guarda tus credenciales.
  - «Automática» usa la clave si la hay; si no, el plan.
- Tareas que pueden ir a Claude: asistente, apuntes y resúmenes, generar tarjetas y exámenes, y **revisar** tarjetas y preguntas (se puede activar solo la revisión).
- **Ventana de consentimiento antes de cada envío**: qué tarea, vía y modelo, fuentes, fragmentos y caracteres, el texto exacto que saldría, coste estimado y gasto del mes. Botones: Cancelar, Hacerlo en local o Enviar a Claude. Opción «no volver a preguntar para esta tarea hasta cerrar la app».
- **Límite mensual de 5 $ por vía** (ajustable). Con el plan se cuenta el coste equivalente que informa Claude Code. Al llegar al límite, todo sigue en local.
- **Registro de envíos**: fecha, tarea, vía, modelo, estado, caracteres y coste. No guarda contenido.
- Si Claude falla o no hay conexión, el trabajo continúa con el modelo local.
- La corrección de respuestas cortas sigue siempre en local. Los audios nunca se envían.
- Migración `0008_cloud.sql`. Dependencias nuevas: `anthropic` 2.6.0 (Apache-2.0) y `keyring` 25.7.0 (MIT), que traen `httpx2`/`httpcore2` (BSD), `truststore` y `jaraco.*` (MIT).
### Cambiado
- Resource Manager revisado con 104 llamadas reales del modelo local: el pico (8.460 MB) nunca superó el presupuesto, así que los valores se mantienen.
### Limitaciones conocidas
- Con salida estructurada (tarjetas, exámenes, apuntes), Claude Code no envía texto parcial: la barra de progreso avanza por lotes, no letra a letra.
- Las peticiones de la API usan los respaldos del servidor ante un rechazo del modelo (`fallbacks: "default"`); el modelo que respondió de verdad queda en el registro.

## [0.7.2] — 2026-11-06 · El asistente también crea ejemplos y preguntas
### Añadido
- El asistente entiende peticiones de **crear**: «dame un ejemplo de…», «hazme una pregunta de opción múltiple con 4 respuestas», «plantéame un ejercicio / caso práctico», «preguntas de verdadero o falso», y «otra» justo después.
  - Si el tema está en tus fuentes, crea a partir de ellas y cita de dónde sale cada concepto. La respuesta lleva la etiqueta «Creado por la IA a partir de tus fuentes».
  - Si el tema no está en tus fuentes, crea con el conocimiento general del modelo (local) y lo marca en ámbar: «Sin respaldo en tus fuentes… Puede contener errores; compruébalo».
  - Las preguntas de opción múltiple traen cuatro opciones (A–D), una correcta y la explicación.
- Las preguntas normales («¿qué es…?») no cambian: solo responden con tus fuentes y, si no está, «no encontrado».
- Sin migración ni dependencias nuevas; nada sale del equipo.

## [0.7.1] — 2026-11-06 · Corrección al crear mazos y exámenes
### Corregido
- «Alguna fuente elegida no es de esta asignatura» al crear un mazo: la ventana conservaba las fuentes marcadas en otra asignatura (ocultas). Ahora la ventana empieza de cero cada vez que se abre y solo envía fuentes y temas de la asignatura actual. El mismo fallo existía en «Nuevo examen» y queda corregido igual.

## [0.7.0] — 2026-11-06 · Fase 7: flashcards y estadísticas
### Añadido
- **Flashcards**: mazos creados con la IA local desde tus fuentes (por asignatura, temas o fuentes). Cada tarjeta guarda la frase literal que la respalda (comprobada); un revisor descarta las no respaldadas, poco claras o poco útiles. Si no hay material para todas, el mazo indica cuántas se pudieron crear.
- **Repaso espaciado con FSRS** (`fsrs` 6.3.2, MIT): Otra vez / Difícil / Bien / Fácil con el intervalo de cada botón, atajos (espacio y 1–4), evidencia al ver la respuesta, límite de tarjetas nuevas al día (20 por defecto, ajustable), repaso por asignatura, por mazo o de todo.
- Editar, suspender y borrar tarjetas; reparto nuevas / aprendiendo / dominadas por mazo y próximas fechas.
- **Estadísticas**: tiempo de estudio por día (tarjetas y exámenes), repasos, retención, racha, días activos, tarjetas y previsión de repasos de 7 días, exámenes corregidos con nota media y últimos intentos. Filtro por asignatura y periodo (7/30/90 días). Gráficos con tooltip y vista de tabla.
- **Inicio**: «Para repasar hoy» con las tarjetas pendientes y la racha.
- Migración `0007_flashcards.sql`. Dependencia nueva: `fsrs` (MIT, sin dependencias pesadas).
### Limitaciones conocidas
- En clases transcritas, ~3 de cada 10 tarjetas pueden ser dudosas (en material escrito, 0 de 20 en la prueba). Todas muestran su cita y se pueden editar o borrar.
- Crear un mazo de 20 tarjetas tarda ~4 min con material escrito y ~10 min con una clase transcrita de una hora.
- El tiempo de estudio no incluye leer apuntes o resúmenes.

## [0.6.2] — 2026-11-05 · Grabaciones por asignatura y retención del audio
### Cambiado
- En **Grabaciones**, la lista muestra solo las grabaciones de la asignatura elegida (antes, las últimas 20 de todas). Mientras se graba, las de la asignatura de la grabación en curso.
### Añadido
- Retención del audio de clases ya transcritas, para liberar espacio (cada hora de clase ocupaba ~510 MB):
  - al terminar bien la transcripción se borra el archivo original (~385 MB/h);
  - la copia ligera (~125 MB/h), que sirve para escuchar la clase y volver a transcribir, se borra sola a los **7 días** (ajustable en Grabaciones › Transcripción: 7 días, 30 días o siempre);
  - botón **«Borrar audio ahora»** en cada clase transcrita, con confirmación y el tamaño que libera.
- La transcripción, los resúmenes, los exámenes y las citas **nunca se borran**. Sin audio, la clase muestra «El audio se borró para liberar espacio» y no ofrece retranscribir.
- No se toca el audio de clases sin transcribir, con transcripción vacía o fallida, o con una tarea en curso. Sin migración ni dependencias nuevas.
### Nota
- Al abrir esta versión se borran los originales de las grabaciones ya transcritas.

## [0.6.1] — 2026-11-05 · Copiar texto y resúmenes más completos
### Corregido
- No se podía seleccionar ni copiar texto en resúmenes, apuntes ni en el asistente (la app bloqueaba la selección en todas las páginas). Ahora el contenido se puede seleccionar y copiar con ⌘C; los botones y menús siguen sin seleccionarse.
### Añadido
- Botón **«Copiar»** en apuntes y resúmenes y en cada respuesta del asistente: copia el texto con las referencias [n] y la lista de fuentes citadas.
### Cambiado
- Los resúmenes crecen con el material: hasta ~3 páginas, como antes; hasta ~25.000 caracteres, ×1,5; en clases largas, ×2 (nivel intermedio: 12 frases + 12 ideas clave). Tope de 15 frases + 12 ideas; el paso final del resumen tiene hasta 5.600 tokens de salida (ventana de 12K) para que no se corte.
- Cada frase del resumen explica la idea (porqué, relación o ejemplo), no solo la nombra.
- Como máximo 3 citas por punto (antes llegaban a 8 y la respuesta final se cortaba por longitud).

## [0.6.0] — 2026-11-04 · Fase 6: exámenes
### Añadido
- Página **Exámenes**: crea un examen por asignatura eligiendo número de preguntas (1–50), tipos (opción múltiple, verdadero/falso, respuesta corta), dificultad, opciones por pregunta (3–5), temas o fuentes, modo (práctica o con tiempo) y penalización por fallo.
- Generación en segundo plano con el modelo local. Cada pregunta guarda la frase **literal** de tus fuentes que la respalda (se comprueba carácter a carácter); se descartan las que citan algo que no está en el texto, las de opciones repetidas o «todas/ninguna de las anteriores» y las duplicadas. Un segundo paso (modelo-juez) descarta las ambiguas o con otra opción también correcta.
- Si no hay material para todas: «Tus fuentes permiten 14 de las 20 preguntas» con opción «Generar con 14» o descartar.
- Hacer el examen: una pregunta a la vez, cuadrícula de navegación, marcar para revisar, progreso guardado (se puede salir y continuar) y temporizador en modo con tiempo (la hora límite la impone el backend; al acabar se entrega con lo respondido). En modo práctica, «Comprobar» corrige cada pregunta al momento.
- Corrección: test y V/F al instante (con penalización si se eligió); respuestas cortas con la IA local y una rúbrica, marcadas «Corregida por IA». Resultado con nota sobre 10, tu respuesta frente a la correcta, explicación, evidencia con enlace a la fuente, rendimiento por fuente y material de repaso con las frases de lo que fallaste.
- Historial de intentos por examen.
- Migración `0006_exams.sql`. Sin dependencias nuevas.
### Limitaciones conocidas
- En clases transcritas, ~1 de cada 5 preguntas puede ser dudosa (en material escrito, ≤ 1 de 20). Todas muestran la frase que las respalda.
### Seguridad
- La API no revela la respuesta correcta antes de comprobar o entregar. La respuesta del estudiante va delimitada como datos al corregir con IA (no puede dar instrucciones al corrector).

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
