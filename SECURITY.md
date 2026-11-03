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
| Vínculos solo dentro de la misma asignatura (servicio + trigger) | `services/sources.py`, `0002` | `test_links_must_be_same_subject` |

## Pendiente (fases siguientes)
Defensa ante prompt injection (Fases 4–6), consentimiento cloud y Keychain (Fase 8), SAST/SCA/DAST (Fase 9).

## Reportar un problema
Proyecto personal: abre una nota en `TASKS.md` con la etiqueta `[SEGURIDAD]`.
