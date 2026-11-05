"""Retención del audio: se borra el audio, nunca la transcripción."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.connection import connect
from app.jobs import handlers, queue
from app.services import audio_files
from app.services import settings as prefs
from app.services import sources as src_svc

from .test_transcription import FakeWhisper, _audio_source, _install_fake_models, _run

H = dict[str, str]
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _transcribed(settings: Settings, processed: datetime = NOW) -> tuple[str, Path, Path]:
    """Audio ya transcrito con su original pesado y su copia ligera."""
    sid = _audio_source(settings, seconds=2)
    d = settings.data_dir / "sources" / sid
    orig = d / "original.wav"
    orig.write_bytes(b"x" * 1000)
    db = connect(settings.db_path)
    db.execute(
        "UPDATE sources SET status = 'ready', stored_path = ?, processed_at = ?,"
        " metadata_json = ? WHERE id = ?",
        (
            f"sources/{sid}/original.wav",
            _ts(processed),
            json.dumps({"transcription": "done"}),
            sid,
        ),
    )
    src_svc.add_version(db, sid, "[00:00] Hola, clase.", "transcribed")
    return sid, orig, d / "normalized.wav"


def _row(settings: Settings, sid: str) -> dict[str, object]:
    db = connect(settings.db_path)
    return dict(db.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone())


def test_original_goes_first_light_copy_after_days(settings: Settings) -> None:
    sid, orig, light = _transcribed(settings)
    db = connect(settings.db_path)
    assert audio_files.state(settings.data_dir, _row(settings, sid))[0] == "full"

    # Recién transcrita: se borra solo el original pesado.
    assert audio_files.sweep(db, settings.data_dir, now=NOW) == 1000
    assert not orig.exists() and light.exists()
    assert audio_files.state(settings.data_dir, _row(settings, sid))[0] == "light"
    assert audio_files.expires_at(db, _row(settings, sid)) == _ts(NOW + timedelta(days=7))

    # A los 6 días sigue; a los 7, se borra la copia ligera.
    assert audio_files.sweep(db, settings.data_dir, now=NOW + timedelta(days=6)) == 0
    assert light.exists()
    assert audio_files.sweep(db, settings.data_dir, now=NOW + timedelta(days=7)) > 0
    assert not light.exists()
    assert audio_files.state(settings.data_dir, _row(settings, sid)) == ("deleted", 0)

    # La transcripción y su texto quedan intactos.
    v = src_svc.current_version(db, sid)
    assert v is not None and v["text"] == "[00:00] Hola, clase."
    assert _row(settings, sid)["status"] == "ready"


def test_keep_days_setting(settings: Settings) -> None:
    sid, _, light = _transcribed(settings)
    db = connect(settings.db_path)
    later = NOW + timedelta(days=20)
    prefs.put(db, audio_files.KEEP_DAYS_KEY, 30)
    audio_files.sweep(db, settings.data_dir, now=later)
    assert light.exists()
    prefs.put(db, audio_files.KEEP_DAYS_KEY, 0)  # conservar siempre
    assert audio_files.expires_at(db, _row(settings, sid)) is None
    audio_files.sweep(db, settings.data_dir, now=NOW + timedelta(days=365))
    assert light.exists()
    prefs.put(db, audio_files.KEEP_DAYS_KEY, 99)  # valor no válido → 7
    assert audio_files.keep_days(db) == 7


def test_untranscribed_or_busy_audio_is_never_touched(settings: Settings) -> None:
    sid, orig, light = _transcribed(settings)
    db = connect(settings.db_path)
    far = NOW + timedelta(days=60)
    # Transcripción vacía o fallida: el audio es lo único que hay.
    for meta, status in ((
        {"transcription": "empty"}, "ready"), ({"transcription": "done"}, "failed"
    )):  # fmt: skip
        db.execute(
            "UPDATE sources SET status = ?, metadata_json = ? WHERE id = ?",
            (status, json.dumps(meta), sid),
        )
        assert audio_files.sweep(db, settings.data_dir, now=far) == 0
    # Con una retranscripción en cola, tampoco.
    db.execute(
        "UPDATE sources SET status = 'ready', metadata_json = ? WHERE id = ?",
        (json.dumps({"transcription": "done"}), sid),
    )
    queue.enqueue(db, "transcribe", "stt", sid, {})
    assert audio_files.sweep(db, settings.data_dir, now=far) == 0
    assert orig.exists() and light.exists()


def test_transcription_end_drops_original(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_models(settings.data_dir)
    sid = _audio_source(settings, seconds=30)
    orig = settings.data_dir / "sources" / sid / "original.wav"
    orig.write_bytes(b"x" * 10)
    db = connect(settings.db_path)
    db.execute(
        "UPDATE sources SET stored_path = ? WHERE id = ?", (f"sources/{sid}/original.wav", sid)
    )
    jid = queue.enqueue(db, "transcribe", "stt", sid, {"language": "es"})
    assert queue.claim_next(db, ["stt"]) is not None  # el propio trabajo está «running»
    monkeypatch.setattr(handlers, "transcribe_wav", FakeWhisper())
    _run(settings, jid)
    assert not orig.exists()
    assert (settings.data_dir / "sources" / sid / "normalized.wav").exists()


def test_audio_endpoints(client: TestClient, auth: H, settings: Settings) -> None:
    sid, orig, light = _transcribed(settings)
    a = client.get(f"/api/v1/sources/{sid}/audio", headers=auth).json()
    assert a["state"] == "full" and a["deletable"] is True and a["bytes"] > 1000
    assert a["expires_at"] is not None

    r = client.delete(f"/api/v1/sources/{sid}/audio", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json() == {"state": "deleted", "bytes": 0, "expires_at": None, "deletable": False}
    assert not orig.exists() and not light.exists()

    # Sin audio: retranscribir y reintentar explican por qué no se puede.
    r = client.post(f"/api/v1/sources/{sid}/transcribe", headers=auth, json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "audio_deleted"
    connect(settings.db_path).execute("UPDATE sources SET status = 'failed' WHERE id = ?", (sid,))
    r = client.post(f"/api/v1/sources/{sid}/retry", headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "audio_deleted"

    # La transcripción sigue ahí.
    c = client.get(f"/api/v1/sources/{sid}/content", headers=auth).json()
    assert "Hola, clase." in json.dumps(c, ensure_ascii=False)


def test_delete_audio_requires_transcription(
    client: TestClient, auth: H, settings: Settings
) -> None:
    sid = _audio_source(settings, seconds=2)  # sin transcribir
    r = client.delete(f"/api/v1/sources/{sid}/audio", headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_transcribed"
    assert (settings.data_dir / "sources" / sid / "normalized.wav").exists()
    assert client.delete("/api/v1/sources/nope/audio", headers=auth).status_code == 404


def test_retry_after_original_dropped_uses_light_copy(
    client: TestClient, auth: H, settings: Settings
) -> None:
    sid, orig, _ = _transcribed(settings)
    orig.unlink()
    _install_fake_models(settings.data_dir)
    connect(settings.db_path).execute("UPDATE sources SET status = 'failed' WHERE id = ?", (sid,))
    r = client.post(f"/api/v1/sources/{sid}/retry", headers=auth)
    assert r.status_code == 200, r.text
    db = connect(settings.db_path)
    types = [t for (t,) in db.execute("SELECT type FROM jobs WHERE source_id = ?", (sid,))]
    assert types == ["transcribe"]  # no intenta preparar un original que ya no existe


def test_keep_days_via_stt_settings(client: TestClient, auth: H) -> None:
    assert client.get("/api/v1/stt", headers=auth).json()["audio_keep_days"] == 7
    r = client.put("/api/v1/stt/settings", headers=auth, json={"audio_keep_days": 30})
    assert r.status_code == 200 and r.json()["audio_keep_days"] == 30
    r = client.put("/api/v1/stt/settings", headers=auth, json={"audio_keep_days": 5})
    assert r.status_code == 422
