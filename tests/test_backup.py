import sqlite3
import hashlib
from pathlib import Path

import pytest

SAMPLE = b"%PDF-synthetic-backup"
SAMPLE_SHA = hashlib.sha256(SAMPLE).hexdigest()


def sample_data(tmp_path):
    data = tmp_path / "source"
    (data / "originals").mkdir(parents=True)
    with sqlite3.connect(data / "clinical.sqlite3") as conn:
        conn.execute("CREATE TABLE patients(id TEXT, code TEXT)")
        conn.execute("INSERT INTO patients VALUES('1','SIM-RESTORE')")
        conn.execute("CREATE TABLE documents(id TEXT PRIMARY KEY,sha256 TEXT)")
        conn.execute("INSERT INTO documents VALUES(?,?)", (SAMPLE_SHA, SAMPLE_SHA))
    conn.close()
    (data / "originals" / f"{SAMPLE_SHA}.pdf").write_bytes(SAMPLE)
    (data / "model-secret.dpapi").write_bytes(b"must-never-be-exported")
    return data


def test_encrypted_backup_restores_database_originals_but_not_credentials(tmp_path):
    from app.backup import create_backup, restore_backup

    data = sample_data(tmp_path)
    encrypted = create_backup(data, "test-password-long-enough")
    assert b"SIM-RESTORE" not in encrypted
    assert b"must-never-be-exported" not in encrypted
    destination = tmp_path / "restored"
    result = restore_backup(encrypted, "test-password-long-enough", destination)
    assert result["files"] == 2
    with sqlite3.connect(destination / "clinical.sqlite3") as conn:
        assert conn.execute("SELECT code FROM patients").fetchone()[0] == "SIM-RESTORE"
    assert (destination / "originals" / f"{SAMPLE_SHA}.pdf").read_bytes() == SAMPLE
    assert not (destination / "model-secret.dpapi").exists()


def test_wrong_password_tamper_and_nonempty_target_never_overwrite(tmp_path):
    from app.backup import create_backup, restore_backup

    encrypted = create_backup(sample_data(tmp_path), "test-password-long-enough")
    for secret in ["incorrect-password", ""]:
        with pytest.raises(ValueError):
            restore_backup(encrypted, secret, tmp_path / "unused")
    with pytest.raises(ValueError):
        restore_backup(encrypted[:-2] + b"xx", "test-password-long-enough", tmp_path / "unused")
    destination = tmp_path / "occupied"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("preserve")
    with pytest.raises(ValueError):
        restore_backup(encrypted, "test-password-long-enough", destination)
    assert marker.read_text() == "preserve"


def test_backup_requires_strong_length_and_valid_database(tmp_path):
    from app.backup import create_backup

    data = sample_data(tmp_path)
    with pytest.raises(ValueError):
        create_backup(data, "short")
    (data / "clinical.sqlite3").write_bytes(b"not a database")
    with pytest.raises(ValueError):
        create_backup(data, "test-password-long-enough")


@pytest.mark.parametrize("corruption", ["missing", "modified"])
def test_backup_rejects_missing_or_changed_registered_original(tmp_path, corruption):
    from app.backup import create_backup

    data = sample_data(tmp_path)
    original = data / "originals" / f"{SAMPLE_SHA}.pdf"
    if corruption == "missing":
        original.unlink()
    else:
        original.write_bytes(b"changed original")
    with pytest.raises(ValueError):
        create_backup(data, "test-password-long-enough")


def test_backup_uses_registered_snapshot_not_unregistered_originals(tmp_path):
    from app.backup import create_backup, restore_backup

    data = sample_data(tmp_path)
    (data / "originals" / ("a" * 64 + ".pdf")).write_bytes(b"uncommitted-orphan")
    result = restore_backup(create_backup(data, "test-password-long-enough"), "test-password-long-enough", tmp_path / "restored")
    assert result["files"] == 2
    assert not (tmp_path / "restored" / "originals" / ("a" * 64 + ".pdf")).exists()


def test_database_only_backup_checks_size_before_reading_archive(tmp_path, monkeypatch):
    import app.backup as backup

    data = sample_data(tmp_path)
    with sqlite3.connect(data / "clinical.sqlite3") as conn:
        conn.execute("DELETE FROM documents")
    conn.close()
    monkeypatch.setattr(backup, "MAX_BYTES", 64)
    with pytest.raises(ValueError):
        backup.create_backup(data, "test-password-long-enough")
