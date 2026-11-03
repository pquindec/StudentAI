# PROJECT_CONTEXT (referencia rápida)

**Qué es:** app de escritorio macOS de estudio con IA local. Uso personal; posible modo web para compañeros en el futuro (ADR-009). UI en español.

**Equipo objetivo:** MacBook M5, 24 GB, macOS 27. Memoria libre real con herramientas de desarrollo abiertas: escasa (ver `BENCHMARKS.md §4`).

## Stack y versiones
| Pieza | Versión |
|---|---|
| Tauri / CLI | 2.12 |
| React · Vite · TS · Tailwind | 19.3 · 8.3 · 7.0 · 4.3 |
| Rust | 1.99 (rustup de Homebrew, edición 2024) |
| Python (backend) | 3.13 (uv) · FastAPI · Uvicorn · Pydantic 2 |
| SQLite | la del Python standalone (FTS5 disponible) |
| whisper.cpp · FFmpeg | 1.9.5 · 9.0.2 (Homebrew) |
| Ollama | 0.40.14, app oficial |

## Modelos elegidos (Fase 0.5)
STT `large-v3-turbo-q5_0` · LLM `qwen3.5:9b` (ligero: `qwen3.5:4b`) · embeddings `qwen3-embedding:0.6b` + BM25 (RRF). Contexto por defecto: 8K.

## Cómo encaja
- `app/src-tauri/src/backend.rs`: arranca el backend, token por stdin, espera a `/health`, emite `backend://status`.
- `app/src-tauri/src/proxy.rs`: HTTP/1.1 sobre Unix socket; valida método y ruta (`/api/v1/*`).
- `app/src-tauri/src/lib.rs`: comandos `api_request` y `backend_status` (únicos permitidos en `capabilities/default.json`).
- `backend/app/main.py`: protocolo de arranque, socket 0600, sale cuando se cierra stdin.
- `backend/app/core/security.py`: middleware de token (todas las rutas).
- `backend/app/db/`: conexión (WAL, FK) y migraciones con copia previa.
- `app/src/lib/api/`: `ApiTransport` (Tauri | HTTP) + `ApiClient` tipado (`schema.d.ts` generado).

## Datos
`~/Library/Application Support/com.aistudyassistant.desktop/` → `app.db`, `backups/`, `logs/backend.log`, `run/backend.sock`. Logs de la app: `~/Library/Logs/com.aistudyassistant.desktop/`.

## Fase actual
Ver `TASKS.md`.
