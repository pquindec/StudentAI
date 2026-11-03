"""Preferencias del modelo de lenguaje y acceso al proveedor local."""

import sqlite3

from app.llm.base import LLMProvider
from app.llm.ollama import OllamaProvider
from app.resources.manager import PROFILES
from app.services import settings as prefs

DEFAULT_MODEL = "qwen3.5:9b"
LIGHT_MODEL = "qwen3.5:4b"
KEEP_ALIVE = ("1m", "2m", "5m", "10m")
DEFAULT_KEEP_ALIVE = "2m"  # BENCHMARKS §4: corto mientras se desarrolla en el mismo Mac


def provider() -> LLMProvider:
    """Punto único para obtener el proveedor (las pruebas lo sustituyen por uno falso)."""
    return OllamaProvider()


def chosen_model(db: sqlite3.Connection) -> str:
    m = prefs.get(db, "llm.model", DEFAULT_MODEL)
    return m if isinstance(m, str) and m in PROFILES else DEFAULT_MODEL


def light_model(db: sqlite3.Connection) -> str | None:
    m = chosen_model(db)
    return LIGHT_MODEL if m != LIGHT_MODEL else None


def keep_alive(db: sqlite3.Connection) -> str:
    k = prefs.get(db, "llm.keep_alive", DEFAULT_KEEP_ALIVE)
    return k if k in KEEP_ALIVE else DEFAULT_KEEP_ALIVE
