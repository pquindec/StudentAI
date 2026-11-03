# Estrategia de pruebas

## Comando único
```bash
scripts/check.sh            # todo
scripts/check.sh backend    # solo una parte (preferible tras cambios acotados)
```

## Niveles
| Nivel | Herramienta | Qué cubre hoy |
|---|---|---|
| Unitarias backend | pytest | token, migraciones (idempotencia, rollback, copia), jerarquía de unidades, sesiones, cola de trabajos |
| Integración backend (F2) | pytest + archivos generados (`tests/factories.py`) | importar PDF/DOCX/TXT/MD/RTF/CSV/MP3/M4A, texto pegado, versiones y conflicto, duplicados, archivos malformados, borrado, filtros |
| Integración backend | pytest + subprocess | arranque real por Unix socket, permisos 0600, 401/200, salida al cerrar stdin |
| Unitarias Rust | cargo test | validación de rutas y métodos del proxy (incl. bloqueo de `/internal`), permisos de rutas de un solo uso |
| Unitarias frontend | vitest | transportes Tauri/HTTP, errores, codificación de queries e IDs, importador, árbol de unidades, formatos |
| Estático | ruff, mypy `--strict`, clippy `-D warnings`, oxlint, tsc, prettier | todo el código |
| E2E | (Fase 9) WebDriver de Tauri o Playwright | — |
| IA | `bench/` + conjuntos de referencia | ver `BENCHMARKS.md` |

## Pruebas manuales de la Fase 1 (2026-11-03)
- `npm run tauri dev`: backend `Ready` y la UI obtiene `/system/info` → 200 (log de la app).
- `curl --unix-socket` sin token o con token falso → 401.
- `kill -9` de la app → el backend sale solo.
- `.app` release copiado fuera del repo: el backend se ejecuta desde `Contents/Resources`, la UI recibe 200 y al salir el backend termina.

## Pruebas de la Fase 2 (2026-11-03)
- Automáticas: pytest 54, vitest 12, cargo test 5 — todas pasan (`scripts/check.sh`).
- `npm run tauri dev`: backend `Ready`; la UI obtiene `/system/info` y `/jobs` → 200.
- **Pendiente:** recorrido manual en la UI (soltar archivos reales, selector, editar texto). La ruta Rust `pick_files`/`import_files` + autorización no tiene prueba automática de extremo a extremo.

## Reglas
- No declarar una prueba como superada si no se ejecutó.
- Cada fallo corregido lleva una prueba que lo reproduce (p. ej. `test_refuses_foreign_socket_dir`).
