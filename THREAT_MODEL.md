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
| T10 | T | Prompt injection en documentos o transcripciones | Fuentes delimitadas como datos, sin herramientas, salida con esquema, scope en SQL | ⏳ F4–F6 (validado en benchmark: 3/3 resistidos) |
| T11 | I | Fuga entre asignaturas | Filtro obligatorio por `subject_id`/`owner_id` en SQL | ⏳ F5 |
| T12 | I | Envío no consentido a la nube | Consentimiento con vista previa + auditoría | ⏳ F8 |
| T13 | I | Robo de claves API | Keychain de macOS | ⏳ F8 |
| T14 | S/I | Cualquier proceso local usa Ollama (puerto 11434 sin autenticación) | Riesgo aceptado: Ollama no recibe datos persistentes; solo prompts efímeros | ⚠️ Aceptado |
| T15 | T | Modelo descargado corrupto o sustituido | Verificación de tamaño y SHA-256; descarga solo a petición | ✅ F3 |
| T17 | E | La UI (p. ej. tras un XSS) importa archivos arbitrarios del disco (`~/.ssh/…`) | Solo rutas autorizadas por un gesto del usuario (selector nativo/soltar); endpoint interno bloqueado en el proxy y protegido por cabecera | ✅ F2 |
| T18 | I | Grabación sin que el usuario lo sepa | Solo se graba tras pulsar «Empezar»; barra roja permanente y título de ventana «● Grabando»; permiso de micrófono de macOS | ✅ F3 |
| T19 | I | La UI lee archivos locales arbitrarios vía `asset://` | Ámbito limitado a los audios normalizados | ✅ F3 |
| T16 | I | Datos de compañeros en el futuro modo web | Auth real, aislamiento por usuario, VPN/Tailscale, RGPD | ⏳ Fuera de alcance actual |

## Riesgos residuales aceptados
- Un proceso malicioso que ya se ejecuta como tu usuario puede leer tus archivos: fuera del alcance de la app (lo cubre macOS: FileVault, TCC).
- T14 (Ollama sin autenticación en localhost).
