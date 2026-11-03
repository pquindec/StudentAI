# Changelog

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
