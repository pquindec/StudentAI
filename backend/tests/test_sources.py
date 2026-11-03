"""Fase 2: importación de fuentes de todos los formatos, vista previa, edición y errores."""

import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.factories import RTF, make_audio, make_docx, make_pdf, make_zip_bomb

H = dict[str, str]


@pytest.fixture
def subject(client: TestClient, auth: H) -> dict[str, Any]:
    s = client.post("/api/v1/subjects", json={"name": "Ingeniería de Software"}, headers=auth)
    assert s.status_code == 201
    sid = s.json()["id"]
    t1 = client.post(
        f"/api/v1/subjects/{sid}/units",
        json={"kind": "topic", "title": "Arquitectura"},
        headers=auth,
    ).json()
    t2 = client.post(
        f"/api/v1/subjects/{sid}/units", json={"kind": "topic", "title": "Patrones"}, headers=auth
    ).json()
    return {"id": sid, "topics": [t1["id"], t2["id"]]}


def import_file(client: TestClient, auth: H, subject_id: str, path: Path, **kw: Any) -> Any:
    return client.post(
        "/api/v1/internal/sources/import-file",
        json={"path": str(path), "subject_id": subject_id, **kw},
        headers={**auth, "x-core-caller": "1"},
    )


def wait_done(client: TestClient, auth: H, source_id: str, timeout: float = 60) -> dict[str, Any]:
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(f"/api/v1/sources/{source_id}", headers=auth).json()
        if s["status"] not in ("pending", "processing"):
            return dict(s)
        time.sleep(0.1)
    raise AssertionError("la fuente no terminó de procesarse")


def content(client: TestClient, auth: H, source_id: str) -> dict[str, Any]:
    r = client.get(f"/api/v1/sources/{source_id}/content", headers=auth)
    assert r.status_code == 200, r.text
    return dict(r.json())


# ------------------------------------------------------------------ formatos válidos
def test_pdf_with_pages_and_headings(
    client: TestClient, auth: H, subject: dict[str, Any], tmp_path: Path
) -> None:
    pdf = make_pdf(
        tmp_path / "clase.pdf",
        [
            [
                "1. Introducción",
                "La arquitectura describe decisiones estructurales.",
                "Son costosas de cambiar más adelante.",
            ],
            [
                "2. Atributos de calidad",
                "El rendimiento y la seguridad determinan la arquitectura.",
            ],
        ],
    )
    r = import_file(client, auth, subject["id"], pdf, unit_ids=[subject["topics"][0]])
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"
    s = wait_done(client, auth, r.json()["id"])
    assert s["status"] == "ready", s
    assert s["page_count"] == 2
    assert s["unit_ids"] == [subject["topics"][0]]
    c = content(client, auth, s["id"])
    assert "--- Página 2 ---" in c["text"]
    heads = [x for x in c["segments"] if x["kind"] == "heading"]
    assert [h["text"] for h in heads] == ["# 1. Introducción", "# 2. Atributos de calidad"]
    para = next(x for x in c["segments"] if "rendimiento" in x["text"])
    assert para["page"] == 2
    assert para["section_path"] == "2. Atributos de calidad"
    assert c["text"][para["char_start"] : para["char_end"]] == para["text"]


def test_docx_structure(
    client: TestClient, auth: H, subject: dict[str, Any], tmp_path: Path
) -> None:
    r = import_file(client, auth, subject["id"], make_docx(tmp_path / "tema2.docx"))
    s = wait_done(client, auth, r.json()["id"])
    assert s["status"] == "ready", s
    segs = content(client, auth, s["id"])["segments"]
    kinds = [x["kind"] for x in segs]
    assert kinds == ["heading", "paragraph", "heading", "paragraph", "table"]
    assert segs[2]["level"] == 2
    assert "Singleton" in segs[4]["text"]
    assert segs[3]["section_path"] == "Tema 2: Patrones de diseño \u203a Patrones estructurales"


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        (
            "notas.txt",
            "Primer párrafo.\n\nSegundo párrafo con acentos: canción".encode("latin-1"),
            "canción",
        ),
        ("apuntes.md", "# Título\n\nTexto **importante**.\n\n- uno\n- dos".encode(), "- uno"),
        ("lectura.rtf", RTF, "árbol"),
        (
            "datos.csv",
            "patrón;familia\nSingleton;Creacional\n".encode(),
            "| Singleton | Creacional |",
        ),
    ],
)
def test_text_formats(
    client: TestClient,
    auth: H,
    subject: dict[str, Any],
    tmp_path: Path,
    name: str,
    data: bytes,
    expected: str,
) -> None:
    p = tmp_path / name
    p.write_bytes(data)
    r = import_file(client, auth, subject["id"], p)
    assert r.status_code == 201, r.text
    s = wait_done(client, auth, r.json()["id"])
    assert s["status"] == "ready", s
    assert expected in content(client, auth, s["id"])["text"]


@pytest.mark.parametrize("ext", ["mp3", "m4a"])
def test_audio_probe_and_normalize(
    client: TestClient, auth: H, subject: dict[str, Any], tmp_path: Path, settings: Any, ext: str
) -> None:
    audio = make_audio(tmp_path / f"clase.{ext}")
    if audio is None:
        pytest.skip("ffmpeg no disponible")
    r = import_file(client, auth, subject["id"], audio)
    assert r.status_code == 201, r.text
    s = wait_done(client, auth, r.json()["id"])
    assert s["status"] == "ready", s
    assert s["kind"] == "audio"
    assert 2900 <= s["duration_ms"] <= 3200
    assert s["metadata"]["transcription"] == "pending"
    norm = settings.data_dir / "sources" / s["id"] / "normalized.wav"
    assert norm.exists()
    original = settings.data_dir / "sources" / s["id"] / f"original.{ext}"
    assert original.read_bytes() == audio.read_bytes()  # el original se conserva intacto


def test_pasted_text_and_note(client: TestClient, auth: H, subject: dict[str, Any]) -> None:
    r = client.post(
        "/api/v1/sources/text",
        headers=auth,
        json={
            "subject_id": subject["id"],
            "kind": "note",
            "title": "Mis notas",
            "text": "## Idea clave\n\nLa deuda técnica genera intereses.",
            "unit_ids": subject["topics"],
        },
    )
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["status"] == "ready" and s["kind"] == "note"
    assert sorted(s["unit_ids"]) == sorted(subject["topics"])


# ------------------------------------------------------------------ edición y versiones
def test_edit_creates_new_version(client: TestClient, auth: H, subject: dict[str, Any]) -> None:
    s = client.post(
        "/api/v1/sources/text",
        headers=auth,
        json={"subject_id": subject["id"], "title": "T", "text": "Texto original con errata"},
    ).json()
    r = client.put(
        f"/api/v1/sources/{s['id']}/content",
        headers=auth,
        json={"text": "Texto original corregido", "base_version": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2
    assert [v["origin"] for v in r.json()["versions"]] == ["user_edit", "pasted"]
    # versión antigua conservada
    old = client.get(f"/api/v1/sources/{s['id']}/content?version=1", headers=auth).json()
    assert old["text"] == "Texto original con errata"
    # edición concurrente sobre una versión vieja → conflicto
    r = client.put(
        f"/api/v1/sources/{s['id']}/content",
        headers=auth,
        json={"text": "Otra cosa", "base_version": 1},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "version_conflict"


# ------------------------------------------------------------------ errores y archivos maliciosos
def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("falso.pdf", b"esto es texto, no un PDF", 415, "content_mismatch"),
        ("falso.docx", b"%PDF-1.4 no soy word", 415, "content_mismatch"),
        ("musica.mp3", b"<html>no audio</html>", 415, "content_mismatch"),
        ("vacio.txt", b"", 400, "empty_file"),
        ("programa.exe", b"MZ\x90\x00", 415, "unsupported_type"),
        ("binario.txt", b"\x00\x01\x02" * 100, 415, "content_mismatch"),
    ],
)
def test_rejected_on_import(
    client: TestClient,
    auth: H,
    subject: dict[str, Any],
    tmp_path: Path,
    name: str,
    data: bytes,
    status: int,
    code: str,
) -> None:
    p = tmp_path / name
    p.write_bytes(data)
    r = import_file(client, auth, subject["id"], p)
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["message"]  # mensaje comprensible en español


@pytest.mark.parametrize(
    ("factory", "code"),
    [
        (lambda p: _write(p / "c.pdf", b"%PDF-1.4\n%%%% basura sin estructura"), "crashed"),
        (lambda p: make_pdf(p / "escaneado.pdf", [[], []]), "no_text"),
        (lambda p: make_zip_bomb(p / "bomba.docx"), "zip_bomb"),
    ],
)
def test_fails_during_processing(
    client: TestClient, auth: H, subject: dict[str, Any], tmp_path: Path, factory: Any, code: str
) -> None:
    path = factory(tmp_path)
    r = import_file(client, auth, subject["id"], path)
    assert r.status_code == 201, r.text
    s = wait_done(client, auth, r.json()["id"])
    assert s["status"] == "failed"
    assert s["error_code"] in (code, "corrupt"), s
    assert s["error_message"]


def test_duplicate_detected(
    client: TestClient, auth: H, subject: dict[str, Any], tmp_path: Path
) -> None:
    p = tmp_path / "a.txt"
    p.write_text("contenido")
    assert import_file(client, auth, subject["id"], p).status_code == 201
    copy = tmp_path / "copia.txt"
    copy.write_text("contenido")
    r = import_file(client, auth, subject["id"], copy)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "duplicate"


def test_paths_that_are_not_files(
    client: TestClient, auth: H, subject: dict[str, Any], tmp_path: Path
) -> None:
    assert import_file(client, auth, subject["id"], tmp_path / "no.txt").status_code == 404
    d = tmp_path / "carpeta.txt"
    d.mkdir()
    assert import_file(client, auth, subject["id"], d).status_code == 400
    r = client.post(
        "/api/v1/internal/sources/import-file",
        headers={**auth, "x-core-caller": "1"},
        json={"path": "relativo.txt", "subject_id": subject["id"]},
    )
    assert r.status_code == 400


def test_original_name_never_used_as_path(
    client: TestClient, auth: H, subject: dict[str, Any], tmp_path: Path, settings: Any
) -> None:
    weird = tmp_path / "..%2F..%2Fetc passwd.txt"
    weird.write_text("hola")
    r = import_file(client, auth, subject["id"], weird)
    assert r.status_code == 201
    stored = list((settings.data_dir / "sources").glob("*/original.txt"))
    assert len(stored) == 1
    assert oct(os.stat(stored[0]).st_mode & 0o777) == "0o400"


# ------------------------------------------------------------------ vínculos y borrado
def test_links_must_be_same_subject(client: TestClient, auth: H, subject: dict[str, Any]) -> None:
    other = client.post("/api/v1/subjects", json={"name": "Otra"}, headers=auth).json()
    unit = client.post(
        f"/api/v1/subjects/{other['id']}/units", json={"kind": "topic", "title": "X"}, headers=auth
    ).json()
    r = client.post(
        "/api/v1/sources/text",
        headers=auth,
        json={"subject_id": subject["id"], "title": "T", "text": "x", "unit_ids": [unit["id"]]},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_link"


def test_delete_source_removes_files_and_index(
    client: TestClient, auth: H, subject: dict[str, Any], tmp_path: Path, settings: Any
) -> None:
    p = tmp_path / "borrar.md"
    p.write_text("# Hola\n\nmundo")
    sid = import_file(client, auth, subject["id"], p).json()["id"]
    wait_done(client, auth, sid)
    assert (settings.data_dir / "sources" / sid).exists()
    assert client.delete(f"/api/v1/sources/{sid}", headers=auth).status_code == 204
    assert not (settings.data_dir / "sources" / sid).exists()
    assert client.get(f"/api/v1/sources/{sid}", headers=auth).status_code == 404


def test_library_filters(client: TestClient, auth: H, subject: dict[str, Any]) -> None:
    for title, units in (("Apuntes Observer", [subject["topics"][1]]), ("Otra nota", [])):
        client.post(
            "/api/v1/sources/text",
            headers=auth,
            json={"subject_id": subject["id"], "title": title, "text": "t", "unit_ids": units},
        )
    by_unit = client.get(f"/api/v1/sources?unit_id={subject['topics'][1]}", headers=auth).json()
    assert [x["title"] for x in by_unit["items"]] == ["Apuntes Observer"]
    by_q = client.get("/api/v1/sources?q=observer", headers=auth).json()
    assert by_q["total"] == 1
    assert client.get("/api/v1/sources?q=%25", headers=auth).json()["total"] == 0  # % literal


def test_internal_requires_core_header(
    client: TestClient, auth: H, subject: dict[str, Any], tmp_path: Path
) -> None:
    p = tmp_path / "x.txt"
    p.write_text("hola")
    r = client.post(
        "/api/v1/internal/sources/import-file",
        headers=auth,
        json={"path": str(p), "subject_id": subject["id"]},
    )
    assert r.status_code == 403
