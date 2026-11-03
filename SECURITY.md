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

## Pendiente (fases siguientes)
Validación de archivos importados (Fase 2), defensa ante prompt injection (Fases 4–6), consentimiento cloud y Keychain (Fase 8), SAST/SCA/DAST (Fase 9).

## Reportar un problema
Proyecto personal: abre una nota en `TASKS.md` con la etiqueta `[SEGURIDAD]`.
