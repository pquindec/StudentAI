# THREAT MODEL — v1 (Fase 1)

Método: STRIDE por frontera de confianza. Se revisa al final de cada fase.

## Activos
1. Grabaciones de clase y documentos (privados; pueden contener voces de terceros).
2. Transcripciones, apuntes, exámenes y progreso del estudiante.
3. Claves API de proveedores cloud (Fase 8).
4. Integridad del Mac del usuario (memoria, procesos, archivos).

## Fronteras de confianza
```
[Contenido importado: NO confiable] → [Backend Python] ↔ [SQLite / archivos]
[WebView (React)] → invoke → [Rust core] → Unix socket → [Backend Python] → [Ollama localhost] / [Claude API]
[Otros procesos y usuarios del Mac] ⇢ socket, archivos de datos, puerto de Ollama
```

## Amenazas
| # | STRIDE | Amenaza | Mitigación | Estado |
|---|---|---|---|---|
| T1 | S/E | Otro proceso local llama a la API del backend | Unix socket 0600 en dir 0700 + token + sin TCP | ✅ F1 |
| T2 | S | Sitio web malicioso vía DNS rebinding / CSRF contra localhost | No hay servidor HTTP en TCP | ✅ F1 |
| T3 | I | Token visible en `ps` o variables de entorno | Token por stdin; `env_clear` | ✅ F1 |
| T4 | T/E | XSS en el WebView para invocar comandos nativos | CSP estricta; sin HTML crudo; capabilities mínimas; proxy con lista blanca | ✅ F1 (base) · revisar en F4 (Markdown generado) |
| T5 | E | Inyección de módulos Python (`PYTHONPATH`, archivos plantados) | `python -I` en el empaquetado; `env_clear` | ✅ F1 |
| T6 | D | Backend huérfano consumiendo recursos | EOF en stdin → salida; `kill_on_drop` | ✅ F1 |
| T7 | I | Fuga de datos en logs | Logs sin contenido de fuentes ni cuerpos de petición | ✅ F1 (regla) |
| T8 | T | Corrupción de BD por migración fallida | Transacción por migración + copia previa | ✅ F1 |
| T9 | T/D | Archivos maliciosos (zip bomb DOCX, PDF malformado, extensión falsa, path traversal) | Magic bytes, límites, rutas UUID, extracción en subproceso con timeout y RLIMIT_CPU | ✅ F2 |
| T10 | T | Prompt injection en documentos o transcripciones | Fuentes delimitadas como datos (delimitadores e ids falsos neutralizados), sin herramientas, salida con esquema, citas verificadas, scope en SQL | ✅ F4 apuntes/resúmenes · ✅ F5 asistente (documento malicioso en `bench_rag.py` y `test_injected_instructions_stay_as_data`) · ✅ F6 exámenes (evidencia literal obligatoria, juez separado; respuesta del estudiante delimitada en la corrección: `test_student_answer_cannot_escape_delimiter`) · ✅ F7 flashcards (cita literal obligatoria y revisor separado: `test_card_prompt_treats_sources_as_data`) · ✅ F9 neutralización resistente a Unicode y batería de 10 ataques en todos los prompts (`test_injection.py`), y prueba con el modelo real (`bench_injection.py`, ver `QA_REPORT.md`) |
| T11 | I | Fuga entre asignaturas | Ámbito traducido a SQL con el propietario siempre incluido (FTS y vectores), trigger que impide chunks de otra asignatura, ids del ámbito validados contra el usuario | ✅ F5 (0 fugas, ver TESTING.md) |
| T12 | I | Envío no consentido a la nube | Desactivado por defecto; consentimiento con vista previa del texto exacto, ligado al trabajo y a las fuentes mostradas (o a la sesión del backend); límite mensual; auditoría sin contenido; fallo → local | ✅ F8 (`test_disabled_by_default_and_nothing_leaves_without_consent`, `test_consent_only_covers_the_previewed_sources`, `test_chat_sends_exactly_the_previewed_fragments`) |
| T13 | I | Robo de claves API | Clave en el Keychain de macOS (nunca en BD ni logs; la API solo devuelve los 4 últimos caracteres). Con el plan, la app no lee los tokens de Claude Code | ✅ F8 (`test_api_key_lives_in_keychain_not_in_db`) |
| T14 | S/I | Cualquier proceso local usa Ollama (puerto 11434 sin autenticación) | Riesgo aceptado: Ollama no recibe datos persistentes; solo prompts efímeros | ⚠️ Aceptado |
| T15 | T | Modelo descargado corrupto o sustituido | Verificación de tamaño y SHA-256; descarga solo a petición | ✅ F3 |
| T17 | E | La UI (p. ej. tras un XSS) importa archivos arbitrarios del disco (`~/.ssh/…`) | Solo rutas autorizadas por un gesto del usuario (selector nativo/soltar); endpoint interno bloqueado en el proxy y protegido por cabecera | ✅ F2 |
| T18 | I | Grabación sin que el usuario lo sepa | Solo se graba tras pulsar «Empezar»; barra roja permanente y título de ventana «● Grabando»; permiso de micrófono de macOS | ✅ F3 |
| T19 | I | La UI lee archivos locales arbitrarios vía `asset://` | Ámbito limitado a los audios normalizados | ✅ F3 |
| T20 | E/I | Desde la Wi-Fi se alcanza la API principal o datos del usuario | Servidor de sala separado, solo rutas del participante, solo mientras hay sala; la API principal sigue en el Unix socket | ✅ F9.5 (`test_room_server_only_serves_the_room`) |
| T21 | S | Alguien entra con el código o suplanta a un compañero | Código aleatorio que caduca, límite de intentos, admisión manual en modo con nota, un dispositivo por persona | ✅ F9.5 (nombres sin verificar: lo cubre la admisión manual) |
| T22 | I | Un participante obtiene las respuestas correctas | Corrección solo en el Mac; nada de soluciones en el teléfono hasta publicar; orden aleatorio por persona | ✅ F9.5 |
| T23 | I | Escucha en la Wi-Fi (HTTP sin cifrar) | Riesgo a confirmar por el usuario: tokens por dispositivo; sin datos sensibles más allá de nombre y respuestas | ⚠️ Aceptación del usuario pendiente |
| T24 | D | Saturar la sala (muchas conexiones o peticiones) | Límite de participantes y de peticiones; cierre de sala | ✅ F9.5 (20 a la vez) |
| T26 | I/S | Sala por internet (Cloudflare): Cloudflare ve el tráfico; cualquiera con enlace y código llega a la sala; falsear la IP para saltarse los límites | Solo con consentimiento en cada activación; aviso explícito; dirección aleatoria y temporal; mismo código, límites y admisión manual; `CF-Connecting-IP` solo desde el propio Mac con el túnel activo; se cierra con la sala o el backend | ✅ F9.5 (`test_tunnel.py`) |
| T25 | I | Retención de datos de otras personas | Solo nombre, respuestas y nota; aviso; borrado manual y automático | 🔄 Manual ✅; automático pendiente de plazo |
| T16 | I | Datos de compañeros en el futuro modo web | Auth real, aislamiento por usuario, VPN/Tailscale, RGPD. F9: el aislamiento por propietario de la API ya está probado ruta a ruta (`test_dast.py`); los ajustes de la app (Claude, IA, transcripción) siguen siendo globales y habría que separarlos | ⏳ Fuera de alcance actual |

## Riesgos residuales aceptados
- Un proceso malicioso que ya se ejecuta como tu usuario puede leer tus archivos: fuera del alcance de la app (lo cubre macOS: FileVault, TCC).
- T14 (Ollama sin autenticación en localhost).
