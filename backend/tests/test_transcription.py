"""Fase 3: modelos, transcripción por tramos con checkpoint, reanudación y exportación."""

import hashlib
import io
import json
import os
import wave
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.connection import connect
from app.jobs import handlers, queue
from app.pipelines.extract.document import segment
from app.services import sources as src_svc
from app.stt import models
from app.stt.transcript import Piece, build_text, to_srt, to_txt

H = dict[str, str]


# ------------------------------------------------------------------ formato del texto
def test_build_text_paragraphs_and_marks() -> None:
    text = build_text(
        [
            Piece(0, 3500, " Hola a todos. "),
            Piece(3600, 7000, "Hoy: arquitectura."),
            Piece(12_000, 15_000, "[00:99] Tras la pausa."),  # nunca una marca falsa
            Piece(3_725_000, 3_726_000, "Una hora después."),
        ]
    )
    assert text == (
        "[00:00] Hola a todos.\n[00:04] Hoy: arquitectura.\n\n"
        "[00:12] Tras la pausa.\n\n[1:02:05] Una hora después."
    )
    segs = segment(text)
    assert [(s.start_ms, s.end_ms) for s in segs] == [
        (0, 4000),
        (4000, 12_000),
        (12_000, 3_725_000),
        (3_725_000, None),
    ]
    assert all(text[s.char_start : s.char_end] == s.text for s in segs)


def test_exports() -> None:
    text = "[00:00] Uno.\n[00:04] Dos\nsigue.\n\n[01:00] Tres."
    srt = to_srt(segment(text), duration_ms=65_000)
    assert srt.split("\n\n")[1] == "2\n00:00:04,000 --> 00:01:00,000\nDos sigue."
    assert srt.rstrip().endswith("00:01:00,000 --> 00:01:05,000\nTres.")
    assert to_txt(text) == "Uno. Dos sigue.\n\nTres.\n"


# ------------------------------------------------------------------ descarga verificada
def _fake_spec(monkeypatch: pytest.MonkeyPatch, data: bytes) -> str:
    spec = models.ModelSpec(
        "fake", "stt", "Fake", "", "ggml-fake.bin", "https://example/fake", len(data),
        hashlib.sha256(data).hexdigest(), 1,
    )  # fmt: skip
    monkeypatch.setitem(models.CATALOG, "fake", spec)
    return "fake"


def test_download_verifies_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"x" * 3_000_000
    mid = _fake_spec(monkeypatch, data)
    progress: list[float] = []
    path = models.download(
        tmp_path, mid, progress.append, lambda: False, opener=lambda _: io.BytesIO(data)
    )
    assert path.read_bytes() == data and progress[-1] == 1.0
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    path.unlink()
    with pytest.raises(models.DownloadError) as e:
        models.download(
            tmp_path, mid, lambda _: None, lambda: False,
            opener=lambda _: io.BytesIO(b"y" * len(data)),
        )  # fmt: skip
    assert e.value.code == "bad_hash"
    # Página de error HTML en lugar del modelo (incidente real de la Fase 0.5).
    with pytest.raises(models.DownloadError) as e:
        models.download(
            tmp_path, mid, lambda _: None, lambda: False, opener=lambda _: io.BytesIO(b"<html>504")
        )
    assert e.value.code == "bad_size"
    assert not list(models.models_dir(tmp_path).iterdir())  # nada a medias


# ------------------------------------------------------------------ transcripción por tramos
def _install_fake_models(data_dir: Path) -> None:
    for m in (models.DEFAULT_STT, models.VAD):
        p = models.model_path(data_dir, m)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            f.truncate(models.CATALOG[m].size)  # archivo disperso: no ocupa disco


def _audio_source(settings: Settings, seconds: int) -> str:
    db = connect(settings.db_path)
    db.execute("INSERT INTO subjects(id, owner_id, name) VALUES ('s','local','S')")
    db.execute(
        "INSERT INTO sources(id, subject_id, kind, title, status)"
        " VALUES ('a', 's', 'audio', 'Clase', 'processing')"
    )
    d = settings.data_dir / "sources" / "a"
    d.mkdir(parents=True)
    with wave.open(str(d / "normalized.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000 * seconds)
    return "a"


class FakeWhisper:
    """Simula whisper: una frase cada 10 s del tramo; puede 'morir' en el tramo N."""

    def __init__(self, crash_on_call: int | None = None) -> None:
        self.calls: list[int] = []
        self.crash_on_call = crash_on_call

    def __call__(self, wav: Path, model: Path, vad: Path, language: str, offset_ms: int,
                 cancelled: Any) -> tuple[list[Piece], str]:  # fmt: skip
        self.calls.append(offset_ms)
        if self.crash_on_call == len(self.calls):
            raise KeyboardInterrupt("cierre forzado simulado")
        with wave.open(str(wav), "rb") as w:
            dur = int(w.getnframes() * 1000 / w.getframerate())
        pieces, t = [], 0
        while t < dur:
            # tiempos absolutos (el proveedor suma el desfase del tramo)
            start = offset_ms + t
            pieces.append(
                Piece(start, min(start + 9000, offset_ms + dur), f"Frase {start // 1000}.")
            )
            t += 10_000
        return pieces, "es"


def _run(settings: Settings, job_id: str) -> None:
    db = connect(settings.db_path)
    job = dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
    handlers.transcribe(handlers.JobContext(job=job, db=db, data_dir=settings.data_dir))


def test_transcribe_resumes_after_forced_close(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_models(settings.data_dir)
    sid = _audio_source(settings, seconds=12 * 60)  # 12 min → 3 tramos
    db = connect(settings.db_path)
    jid = queue.enqueue(db, "transcribe", "stt", sid, {"language": "auto"})
    assert queue.claim_next(db, ["stt"]) is not None

    crashing = FakeWhisper(crash_on_call=3)
    monkeypatch.setattr(handlers, "transcribe_wav", crashing)
    with pytest.raises(KeyboardInterrupt):
        _run(settings, jid)
    cp = json.loads(db.execute("SELECT checkpoint_json FROM jobs WHERE id=?", (jid,)).fetchone()[0])
    assert cp["parts"] == 2 and cp["language"] == "es"  # el idioma detectado se fija
    assert 0 < cp["next_ms"] < 12 * 60_000

    # Reapertura: el trabajo vuelve a la cola y continúa desde el checkpoint.
    assert queue.recover_interrupted(db) == 1
    resumed = FakeWhisper()
    monkeypatch.setattr(handlers, "transcribe_wav", resumed)
    _run(settings, jid)
    assert resumed.calls == [cp["next_ms"]]  # no repite lo ya transcrito

    v = src_svc.current_version(db, sid)
    assert v is not None and v["origin"] == "transcribed"
    starts = [s.start_ms or 0 for s in segment(v["text"])]
    assert starts == sorted(starts) and len(starts) == len(set(starts))  # sin duplicados
    assert starts[0] == 0 and starts[-1] >= 11 * 60_000  # cubre todo el audio
    row = db.execute("SELECT status, language FROM sources WHERE id = ?", (sid,)).fetchone()
    assert tuple(row) == ("ready", "es")
    assert not (settings.data_dir / "sources" / sid / "transcript-parts").exists()


def test_chunk_edges_do_not_cut_phrases(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_models(settings.data_dir)
    sid = _audio_source(settings, seconds=11 * 60)
    db = connect(settings.db_path)
    jid = queue.enqueue(db, "transcribe", "stt", sid, {"language": "es"})
    fake = FakeWhisper()
    monkeypatch.setattr(handlers, "transcribe_wav", fake)
    _run(settings, jid)
    # El 2.º tramo empieza donde acabó la última frase completa del 1.º, no en el corte.
    assert fake.calls[0] == 0 and fake.calls[1] < 5 * 60_000


# ------------------------------------------------------------------ API
def test_stt_status_and_settings(client: TestClient, auth: H, settings: Settings) -> None:
    s = client.get("/api/v1/stt", headers=auth).json()
    assert s["ready"] is False and s["model"] == models.DEFAULT_STT
    assert {m["id"] for m in s["models"]} >= {models.DEFAULT_STT, models.VAD}
    r = client.put("/api/v1/stt/settings", headers=auth, json={"model": "small", "language": "es"})
    assert r.json()["model"] == "small" and r.json()["language"] == "es"
    r = client.put("/api/v1/stt/settings", headers=auth, json={"model": models.VAD})
    assert r.status_code == 400
    _install_fake_models(settings.data_dir)
    client.put("/api/v1/stt/settings", headers=auth, json={"model": models.DEFAULT_STT})
    assert client.get("/api/v1/stt", headers=auth).json()["ready"] is True


def test_transcribe_requires_model(client: TestClient, auth: H, settings: Settings) -> None:
    sid = _audio_source(settings, seconds=2)
    connect(settings.db_path).execute("UPDATE sources SET status='ready' WHERE id=?", (sid,))
    r = client.post(f"/api/v1/sources/{sid}/transcribe", headers=auth, json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "needs_model"


def test_export_endpoint(client: TestClient, auth: H, settings: Settings) -> None:
    sid = _audio_source(settings, seconds=2)
    db = connect(settings.db_path)
    db.execute(
        "UPDATE sources SET duration_ms = 70000, title = 'Clase 1: intro/tema' WHERE id=?", (sid,)
    )
    src_svc.add_version(db, sid, "[00:00] Hola.\n[00:30] Adiós.", "transcribed")
    r = client.get(f"/api/v1/sources/{sid}/export?format=srt", headers=auth).json()
    assert r["filename"] == "Clase 1 introtema.srt"
    assert "00:00:30,000 --> 00:01:10,000" in r["content"]
    r = client.get(f"/api/v1/sources/{sid}/export?format=txt", headers=auth).json()
    assert r["content"] == "Hola. Adiós.\n"


def test_recording_import_kind(client: TestClient, auth: H, tmp_path: Path) -> None:
    sid = client.post("/api/v1/subjects", json={"name": "S"}, headers=auth).json()["id"]
    wav = tmp_path / "rec.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(os.urandom(32000))
    r = client.post(
        "/api/v1/internal/sources/import-file",
        headers={**auth, "x-core-caller": "1"},
        json={"path": str(wav), "subject_id": sid, "kind": "recording", "title": "Clase del lunes"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "recording" and r.json()["title"] == "Clase del lunes"


def test_waiting_audio_is_queued_once_model_installed(settings: Settings) -> None:
    from app.services import transcription

    sid = _audio_source(settings, seconds=2)
    db = connect(settings.db_path)
    db.execute(
        "UPDATE sources SET status = 'ready', metadata_json = ? WHERE id = ?",
        (json.dumps({"transcription": "needs_model"}), sid),
    )
    assert transcription.enqueue_waiting(db, settings.data_dir) == 0  # sin modelo
    _install_fake_models(settings.data_dir)
    assert transcription.enqueue_waiting(db, settings.data_dir) == 1
    assert transcription.enqueue_waiting(db, settings.data_dir) == 0  # no duplica
    job = db.execute("SELECT type, priority FROM jobs WHERE source_id = ?", (sid,)).fetchone()
    assert tuple(job) == ("transcribe", queue.PRIORITY["recording"])
