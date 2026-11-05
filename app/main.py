import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import knowledge, library, personal, research, storage
from .engine import analyze, apply_modifications, check_formula, validate_rule

ROOT = Path(__file__).resolve().parents[1]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Fact(Input):
    key: str = Field(min_length=1, max_length=100)
    state: Literal["present", "absent", "unknown", "conflict"]
    verified: StrictBool
    raw: str = Field(default="", max_length=4000)
    source: Literal["patient", "clinician", "test"] = "clinician"
    observed_at: str | None = Field(default=None, max_length=50)
    scope: Literal["current", "history"] = "current"
    subject: Literal["patient", "family", "other", "unknown"] = "patient"
    value: str | int | float | None = None
    unit: str = Field(default="", max_length=50)


class Context(Input):
    age_years: float | None = Field(default=None, ge=0, le=150)
    pregnancy: Literal["yes", "no", "unknown"] = "unknown"
    allergies: list[str] = Field(default_factory=list, max_length=100)
    medications: list[str] = Field(default_factory=list, max_length=100)
    simulation: Literal[True] = True


class Patient(Input):
    code: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=4000)


class VisitFields(Input):
    chief_complaint: str = Field(default="", max_length=10000)
    facts: list[Fact] = Field(default_factory=list, max_length=500)
    context: Context = Field(default_factory=Context)
    clinician: str = Field(min_length=1, max_length=80)


class NewVisit(VisitFields):
    patient_id: str
    previous_visit_id: str | None = None


class EditVisit(VisitFields):
    expected_revision: int = Field(ge=1)


class AnalyzeInput(Input):
    expected_revision: int = Field(ge=1)
    selected_rule_ids: list[str] = Field(default_factory=list, max_length=500)
    base_rule_id: str | None = None
    modification_ids: list[str] = Field(default_factory=list, max_length=50)


class Reviewer(Input):
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=4000)


class RuleReview(Reviewer):
    stage: Literal["text", "semantic", "clinical"]


class RuleInput(Input):
    rule: dict[str, Any]


class PageReview(Reviewer):
    corrected_text: str = Field(max_length=200000)
    kind: str = Field(min_length=1, max_length=80)
    printed_page: str | int | None = None


class EvidenceInput(Input):
    document_id: str
    physical_page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=30000)
    kind: str = Field(min_length=1, max_length=80)
    reviewer: str = Field(min_length=1, max_length=80)
    printed_page: str | int | None = None


class DecisionInput(Input):
    decision: Literal["adopt", "modify", "reject"]
    clinician: str = Field(min_length=1, max_length=80)
    notes: str = Field(min_length=1, max_length=10000)
    final_formula: list[dict[str, Any]] | None = Field(default=None, max_length=200)


def stored_facts(facts):
    result = []
    for fact in facts:
        item = fact.model_dump(exclude_none=True)
        for key in ("unit", "observed_at"):
            if item.get(key) == "":
                item.pop(key)
        result.append(item)
    return result


def create_app(data_dir: Path | None = None):
    data_dir = Path(data_dir or os.environ.get("TCM_DATA_DIR", ROOT / "data")).resolve()
    storage.initialize(data_dir)
    with storage.connect(data_dir) as conn:
        library.initialize(conn, data_dir)
        research.initialize_research(conn)
        personal.initialize(conn)
    conn.close()
    app = FastAPI(title="倪海厦辨证研究工作台", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.data_dir = data_dir
    sessions: dict[str, str] = {}
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.url.path.startswith("/api"):
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": "不允许跨来源访问本地工作台"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "不允许跨站请求"}, status_code=403)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                limit = 51 * 1024 * 1024 if request.url.path == "/api/documents" else 2 * 1024 * 1024
                try:
                    if int(request.headers.get("content-length", "0")) > limit:
                        return JSONResponse({"detail": "请求超过大小限制"}, status_code=413)
                except ValueError:
                    return JSONResponse({"detail": "无效的请求长度"}, status_code=400)
                if request.headers.get("content-type", "").startswith("application/json"):
                    if len(await request.body()) > limit:
                        return JSONResponse({"detail": "请求超过大小限制"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self' blob:; object-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def authenticated(request: Request):
        token = request.cookies.get("tcm_session", "")
        if token not in sessions:
            raise HTTPException(401, "请从本机工作台建立会话")
        if request.method not in {"GET", "HEAD"}:
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), sessions[token]):
                raise HTTPException(403, "写入请求缺少有效的CSRF令牌")
        return token

    def database():
        conn = storage.connect(data_dir)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflicting_input(request, exc):
        return JSONResponse({"detail": "记录重复或引用关系无效，请核对后重试"}, status_code=409)

    @app.get("/api/status")
    def status():
        return {"status": "ok", "app_id": "nihaixia-clinical-engine", "version": "0.3.0", "mode": "personal"}

    @app.get("/api/session")
    def session(request: Request):
        token = request.cookies.get("tcm_session")
        if token not in sessions:
            if len(sessions) >= 100:
                sessions.pop(next(iter(sessions)))
            token = secrets.token_urlsafe(32)
            sessions[token] = secrets.token_urlsafe(32)
        response = JSONResponse({"csrf_token": sessions[token], "mode": "personal", "version": "0.3.0"})
        response.set_cookie("tcm_session", token, httponly=True, samesite="strict", path="/")
        return response

    protected = [Depends(authenticated)]

    @app.get("/api/overview", dependencies=protected)
    def overview(conn=Depends(database)):
        documents = knowledge.list_documents(conn)
        rules = load_rules(conn)
        return {"documents": len(documents), "pages": sum(d["physical_pages"] for d in documents),
                "patients": conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
                "visits": conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0],
                "published_rules": sum(r["status"] == "published" for r in rules),
                "clinical_published_rules": sum(r["status"] == "published" and not r["synthetic"] for r in rules),
                "research_entries": conn.execute("SELECT COUNT(*) FROM research_entries").fetchone()[0]}

    @app.get("/api/documents", dependencies=protected)
    def documents(conn=Depends(database)):
        return {"items": knowledge.list_documents(conn)}

    @app.get("/api/research", dependencies=protected)
    def research_entries(conn=Depends(database)):
        return {"items": research.list_research(conn)}

    @app.post("/api/documents", dependencies=protected)
    def upload_document(file: UploadFile = File(...), conn=Depends(database)):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix != ".pdf":
            raise HTTPException(400, "仅支持PDF文件")
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=data_dir, suffix=".pdf", delete=False) as handle:
                temp_path = Path(handle.name)
                size = 0
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 50 * 1024 * 1024:
                        raise HTTPException(413, "PDF超过50MiB限制")
                    handle.write(chunk)
            if not temp_path.read_bytes()[:8].startswith(b"%PDF-"):
                raise HTTPException(400, "文件不是有效PDF")
            result = knowledge.import_pdf(conn, data_dir, temp_path, Path(file.filename).name)
            storage.audit(conn, "document_import", result["id"])
            return result
        finally:
            file.file.close()
            if temp_path:
                temp_path.unlink(missing_ok=True)

    @app.get("/api/search", dependencies=protected)
    def search(q: str = "", document_id: str | None = None, limit: int = 30, conn=Depends(database)):
        return {"items": knowledge.search(conn, q, document_id, limit)}

    @app.get("/api/documents/{document_id}/pdf", dependencies=protected)
    def pdf(document_id: str, conn=Depends(database)):
        path = knowledge.document_path(conn, data_dir, document_id)
        return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")

    @app.get("/api/documents/{document_id}/pages/{physical_page}", dependencies=protected)
    def page(document_id: str, physical_page: int, conn=Depends(database)):
        result = knowledge.get_page(conn, document_id, physical_page)
        if result is None:
            raise HTTPException(404, "文档或物理页不存在")
        return result

    @app.post("/api/documents/{document_id}/pages/{physical_page}/review", dependencies=protected)
    def page_review(document_id: str, physical_page: int, payload: PageReview, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        result = knowledge.review_page(conn, document_id, physical_page, payload.model_dump())
        storage.audit(conn, "page_review", document_id, page=physical_page, reviewer=payload.reviewer)
        return result

    @app.get("/api/documents/{document_id}/pages/{physical_page}/image", dependencies=protected)
    def original_page_image(document_id: str, physical_page: int, conn=Depends(database)):
        if knowledge.get_page(conn, document_id, physical_page) is None:
            raise HTTPException(404, "文档或物理页不存在")
        return Response(knowledge.render_page(conn, data_dir, document_id, physical_page), media_type="image/png")

    @app.get("/api/evidence", dependencies=protected)
    def evidence_list(conn=Depends(database)):
        return {"items": knowledge.list_evidence(conn)}

    @app.post("/api/evidence", dependencies=protected)
    def evidence_create(payload: EvidenceInput, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        result = knowledge.create_evidence(conn, payload.model_dump())
        storage.audit(conn, "evidence_create", result["id"], reviewer=payload.reviewer)
        return result

    def load_rules(conn):
        result = []
        for row in conn.execute("SELECT * FROM rules ORDER BY created_at,id"):
            rule = json.loads(row["document"])
            result.append({**rule, "reviews": json.loads(row["reviews"]), "created_at": row["created_at"]})
        return result

    def get_rule(conn, rule_id):
        row = conn.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "规则不存在")
        return row, json.loads(row["document"])

    def checked_evidence(conn, rule):
        if rule.get("synthetic"):
            return []
        if not rule.get("evidence_ids"):
            raise HTTPException(409, "真实规则缺少已校核证据")
        evidence_ids = set(rule["evidence_ids"])
        drugs = list(rule.get("formula", [])) + [action["drug"] for action in rule.get("actions", []) if "drug" in action]
        for drug in drugs:
            if not drug.get("evidence_ids"):
                raise HTTPException(409, "真实方药及加减剂量需要逐项来源依据")
            evidence_ids.update(drug["evidence_ids"])
        evidence = []
        for evidence_id in sorted(evidence_ids):
            item = knowledge.get_evidence(conn, evidence_id)
            if item is None:
                raise HTTPException(409, "规则证据不存在")
            page = knowledge.get_page(conn, item["document_id"], item["physical_page"])
            if page is None or page["review_status"] != "verified":
                raise HTTPException(409, "规则引用页尚未完成校核")
            text = page["corrected_text"] if page["corrected_text"] is not None else page["raw_text"]
            frozen_text = item["corrected_text"] if item["source_type"] == "corrected" else item["raw_text"]
            if item["quote"] not in text or frozen_text != text:
                raise HTTPException(409, "原文订正后证据已失效，须重新核对规则")
            evidence.append(item)
        return evidence

    @app.get("/api/rules", dependencies=protected)
    def rules(conn=Depends(database)):
        return {"items": load_rules(conn)}

    @app.post("/api/rules", dependencies=protected)
    def rule_create(payload: RuleInput, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        rule = dict(payload.rule)
        rule["status"] = "draft"
        rule = validate_rule(rule)
        if conn.execute("SELECT 1 FROM rules WHERE id=?", (rule["id"],)).fetchone():
            raise HTTPException(409, "规则id已存在；请为新版本使用新id，禁止覆盖已发布记录")
        conn.execute("INSERT INTO rules VALUES(?,?,?,?)", (rule["id"], storage.encode(rule), "{}", storage.now()))
        storage.audit(conn, "rule_draft", rule["id"])
        return {**rule, "reviews": {}}

    @app.post("/api/rules/{rule_id}/review", dependencies=protected)
    def rule_review(rule_id: str, payload: RuleReview, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        row, rule = get_rule(conn, rule_id)
        if rule["status"] != "draft":
            raise HTTPException(409, "只能审核草稿版本")
        if payload.stage == "text":
            checked_evidence(conn, rule)
        reviews = json.loads(row["reviews"])
        reviews[payload.stage] = {**payload.model_dump(), "at": storage.now(), "identity_verified": False}
        conn.execute("UPDATE rules SET reviews=? WHERE id=?", (storage.encode(reviews), rule_id))
        storage.audit(conn, "rule_review", rule_id, stage=payload.stage, reviewer=payload.reviewer)
        return {**rule, "reviews": reviews}

    @app.post("/api/rules/{rule_id}/publish", dependencies=protected)
    def rule_publish(rule_id: str, payload: Reviewer, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        row, rule = get_rule(conn, rule_id)
        reviews = json.loads(row["reviews"])
        if rule["status"] != "draft" or not all(s in reviews for s in ["text", "semantic", "clinical"]):
            raise HTTPException(409, "发布需要文本、规则语义、临床适用三级审核")
        if "__clinical_rule_not_defined__" in storage.encode(rule["required"]):
            raise HTTPException(409, "必要条件尚未由临床医师定义，不能发布研究占位规则")
        if rule["kind"] == "modification" and not rule.get("actions"):
            raise HTTPException(409, "加减规则尚无可执行且有据的动作")
        checked_evidence(conn, rule)
        rule.update(status="published", published_at=storage.now(), published_by=payload.reviewer)
        conn.execute("UPDATE rules SET document=? WHERE id=?", (storage.encode(rule), rule_id))
        storage.audit(conn, "rule_publish_simulation", rule_id, reviewer=payload.reviewer)
        return {**rule, "reviews": reviews}

    @app.post("/api/rules/{rule_id}/withdraw", dependencies=protected)
    def rule_withdraw(rule_id: str, payload: Reviewer, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        row, rule = get_rule(conn, rule_id)
        rule.update(status="withdrawn", withdrawn_at=storage.now(), withdrawal_note=payload.note)
        conn.execute("UPDATE rules SET document=? WHERE id=?", (storage.encode(rule), rule_id))
        storage.audit(conn, "rule_withdraw", rule_id, reviewer=payload.reviewer)
        return {**rule, "reviews": json.loads(row["reviews"])}

    @app.get("/api/patients", dependencies=protected)
    def patients(conn=Depends(database)):
        return {"items": [dict(r) for r in conn.execute("SELECT * FROM patients ORDER BY created_at DESC")]}

    @app.post("/api/patients", dependencies=protected)
    def patient_create(payload: Patient, conn=Depends(database)):
        result = {"id": str(uuid4()), **payload.model_dump(), "created_at": storage.now()}
        conn.execute("INSERT INTO patients VALUES(:id,:code,:notes,:created_at)", result)
        storage.audit(conn, "patient_create", result["id"])
        return result

    def visit_record(conn, visit_id):
        row = conn.execute("SELECT * FROM visits WHERE id=?", (visit_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "访次不存在")
        result = dict(row)
        result["facts"] = json.loads(result["facts"])
        result["context"] = json.loads(result["context"])
        return result

    def visit_details(conn, visit_id):
        visit = visit_record(conn, visit_id)
        analyses = [json.loads(r["document"]) for r in conn.execute("SELECT document FROM analyses WHERE visit_id=? ORDER BY created_at DESC", (visit_id,))]
        for analysis in analyses:
            analysis["dependency_warnings"] = storage.analysis_dependency_errors(conn, analysis)
            analysis["stale"] = bool(analysis["dependency_warnings"])
            analysis["withdrawn_rules"] = [r["id"] for r in analysis["rule_snapshot"] if conn.execute("SELECT document FROM rules WHERE id=?", (r["id"],)).fetchone() and json.loads(conn.execute("SELECT document FROM rules WHERE id=?", (r["id"],)).fetchone()[0])["status"] == "withdrawn"]
        decisions = [json.loads(r["document"]) for r in conn.execute("SELECT d.document FROM decisions d JOIN analyses a ON d.analysis_id=a.id WHERE a.visit_id=? ORDER BY d.created_at DESC", (visit_id,))]
        supplements = []
        for row in conn.execute("SELECT m.* FROM model_calls m JOIN analyses a ON m.analysis_id=a.id WHERE a.visit_id=? ORDER BY m.created_at DESC", (visit_id,)):
            supplement = json.loads(row["document"])
            supplement["analysis_id"] = row["analysis_id"]
            dependency = next((a for a in analyses if a["id"] == row["analysis_id"]), None)
            supplement["stale"] = dependency is None or dependency["stale"]
            if supplement["stale"]:
                supplement["validated"] = False
            supplements.append(supplement)
        return {**visit, "analyses": analyses, "decisions": decisions, "model_supplements": supplements}

    @app.get("/api/visits", dependencies=protected)
    def visits(patient_id: str | None = None, conn=Depends(database)):
        rows = conn.execute("SELECT id FROM visits WHERE (? IS NULL OR patient_id=?) ORDER BY created_at DESC", (patient_id, patient_id))
        return {"items": [visit_record(conn, r["id"]) for r in rows]}

    @app.post("/api/visits", dependencies=protected)
    def visit_create(payload: NewVisit, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM patients WHERE id=?", (payload.patient_id,)).fetchone() is None:
            raise HTTPException(404, "病例不存在")
        if payload.previous_visit_id and visit_record(conn, payload.previous_visit_id)["patient_id"] != payload.patient_id:
            raise HTTPException(400, "前次访次不属于该病例")
        result = {"id": str(uuid4()), **payload.model_dump(), "revision": 1, "created_at": storage.now(), "updated_at": storage.now()}
        result["context"] = payload.context.model_dump(exclude_none=True)
        result["facts"] = stored_facts(payload.facts)
        analyze(result["facts"], [], result["context"])
        conn.execute("INSERT INTO visits VALUES(?,?,?,?,?,?,?,?,?,?)", (result["id"], result["patient_id"], result["previous_visit_id"], 1, result["chief_complaint"], storage.encode(result["facts"]), storage.encode(result["context"]), result["clinician"], result["created_at"], result["updated_at"],))
        conn.execute("INSERT INTO visit_revisions VALUES(?,?,?,?)", (result["id"], 1, storage.encode(result), storage.now()))
        storage.audit(conn, "visit_create", result["id"])
        return result

    @app.get("/api/visits/{visit_id}", dependencies=protected)
    def visit_get(visit_id: str, conn=Depends(database)):
        return visit_details(conn, visit_id)

    @app.put("/api/visits/{visit_id}", dependencies=protected)
    def visit_edit(visit_id: str, payload: EditVisit, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        old = visit_record(conn, visit_id)
        if payload.expected_revision != old["revision"]:
            raise HTTPException(409, "访次已被修改，请重新载入")
        fields = payload.model_dump(exclude={"expected_revision"})
        fields["context"] = payload.context.model_dump(exclude_none=True)
        fields["facts"] = stored_facts(payload.facts)
        analyze(fields["facts"], [], fields["context"])
        result = {**old, **fields, "revision": old["revision"] + 1, "updated_at": storage.now()}
        changed = conn.execute("UPDATE visits SET revision=?,chief_complaint=?,facts=?,context=?,clinician=?,updated_at=? WHERE id=? AND revision=?", (result["revision"], result["chief_complaint"], storage.encode(result["facts"]), storage.encode(result["context"]), result["clinician"], result["updated_at"], visit_id, old["revision"])).rowcount
        if changed != 1:
            raise HTTPException(409, "访次已被修改，请重新载入")
        conn.execute("INSERT INTO visit_revisions VALUES(?,?,?,?)", (visit_id, result["revision"], storage.encode(result), storage.now()))
        storage.audit(conn, "visit_edit", visit_id, revision=result["revision"])
        return result

    @app.post("/api/visits/{visit_id}/analyze", dependencies=protected)
    def visit_analyze(visit_id: str, payload: AnalyzeInput, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        visit = visit_record(conn, visit_id)
        if visit["revision"] != payload.expected_revision:
            raise HTTPException(409, "输入版本已变化，请保存并重新分析")
        all_rules = load_rules(conn)
        selected = set(payload.selected_rule_ids)
        available = {r["id"] for r in all_rules if r["status"] == "published"}
        if (selected | set(payload.modification_ids) | ({payload.base_rule_id} if payload.base_rule_id else set())) - available:
            raise HTTPException(409, "选定规则未发布或已撤回")
        eligible, evidence, warnings = [], {}, []
        for rule in all_rules:
            if rule["status"] != "published" or (selected and rule["id"] not in selected and rule["kind"] not in {"red_flag", "safety", "modification"}):
                continue
            try:
                for item in checked_evidence(conn, rule):
                    evidence[item["id"]] = item
                eligible.append(rule)
            except HTTPException as exc:
                warnings.append({"rule_id": rule["id"], "reason": exc.detail})
        result = analyze(visit["facts"], eligible, visit["context"])
        result["publication_warnings"] = warnings
        result["literature_candidates"] = research.compare_literature(visit["facts"], research.list_research(conn))
        result["mode"] = "simulation"
        result["formula"] = []
        if payload.base_rule_id and not result["urgent"]:
            candidate = next((c for c in result["candidates"] if c["rule_id"] == payload.base_rule_id), None)
            if not candidate or candidate["status"] != "matched":
                raise HTTPException(409, "基础方规则尚未满足或证据失效")
            base = next(r for r in eligible if r["id"] == payload.base_rule_id)
            modifications = [r for r in eligible if r["id"] in payload.modification_ids and r["kind"] == "modification"]
            result["modifications"] = apply_modifications(base.get("formula", []), modifications, visit["facts"], base.get("formula_id", ""), visit["context"])
            result["formula"] = result["modifications"]["formula"]
            result["safety"] = check_formula(result["formula"], visit["context"], [r for r in eligible if r["kind"] == "safety"])
        snapshot = {"id": str(uuid4()), "visit_id": visit_id, "visit_revision": visit["revision"], "created_at": storage.now(), "result": result,
                    "input_snapshot": visit, "rule_snapshot": eligible, "evidence_snapshot": list(evidence.values()), "stale": False}
        snapshot["snapshot_sha256"] = hashlib.sha256(storage.encode(snapshot).encode("utf-8")).hexdigest()
        conn.execute("INSERT INTO analyses VALUES(?,?,?,?,?)", (snapshot["id"], visit_id, visit["revision"], storage.encode(snapshot), snapshot["created_at"]))
        storage.audit(conn, "analysis_create", snapshot["id"], revision=visit["revision"])
        return snapshot

    @app.post("/api/analyses/{analysis_id}/decision", dependencies=protected)
    def analysis_decision(analysis_id: str, payload: DecisionInput, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "分析不存在")
        visit = visit_record(conn, row["visit_id"])
        snapshot = json.loads(row["document"])
        if visit["revision"] != row["visit_revision"]:
            raise HTTPException(409, "分析已过期，须根据最新输入重新分析")
        for rule in snapshot["rule_snapshot"]:
            current = get_rule(conn, rule["id"])[1]
            if current["status"] != "published":
                raise HTTPException(409, "分析所用规则已撤回，须重新分析")
            checked_evidence(conn, current)
        formula = payload.final_formula if payload.final_formula is not None else snapshot["result"].get("formula", [])
        if snapshot["result"]["urgent"] and formula:
            raise HTTPException(409, "危险信号处理中不接受方药草稿")
        risk = check_formula(formula, visit["context"], [r for r in snapshot["rule_snapshot"] if r["kind"] == "safety"])
        result = {"id": str(uuid4()), "analysis_id": analysis_id, **payload.model_dump(), "final_formula": formula, "risk_check": risk, "created_at": storage.now(), "mode": "simulation"}
        conn.execute("INSERT INTO decisions VALUES(?,?,?,?)", (result["id"], analysis_id, storage.encode(result), result["created_at"]))
        storage.audit(conn, "doctor_decision", result["id"], decision=payload.decision, clinician=payload.clinician)
        return result

    @app.get("/api/patients/{patient_id}/timeline", dependencies=protected)
    def timeline(patient_id: str, conn=Depends(database)):
        return {"items": [visit_details(conn, r["id"]) for r in conn.execute("SELECT id FROM visits WHERE patient_id=? ORDER BY created_at DESC", (patient_id,))]}

    from .model import mount_model_routes
    from .backup import mount_backup_route
    mount_model_routes(app, data_dir, protected, database)
    mount_backup_route(app, data_dir, protected, database)
    personal.mount_personal_routes(app, data_dir, protected, database)

    dist = ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/")
        def not_built():
            return JSONResponse({"detail": "界面尚未构建，请在frontend运行npm run build", "mode": "simulation"}, status_code=503)
    return app
