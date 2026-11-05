"""Source-linked literature comparison, explicitly separate from clinical rules."""
from collections import defaultdict
import json
from pathlib import Path

from .knowledge import _normalize
from .storage import encode, now


def initialize_research(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS research_entries (
        id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
        document TEXT NOT NULL, created_at TEXT NOT NULL)""")


def import_research(conn, path: Path):
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or len(entries) > 10000:
        raise ValueError("研究资料须为条目数组")
    checked = []
    for item in entries:
        if not isinstance(item, dict) or not item.get("id") or not item.get("title"):
            raise ValueError("研究条目缺少身份或标题")
        if item.get("status") != "clinical_review_required" or item.get("required_not_established") is not True:
            raise ValueError("研究导入不能冒充已审核临床规则")
        source = conn.execute("SELECT physical_pages FROM documents WHERE id=?", (item.get("document_sha256"),)).fetchone()
        pages = item.get("physical_pages")
        if source is None or not isinstance(pages, list) or not pages or any(type(n) is not int or n < 1 or n > source[0] for n in pages):
            raise ValueError("研究条目的原件或页码不存在")
        if not isinstance(item.get("classic_quote"), str) or not item["classic_quote"].strip():
            raise ValueError("研究条目缺少可核对的引文")
        features = item.get("features")
        if not isinstance(features, list) or not features or any(not isinstance(f, dict) or not isinstance(f.get("key"), str) or not _normalize(f["key"]) or f.get("expected") not in {"present", "absent"} for f in features):
            raise ValueError("研究症候字段无效")
        if len({_normalize(f["key"]) for f in features}) != len(features):
            raise ValueError("同一研究条目不能重复计数同一症候")
        existing = conn.execute("SELECT document FROM research_entries WHERE id=?", (item["id"],)).fetchone()
        if existing and existing[0] != encode(item):
            raise ValueError("研究条目已存在且内容不同，请使用新的版本id")
        checked.append((item, existing))
    result = {"imported": 0, "duplicate": 0}
    for item, existing in checked:
        if existing:
            result["duplicate"] += 1
        else:
            conn.execute("INSERT INTO research_entries VALUES(?,?,?,?)", (item["id"], item["document_sha256"], encode(item), now()))
            result["imported"] += 1
    return result


def list_research(conn):
    result = []
    for row in conn.execute("SELECT r.document,d.title FROM research_entries r JOIN documents d ON r.document_id=d.id ORDER BY r.id"):
        result.append({**json.loads(row[0]), "document_title": row[1]})
    return result


def rule_draft(entry):
    action = entry.get("modification_action")
    rule = {"id": "research-" + entry["id"] + "-v1", "version": 1, "title": entry["formula_name"] + "（待医师定义）",
            "kind": "modification" if action else "pattern", "status": "draft", "synthetic": False,
            "scope": {"description": "适用人群、场景及排除范围须由合作执业中医师定义"},
            "required": {"fact": "__clinical_rule_not_defined__:" + entry["id"]},
            "support": [{"fact": f["key"], "state": f["expected"]} for f in entry["features"]],
            "evidence_ids": [], "formula_id": "research:" + entry["formula_name"] + "@1", "formula": [], "actions": [],
            "description": f"研究来源：{entry['document_sha256']}，PDF物理页{entry['physical_pages']}。文献卡{entry['id']}。现有症候仅列为待核支持项，未建立必要/充分条件。请核对原件并创建证据，重写required/排除条件，补适用范围及逐味依据；未确认的剂量和加减动作留空，禁止直接发布。"}
    if action:
        rule["base_formula_id"] = "research:" + action["base"] + "@1"
        rule["description"] += " 原文加减记载（非已编译动作）：" + encode(action)
    return rule


def compare_literature(facts, entries):
    indexed = defaultdict(set)
    for fact in facts:
        if fact.get("verified") is True and fact.get("scope", "current") == "current" and fact.get("subject", "patient") == "patient":
            if fact.get("state") != "unknown":
                indexed[_normalize(fact["key"])].add(fact["state"])
    candidates = []
    for entry in entries:
        supporting, opposing, unknown, conflicting = [], [], [], []
        for feature in entry["features"]:
            states = indexed.get(_normalize(feature["key"]), set())
            if "conflict" in states or len(states) > 1:
                conflicting.append(feature["key"])
            elif not states:
                unknown.append(feature["key"])
            elif feature["expected"] in states:
                supporting.append(feature["key"])
            else:
                opposing.append(feature["key"])
        if not (supporting or opposing or conflicting):
            continue
        candidates.append({**entry, "supporting": supporting, "opposing": opposing, "unknown": unknown,
                           "conflicting": conflicting, "comparison_scope": "原文症候对照，非已验证方证判定；不计算诊断概率",
                           "pdf_url": f"/api/documents/{entry['document_sha256']}/pdf#page={entry['physical_pages'][0]}"})
    return sorted(candidates, key=lambda c: (c["document_sha256"], c["physical_pages"][0], c["id"]))
