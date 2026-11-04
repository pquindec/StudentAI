"""ScopeResolver: en qué fuentes se busca. Se traduce SIEMPRE a SQL (nunca se filtra después en
Python), y siempre incluye el propietario: así no puede haber fugas entre asignaturas ni entre
usuarios (ADR-009)."""

from typing import Any

from pydantic import BaseModel, Field

IdList = list[str]


class Scope(BaseModel):
    """subject_id=None busca en toda la biblioteca del usuario."""

    subject_id: str | None = None
    unit_ids: IdList = Field(default_factory=list, max_length=200)  # incluye sus subunidades
    source_ids: IdList = Field(default_factory=list, max_length=200)
    exclude_source_ids: IdList = Field(default_factory=list, max_length=200)


def _marks(n: int) -> str:
    return ",".join("?" * n)


def scope_sql(scope: Scope, owner: str, alias: str = "c") -> tuple[str, list[Any]]:
    """Condición WHERE sobre la tabla de chunks `alias` (se une a `subjects` por dentro)."""
    subject = " AND id = ?" if scope.subject_id else ""
    where = [f"{alias}.subject_id IN (SELECT id FROM subjects WHERE owner_id = ?{subject})"]  # noqa: S608
    params: list[Any] = [owner]
    if scope.subject_id:
        params.append(scope.subject_id)
    if scope.source_ids:
        where.append(f"{alias}.source_id IN ({_marks(len(scope.source_ids))})")
        params += scope.source_ids
    if scope.unit_ids:
        # Las fuentes vinculadas a esas unidades o a cualquiera de sus descendientes.
        where.append(
            f"""{alias}.source_id IN (
                WITH RECURSIVE tree(id) AS (
                    SELECT id FROM units WHERE id IN ({_marks(len(scope.unit_ids))})
                    UNION SELECT u.id FROM units u JOIN tree t ON u.parent_id = t.id
                )
                SELECT source_id FROM source_links WHERE unit_id IN (SELECT id FROM tree))"""  # noqa: S608
        )
        params += scope.unit_ids
    if scope.exclude_source_ids:
        where.append(f"{alias}.source_id NOT IN ({_marks(len(scope.exclude_source_ids))})")
        params += scope.exclude_source_ids
    return " AND ".join(where), params
