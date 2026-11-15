"""Deterministic verifiable grounded study synthesizer (Stage 5B).

Every textual citation returned MUST verify against the underlying JSONL library page text_sha256.
High-risk personal dosing/emergency prompts trigger explicit boundary guidance instead of prescribing.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from app import library_catalog
from retrieval.index import norm_simp, search_all_knowledge, search_library_pages, tokenize_query


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data"

SELF_PRESCRIBE_CUES = (
    "给我开", "帮我开", "开个方", "开副药", "开几副", "我该吃几克", "我能吃多少克",
    "每天吃多少", "帮我配", "我自己抓", "孕期扎", "怀孕针刺", "孕妇可以喝", "小孩发烧开",
    "生附子怎么煮给我", "自己扎针", "代茶饮用量多少", "替我诊断开方",
)

EMERGENCY_CUES = (
    "剧烈胸痛", "压榨痛", "心肌梗塞", "心梗", "大口呕血", "吐血不止", "昏迷不醒",
    "偏瘫", "口眼歪斜突发", "喘不上气发绀", "中毒昏厥", "尿闭胀痛", "急腹症剧痛",
)

TOXIC_HERB_CUES = ("附子", "生附", "乌头", "川乌", "草乌", "细辛", "大戟", "甘遂", "芫花", "水蛭", "虻虫", "水银", "砒霜", "巴豆")


def _detect_safety_boundary(q: str) -> dict[str, Any]:
    nq = norm_simp(q)
    is_emergency = any(cue in nq for cue in EMERGENCY_CUES)
    is_prescribe = any(cue in nq for cue in SELF_PRESCRIBE_CUES)
    has_toxic = any(cue in nq for cue in TOXIC_HERB_CUES)

    if is_emergency:
        return {
            "triggered": True,
            "mode": "emergency_refusal_and_study",
            "risk_level": "critical_emergency",
            "title": "高危急症边界触发 · 严禁仅依文献延误救治",
            "message": "检测到潜在急性危重症表述（如心胸剧痛、大出血、卒中昏迷、严重呼吸困难等）。本系统仅提供古籍文献研习与理论辨证框架，不能也不应替代急诊抢救或当面临床诊疗。请立即前往医院急诊或拨打急救电话！",
        }
    if is_prescribe:
        return {
            "triggered": True,
            "mode": "non_prescribing_study_only",
            "risk_level": "high_risk_refusal",
            "title": "个体处方/行针拒答边界 · 仅提供教材辨证思路与原文索引",
            "message": "系统严格遵循医疗安全边界：不针对具体个人症状直接开具处方剂量、配伍克数或家庭针刺指令。以下仅呈现《黄帝内经》《神农本草经》《伤寒金匮》《针灸》原书理论对照与鉴别框架供学术研究；实际诊治须由执业中医师面诊四诊合参并核对法定药典。",
        }
    if has_toxic:
        return {
            "triggered": True,
            "mode": "toxic_herb_caution",
            "risk_level": "caution",
            "title": "峻猛/毒性中药及禁忌检索提示",
            "message": "所涉条文包含毒性峻烈药物或特殊禁忌（如乌头、附子、细辛、甘遂、大戟、芫花、破血虫药等）。不同版本对炮制、克数及毒性边界表述各异，切勿自行试服或更改传统煎服次序。",
        }
    return {
        "triggered": False,
        "mode": "standard_study",
        "risk_level": "normal",
        "title": "正常文献研习模式",
        "message": "所有引用均溯源至本地藏书库逐页抽取记录与结构化校注，区分经典原文、倪师讲授、各家注释与整理综合。",
    }


@lru_cache(maxsize=1)
def _syndrome_clusters() -> list[dict[str, Any]]:
    return json.loads((DATA_DIR / "relations" / "syndrome_clusters.json").read_text(encoding="utf-8")).get("items", [])


def _match_syndromes(q: str, limit: int = 3) -> list[dict[str, Any]]:
    clusters = _syndrome_clusters()
    tokens = tokenize_query(q)
    cleaned = norm_simp(q)
    if not tokens:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for c in clusters:
        blob = norm_simp(
            " ".join(
                [
                    c["title"],
                    " ".join(c.get("keywords", [])),
                    c.get("clinical_reasoning", ""),
                    c.get("differentials", ""),
                ]
            )
        )
        sc = 0
        for tok in tokens:
            if tok in norm_simp(c["title"]):
                sc += 18
            elif any(tok in norm_simp(kw) for kw in c.get("keywords", [])):
                sc += 12
            elif tok in blob:
                sc += 4
        if cleaned and any(kw in cleaned for kw in c.get("keywords", [])):
            sc += 15
        if sc > 0:
            scored.append((sc, c))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [c for _, c in scored[:limit]]


def _verify_citations(raw_hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Verify every cited passage against actual JSONL page content and SHA256 before returning."""
    verified: list[dict[str, Any]] = []
    for hit in raw_hits:
        page = library_catalog.get_book_page(hit["book_id"], hit["page_no"])
        if not page or page.get("search_index_status") == "scan_browse_only":
            continue
        if page.get("text_sha256") != hit.get("text_sha256"):
            continue
        verified.append(
            {
                "book_id": hit["book_id"],
                "book_title": hit["book_title"],
                "shelf": hit["shelf"],
                "shelf_label": hit["shelf_label"],
                "tradition_layer": hit["tradition_layer"],
                "page_no": hit["page_no"],
                "unit_label": hit["unit_label"],
                "section_title": hit.get("section_title", ""),
                "snippet": hit["snippet"],
                "text_sha256": page["text_sha256"],
                "verified": True,
            }
        )
    return verified


def ground_study_query(q: str = "", limit_citations: int = 12) -> dict[str, Any]:
    cleaned = (q or "").strip()
    safety = _detect_safety_boundary(cleaned)
    if not cleaned:
        return {
            "query": "",
            "safety_boundary": safety,
            "layers": {},
            "matched_syndromes": [],
            "four_pillar_links": [],
            "verified_citations": [],
            "version_conflicts": [],
            "insufficiencies_and_gaps": ["请输入研习问题、条文关键字、方证对比或症状组合。"],
        }

    lib_res = search_library_pages(cleaned, limit=max(limit_citations, 14))
    verified_cites = _verify_citations(lib_res.get("items", []))[:limit_citations]
    matched_syndromes = _match_syndromes(cleaned, limit=3)
    knowledge_hits = search_all_knowledge(cleaned, limit=16)

    classic_cites = [c for c in verified_cites if c["book_id"] in ("ni-neijing-vol1-pdf", "ni-neijing-vol2-pdf", "ni-bencao-pdf", "ni-shanghan-pdf", "ni-jinkui-pdf", "ni-acupuncture-v2-20100703")]
    hantang_cites = [c for c in verified_cites if c["shelf"] == "hantang_clinical" or c["book_id"] == "ni-jinkui-video-pdf"]
    commentary_cites = [c for c in verified_cites if c["shelf"] == "classical_companions"]

    conflicts: list[str] = []
    for sc in matched_syndromes:
        if sc.get("version_conflicts"):
            conflicts.append(f"【{sc['title']}】{sc['version_conflicts']}")

    gaps: list[str] = []
    if lib_res.get("scan_only_notice"):
        gaps.append(
            f"扫描影印保留卷（{', '.join(lib_res['scan_only_notice'])}）未生成虚假OCR文本，上述自动正文检索不包含这两部影印古籍；请于「书库」板块翻阅原页图像。"
        )
    if not classic_cites:
        gaps.append("本关键词在《人纪核心经典》整句直接命中较少，建议拆分2-3字中医核心词再检。")
    if not hantang_cites:
        gaps.append("《汉唐方剂/文章医案》当前检索词未直接高分命中具体医案，可尝试更换方名或病名。")
    if not knowledge_hits and not matched_syndromes:
        gaps.append("四大学科结构化专条中未见高相关聚簇，系统仅基于书库原文本次检得材料回答，请自行核对上下文。")

    # Compose strictly separated educational layers
    classic_summary = (
        f"匹配核心经典/人纪原文共 {len(classic_cites)} 处，重点涉："
        + "；".join(f"《{c['book_title']}》{c['unit_label']}“{c['snippet'][:60]}”" for c in classic_cites[:2])
        if classic_cites
        else "本次检索词在四大经典原籍正文直接命中有限，以下主依据结构化辨证节点与其他注释书对照。"
    )
    ni_summary = (
        (matched_syndromes[0]["clinical_reasoning"] + " ") if matched_syndromes else ""
    ) + (
        "汉唐临床方论与医案佐证：" + "；".join(f"《{c['book_title']}》{c['unit_label']}" for c in hantang_cites[:3])
        if hantang_cites
        else "汉唐临床医案库本次未检得直接同词医案记录。"
    )
    commentary_summary = (
        "他家辅注古籍互参（唐容川/陈士铎/徐灵胎/丹波元珍/大冢敬节/汪汝麟/黄帝外经）："
        + "；".join(f"《{c['book_title']}》{c['unit_label']}（{c['section_title'] or '正文'}）" for c in commentary_cites[:3])
        if commentary_cites
        else "辅注古籍中未直接匹配同词段落（或属繁简异写/不同病名归类）。"
    )
    syndrome_count = len(_syndrome_clusters())
    organizer_diff = (
        "；".join(f"{sc['title']}鉴别要点：{sc['differentials']}" for sc in matched_syndromes)
        if matched_syndromes
        else f"本问暂未落入预置 {syndrome_count} 大跨书证候群核心边界，请依据下方检出的跨板块实体与书库页码继续对照。"
    )

    return {
        "query": cleaned,
        "safety_boundary": safety,
        "layers": {
            "classic_layer": classic_summary,
            "ni_layer": ni_summary.strip(),
            "commentary_layer": commentary_summary,
            "organizer_synthesis": organizer_diff,
        },
        "matched_syndromes": [
            {
                "id": sc["id"],
                "title": sc["title"],
                "clinical_reasoning": sc["clinical_reasoning"],
                "differentials": sc["differentials"],
                "safety_note": sc["safety_note"],
                "library_refs": sc.get("library_refs", [])[:3],
            }
            for sc in matched_syndromes
        ],
        "four_pillar_links": knowledge_hits,
        "verified_citations": verified_cites,
        "citation_groups": {
            "renji_core": classic_cites,
            "hantang_clinical": hantang_cites,
            "classical_companions": commentary_cites,
        },
        "version_conflicts": conflicts,
        "insufficiencies_and_gaps": gaps,
    }
