import json
import sqlite3

import pytest


def entry():
    return {"id": "research-test", "title": "合成原文对照测试", "formula_name": "合成方", "type": "formula",
            "document_sha256": "a" * 64, "physical_pages": [1], "classic_quote": "合成条文",
            "ni_comment_summary": "", "features": [{"key": "汗出", "expected": "present", "source": "classic"},
                                                     {"key": "恶风", "expected": "present", "source": "classic"}],
            "differential_questions": ["这是当前观察还是既往？"], "modification_action": None,
            "dose_source_status": "historical_only_not_converted", "required_not_established": True,
            "quality_notes": ["仅工程测试"], "status": "clinical_review_required"}


def test_literature_comparison_preserves_unknown_negative_and_conflicting_facts():
    from app.research import compare_literature

    facts = [{"key": "汗出", "state": "absent", "verified": True, "scope": "current"},
             {"key": "恶风", "state": "present", "verified": False, "scope": "current"},
             {"key": "恶风", "state": "present", "verified": True, "scope": "history"}]
    item = compare_literature(facts, [entry()])[0]
    assert item["opposing"] == ["汗出"]
    assert item["unknown"] == ["恶风"]
    assert item["supporting"] == []
    assert item["status"] == "clinical_review_required"
    facts.append({"key": "汗出", "state": "present", "verified": True})
    assert compare_literature(facts, [entry()])[0]["conflicting"] == ["汗出"]
    assert compare_literature([], [entry()]) == []


def test_research_import_checks_registered_source_and_never_publishes_rule(tmp_path):
    from app.research import initialize_research, import_research, list_research

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents(id TEXT PRIMARY KEY,title TEXT,physical_pages INTEGER)")
    conn.execute("INSERT INTO documents VALUES(?,?,?)", ("a" * 64, "合成来源", 2))
    initialize_research(conn)
    source = tmp_path / "seed.json"
    source.write_text(json.dumps([entry()], ensure_ascii=False), encoding="utf-8")
    assert import_research(conn, source)["imported"] == 1
    assert import_research(conn, source)["duplicate"] == 1
    assert list_research(conn)[0]["status"] == "clinical_review_required"
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rules'").fetchone() is None
    bad = entry()
    bad.update(id="bad-page", physical_pages=[3])
    source.write_text(json.dumps([bad]), encoding="utf-8")
    with pytest.raises(ValueError):
        import_research(conn, source)


def test_source_order_does_not_present_symptom_counts_as_clinical_priority():
    from app.research import compare_literature

    early, later = entry(), entry()
    early.update(id="early", physical_pages=[1], features=early["features"][:1])
    later.update(id="later", physical_pages=[2])
    facts = [{"key": key, "state": "present", "verified": True} for key in ["汗出", "恶风"]]
    assert [r["id"] for r in compare_literature(facts, [later, early])] == ["early", "later"]


def test_generated_rule_draft_does_not_invent_necessary_conditions_or_doses():
    from app.research import rule_draft
    from app.engine import validate_rule

    draft = validate_rule(rule_draft(entry()))
    assert draft["status"] == "draft" and draft["synthetic"] is False
    assert draft["required"] == {"fact": "__clinical_rule_not_defined__:research-test"}
    assert draft["formula"] == [] and draft["actions"] == []
    assert draft["support"] == [{"fact": "汗出", "state": "present"}, {"fact": "恶风", "state": "present"}]
