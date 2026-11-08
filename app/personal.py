"""Personal consultations: desktop Pydantic schemas and portable-core wrappers."""
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from typing import get_origin

from . import consultation_core, decision, formula_engine, library, storage
from .consultation_core import ANALYSIS_REVISION, CONSULT_SYSTEM, RETRIEVAL_ALIASES, ROOT
from .engine import analyze


# Desktop re-exports keep existing callers and tests working. Clinical logic is
# implemented once in consultation_core, which Android imports directly.
def initialize(conn):
    return consultation_core.initialize(conn)


def get_record(conn, consultation_id, include_messages=True):
    return consultation_core.get_record(conn, consultation_id, include_messages)


def facts_from_intake(intake):
    return consultation_core.facts_from_intake(intake)


def retrieval_queries(intake, messages):
    return consultation_core.retrieval_queries(intake, messages)


def build_context(conn, consultation_id, record=None):
    return consultation_core.build_context(conn, consultation_id, record)


def task_warnings(conn, frozen):
    return consultation_core.task_warnings(conn, frozen)


def book_components(proposed, evidence, limitations):
    return consultation_core.book_components(proposed, evidence, limitations)


def prepare_task(conn, consultation_id):
    # Look up build_context at call time so callers/tests can inject a context
    # reader without forking the business logic.
    return consultation_core.prepare_task(conn, consultation_id, context_builder=build_context)


def save_assistant_result(conn, job, result, context):
    return consultation_core.save_assistant_result(conn, job, result, context)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class ModelPayload(Payload):
    """AI output is untrusted prose: ignore unknown keys and treat null lists as empty."""
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def _null_lists_to_empty(cls, value):
        if isinstance(value, dict):
            for name, field in cls.model_fields.items():
                if value.get(name) is None and get_origin(field.annotation) is list:
                    value[name] = []
        return value


class Intake(Payload):
    sex: Literal["male", "female", "unknown"] = "unknown"
    age_years: float | None = Field(default=None, ge=0, le=150)
    chief_complaint: str = Field(default="", max_length=8000)
    body_locations: list[str] = Field(default_factory=list, max_length=60)
    pain_natures: list[str] = Field(default_factory=list, max_length=60)
    symptoms: list[str] = Field(default_factory=list, max_length=100)
    duration: str = Field(default="", max_length=2000)
    tongue: str = Field(default="", max_length=3000)
    pulse: str = Field(default="", max_length=3000)
    sleep: str = Field(default="", max_length=3000)
    appetite: str = Field(default="", max_length=3000)
    stool: str = Field(default="", max_length=3000)
    urine: str = Field(default="", max_length=3000)
    medical_history: str = Field(default="", max_length=5000)
    medications: str = Field(default="", max_length=5000)
    allergies: str = Field(default="", max_length=3000)
    notes: str = Field(default="", max_length=8000)
    facts: list[dict] = Field(default_factory=list, max_length=300)


class NewConsultation(Payload):
    title: str = Field(default="", max_length=100)
    intake: Intake = Field(default_factory=Intake)


class EditConsultation(Payload):
    expected_revision: int = Field(ge=1, strict=True)
    intake: Intake


class MessageInput(Payload):
    text: str = Field(min_length=1, max_length=20000)
    expected_revision: int | None = Field(default=None, ge=1, strict=True)


class MatchInput(Payload):
    facts: list[dict] = Field(default_factory=list, max_length=300)
    query: str = Field(default="", max_length=4000)
    limit: int = Field(default=8, ge=1, le=30)


class Question(ModelPayload):
    key: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2000)
    reason: str = Field(default="", max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class Syndrome(ModelPayload):
    name: str = Field(min_length=1, max_length=200)
    six_meridian: str = Field(default="", max_length=200)
    eight_principles: str = Field(default="", max_length=500)
    supporting_symptoms: list[str] = Field(default_factory=list, max_length=100)
    contradictions: list[str] = Field(default_factory=list, max_length=100)
    missing_information: list[str] = Field(default_factory=list, max_length=100)
    brief_reason: str = Field(default="", max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class Component(ModelPayload):
    name: str = Field(min_length=1, max_length=100)
    processing: str | None = Field(default=None, max_length=300)
    source_dose: str | None = Field(default=None, max_length=300)
    source_unit: str | None = Field(default=None, max_length=100)
    source_ref: str | None = Field(default=None, max_length=2000)


class Modification(ModelPayload):
    action: Literal["add", "remove", "replace", "adjust"]
    herb: str = Field(min_length=1, max_length=100)
    replacement: str | None = Field(default=None, max_length=100)
    trigger_symptoms: list[str] = Field(default_factory=list, max_length=100)
    source_note: str = Field(default="", max_length=3000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class FormulaProposal(ModelPayload):
    formula_version_id: str | None = Field(default=None, max_length=200)
    decision_package_id: str | None = Field(default=None, max_length=200)
    decision_package_version: int | None = Field(default=None, ge=1)
    source_modification_ids: list[str] = Field(default_factory=list, max_length=20)
    formula_id: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=4000)
    components: list[Component] = Field(default_factory=list, max_length=100)
    modifications: list[Modification] = Field(default_factory=list, max_length=30)
    preparation: str | None = Field(default=None, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class ConsultResult(ModelPayload):
    stage: Literal["follow_up", "assessment"]
    summary: str = Field(min_length=1, max_length=15000)
    questions: list[Question] = Field(default_factory=list, max_length=10)
    syndromes: list[Syndrome] = Field(default_factory=list, max_length=8)
    formulas: list[FormulaProposal] = Field(default_factory=list, max_length=6)
    risks: list[str] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    urgent: bool = False


def validate_consult_result(text, context):
    try:
        result = ConsultResult.model_validate_json(text).model_dump()
    except ValidationError as exc:
        raise ValueError("AI返回尚不符合问诊结构，未保存为有效答复") from exc
    return consultation_core.validate_result(result, context)


class DecisionInput(Payload):
    facts: list[dict] = Field(default_factory=list, max_length=300)
    package_id: str | None = Field(default=None, max_length=200)


class DecisionPreview(DecisionInput):
    package_id: str = Field(min_length=1, max_length=200)
    base_version_id: str = Field(min_length=1, max_length=200)
    modification_ids: list[str] = Field(min_length=1, max_length=20)


def mount_personal_routes(app, data_dir, protected, database):
    @app.get("/api/decision/coverage", dependencies=protected)
    def decision_coverage(conn=Depends(database)):
        return {**decision.coverage(conn), "external_catalog_formulas": len(formula_engine.load_library()["formulas"]),
                "external_catalog_boundary": "外部目录不计作本机倪氏原件映射", "safety": "incomplete"}

    @app.get("/api/decision/packages", dependencies=protected)
    def decision_packages(conn=Depends(database)):
        return {"items": decision.load_packages(conn)}

    @app.post("/api/decision/evaluate", dependencies=protected)
    def decision_evaluate(payload: DecisionInput, conn=Depends(database)):
        return decision.evaluate(conn, payload.facts, payload.package_id)

    @app.post("/api/decision/modifications/preview", dependencies=protected)
    def decision_preview(payload: DecisionPreview, conn=Depends(database)):
        return decision.preview_modifications(conn, payload.package_id, payload.base_version_id, payload.modification_ids, payload.facts)

    @app.get("/api/personal/overview", dependencies=protected)
    def overview(conn=Depends(database)):
        sources = library.list_sources(conn)
        data = formula_engine.load_library()
        return {"sources": len(sources), "pdf_pages": sum(s["pdf_pages"] or 0 for s in sources),
                "text_units": sum(s["units"] for s in sources if s["format"] != "pdf"),
                "formula_count": len(data["formulas"]), "pattern_count": len(data["patterns"]),
                "consultations": conn.execute("SELECT COUNT(*) FROM consultations").fetchone()[0],
                "ocr_pages": conn.execute("SELECT COUNT(*) FROM pages WHERE ocr_text IS NOT NULL").fetchone()[0]}

    @app.get("/api/library/sources", dependencies=protected)
    def sources(conn=Depends(database)):
        return {"items": library.list_sources(conn)}

    @app.get("/api/library/search", dependencies=protected)
    def search(q: str = "", source_id: str | None = None, limit: int = 30, conn=Depends(database)):
        return {"items": library.search(conn, q, source_id or None, limit)}

    @app.get("/api/library/sources/{source_id}/units/{unit_no}", dependencies=protected)
    def unit(source_id: str, unit_no: int, conn=Depends(database)):
        result = library.get_unit(conn, data_dir, source_id, unit_no)
        if result is None:
            raise HTTPException(404, "来源或位置不存在")
        return result

    @app.get("/api/library/sources/{source_id}/original", dependencies=protected)
    def original(source_id: str, conn=Depends(database)):
        path = library.original_path(conn, data_dir, source_id)
        return FileResponse(path, filename=path.name, content_disposition_type="attachment")

    @app.post("/api/consultations/{consultation_id}/facts/confirm", dependencies=protected)
    def confirm_fact(consultation_id: str, payload: dict, conn=Depends(database)):
        from . import consultation_library
        return consultation_library.confirm_fact(conn, consultation_id, payload.get('term'), payload.get('state'), payload.get('expected_revision'))

    @app.get("/api/formulas", dependencies=protected)
    def formulas(q: str = "", limit: int = 30):
        if len(q) > 256 or not 1 <= limit <= 100:
            raise ValueError("检索词或数量无效")
        data = formula_engine.load_library()["formulas"]
        return {"items": [f for f in data if not q or q in f["name"] or q in f.get("syndrome", "")][:limit]}

    @app.post("/api/formulas/match", dependencies=protected)
    def match(payload: MatchInput):
        analyze(payload.facts, [], {})
        return {"items": formula_engine.match_patterns(payload.facts, payload.query, payload.limit)}

    @app.get("/api/formulas/{formula_id}", dependencies=protected)
    def formula(formula_id: str):
        result = formula_engine.get_formula(formula_id)
        if result is None:
            raise HTTPException(404, "方剂条目不存在")
        return result

    @app.get("/api/consultations", dependencies=protected)
    def consultations(conn=Depends(database)):
        return {"items": [dict(r) for r in conn.execute("SELECT id,title,revision,created_at,updated_at FROM consultations ORDER BY updated_at DESC")]}

    @app.post("/api/consultations", dependencies=protected)
    def create(payload: NewConsultation, conn=Depends(database)):
        facts_from_intake(payload.intake.model_dump())
        key = str(uuid4())
        conn.execute("INSERT INTO consultations VALUES(?,?,?,?,?,?)", (key, payload.title or "新问诊", storage.encode(payload.intake.model_dump()), 1, storage.now(), storage.now()))
        return get_record(conn, key)

    @app.get("/api/consultations/{consultation_id}", dependencies=protected)
    def consultation(consultation_id: str, conn=Depends(database)):
        return get_record(conn, consultation_id)

    @app.put("/api/consultations/{consultation_id}", dependencies=protected)
    def edit(consultation_id: str, payload: EditConsultation, conn=Depends(database)):
        facts_from_intake(payload.intake.model_dump())
        conn.execute("BEGIN IMMEDIATE")
        record = get_record(conn, consultation_id, False)
        if record["revision"] != payload.expected_revision:
            raise HTTPException(409, "问诊信息已变化，请重新加载")
        conn.execute("UPDATE consultations SET intake=?,revision=revision+1,updated_at=? WHERE id=?", (storage.encode(payload.intake.model_dump()), storage.now(), consultation_id))
        return get_record(conn, consultation_id)

    @app.post("/api/consultations/{consultation_id}/messages", dependencies=protected)
    def add_message(consultation_id: str, payload: MessageInput, conn=Depends(database)):
        conn.execute("BEGIN IMMEDIATE")
        record = get_record(conn, consultation_id, False)
        if payload.expected_revision is not None and payload.expected_revision != record["revision"]:
            raise HTTPException(409, "对话已更新，请重新加载")
        revision = record["revision"] + 1
        key, at = str(uuid4()), storage.now()
        conn.execute("INSERT INTO consultation_messages VALUES(?,?,?,?,?,?,?,?,?)", (key, consultation_id, "user", payload.text, None, None, None, revision, at))
        title = payload.text[:30] if record["title"] == "新问诊" else record["title"]
        conn.execute("UPDATE consultations SET title=?,revision=?,updated_at=? WHERE id=?", (title, revision, at, consultation_id))
        return {"consultation": get_record(conn, consultation_id), "message": {"id": key, "role": "user", "text": payload.text, "created_at": at}, "revision": revision}

    @app.get("/api/consultations/{consultation_id}/context", dependencies=protected)
    def context(consultation_id: str, conn=Depends(database)):
        return build_context(conn, consultation_id)
