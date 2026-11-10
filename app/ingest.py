"""受写入令牌保护的数据导入接口：把原件与清单写进本地知识库。

读取接口不需要令牌；所有写入都必须带 X-Write-Token。
令牌在首次启动时生成，落在 data/write_token.txt，不入库、不打印。
"""
from contextlib import closing
import os
from pathlib import Path
import secrets as stdlib_secrets
import tempfile
import zipfile

from fastapi import File, Form, HTTPException, UploadFile

from app import knowledge, library

TOKEN_NAME = "write_token.txt"
HEADER = "x-write-token"
MAX_DOCUMENT = 64 * 1024 * 1024
MAX_ARCHIVE = 128 * 1024 * 1024


def ensure_token(data_dir: Path) -> Path:
    path = data_dir / TOKEN_NAME
    if not path.is_file():
        path.write_text(stdlib_secrets.token_urlsafe(32), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path


def token_matches(data_dir: Path, supplied: str) -> bool:
    path = data_dir / TOKEN_NAME
    if not supplied or not path.is_file():
        return False
    return stdlib_secrets.compare_digest(path.read_text(encoding="utf-8").strip(), supplied)


def _extract(archive: Path, target: Path) -> Path:
    """解压到临时目录，拒绝绝对路径与 .. 穿越，并限制总解压体积。"""
    root = target.resolve()
    written = 0
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.is_dir():
                continue
            name = Path(member.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("压缩包含非法路径")
            destination = (root / name).resolve()
            if destination != root and root not in destination.parents:
                raise ValueError("压缩包含非法路径")
            written += member.file_size
            if written > MAX_ARCHIVE:
                raise ValueError("压缩包解压后超过大小限制")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, destination.open("wb") as out:
                while chunk := source.read(1024 * 1024):
                    out.write(chunk)
    return root


def _manifest(root: Path, name: str = "manifest.json") -> Path:
    path = root / name
    if not path.is_file():
        raise ValueError(f"压缩包内缺少 {name}")
    return path


def _bundle(payload: UploadFile, data: Path, handler):
    with tempfile.TemporaryDirectory(prefix=".import-", dir=data) as temporary:
        upload = Path(temporary) / "upload.zip"
        size = 0
        with upload.open("wb") as out:
            while chunk := payload.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE:
                    raise HTTPException(413, "上传超大")
                out.write(chunk)
        root = _extract(upload, Path(temporary) / "bundle")
        return handler(root)


def mount(app, data: Path, connect):
    @app.post("/api/documents/import")
    def import_document(file: UploadFile = File(...), title: str = Form("")):
        with tempfile.TemporaryDirectory(prefix=".import-", dir=data) as temporary:
            upload = Path(temporary) / "upload.pdf"
            size = 0
            with upload.open("wb") as out:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_DOCUMENT:
                        raise HTTPException(413, "PDF 超过 64MB 限制")
                    out.write(chunk)
            with closing(connect(data)) as conn, conn:
                return knowledge.import_pdf(conn, data, upload, title)

    @app.post("/api/import/text")
    def import_text(file: UploadFile = File(...)):
        def handler(root: Path):
            with closing(connect(data)) as conn, conn:
                return library.import_text_manifest(conn, data, _manifest(root))
        return _bundle(file, data, handler)

    @app.post("/api/import/audit")
    def import_audit(file: UploadFile = File(...)):
        def handler(root: Path):
            with closing(connect(data)) as conn, conn:
                return knowledge.import_audit(conn, data, _manifest(root))
        return _bundle(file, data, handler)

    @app.post("/api/import/ocr")
    def import_ocr(file: UploadFile = File(...)):
        def handler(root: Path):
            with closing(connect(data)) as conn, conn:
                return library.import_ocr(conn, _manifest(root))
        return _bundle(file, data, handler)

    @app.post("/api/import/expansion")
    def import_expansion(file: UploadFile = File(...)):
        def handler(root: Path):
            with closing(connect(data)) as conn, conn:
                return library.import_expansion(conn, data, _manifest(root, "pdf_manifest.json"),
                                                _manifest(root, "text_manifest.json"))
        return _bundle(file, data, handler)

    @app.post("/api/documents/{document_id}/pages/{physical_page}/review")
    def review(document_id: str, physical_page: int, payload: dict):
        with closing(connect(data)) as conn, conn:
            return knowledge.review_page(conn, document_id, physical_page, payload)

    @app.post("/api/evidence")
    def evidence(payload: dict):
        with closing(connect(data)) as conn, conn:
            return knowledge.create_evidence(conn, payload)

    @app.get("/api/evidence")
    def evidence_list():
        with closing(connect(data)) as conn:
            return knowledge.list_evidence(conn)

    return app
