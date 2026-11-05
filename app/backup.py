"""Authenticated encrypted backup; restore never replaces an occupied directory."""
import base64
from contextlib import closing
import hashlib
from io import BytesIO
import json
import os
import re
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
import zipfile

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi.responses import Response
from pydantic import BaseModel, Field

MAGIC = b"TCMBACK1"
MAX_BYTES = 512 * 1024 * 1024


def _registered_hashes(conn):
    try:
        rows = conn.execute("SELECT id,sha256 FROM documents").fetchall()
    except sqlite3.DatabaseError as exc:
        raise ValueError("备份数据库缺少受支持的资料登记结构") from exc
    if any(row[0] != row[1] or not isinstance(row[1], str) or not re.fullmatch(r"[0-9a-f]{64}", row[1]) for row in rows):
        raise ValueError("资料登记哈希无效")
    return {row[1] for row in rows}


def _fernet(password, salt):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("备份口令需要12至1024个字符")
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(password.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def create_backup(data_dir: Path, password: str):
    data_dir = data_dir.resolve()
    salt = os.urandom(16)
    cipher = _fernet(password, salt)
    files = {}
    try:
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "snapshot.sqlite3"
            with closing(sqlite3.connect(data_dir / "clinical.sqlite3")) as source, closing(sqlite3.connect(copy)) as target:
                if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("数据库完整性检查未通过")
                source.backup(target)
                registered = _registered_hashes(target)
            files["clinical.sqlite3"] = copy.read_bytes()
    except sqlite3.DatabaseError as exc:
        raise ValueError("数据库无法备份，请先修复或恢复") from exc
    for sha in registered:
        original = data_dir / "originals" / f"{sha}.pdf"
        if not original.resolve().is_relative_to(data_dir) or original.is_symlink() or not original.is_file():
            raise ValueError("登记原件缺失或路径无效，不能生成完整备份")
        content = original.read_bytes()
        if hashlib.sha256(content).hexdigest() != sha:
            raise ValueError("登记原件哈希不一致，不能生成完整备份")
        files[f"originals/{sha}.pdf"] = content
        if sum(len(value) for value in files.values()) > MAX_BYTES:
            # shortcut: bounded in-memory archives; upgrade to streaming above 512 MiB.
            raise ValueError("此版本备份上限为512MiB")
    manifest = {"format": 1, "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}, "credentials_included": False}
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
        bundle.writestr("manifest.json", json.dumps(manifest))
    return MAGIC + salt + cipher.encrypt(archive.getvalue())


def restore_backup(encrypted: bytes, password: str, destination: Path):
    destination = destination.resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("恢复目标必须不存在或为空目录，不覆盖已有数据")
    if len(encrypted) > MAX_BYTES * 2 or not encrypted.startswith(MAGIC) or len(encrypted) < 25:
        raise ValueError("备份格式或大小无效")
    try:
        raw = _fernet(password, encrypted[8:24]).decrypt(encrypted[24:])
    except InvalidToken as exc:
        raise ValueError("口令错误或备份已损坏") from exc
    try:
        with zipfile.ZipFile(BytesIO(raw)) as bundle:
            infos = bundle.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or sum(i.file_size for i in infos) > MAX_BYTES:
                raise ValueError("备份重复条目或解压大小超限")
            if "manifest.json" not in names or "clinical.sqlite3" not in names:
                raise ValueError("备份缺少清单或数据库")
            for item in infos:
                path = PurePosixPath(item.filename)
                allowed = item.filename in {"manifest.json", "clinical.sqlite3"} or re.fullmatch(r"originals/[0-9a-f]{64}\.pdf", item.filename)
                if not allowed or ".." in path.parts or "\\" in item.filename or path.is_absolute() or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("备份包含不允许的路径或链接")
            manifest = json.loads(bundle.read("manifest.json"))
            if not isinstance(manifest, dict):
                raise ValueError("备份清单格式无效")
            hashes_by_name = manifest.get("files", {})
            if manifest.get("format") != 1 or set(hashes_by_name) != set(names) - {"manifest.json"}:
                raise ValueError("备份清单不一致")
            files = {name: bundle.read(name) for name in hashes_by_name}
            if any(hashlib.sha256(content).hexdigest() != hashes_by_name[name] for name, content in files.items()):
                raise ValueError("备份文件哈希不一致")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("备份内容格式无效") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / "restored"
        staged.mkdir()
        for name, content in files.items():
            target = (staged / name).resolve()
            if not target.is_relative_to(staged.resolve()):
                raise ValueError("备份路径越界")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        try:
            with closing(sqlite3.connect(staged / "clinical.sqlite3")) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("恢复数据库完整性或引用检查失败")
                registered = _registered_hashes(conn)
                expected = {"clinical.sqlite3"} | {f"originals/{sha}.pdf" for sha in registered}
                if set(files) != expected or any(hashlib.sha256(files[f"originals/{sha}.pdf"]).hexdigest() != sha for sha in registered):
                    raise ValueError("恢复资料原件缺失、多余或与登记哈希不一致")
        except sqlite3.DatabaseError as exc:
            raise ValueError("恢复数据库无效") from exc
        if destination.exists():
            destination.rmdir()  # only an empty, explicitly selected directory may be replaced
        staged.rename(destination)
    return {"files": len(files), "destination": str(destination)}


class BackupInput(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


def mount_backup_route(app, data_dir, protected, database):
    @app.post("/api/backup", dependencies=protected)
    def backup(payload: BackupInput):
        return Response(create_backup(data_dir, payload.password), media_type="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="tcm-encrypted-backup.tcmbak"'})
