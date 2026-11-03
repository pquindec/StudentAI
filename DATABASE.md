# Base de datos

El modelo de datos completo y su justificación están en `ARCHITECTURE.md §5`. **El esquema real es el de las migraciones** en `backend/app/db/migrations/`.

## Estado
| Versión | Migración | Contenido |
|---|---|---|
| 1 | `0001_init.sql` | `users` (usuario `local`), `settings`, `subjects`, `units` (course/module/topic), `sessions` |

## Reglas
- SQLite en modo **WAL**, `foreign_keys=ON`, `busy_timeout=5000`. Una conexión por petición.
- IDs en texto (UUID); fechas ISO-8601 UTC.
- Integridad en la propia BD: `CHECK` de longitudes y enumerados; triggers que impiden que una unidad o sesión apunte a una unidad de otra asignatura; una unidad no puede ser su propio padre; borrado en cascada desde `subjects`.
- Ciclos más largos en el árbol de unidades (A→B→A) se validan en el servicio (Fase 2).

## Migraciones
- Archivo nuevo `NNNN_nombre.sql` (4 dígitos, minúsculas). Nunca editar uno aplicado.
- Cada migración se aplica en **una transacción**; si falla, se revierte entera.
- Antes de migrar una BD existente se crea `backups/app-<fecha>-pre-NNNN.db` (se conservan 5).
- Archivos de BD y copias con permisos `0600`.
