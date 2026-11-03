import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.config import Settings
from app.db.migrate import migrate
from app.llm.base import LoadedModel, RuntimeInfo
from app.services import llm


class NoLLM:
    """Proveedor falso por defecto: las pruebas nunca hablan con el Ollama real del Mac."""

    name = "fake"

    def info(self) -> RuntimeInfo:
        return RuntimeInfo(running=False)

    def loaded(self) -> list[LoadedModel]:
        return []

    def unload(self, model: str) -> None:
        pass

    def chat(self, req: object, on_token: object = None, cancelled: object = None) -> object:
        raise AssertionError("chat no esperado")


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "provider", lambda: NoLLM())


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(
        data_dir=tmp_path / "data",
        socket_path=tmp_path / "run" / "b.sock",
        token=secrets.token_hex(32),
    )
    s.prepare_dirs()
    migrate(s.db_path, s.backups_dir)
    return s


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}
