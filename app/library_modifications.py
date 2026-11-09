"""Read-only classical formula modification rules from the local corpus."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "library_evidence"
FORMAT = "nihaixia-library-modifications"
VERSION = 1
NOTICE = "库内原文抽取的加减规则，仅表示原文在某个方后写了该动作；不表示当前患者适用，须回看原件。"
VERIFIED = "verified_in_current_library"


def _read(name: str) -> dict:
    path = DATA_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"库内加减数据缺失：{name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"库内加减数据格式错误：{name}") from exc


@lru_cache(maxsize=1)
def _data() -> dict:
    data = _read("modifications.json")
    if (not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != VERSION
            or not isinstance(data.get("rules"), list)):
        raise ValueError("库内加减数据格式或版本不兼容")
    seen = set()
    for item in data["rules"]:
        if not isinstance(item, dict) or not item.get("formula_id") or not item.get("raw"):
            raise ValueError("库内加减规则格式无效")
        if not isinstance(item.get("actions"), list) or not item["actions"]:
            raise ValueError("库内加减规则缺少动作")
        key = (item["formula_id"], item["raw"], item.get("source", {}).get("locator"))
        if key in seen:
            raise ValueError("库内加减规则重复")
        seen.add(key)
    return data


@lru_cache(maxsize=1)
def _index() -> dict:
    index = {}
    for item in _data()["rules"]:
        index.setdefault(item["formula_id"], []).append(item)
    return index


def all_rules() -> list[dict]:
    return deepcopy(_data()["rules"])


def clear_cache() -> None:
    _data.cache_clear()
    _index.cache_clear()


def summary() -> dict:
    data = _data()
    return {
        "review_status": "library_source",
        "notice": NOTICE,
        **deepcopy(data.get("counts") or {}),
        "source": deepcopy(data.get("source") or {}),
    }


def for_formula(formula_id: str) -> list[dict]:
    return deepcopy(_index().get(str(formula_id), []))


def verify_rule(conn, rule: dict) -> tuple[dict | None, str | None]:
    source = rule.get("source") or {}
    page_match = re.fullmatch(r"physical_page:([1-9][0-9]*)", str(source.get("locator", "")))
    if not page_match or not source.get("document_id") or not source.get("quote"):
        return None, "invalid_source"
    page = int(page_match[1])
    row = conn.execute("""SELECT p.raw_text,p.corrected_text,p.ocr_text,d.title
        FROM pages p JOIN documents d ON d.id=p.document_id
        WHERE p.document_id=? AND p.physical_page=?""", (source["document_id"], page)).fetchone()
    if not row:
        return None, "source_page_missing"
    raw, corrected, ocr, title = row
    using_ocr = corrected is None and not (raw or "").strip()
    text = corrected if corrected is not None else ((ocr or "") if using_ocr else (raw or ""))
    if title != source.get("source_title"):
        return None, "source_title_mismatch"
    if source["quote"] not in text:
        return None, "quote_not_on_source_page"
    if hashlib.sha256(source["quote"].encode("utf-8")).hexdigest() != source.get("quote_sha256"):
        return None, "quote_hash_mismatch"
    verified = deepcopy(rule)
    verified["source"] = {
        **source,
        "unit_no": page,
        "verification": VERIFIED,
        "verification_method": "quote_on_page_and_sha256",
    }
    return verified, None


def verified_for_formula(conn, formula_id: str) -> tuple[list[dict], list[dict]]:
    verified, rejected = [], []
    for rule in for_formula(formula_id):
        item, reason = verify_rule(conn, rule)
        if item is not None:
            verified.append(item)
        else:
            rejected.append({
                "formula_id": rule.get("formula_id"),
                "formula_name": rule.get("formula_name"),
                "condition": rule.get("condition"),
                "reason": reason,
            })
    return verified, rejected


def search(query: str = "", formula_id: str = "", limit: int = 60) -> dict:
    if not isinstance(query, str) or len(query) > 80:
        raise ValueError("搜索词过长")
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("limit 须在 1 到 200 之间")
    term = query.strip()
    items = []
    for rule in _data()["rules"]:
        if formula_id and rule["formula_id"] != formula_id:
            continue
        haystack = " ".join([
            rule["formula_name"], rule.get("condition", ""), rule["raw"],
            *[action.get("herb", "") for action in rule.get("actions") or []],
        ])
        if term and term not in haystack:
            continue
        items.append(deepcopy(rule))
        if len(items) >= limit:
            break
    return {"items": items, "total": len(items), "review_status": "library_source", "notice": NOTICE}


def mount_library_modification_routes(app, protected):
    from fastapi import Query

    @app.get("/api/library/modifications/summary", dependencies=protected)
    def library_modifications_summary():
        return summary()

    @app.get("/api/library/modifications", dependencies=protected)
    def library_modifications(q: str = Query(default="", max_length=80),
                              formula_id: str = Query(default="", max_length=120),
                              limit: int = Query(default=60, ge=1, le=200)):
        return search(q, formula_id, limit)

    @app.get("/api/library/modifications/formulas/{formula_id}", dependencies=protected)
    def library_modifications_for_formula(formula_id: str):
        return {"items": for_formula(formula_id), "review_status": "library_source", "notice": NOTICE}
