"""Secretos en el Keychain de macOS (nunca en SQLite, archivos ni registros).

`keyring` (MIT) usa el Security framework del sistema. Las pruebas sustituyen `_backend` por uno
en memoria para no tocar el llavero del usuario.
"""

import contextlib
from typing import Protocol

import keyring
import keyring.errors

SERVICE = "com.aistudyassistant.desktop"
ANTHROPIC_KEY = "anthropic_api_key"


class _Backend(Protocol):
    def get_password(self, service: str, user: str) -> str | None: ...
    def set_password(self, service: str, user: str, password: str) -> None: ...
    def delete_password(self, service: str, user: str) -> None: ...


_backend: _Backend = keyring


def get(name: str) -> str | None:
    try:
        return _backend.get_password(SERVICE, name)
    except keyring.errors.KeyringError:
        return None


def put(name: str, value: str) -> None:
    _backend.set_password(SERVICE, name, value)


def delete(name: str) -> None:
    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        _backend.delete_password(SERVICE, name)
