# API — contrato UI ↔ backend

**Fuente de verdad:** el esquema OpenAPI generado (`app/src/lib/api/openapi.json`, regenerar con `npm run gen:api`). Este documento describe solo lo que el esquema no dice.

## Transporte
| Modo | Camino | Autenticación |
|---|---|---|
| Escritorio | `invoke('api_request', {request:{method, path, body}})` → Rust → HTTP/1.1 sobre Unix socket | Token de sesión (32 bytes) que Rust añade como `Authorization: Bearer …` |
| Web (futuro, ADR-009) | `fetch` HTTPS al mismo origen | Sesión con cookie `HttpOnly` + CSRF |

Restricciones del proxy Rust: métodos `GET POST PUT PATCH DELETE`; ruta que empiece por `/api/v1/`, ASCII imprimible, sin `..`, `#` ni `\`, ≤ 2048 caracteres; cuerpo JSON ≤ 1 MB; respuesta ≤ 32 MB. Los archivos grandes tendrán un canal propio (Fase 2).

## Errores
Formato único:
```json
{ "error": { "code": "unauthorized", "message": "No autorizado" } }
```
`message` está en español y puede mostrarse al usuario. Nunca se devuelven trazas. Si el fallo ocurre en Rust (backend caído, ruta no permitida), la UI recibe `ApiError` con `code = "transport_error"`.

## Endpoints (v1)
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/health` | Estado, versión y versión del esquema de BD |
| GET | `/api/v1/system/info` | Versiones (Python, SQLite), FTS5, carpeta de datos, usuario local |

`/docs`, `/redoc` y `/openapi.json` están **desactivados** en ejecución.
