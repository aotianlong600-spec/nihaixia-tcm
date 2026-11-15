"""Stage 5A Unified Cross-Book Syndrome Network & Integrated Differentiation Orchestrator."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from app import (
    acupuncture_diagnose,
    bencao_catalog,
    formula_diagnose,
    library_catalog,
    neijing_catalog,
)
from ai import grounded_study
from retrieval.index import norm_simp, search_library_pages, tokenize_query


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data"


@lru_cache(maxsize=1)
def _syndrome_clusters() -> list[dict[str, Any]]:
    return json.loads((DATA_DIR / "relations" / "syndrome_clusters.json").read_text(encoding="utf-8")).get("items", [])


@lru_cache(maxsize=1)
def _entity_label_map() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for fn in ("formulas.json", "jinkui_formulas.json"):
        for f in json.loads((DATA_DIR / fn).read_text(encoding="utf-8")):
            out[f["id"]] = {"title": f["name"], "meta": f"{f.get('book', '')} · {f.get('six_meridian') or f.get('chapter') or ''}"}
    for h in json.loads((DATA_DIR / "bencao" / "entries.json").read_text(encoding="utf-8")):
        out[h["id"]] = {"title": h.get("short_name") or h["name"], "meta": f"{h.get('grade', '')}"}
    for pt in json.loads((DATA_DIR / "acupuncture" / "acupoints.json").read_text(encoding="utf-8")).get("items", []):
        out[pt["id"]] = {"title": pt["canonical_name"], "meta": pt.get("meridian_name") or "穴位"}
    for cd in json.loads((DATA_DIR / "acupuncture" / "conditions.json").read_text(encoding="utf-8")).get("items", []):
        out[cd["id"]] = {"title": cd["canonical_name"], "meta": "针灸治症"}
    for c in json.loads((DATA_DIR / "neijing" / "concepts.json").read_text(encoding="utf-8")).get("items", []):
        out[c["id"]] = {"title": c["canonical_name"], "meta": c.get("submodule", "内经专题")}
    for ch in json.loads((DATA_DIR / "neijing" / "chapters.json").read_text(encoding="utf-8")).get("chapters", []):
        out[ch["id"]] = {"title": ch["title"], "meta": ch.get("volume_label", "素问")}
    return out


def _resolve_cluster(sc: dict[str, Any]) -> dict[str, Any]:
    lmap = _entity_label_map()

    def resolve_list(ids: list[str], module: str) -> list[dict[str, str]]:
        return [
            {
                "id": eid,
                "module": module,
                "title": lmap.get(eid, {}).get("title", eid),
                "meta": lmap.get(eid, {}).get("meta", ""),
            }
            for eid in ids
        ]

    return {
        "id": sc["id"],
        "title": sc["title"],
        "keywords": sc.get("keywords", []),
        "clinical_reasoning": sc["clinical_reasoning"],
        "differentials": sc["differentials"],
        "version_conflicts": sc["version_conflicts"],
        "safety_note": sc["safety_note"],
        "neijing_concepts": resolve_list(sc.get("neijing_concept_ids", []), "neijing"),
        "neijing_chapters": resolve_list(sc.get("neijing_chapter_ids", []), "neijing"),
        "formulas": resolve_list(sc.get("formula_ids", []), "formulas"),
        "bencao": resolve_list(sc.get("bencao_ids", []), "bencao"),
        "acupuncture_conditions": resolve_list(sc.get("acupuncture_condition_ids", []), "acupuncture"),
        "acupuncture_points": resolve_list(sc.get("acupuncture_point_ids", []), "acupuncture"),
        "library_refs": sc.get("library_refs", []),
    }


def overview() -> dict[str, Any]:
    lib = library_catalog.overview()
    net = json.loads((DATA_DIR / "relations" / "unified_network.json").read_text(encoding="utf-8"))
    clusters = _syndrome_clusters()
    return {
        "stage5_ready": True,
        "modules": {
            "acupuncture": acupuncture_diagnose.__name__,
            "bencao_entries": 385,
            "neijing_chapters": 74,
            "neijing_concepts": 34,
            "formulas": 299,
        },
        "library": lib["stats"],
        "syndromes_count": len(clusters),
        "network_edges": net.get("edge_count", 0),
        "sample_chips": [
            {"label": "胸痹短气 · 心痛彻背", "q": "胸痹 短气 心痛彻背"},
            {"label": "往来寒热 · 胸胁苦满", "q": "往来寒热 胸胁苦满"},
            {"label": "太阳有汗恶风 · 桂枝", "q": "发热 汗出 恶风"},
            {"label": "下利清谷 · 四肢厥逆", "q": "下利清谷 四肢厥逆"},
            {"label": "心烦失眠 · 心中懊憹", "q": "心中烦 不得卧 失眠"},
            {"label": "水肿小便不利 · 渴欲饮水", "q": "水肿 小便不利 渴欲饮水"},
            {"label": "吐血便血 · 血证论", "q": "吐血 便血 先便后血"},
            {"label": "偏头痛 · 巅顶痛干呕", "q": "头痛 巅顶痛 干呕"},
            {"label": "黄疸发黄 · 身目黄", "q": "黄疸 身目黄 小便不利"},
            {"label": "风湿历节 · 关节痛", "q": "风湿 历节 关节痛"},
        ],
    }


def list_syndromes(q: str = "") -> dict[str, Any]:
    clusters = _syndrome_clusters()
    nq = norm_simp(q)
    tokens = tokenize_query(q)
    items = []
    for c in clusters:
        if nq:
            blob = norm_simp(" ".join([c["title"], " ".join(c.get("keywords", [])), c["clinical_reasoning"], c["differentials"]]))
            if not any(t in blob for t in tokens):
                continue
        items.append(_resolve_cluster(c))
    return {"total": len(items), "items": items}


def get_syndrome(syndrome_id: str) -> dict[str, Any] | None:
    for c in _syndrome_clusters():
        if c["id"] == syndrome_id:
            return _resolve_cluster(c)
    return None


def diagnose_unified(q: str = "") -> dict[str, Any]:
    cleaned = (q or "").strip()
    if not cleaned:
        ov = overview()
        return {
            "query": "",
            "safety_boundary": grounded_study._detect_safety_boundary(""),
            "syndrome_clusters": [_resolve_cluster(c) for c in _syndrome_clusters()[:6]],
            "neijing": {"concepts": [], "chapters": []},
            "formulas": {"matched_formulas": [], "differentiation_guides": [], "matched_six_channels": []},
            "bencao": {"items": [], "related_comparisons": []},
            "acupuncture": {"matched_patterns": [], "matched_points": [], "channel_guides": []},
            "library_hits": [],
            "sample_chips": ov["sample_chips"],
        }

    safety = grounded_study._detect_safety_boundary(cleaned)
    raw_clusters = grounded_study._match_syndromes(cleaned, limit=4)
    resolved_clusters = [_resolve_cluster(c) for c in raw_clusters]

    nj = neijing_catalog.diagnose(cleaned, limit_concepts=4, limit_chapters=4)
    frm = formula_diagnose.diagnose_formulas(cleaned, limit_formulas=8)
    ben = bencao_catalog.diagnose(cleaned)
    acu = acupuncture_diagnose.diagnose_symptoms(cleaned, limit_patterns=5, limit_points=8)
    lib = search_library_pages(cleaned, limit=10)

    combined_alerts: list[str] = []
    if safety.get("triggered"):
        combined_alerts.append(f"[{safety['title']}] {safety['message']}")
    for a in (frm.get("safety_alerts") or []) + (acu.get("safety_alerts") or []) + (ben.get("safety_alerts") or []):
        msg = a.get("message") or a.get("text") or str(a) if isinstance(a, dict) else str(a)
        if msg and msg not in combined_alerts:
            combined_alerts.append(msg)
    if nj.get("safety_banner") and nj.get("has_high_risk"):
        combined_alerts.append(str(nj["safety_banner"]))

    return {
        "query": cleaned,
        "safety_boundary": safety,
        "combined_safety_alerts": combined_alerts[:6],
        "syndrome_clusters": resolved_clusters,
        "neijing": {
            "concepts": nj.get("concepts", [])[:4],
            "chapters": nj.get("chapters", [])[:4],
        },
        "formulas": {
            "matched_formulas": frm.get("matched_formulas", [])[:8],
            "differentiation_guides": frm.get("differentiation_guides", [])[:3],
            "matched_six_channels": frm.get("matched_six_channels", [])[:3],
            "matched_jinkui_chapters": frm.get("matched_jinkui_chapters", [])[:4],
        },
        "bencao": {
            "items": ben.get("items", [])[:8],
            "related_comparisons": ben.get("related_comparisons", [])[:4],
        },
        "acupuncture": {
            "matched_patterns": acu.get("matched_patterns", [])[:5],
            "matched_points": acu.get("matched_points", [])[:8],
            "channel_guides": acu.get("channel_guides", [])[:3],
        },
        "library_hits": lib.get("items", [])[:8],
    }
