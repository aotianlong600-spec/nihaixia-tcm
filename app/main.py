"""只读知识库 API：检索原文、读取页面、查询方剂索引。

本仓库是数据底座：原文库、方剂索引、检索与溯源读取。
辨证算法、方证匹配、问诊记录、模型接入不在本服务内，也不在本仓库内。
所有接口只接受 GET，不存在写入路径。
"""
from contextlib import contextmanager
import json
import os
from functools import lru_cache
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import knowledge, library
from app.domain import DomainError

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(__file__).resolve().parent / "resources" / "open_formula_library.json"
MAX_LIMIT = 50
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


@lru_cache(maxsize=1)
def catalog() -> dict:
    """开源方剂索引；构建期校验过，只读一次并缓存。"""
    with CATALOG.open(encoding="utf-8") as stream:
        return json.load(stream)


def _summary(formula: dict) -> dict:
    return {key: formula.get(key) for key in ("id", "name", "syndrome", "six_meridian", "source_refs")}


def create_app(data_dir: Path | None = None) -> FastAPI:
    data = Path(data_dir or os.environ.get("TCM_DATA_DIR", ROOT / "data")).resolve()
    data.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="经方原文库（只读）", version="1.0.0", docs_url="/api/docs")
    app.state.data_dir = data

    @contextmanager
    def session():
        conn = sqlite3.connect(data / "knowledge.sqlite3", timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    with session() as conn:
        library.initialize(conn, data)

    @app.middleware("http")
    async def readonly_boundary(request, call_next):
        if request.url.path.startswith("/api") and request.method not in {"GET", "HEAD"}:
            return JSONResponse({"detail": "本服务只提供只读查询"}, status_code=405)
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_failure(request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def invalid_fields(request, exc):
        return JSONResponse({"detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                                       for error in exc.errors()]}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def storage_failure(request, exc):
        return JSONResponse({"detail": "知识库读取失败，请检查 data 目录"}, status_code=503)

    @app.get("/api/status")
    def status():
        return {"status": "ok", "app_id": "tcm-knowledge-core", "version": "1.0.0", "read_only": True}

    @app.get("/api/overview")
    def overview():
        index = catalog()
        with session() as conn:
            documents = knowledge.list_documents(conn)
            sources = library.list_sources(conn)
        return {
            "documents": len(documents),
            "pages": sum(document["physical_pages"] for document in documents),
            "sources": len(sources),
            "formulas": len(index.get("formulas", [])),
            "patterns": len(index.get("patterns", [])),
            "source_metadata": index.get("source_metadata", {}),
        }

    @app.get("/api/documents")
    def documents():
        with session() as conn:
            return knowledge.list_documents(conn)

    @app.get("/api/documents/{document_id}/pages/{physical_page}")
    def page(document_id: str, physical_page: int):
        with session() as conn:
            found = knowledge.get_page(conn, document_id, physical_page)
        if found is None:
            raise HTTPException(404, "页面不存在")
        return found

    @app.get("/api/documents/{document_id}/pages/{physical_page}/image")
    def page_image(document_id: str, physical_page: int):
        with session() as conn:
            try:
                image = knowledge.render_page(conn, data, document_id, physical_page)
            except ValueError as exc:
                raise HTTPException(404 if "不存在" in str(exc) else 400, str(exc)) from exc
        return Response(image, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/sources")
    def sources():
        with session() as conn:
            return library.list_sources(conn)

    @app.get("/api/sources/{source_id}/units/{unit_no}")
    def source_unit(source_id: str, unit_no: int):
        with session() as conn:
            found = library.get_unit(conn, data, source_id, unit_no)
        if found is None:
            raise HTTPException(404, "单元不存在")
        return found

    @app.get("/api/search")
    def search(q: str = Query(..., min_length=1, max_length=200),
               document_id: str | None = None,
               limit: int = Query(20, ge=1, le=MAX_LIMIT)):
        with session() as conn:
            return library.search(conn, q, source_id=document_id, limit=limit)

    @app.get("/api/formulas")
    def formulas(q: str | None = Query(None, max_length=100),
                 limit: int = Query(MAX_LIMIT, ge=1, le=500)):
        entries = catalog().get("formulas", [])
        if q:
            needle = q.strip()
            entries = [entry for entry in entries
                       if needle in entry.get("name", "")
                       or needle in entry.get("syndrome", "")
                       or any(needle in component.get("name", "") for component in entry.get("components", []))]
        return {"total": len(entries), "items": [_summary(entry) for entry in entries[:limit]]}

    @app.get("/api/formulas/{formula_id}")
    def formula(formula_id: str):
        for entry in catalog().get("formulas", []):
            if entry.get("id") == formula_id:
                return entry
        raise HTTPException(404, "方剂不存在")

    dist = ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/")
        def not_built():
            return JSONResponse({"detail": "界面尚未构建；本服务只提供 /api 只读接口", "read_only": True},
                                status_code=503)
    return app
