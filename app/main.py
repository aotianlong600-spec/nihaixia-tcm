"""FastAPI service uniting Stage 1-5 TCM Study Brain, local SQLite ingest, and Ni Shi streaming AI."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ai import config_store, grounded_study, llm_client, ni_consult, ni_persona
from app import (
    acupuncture_catalog,
    acupuncture_diagnose,
    bencao_catalog,
    catalog,
    consult_history,
    formula_diagnose,
    formula_extras,
    hantang_catalog,
    ingest,
    knowledge,
    library,
    library_catalog,
    neijing_catalog,
    stage5_service,
    syndrome_composer,
)
from app.domain import DomainError
from app.paths import ROOT, WEB_DIR, default_runtime_data_dir


_TOKEN_PROTECTED_PREFIXES = ("/api/documents/", "/api/import/", "/api/evidence")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}


class AIConfigPayload(BaseModel):
    provider: str | None = None
    protocol: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    persona_style: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_sec: int | None = None


class ChatMessageItem(BaseModel):
    role: str
    content: str


class AIChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    pulse: str = Field(default="", max_length=240)
    tongue: str = Field(default="", max_length=240)
    style: str = Field(default="master_balanced", max_length=48)
    offline: bool = False
    history: list[ChatMessageItem] = Field(default_factory=list)
    entity_focus: dict[str, Any] | None = None
    config_override: AIConfigPayload | None = None


class AIPacketRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    pulse: str = Field(default="", max_length=240)
    tongue: str = Field(default="", max_length=240)
    entity_focus: dict[str, Any] | None = None


class PatientPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    gender: str = Field(default="", max_length=16)
    age: str = Field(default="", max_length=24)
    notes: str = Field(default="", max_length=400)


class PatientUpdatePayload(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    gender: str | None = Field(default=None, max_length=16)
    age: str | None = Field(default=None, max_length=24)
    notes: str | None = Field(default=None, max_length=400)


class SessionCreatePayload(BaseModel):
    title: str = Field(default="", max_length=60)
    intake: dict[str, Any] | None = None
    pinned_entity: dict[str, Any] | None = None


class SessionSavePayload(BaseModel):
    title: str | None = Field(default=None, max_length=60)
    intake: dict[str, Any] | None = None
    pinned_entity: dict[str, Any] | None = None
    turns: list[dict[str, Any]] | None = None
    latest_packet: dict[str, Any] | None = None
    update_pinned: bool = False
    update_packet: bool = False


def connect(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir / "knowledge.sqlite3", timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _sse_frame(event: str, payload: Any) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


def _origin_is_safe(request: Request) -> bool:
    for header_name in ("origin", "referer"):
        raw = request.headers.get(header_name)
        if not raw:
            continue
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host not in _LOOPBACK_HOSTS:
            return False
    return True


def _assert_ai_origin(request: Request) -> None:
    if not _origin_is_safe(request):
        raise HTTPException(status_code=403, detail="禁止跨源调用本地 AI 接口")


def _mount_static_web(app: FastAPI) -> None:
    if not WEB_DIR.is_dir():
        return

    @app.get("/")
    def index_page():
        return FileResponse(WEB_DIR / "index.html")

    for asset_name in (
        "style.css",
        "app.js",
        "acupuncture.js",
        "bencao.js",
        "neijing.js",
        "formulas_stage4.js",
        "library_stage5.js",
        "ni_ai.js",
        "favicon.svg",
    ):
        asset_path = WEB_DIR / asset_name
        if asset_path.is_file():
            media = "image/svg+xml" if asset_name.endswith(".svg") else None

            def _make_asset(file_path: Path, media_type: str | None):
                def _serve():
                    return FileResponse(file_path, media_type=media_type)

                return _serve

            app.add_api_route(f"/{asset_name}", _make_asset(asset_path, media), methods=["GET"])

    app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    data = Path(data_dir).resolve() if data_dir is not None else default_runtime_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    with closing(connect(data)) as conn, conn:
        library.initialize(conn, data)
    token_path = ingest.ensure_token(data)

    app = FastAPI(title="倪氏经方 · 中医大脑工作台")
    app.state.data_dir = data
    app.state.write_token_path = token_path

    @app.exception_handler(DomainError)
    def handle_domain_error(_, exc: DomainError):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(ValueError)
    def handle_value_error(_, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.middleware("http")
    async def guard_requests(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "POST"}:
            return JSONResponse({"detail": "Method not allowed"}, status_code=405)
        path = request.url.path
        if request.method == "POST":
            if path.startswith(_TOKEN_PROTECTED_PREFIXES):
                supplied = request.headers.get(ingest.HEADER, "")
                if not ingest.token_matches(data, supplied):
                    return JSONResponse({"detail": "写入操作需要有效的 X-Write-Token"}, status_code=401)
            elif path.startswith("/api/ai/") and not _origin_is_safe(request):
                return JSONResponse({"detail": "禁止跨源调用本地 AI 接口"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ── Status & Unified Overview ────────────────────────────────────────
    @app.get("/api/status")
    def api_status():
        ai_cfg = config_store.resolve_runtime_config(data)
        return {
            "status": "ok",
            "app_id": "tcm-knowledge-core",
            "engine": "tcm-study-brain-v2+ni-ai",
            "reads_open": True,
            "writes_require_token": True,
            "ai_ready": ai_cfg["ready"],
            "ai_provider": ai_cfg["provider"],
            "ai_model": ai_cfg["model"],
        }

    @app.get("/api/health")
    def api_health():
        return {"status": "ok", "module": "nihaixia-tcm-brain", "runtime": "fastapi"}

    @app.get("/api/overview")
    def api_overview():
        payload = catalog.overview()
        payload["formula_summary"] = formula_extras.stage4_summary()
        if isinstance(payload.get("modules"), dict):
            payload["modules"]["six_channels"] = "complete"
            payload["modules"]["diagnosis"] = "ready"
            payload["modules"]["jinkui"] = "complete"
            payload["modules"]["ni_ai"] = "ready"
        with closing(connect(data)) as conn:
            docs = knowledge.list_documents(conn)
            srcs = library.list_sources(conn)
            evs = knowledge.list_evidence(conn)
        payload["documents"] = len(docs)
        payload["sources"] = len(srcs)
        payload["evidence"] = len(evs)
        payload["source_metadata"] = {"books": library_catalog.overview().get("total_books", 17)}
        return payload

    # ── Formulas / Herbs / Six Channels / Jinkui (Stage 4) ───────────────
    @app.get("/api/formulas")
    def api_formulas(
        q: str = Query(default=""),
        type: str = Query(default=""),
        meridian: str = Query(default=""),
        book: str = Query(default=""),
        status: str = Query(default=""),
        review: str = Query(default=""),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=24, ge=1, le=60),
    ):
        return catalog.list_formulas(
            query=q,
            kind=type,
            meridian=meridian,
            book=book,
            status=status,
            review=review,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/formulas/diagnose")
    def api_formulas_diagnose(
        q: str = Query(default=""),
        book: str = Query(default=""),
        six_meridian: str = Query(default=""),
        chapter_id: str = Query(default=""),
    ):
        return formula_diagnose.diagnose_formulas(
            q=q,
            book=book,
            six_meridian=six_meridian,
            chapter_id=chapter_id,
        )

    @app.get("/api/formulas/{formula_id:path}")
    def api_formula_detail(formula_id: str):
        item = catalog.get_formula(formula_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到方剂")
        return formula_extras.enrich_formula_payload(item)

    @app.get("/api/herbs")
    def api_herbs(
        q: str = Query(default=""),
        category: str = Query(default=""),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=24, ge=1, le=60),
    ):
        return catalog.list_herbs(query=q, category=category, page=page, page_size=page_size)

    @app.get("/api/herbs/{herb_id:path}")
    def api_herb_detail(herb_id: str):
        item = catalog.get_herb(herb_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到中药")
        return item

    @app.get("/api/six-channels")
    def api_six_channels():
        return catalog.list_six_channels()

    @app.get("/api/six-channels/{channel_id:path}")
    def api_six_channel_detail(channel_id: str):
        item = catalog.get_six_channel(channel_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到六经条目")
        return formula_extras.enrich_six_channel_payload(item)

    @app.get("/api/jinkui-chapters")
    def api_jinkui_chapters(q: str = Query(default=""), review_status: str = Query(default="")):
        return formula_extras.list_jinkui_chapters(q=q, review_status=review_status)

    @app.get("/api/jinkui-chapters/{chapter_id:path}")
    def api_jinkui_chapter_detail(chapter_id: str):
        item = formula_extras.get_jinkui_chapter(chapter_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到金匮要略篇目")
        return item

    @app.get("/api/formula-modifications")
    def api_formula_modifications(
        q: str = Query(default=""),
        base_formula_id: str = Query(default=""),
        target_formula_id: str = Query(default=""),
    ):
        return formula_extras.list_formula_modifications(
            q=q, base_formula_id=base_formula_id, target_formula_id=target_formula_id
        )

    @app.get("/api/formula-variants")
    def api_formula_variants(q: str = Query(default=""), diff_only: bool = Query(default=False)):
        return formula_extras.list_formula_variants(q=q, diff_only=diff_only)

    @app.get("/api/formula-acupuncture-links")
    def api_formula_acupuncture_links(
        q: str = Query(default=""),
        formula_id: str = Query(default=""),
        channel_id: str = Query(default=""),
        chapter_id: str = Query(default=""),
    ):
        return formula_extras.list_formula_acupuncture_links(
            q=q, formula_id=formula_id, channel_id=channel_id, chapter_id=chapter_id
        )

    # ── Acupuncture (Stage 1) ────────────────────────────────────────────
    @app.get("/api/acupuncture/overview")
    def api_acu_overview():
        return acupuncture_catalog.overview()

    @app.get("/api/acupuncture/chapters")
    def api_acu_chapters():
        return acupuncture_catalog.list_chapters()

    @app.get("/api/acupuncture/chapters/{chapter_id:path}")
    def api_acu_chapter(chapter_id: str):
        item = acupuncture_catalog.get_chapter(chapter_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到针灸章节")
        return item

    @app.get("/api/acupuncture/indexes")
    def api_acu_indexes(q: str = Query(default=""), kind: str = Query(default="")):
        return acupuncture_catalog.list_book_indexes(q=q, kind=kind)

    @app.get("/api/acupuncture/meridians")
    def api_acu_meridians(
        q: str = Query(default=""), review_status: str = Query(default=""), risk_level: str = Query(default="")
    ):
        return acupuncture_catalog.list_meridians(q=q, review_status=review_status, risk_level=risk_level)

    @app.get("/api/acupuncture/meridians/{meridian_id:path}")
    def api_acu_meridian(meridian_id: str):
        item = acupuncture_catalog.get_meridian(meridian_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到经络条目")
        return item

    @app.get("/api/acupuncture/points")
    def api_acu_points(
        q: str = Query(default=""),
        meridian_id: str = Query(default=""),
        review_status: str = Query(default=""),
        risk_level: str = Query(default=""),
    ):
        return acupuncture_catalog.list_points(
            q=q, meridian_id=meridian_id, review_status=review_status, risk_level=risk_level
        )

    @app.get("/api/acupuncture/points/{point_id:path}")
    def api_acu_point(point_id: str):
        item = acupuncture_catalog.get_point(point_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到穴位条目")
        return item

    @app.get("/api/acupuncture/techniques")
    def api_acu_techniques(
        q: str = Query(default=""),
        category: str = Query(default=""),
        review_status: str = Query(default=""),
        risk_level: str = Query(default=""),
    ):
        return acupuncture_catalog.list_techniques(
            q=q, category=category, review_status=review_status, risk_level=risk_level
        )

    @app.get("/api/acupuncture/techniques/{technique_id:path}")
    def api_acu_technique(technique_id: str):
        item = acupuncture_catalog.get_technique(technique_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到针灸技法条目")
        return item

    @app.get("/api/acupuncture/conditions")
    def api_acu_conditions(
        q: str = Query(default=""), review_status: str = Query(default=""), risk_level: str = Query(default="")
    ):
        return acupuncture_catalog.list_conditions(q=q, review_status=review_status, risk_level=risk_level)

    @app.get("/api/acupuncture/conditions/{condition_id:path}")
    def api_acu_condition(condition_id: str):
        item = acupuncture_catalog.get_condition(condition_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到针灸治症条目")
        return item

    @app.get("/api/acupuncture/diagnose")
    def api_acu_diagnose(
        q: str = Query(default=""), risk_level: str = Query(default=""), meridian_id: str = Query(default="")
    ):
        return acupuncture_diagnose.diagnose_symptoms(q=q, risk_level=risk_level, meridian_id=meridian_id)

    @app.get("/api/acupuncture/source-pages/{pdf_page}/image")
    def api_acu_page_image(pdf_page: int):
        img = acupuncture_catalog.render_page_image(pdf_page)
        if not img:
            raise HTTPException(status_code=404, detail="未找到针灸原书页面图像")
        return FileResponse(img, media_type="image/png")

    @app.get("/api/acupuncture/source-pages/{pdf_page}")
    def api_acu_page(pdf_page: int):
        item = acupuncture_catalog.get_source_page(pdf_page)
        if not item:
            raise HTTPException(status_code=404, detail="未找到针灸原书页面")
        return item

    # ── Bencao (Stage 2) ─────────────────────────────────────────────────
    @app.get("/api/bencao/overview")
    def api_bencao_overview():
        return bencao_catalog.overview()

    @app.get("/api/bencao/chapters")
    def api_bencao_chapters():
        return bencao_catalog.list_chapters()

    @app.get("/api/bencao/chapters/{chapter_id:path}")
    def api_bencao_chapter(chapter_id: str):
        item = bencao_catalog.get_chapter(chapter_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到本草经章节")
        return item

    @app.get("/api/bencao/entries")
    def api_bencao_entries(
        q: str = "",
        grade: str = "",
        nature: str = "",
        flavor: str = "",
        toxicity: str = "",
        risk_level: str = "",
        review_status: str = "",
        has_formulas: bool = False,
        recovered_only: bool = False,
        meridian: str = "",
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=24, ge=1, le=80),
    ):
        return bencao_catalog.list_entries(
            q=q,
            grade=grade,
            nature=nature,
            flavor=flavor,
            toxicity=toxicity,
            risk_level=risk_level,
            review_status=review_status,
            has_formulas=has_formulas,
            recovered_only=recovered_only,
            meridian=meridian,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/bencao/comparisons")
    def api_bencao_comparisons(q: str = "", category: str = ""):
        return bencao_catalog.list_comparisons(q=q, category=category)

    @app.get("/api/bencao/comparisons/{comp_id:path}")
    def api_bencao_comparison(comp_id: str):
        item = bencao_catalog.get_comparison(comp_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到本草比较专题")
        return item

    @app.get("/api/bencao/diagnose")
    def api_bencao_diagnose(q: str = "", grade: str = "", risk_level: str = ""):
        return bencao_catalog.diagnose(q=q, grade=grade, risk_level=risk_level)

    @app.get("/api/bencao/pages")
    def api_bencao_pages(q: str = "", page_role: str = "", limit: int = Query(default=40, ge=1, le=160)):
        return bencao_catalog.search_pages(q=q, page_role=page_role, limit=limit)

    @app.get("/api/bencao/source-pages/{pdf_page}/image")
    def api_bencao_page_image(pdf_page: int):
        img = bencao_catalog.render_page_image(pdf_page)
        if not img:
            raise HTTPException(status_code=404, detail="未找到本草经原书页面图像")
        return FileResponse(img, media_type="image/png")

    @app.get("/api/bencao/source-pages/{pdf_page}")
    def api_bencao_page(pdf_page: int):
        item = bencao_catalog.get_source_page(pdf_page)
        if not item:
            raise HTTPException(status_code=404, detail="未找到本草经原书页面")
        return item

    @app.get("/api/bencao/entries/{entry_id:path}")
    def api_bencao_entry(entry_id: str):
        item = bencao_catalog.get_entry(entry_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到神农本草经条目")
        return item

    # ── Neijing (Stage 3) ────────────────────────────────────────────────
    @app.get("/api/neijing/overview")
    def api_neijing_overview():
        return neijing_catalog.overview()

    @app.get("/api/neijing/chapters")
    def api_neijing_chapters(
        q: str = Query(default=""),
        volume: str = Query(default=""),
        review_status: str = Query(default=""),
        risk_level: str = Query(default=""),
    ):
        return neijing_catalog.list_chapters(
            q=q, volume=volume, review_status=review_status, risk_level=risk_level
        )

    @app.get("/api/neijing/chapters/{chapter_id:path}")
    def api_neijing_chapter(chapter_id: str):
        item = neijing_catalog.get_chapter(chapter_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到内经篇目")
        return item

    @app.get("/api/neijing/concepts")
    def api_neijing_concepts(
        q: str = Query(default=""),
        submodule: str = Query(default=""),
        review_status: str = Query(default=""),
        risk_level: str = Query(default=""),
    ):
        return neijing_catalog.list_concepts(
            q=q, submodule=submodule, review_status=review_status, risk_level=risk_level
        )

    @app.get("/api/neijing/concepts/{concept_id:path}")
    def api_neijing_concept(concept_id: str):
        item = neijing_catalog.get_concept(concept_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到内经专题")
        return item

    @app.get("/api/neijing/diagnose")
    def api_neijing_diagnose(
        q: str = Query(default=""), submodule: str = Query(default=""), risk_level: str = Query(default="")
    ):
        return neijing_catalog.diagnose(q=q, submodule=submodule, risk_level=risk_level)

    @app.get("/api/neijing/pages")
    def api_neijing_pages(
        q: str = Query(default=""),
        volume: str = Query(default=""),
        page_role: str = Query(default=""),
        limit: int = Query(default=60, ge=1, le=120),
    ):
        return neijing_catalog.search_pages(q=q, volume=volume, page_role=page_role, limit=limit)

    @app.get("/api/neijing/source-pages/{source_id}/{pdf_page}/image")
    def api_neijing_page_image(source_id: str, pdf_page: int):
        img = neijing_catalog.render_page_image(source_id, pdf_page)
        if not img:
            raise HTTPException(status_code=404, detail="未找到内经原书页面图像")
        return FileResponse(img, media_type="image/png")

    @app.get("/api/neijing/source-pages/{source_id}/{pdf_page}")
    def api_neijing_page(source_id: str, pdf_page: int):
        item = neijing_catalog.get_source_page(source_id, pdf_page)
        if not item:
            raise HTTPException(status_code=404, detail="未找到内经原书页面")
        return item

    @app.get("/api/neijing/page-by-id/{page_id:path}")
    def api_neijing_page_by_id(page_id: str):
        item = neijing_catalog.get_source_page_by_id(page_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到内经原书页面")
        return item

    # ── Stage 5 & 17-Book Library ────────────────────────────────────────
    @app.get("/api/library/overview")
    def api_library_overview():
        return library_catalog.overview()

    @app.get("/api/library/books")
    def api_library_books(shelf: str = Query(default=""), q: str = Query(default="")):
        return library_catalog.list_books(shelf=shelf, q=q)

    @app.get("/api/library/locate")
    def api_library_locate(
        book_id: str = Query(default=""),
        page_no: int = Query(default=0, ge=0),
        line: int = Query(default=0, ge=0),
        q: str = Query(default=""),
        book_hint: str = Query(default=""),
        before: int = Query(default=2, ge=0, le=6),
        after: int = Query(default=4, ge=0, le=8),
    ):
        item = library_catalog.locate_book_context(
            book_id=book_id, page_no=page_no, line=line, q=q, book_hint=book_hint, before=before, after=after
        )
        if not item:
            raise HTTPException(status_code=404, detail="未能在书库中定位对应原书页码")
        return item

    @app.get("/api/library/books/{book_id}/pages/{page_no}/image")
    def api_library_page_image(book_id: str, page_no: int):
        img = library_catalog.render_book_page_image(book_id, page_no)
        if not img:
            raise HTTPException(status_code=404, detail="未找到该书原页图像")
        return FileResponse(img, media_type="image/png")

    @app.get("/api/library/books/{book_id}/pages/{page_no}")
    def api_library_book_page(book_id: str, page_no: int):
        item = library_catalog.get_book_page(book_id, page_no)
        if not item:
            raise HTTPException(status_code=404, detail="未找到指定书页或章节")
        return item

    @app.get("/api/library/books/{book_id}/context")
    def api_library_book_context(
        book_id: str,
        page_no: int = Query(default=1, ge=1),
        before: int = Query(default=2, ge=0, le=6),
        after: int = Query(default=4, ge=0, le=8),
    ):
        item = library_catalog.get_book_context(book_id, page_no=page_no, before=before, after=after)
        if not item:
            raise HTTPException(status_code=404, detail="未找到指定书籍或上下文页面")
        return item

    @app.get("/api/library/books/{book_id}/pages")
    def api_library_book_pages(
        book_id: str,
        q: str = Query(default=""),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=60, ge=1, le=200),
    ):
        item = library_catalog.list_book_pages(book_id, q=q, offset=offset, limit=limit)
        if not item:
            raise HTTPException(status_code=404, detail="未找到指定书籍")
        return item

    @app.get("/api/library/books/{book_id:path}")
    def api_library_book(book_id: str):
        item = library_catalog.get_book(book_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到指定书籍")
        return item

    @app.get("/api/library/search")
    def api_library_search(
        q: str = Query(default=""),
        shelf: str = Query(default=""),
        book_id: str = Query(default=""),
        limit: int = Query(default=36, ge=1, le=100),
    ):
        return library_catalog.search(q=q, shelf=shelf, book_id=book_id, limit=limit)

    @app.get("/api/library/entity-links/{entity_id:path}")
    def api_library_entity_links(entity_id: str):
        return library_catalog.get_entity_links(entity_id)

    @app.get("/api/stage5/overview")
    def api_stage5_overview():
        return stage5_service.overview()

    @app.get("/api/stage5/syndromes")
    def api_stage5_syndromes(q: str = Query(default="")):
        return stage5_service.list_syndromes(q=q)

    @app.get("/api/stage5/syndromes/{syndrome_id:path}")
    def api_stage5_syndrome(syndrome_id: str):
        item = stage5_service.get_syndrome(syndrome_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到跨书辨证证候群")
        return item

    @app.get("/api/stage5/diagnose")
    def api_stage5_diagnose(q: str = Query(default="")):
        return stage5_service.diagnose_unified(q=q)

    @app.get("/api/stage5/compose")
    def api_stage5_compose(q: str = Query(default=""), pulse: str = Query(default="")):
        return syndrome_composer.compose_differentiation(q=q, pulse=pulse)

    @app.get("/api/stage5/ground")
    def api_stage5_ground(q: str = Query(default=""), limit: int = Query(default=12, ge=1, le=24)):
        return grounded_study.ground_study_query(q=q, limit_citations=limit)

    # ── Hantang System ───────────────────────────────────────────────────
    @app.get("/api/hantang/overview")
    def api_hantang_overview():
        return hantang_catalog.overview()

    @app.get("/api/hantang/formulas")
    def api_hantang_formulas(
        category: str = Query(default=""), safety: str = Query(default=""), q: str = Query(default="")
    ):
        return hantang_catalog.list_formulas(category=category, safety=safety, q=q)

    @app.get("/api/hantang/formulas/{formula_id:path}")
    def api_hantang_formula(formula_id: str):
        item = hantang_catalog.get_formula(formula_id)
        if not item:
            raise HTTPException(status_code=404, detail="未找到汉唐方剂")
        return item

    @app.get("/api/hantang/match")
    def api_hantang_match(q: str = Query(default=""), limit: int = Query(default=4, ge=1, le=8)):
        return hantang_catalog.match_clinical_context(q=q, limit=limit)

    # ── Ni Shi Streaming AI Routes (Pure Python, No Node ai-bridge) ─────
    @app.get("/api/ai/config")
    def api_ai_config():
        return {
            **config_store.get_public_config(data),
            "styles": ni_persona.list_persona_styles(),
        }

    @app.post("/api/ai/config")
    def api_ai_save_config(request: Request, payload: AIConfigPayload):
        _assert_ai_origin(request)
        saved = config_store.save_config(data, payload.model_dump(exclude_none=True))
        return {
            **saved,
            "styles": ni_persona.list_persona_styles(),
        }

    @app.post("/api/ai/models")
    async def api_ai_models(request: Request, payload: AIConfigPayload | None = None):
        _assert_ai_origin(request)
        override = payload.model_dump(exclude_none=True) if payload else None
        cfg = config_store.resolve_runtime_config(data, override)
        try:
            return await llm_client.list_models(cfg)
        except llm_client.LLMClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/ai/test")
    async def api_ai_test(request: Request, payload: AIConfigPayload | None = None):
        _assert_ai_origin(request)
        override = payload.model_dump(exclude_none=True) if payload else None
        cfg = config_store.resolve_runtime_config(data, override)
        try:
            return await llm_client.test_connection(cfg)
        except llm_client.LLMClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/ai/packet")
    def api_ai_packet(request: Request, payload: AIPacketRequest):
        _assert_ai_origin(request)
        with closing(connect(data)) as conn:
            return ni_consult.build_clinical_context(
                payload.query,
                pulse=payload.pulse,
                tongue=payload.tongue,
                entity_focus=payload.entity_focus,
                sqlite_conn=conn,
            )

    @app.post("/api/ai/chat")
    async def api_ai_chat(request: Request, payload: AIChatRequest):
        _assert_ai_origin(request)
        override = payload.config_override.model_dump(exclude_none=True) if payload.config_override else None
        cfg = config_store.resolve_runtime_config(data, override)
        style = payload.style or cfg.get("persona_style", "master_balanced")
        with closing(connect(data)) as conn:
            packet, sys_prompt, messages = ni_consult.prepare_llm_request(
                payload.query,
                pulse=payload.pulse,
                tongue=payload.tongue,
                style=style,
                history=[m.model_dump() for m in payload.history],
                entity_focus=payload.entity_focus,
                sqlite_conn=conn,
            )

        if payload.offline or not cfg["ready"]:
            reply = ni_consult.build_offline_ni_reply(packet, style=style)
            return {
                "mode": "offline",
                "provider": cfg["provider"],
                "model": cfg["model"],
                "style": style,
                "packet": packet,
                "reply": reply,
                "reasoning": "",
                "cited": ni_consult.extract_cited_refs(reply, packet["citations"]),
                "usage": {},
            }

        try:
            res = await llm_client.complete_chat(cfg, sys_prompt, messages)
        except llm_client.LLMClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

        return {
            "mode": "live",
            "provider": cfg["provider"],
            "model": cfg["model"],
            "style": style,
            "packet": packet,
            "reply": res["text"],
            "reasoning": res["reasoning"],
            "cited": ni_consult.extract_cited_refs(res["text"], packet["citations"]),
            "usage": res["usage"],
        }

    @app.post("/api/ai/chat/stream")
    async def api_ai_chat_stream(request: Request, payload: AIChatRequest):
        _assert_ai_origin(request)
        override = payload.config_override.model_dump(exclude_none=True) if payload.config_override else None
        cfg = config_store.resolve_runtime_config(data, override)
        style = payload.style or cfg.get("persona_style", "master_balanced")
        with closing(connect(data)) as conn:
            packet, sys_prompt, messages = ni_consult.prepare_llm_request(
                payload.query,
                pulse=payload.pulse,
                tongue=payload.tongue,
                style=style,
                history=[m.model_dump() for m in payload.history],
                entity_focus=payload.entity_focus,
                sqlite_conn=conn,
            )

        use_offline = bool(payload.offline or not cfg["ready"])
        mode = "offline" if use_offline else "live"

        async def event_stream():
            yield _sse_frame("context", {"mode": mode, "provider": cfg["provider"], "model": cfg["model"], "style": style, "packet": packet})

            if use_offline:
                reply = ni_consult.build_offline_ni_reply(packet, style=style)
                for idx in range(0, len(reply), 80):
                    yield _sse_frame("delta", {"text": reply[idx : idx + 80]})
                yield _sse_frame(
                    "done",
                    {
                        "mode": "offline",
                        "provider": cfg["provider"],
                        "model": cfg["model"],
                        "style": style,
                        "text": reply,
                        "reasoning": "",
                        "usage": {},
                        "cited": ni_consult.extract_cited_refs(reply, packet["citations"]),
                    },
                )
                return

            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            usage: dict[str, Any] = {}
            try:
                async for ev in llm_client.stream_chat(cfg, sys_prompt, messages):
                    if ev["type"] == "reasoning":
                        reasoning_parts.append(ev["text"])
                        yield _sse_frame("reasoning", {"text": ev["text"]})
                    elif ev["type"] == "delta":
                        text_parts.append(ev["text"])
                        yield _sse_frame("delta", {"text": ev["text"]})
                    elif ev["type"] == "usage":
                        usage = ev["usage"]
            except llm_client.LLMClientError as exc:
                fallback = ni_consult.build_offline_ni_reply(packet, style=style)
                yield _sse_frame("error", {"detail": str(exc), "fallback_text": fallback})
                yield _sse_frame(
                    "done",
                    {
                        "mode": "offline_fallback",
                        "error": str(exc),
                        "text": fallback,
                        "reasoning": "".join(reasoning_parts),
                        "usage": usage,
                        "cited": ni_consult.extract_cited_refs(fallback, packet["citations"]),
                    },
                )
                return

            full_text = "".join(text_parts)
            yield _sse_frame(
                "done",
                {
                    "mode": "live",
                    "provider": cfg["provider"],
                    "model": cfg["model"],
                    "style": style,
                    "text": full_text,
                    "reasoning": "".join(reasoning_parts),
                    "usage": usage,
                    "cited": ni_consult.extract_cited_refs(full_text, packet["citations"]),
                },
            )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # ── Per-Patient Profiles & Consultation History ───────────────────────
    @app.get("/api/ai/patients")
    def api_ai_list_patients():
        return {"patients": consult_history.list_patients(data)}

    @app.post("/api/ai/patients")
    def api_ai_create_patient(request: Request, payload: PatientPayload):
        _assert_ai_origin(request)
        try:
            patient, session = consult_history.create_patient(
                data,
                name=payload.name,
                gender=payload.gender,
                age=payload.age,
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "patient": patient,
            "initial_session": session,
            "patients": consult_history.list_patients(data),
        }

    @app.post("/api/ai/patients/{patient_id}/update")
    def api_ai_update_patient(request: Request, patient_id: str, payload: PatientUpdatePayload):
        _assert_ai_origin(request)
        try:
            updated = consult_history.update_patient(
                data,
                patient_id,
                name=payload.name,
                gender=payload.gender,
                age=payload.age,
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not updated:
            raise HTTPException(status_code=404, detail="未找到该问诊人")
        return {"patient": updated, "patients": consult_history.list_patients(data)}

    @app.post("/api/ai/patients/{patient_id}/delete")
    def api_ai_delete_patient(request: Request, patient_id: str):
        _assert_ai_origin(request)
        if not consult_history.delete_patient(data, patient_id):
            raise HTTPException(status_code=404, detail="未找到该问诊人")
        return {"deleted": patient_id, "patients": consult_history.list_patients(data)}

    @app.get("/api/ai/patients/{patient_id}/sessions")
    def api_ai_list_sessions(patient_id: str):
        patient = consult_history.get_patient(data, patient_id)
        if not patient:
            raise HTTPException(status_code=404, detail="未找到该问诊人")
        return {"patient": patient, "sessions": consult_history.list_sessions(data, patient_id)}

    @app.post("/api/ai/patients/{patient_id}/sessions")
    def api_ai_create_session(request: Request, patient_id: str, payload: SessionCreatePayload | None = None):
        _assert_ai_origin(request)
        body = payload or SessionCreatePayload()
        session = consult_history.create_session(
            data,
            patient_id,
            title=body.title,
            intake=body.intake,
            pinned_entity=body.pinned_entity,
        )
        if not session:
            raise HTTPException(status_code=404, detail="未找到该问诊人")
        return {"session": session, "sessions": consult_history.list_sessions(data, patient_id)}

    @app.get("/api/ai/sessions/{session_id}")
    def api_ai_get_session(session_id: str):
        session = consult_history.get_session(data, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="未找到该问诊历史记录")
        return {"session": session}

    @app.post("/api/ai/sessions/{session_id}/save")
    def api_ai_save_session(request: Request, session_id: str, payload: SessionSavePayload):
        _assert_ai_origin(request)
        fields_set = getattr(payload, "model_fields_set", set())
        saved = consult_history.save_session(
            data,
            session_id,
            title=payload.title,
            intake=payload.intake,
            pinned_entity=payload.pinned_entity,
            turns=payload.turns,
            latest_packet=payload.latest_packet,
            update_pinned=bool(payload.update_pinned or ("pinned_entity" in fields_set)),
            update_packet=bool(payload.update_packet or ("latest_packet" in fields_set)),
        )
        if not saved:
            raise HTTPException(status_code=404, detail="未找到该问诊历史记录")
        return {"session": saved, "sessions": consult_history.list_sessions(data, saved["patient_id"])}

    @app.post("/api/ai/sessions/{session_id}/delete")
    def api_ai_delete_session(request: Request, session_id: str):
        _assert_ai_origin(request)
        ok, pat_id = consult_history.delete_session(data, session_id)
        if not ok or not pat_id:
            raise HTTPException(status_code=404, detail="未找到该问诊历史记录")
        return {"deleted": session_id, "patient_id": pat_id, "sessions": consult_history.list_sessions(data, pat_id)}

    # ── Local SQLite Documents, Sources & Write-Token Ingest ─────────────
    @app.get("/api/documents")
    def api_documents():
        with closing(connect(data)) as conn:
            return knowledge.list_documents(conn)

    @app.get("/api/documents/{document_id}/pdf")
    def api_document_pdf(document_id: str):
        with closing(connect(data)) as conn:
            path = knowledge.document_path(conn, data, document_id)
        return FileResponse(path, media_type="application/pdf")

    @app.get("/api/documents/{document_id}/pages/{physical_page}")
    def api_document_page(document_id: str, physical_page: int):
        with closing(connect(data)) as conn:
            page = knowledge.get_page(conn, document_id, physical_page)
        if page is None:
            raise HTTPException(status_code=404, detail="页面不存在")
        return page

    @app.get("/api/documents/{document_id}/pages/{physical_page}/image")
    def api_document_page_image(document_id: str, physical_page: int):
        with closing(connect(data)) as conn:
            image = knowledge.render_page(conn, data, document_id, physical_page)
        return Response(image, media_type="image/png")

    @app.get("/api/sources")
    def api_sources():
        with closing(connect(data)) as conn:
            return library.list_sources(conn)

    @app.get("/api/sources/{source_id}/units/{unit_no}")
    def api_source_unit(source_id: str, unit_no: int):
        with closing(connect(data)) as conn:
            unit = library.get_unit(conn, data, source_id, unit_no)
        if unit is None:
            raise HTTPException(status_code=404, detail="原文单元不存在")
        return unit

    @app.get("/api/search")
    def api_local_search(q: str = Query(..., min_length=1), limit: int = Query(default=20, ge=1, le=50)):
        with closing(connect(data)) as conn:
            hits = library.search(conn, q, limit=limit)
            if hits:
                return hits
            return knowledge.search(conn, q, limit=limit)

    ingest.mount(app, data, connect)
    _mount_static_web(app)
    return app


app = create_app()
