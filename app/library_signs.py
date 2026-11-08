"""Read-only sign-term evidence from the local library."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "library_evidence"
FORMAT = "nihaixia-library-sign-terms"
VERSION = 1
NOTICE = "体征词表为项目整理；引文来自本机库原文，可能受 OCR 影响，须回看原件。"


def _read(name: str) -> dict:
    path = DATA_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"库内体征数据缺失：{name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"库内体征数据格式错误：{name}") from exc


@lru_cache(maxsize=1)
def _data() -> dict:
    data = _read("sign_terms.json")
    if (not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != VERSION
            or not isinstance(data.get("terms"), list) or not data["terms"]):
        raise ValueError("库内体征数据格式或版本不兼容")
    seen = set()
    for item in data["terms"]:
        if not isinstance(item, dict) or not item.get("id") or not item.get("term"):
            raise ValueError("库内体征条目格式无效")
        if item["id"] in seen:
            raise ValueError(f"库内体征 id 重复：{item['id']}")
        seen.add(item["id"])
    return data


@lru_cache(maxsize=1)
def _index() -> dict:
    index = {}
    for item in _data()["terms"]:
        index[item["id"]] = item
        index.setdefault(item["term"], item)
        for alias in item.get("aliases") or []:
            index.setdefault(alias, item)
    return index


def all_terms() -> list[dict]:
    return deepcopy(_data()["terms"])


def clear_cache() -> None:
    _data.cache_clear()
    _index.cache_clear()


def summary() -> dict:
    data = _data()
    kinds = {}
    for item in data["terms"]:
        kinds[item.get("kind", "")] = kinds.get(item.get("kind", ""), 0) + 1
    return {
        "review_status": "library_source",
        "notice": NOTICE,
        **deepcopy(data.get("counts") or {}),
        "kinds": kinds,
        "source": deepcopy(data.get("source") or {}),
    }


def _summary(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "term": entry["term"],
        "label": entry.get("label", ""),
        "kind": entry.get("kind", ""),
        "aliases": deepcopy(entry.get("aliases") or []),
        "six_meridian": deepcopy(entry.get("six_meridian") or []),
        "eight_principles": deepcopy(entry.get("eight_principles") or []),
        "mention_count": entry.get("mention_count", 0),
        "source_count": entry.get("source_count", 0),
    }


def search(query: str = "", kind: str = "", limit: int = 60) -> dict:
    if not isinstance(query, str) or len(query) > 80:
        raise ValueError("搜索词过长")
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("limit 须在 1 到 200 之间")
    term = query.strip()
    items = []
    for entry in _data()["terms"]:
        if kind and entry.get("kind") != kind:
            continue
        haystack = " ".join([entry["term"], entry.get("label", ""), *(entry.get("aliases") or []),
                             *[item.get("quote", "") for item in entry.get("evidence") or []]])
        if term and term not in haystack:
            continue
        items.append(_summary(entry))
        if len(items) >= limit:
            break
    return {"items": items, "total": len(items), "review_status": "library_source", "notice": NOTICE}


def get_term(key: str) -> dict | None:
    entry = _index().get(str(key).strip())
    if entry is None:
        return None
    result = deepcopy(entry)
    result["review_status"] = "library_source"
    result["notice"] = NOTICE
    return result


def mount_library_sign_routes(app, protected):
    from fastapi import HTTPException, Query

    @app.get("/api/library/signs/summary", dependencies=protected)
    def library_signs_summary():
        return summary()

    @app.get("/api/library/signs", dependencies=protected)
    def library_signs(q: str = Query(default="", max_length=80),
                      kind: str = Query(default="", max_length=20),
                      limit: int = Query(default=60, ge=1, le=200)):
        return search(q, kind, limit)

    @app.get("/api/library/signs/{key}", dependencies=protected)
    def library_sign(key: str):
        item = get_term(key)
        if item is None:
            raise HTTPException(404, "未找到该体征")
        return item
