import sqlite3
from pathlib import Path

import pytest


def sample_data(tmp_path):
    data = tmp_path / "source"
    (data / "originals").mkdir(parents=True)
    with sqlite3.connect(data / "clinical.sqlite3") as conn:
        conn.execute("CREATE TABLE patients(id TEXT, code TEXT)")
        conn.execute("INSERT INTO patients VALUES('1','SIM-RESTORE')")
    (data / "originals" / "sample.pdf").write_bytes(b"%PDF-synthetic-backup")
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
    assert (destination / "originals" / "sample.pdf").read_bytes() == b"%PDF-synthetic-backup"
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
