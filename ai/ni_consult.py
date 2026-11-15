"""Grounded clinical & classic-study orchestrator bridging Stage 1-5 brain data with Ni Shi AI."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

from ai import grounded_study
from ai.ni_persona import build_chat_messages, build_system_prompt
from app import (
    acupuncture_catalog,
    bencao_catalog,
    catalog,
    hantang_catalog,
    library_catalog,
    neijing_catalog,
    syndrome_composer,
)
from retrieval.index import search_library_pages


_EMERGENCY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("胸背剧痛/疑似心脑血管急症", ("胸痛", "胸背痛", "心痛彻背", "剧烈胸痛", "心梗", "中风", "偏瘫", "口眼歪斜", "昏迷", "神昏", "晕厥", "休克")),
    ("呼吸困难/重症缺氧", ("呼吸困难", "喘憋不能平卧", "憋喘窒息", "喉中窒息", "紫绀")),
    ("急性出血/急腹症", ("呕血", "吐血", "咳血", "大出血", "黑便", "剧烈腹痛", "板状腹")),
    ("高热惊厥/危重神经症状", ("高热惊厥", "抽搐不止", "角弓反张", "剧烈头痛呕吐")),
]

_ADVERSE_TOXIC_PATTERNS = (
    "发麻", "舌麻", "唇麻", "口麻", "麻木", "头晕", "昏沉", "心悸大汗", "视物模糊", "剧吐", "服药后麻", "服药后昏",
)

_REF_MARKER_RE = re.compile(r"\[ref\s*[:：]\s*(\d+)\]", re.IGNORECASE)


def _enhance_safety_boundary(query: str, base: dict[str, Any]) -> dict[str, Any]:
    """Ensure acute red-flag & post-dose toxicity alerts always elevate cleanly."""
    merged = dict(base or {})
    matched_groups: list[str] = []
    for label, kws in _EMERGENCY_PATTERNS:
        hits = [kw for kw in kws if kw in query]
        if hits:
            matched_groups.append(f"{label}（{'、'.join(hits[:3])}）")
    toxic_reaction_hits = [kw for kw in _ADVERSE_TOXIC_PATTERNS if kw in query]

    if matched_groups:
        merged["triggered"] = True
        merged["mode"] = "emergency_triage"
        merged["risk_level"] = "emergency"
        merged["title"] = "急危重预警：请优先线下面诊或急诊排查"
        merged["matched_triggers"] = matched_groups
        merged["message"] = (
            "检测到潜在急危重表现：" + "；".join(matched_groups) + "。"
            "请先就近急诊或由执业医师现场评估生命体征，经典研习内容仅作病机对照参考，切勿因自服成方延误抢救。"
        )
    elif toxic_reaction_hits:
        merged["triggered"] = True
        merged["mode"] = "toxic_adverse_reaction"
        merged["risk_level"] = "high_risk"
        merged["title"] = "峻猛药物不良反应预警：请立即停服并就医"
        merged["matched_triggers"] = toxic_reaction_hits
        merged["message"] = (
            "提及「" + "、".join(toxic_reaction_hits[:4]) + "」等表现。若系服用乌头、附子、半夏、细辛等药物后出现唇舌麻木、头晕昏沉或心悸，"
            "绝不可轻信“瞑眩反应硬扛”，应立即停药并就医检查。"
        )
    return merged


def _resolve_pinned_entity(focus: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve user-clicked entity from any Stage 1-5 tab into grounded detail & boost terms."""
    if not isinstance(focus, dict):
        return None, []
    kind = str(focus.get("kind") or "").strip().lower()
    eid = str(focus.get("id") or "").strip()
    if not kind or (kind != "library_page" and not eid):
        return None, []

    if kind == "formula":
        item = catalog.get_formula(eid)
        if not item:
            return None, []
        return {
            "kind": "经方详情",
            "id": item["id"],
            "name": item["name"],
            "book": item.get("book", ""),
            "six_meridian": item.get("six_meridian", ""),
            "indication": item.get("indication", ""),
            "composition_raw": item.get("composition_raw", ""),
            "decoction": item.get("decoction", ""),
            "evidence": item.get("evidence", {}),
        }, [item["name"]]

    if kind == "hantang":
        item = hantang_catalog.get_formula(eid)
        if not item:
            return None, []
        ni_orig = item.get("ni_original") or {}
        return {
            "kind": "汉唐经验方",
            "id": item["id"],
            "ht_number": item.get("ht_number", ""),
            "name": item.get("name", ""),
            "indication": ni_orig.get("indications") or item.get("full_title", ""),
            "partial_herbs": ni_orig.get("partial_herbs", []),
            "contraindications": ni_orig.get("contraindications", ""),
            "safety_level": item.get("safety_level", ""),
            "ziji_commentary": (item.get("ziji_note") or {}).get("commentary", ""),
        }, [item.get("ht_number", ""), item.get("name", "")]

    if kind == "acupoint":
        item = acupuncture_catalog.get_point(eid)
        if not item:
            return None, []
        name = item.get("canonical_name") or item.get("name") or eid
        meridian_obj = item.get("meridian")
        meridian_name = (
            meridian_obj.get("canonical_name", "")
            if isinstance(meridian_obj, dict)
            else item.get("meridian_name", "")
        )
        return {
            "kind": "针灸穴位",
            "id": item["id"],
            "name": name,
            "meridian": meridian_name,
            "location": item.get("location_simplified") or item.get("location_source") or item.get("location", ""),
            "indications": item.get("indications", []),
            "needling": item.get("technique_notes") or item.get("needling", ""),
            "cautions": item.get("cautions", ""),
        }, [name]

    if kind == "condition":
        item = acupuncture_catalog.get_condition(eid)
        if not item:
            return None, []
        name = item.get("canonical_name") or item.get("name") or item.get("title") or eid
        return {
            "kind": "针灸治症",
            "id": item["id"],
            "name": name,
            "summary": item.get("summary") or item.get("ni_notes", ""),
            "sub_patterns": item.get("sub_patterns", [])[:4],
        }, [name]

    if kind == "library_page":
        book_id = str(focus.get("book_id") or "").strip()
        try:
            page_no = int(focus.get("page_no") or 1)
        except (TypeError, ValueError):
            page_no = 1
        pg = library_catalog.get_book_page(book_id, page_no) if book_id else None
        if not pg:
            return None, []
        return {
            "kind": "原典书页",
            "book_id": pg["book_id"],
            "book_title": pg.get("book_title", ""),
            "page_no": pg["page_no"],
            "unit_label": pg.get("unit_label", ""),
            "section_title": pg.get("section_title", ""),
            "body_text": str(pg.get("body_text") or "")[:900],
        }, [pg.get("section_title") or pg.get("book_title", "")]

    if kind in {"herb", "bencao"}:
        item = bencao_catalog.get_entry(eid) or catalog.get_herb(eid)
        if not item:
            return None, []
        name = item.get("name") or item.get("short_name") or eid
        return {
            "kind": "神农本草",
            "id": item["id"],
            "name": name,
            "grade": item.get("grade", ""),
            "properties": item.get("properties", {}),
            "classic_text": item.get("classic_original") or item.get("classic_text", ""),
            "ni_notes": item.get("ni_haixia_annotations") or item.get("ni_notes", ""),
        }, [item.get("short_name") or name]

    if kind == "neijing":
        item = neijing_catalog.get_concept(eid) or neijing_catalog.get_chapter(eid)
        if not item:
            return None, []
        title = item.get("canonical_name") or item.get("title") or item.get("name") or eid
        return {
            "kind": "黄帝内经《素问》",
            "id": item.get("id", eid),
            "title": title,
            "summary": item.get("summary") or item.get("core_teaching", ""),
            "differentiation_rules": (item.get("differentiation_rules") or [])[:4],
        }, [title]

    return None, []


def _extract_search_query(raw_query: str, composed: dict[str, Any], extra_terms: list[str]) -> str:
    tokens: list[str] = []
    for t in extra_terms:
        if t and t not in tokens:
            tokens.append(t)
    for sym in (composed.get("recognized_symptoms") or [])[:6]:
        if sym not in tokens:
            tokens.append(sym)
    for cand in (composed.get("candidate_formulas") or [])[:3]:
        name = cand.get("name")
        if name and not cand.get("suppressed") and name not in tokens:
            tokens.append(name)
    cleaned = re.sub(r"[，。？！、；：\s]+", " ", raw_query).strip()
    if not tokens:
        return cleaned
    # Combine focused clinical entities with the concise raw phrase for balanced lexical + semantic recall.
    prefix = " ".join(tokens[:6])
    return prefix if len(cleaned) > 22 else f"{prefix} {cleaned}".strip()


def _merge_citations(
    ground_res: dict[str, Any],
    sqlite_conn: sqlite3.Connection | None,
    search_terms: list[str],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    seen: set[tuple[str, int]] = set()
    pool: list[dict[str, Any]] = []

    raw_items: list[dict[str, Any]] = []
    # Also actively pull verified primary Renji lectures & Hantang classics so commentaries never crowd them out.
    primary_q = " ".join(t for t in search_terms[:2] if t).strip()
    if primary_q:
        for shelf_name, shelf_limit in (("renji_core", 5), ("hantang_clinical", 3)):
            try:
                hits = search_library_pages(primary_q, shelf=shelf_name, limit=shelf_limit).get("items") or []
                for h in hits:
                    pg = library_catalog.get_book_page(h["book_id"], h["page_no"])
                    if pg and pg.get("text_sha256") == h.get("text_sha256"):
                        raw_items.append({**h, "score": h.get("score", 20), "verified": True})
            except Exception:
                pass

    for sc in ground_res.get("matched_syndromes") or []:
        raw_items.extend(sc.get("library_refs") or [])
    raw_items.extend(ground_res.get("verified_citations") or [])

    # Prioritize Ni Haixia primary lectures & Hantang clinical texts ahead of companion commentaries.
    def _rank_key(item: dict[str, Any]) -> tuple[int, int]:
        bid = str(item.get("book_id") or "")
        layer = str(item.get("tradition_layer") or "")
        if bid.startswith("ni-") or layer in {"ni_lecture", "hantang_clinical", "classic", "ni_teaching"}:
            tier = 0
        else:
            tier = 1
        return (tier, -int(item.get("score") or 0))

    for item in sorted(raw_items, key=_rank_key):
        bid = str(item.get("book_id") or "")
        pno = int(item.get("page_no") or 1)
        key = (bid, pno)
        if not bid or key in seen:
            continue
        seen.add(key)
        quote = str(item.get("quote") or item.get("snippet") or "").strip()
        if not quote:
            continue
        pool.append(
            {
                "source_scope": "curated_library",
                "book_id": bid,
                "book_title": item.get("book_title", bid),
                "shelf_label": item.get("shelf_label", ""),
                "tradition_layer": item.get("tradition_layer", ""),
                "page_no": pno,
                "unit_label": item.get("unit_label") or f"第 {pno} 页",
                "section_title": item.get("section_title", ""),
                "quote": quote,
                "text_sha256": item.get("text_sha256", ""),
                "verified": bool(item.get("verified", True)),
                "reader_url": f"/api/library/books/{bid}/pages/{pno}",
            }
        )
        if len(pool) >= limit - 2:
            break

    if sqlite_conn is not None and search_terms:
        try:
            from app import library

            local_hits = library.retrieve_context(sqlite_conn, search_terms, max_items=3, max_chars=1800)
            for lh in local_hits:
                pool.append(
                    {
                        "source_scope": "local_sqlite",
                        "book_id": lh["source_id"],
                        "book_title": lh["title"],
                        "shelf_label": "本地私有导入文献",
                        "tradition_layer": lh.get("corpus_role", "local"),
                        "page_no": int(lh.get("unit_no") or 1),
                        "unit_label": f"单元 {lh.get('unit_no')}",
                        "section_title": "",
                        "quote": str(lh.get("text") or "").strip(),
                        "text_sha256": lh.get("content_sha256", ""),
                        "verified": True,
                        "reader_url": lh.get("preview_url", ""),
                    }
                )
        except Exception:
            pass

    for idx, cit in enumerate(pool[:limit], 1):
        cit["ref_id"] = idx
    return pool[:limit]


def _enrich_formula_item(cand: dict[str, Any]) -> dict[str, Any]:
    """Attach canonical composition, original doses, decoction method & risk tags from catalog."""
    fid = str(cand.get("formula_id") or "")
    detail = catalog.get_formula(fid) if fid else None
    ev = (detail or {}).get("evidence") or {}
    raw_ings = (detail or {}).get("ingredients") or []
    ingredients = [
        {
            "name": ing.get("name", ""),
            "dose": ing.get("dose", ""),
            "processing": ing.get("processing", ""),
            "risk_level": ing.get("herb_risk_level", "standard"),
        }
        for ing in raw_ings
    ]
    high_risk_herbs = [
        f"{ing['name']}{'（' + ing['processing'] + '）' if ing['processing'] else ''}"
        for ing in ingredients
        if ing["risk_level"] in {"emergency", "high_risk"}
    ]
    herbs_fallback = cand.get("herbs") or [ing["name"] for ing in ingredients]
    return {
        "formula_id": fid,
        "name": cand.get("name") or (detail or {}).get("name", ""),
        "book": (detail or {}).get("book", ""),
        "chapter": (detail or {}).get("chapter", ""),
        "six_meridian": cand.get("six_meridian") or (detail or {}).get("six_meridian", ""),
        "pathogenesis": cand.get("pathogenesis") or ev.get("why", ""),
        "composition_raw": (detail or {}).get("composition_raw", ""),
        "ingredients": ingredients,
        "herbs": herbs_fallback,
        "decoction": (detail or {}).get("decoction", ""),
        "usage_plain": ev.get("usage_plain") or (detail or {}).get("decoction", "") or cand.get("decoction", ""),
        "clinical_rationale": ev.get("why", ""),
        "high_risk_herbs": high_risk_herbs,
        "matched_symptoms": cand.get("matched_symptoms", []),
        "matched_pulses": cand.get("matched_pulses", []),
        "score": cand.get("score", 0),
    }


def _normalize_case_packet(composed: dict[str, Any]) -> dict[str, Any]:
    cands = [c for c in (composed.get("candidate_formulas") or []) if not c.get("suppressed")]
    top_score = max([int(c.get("score") or 0) for c in cands] or [1])
    matched_formulas: list[dict[str, Any]] = []
    for c in cands[:5]:
        item = _enrich_formula_item(c)
        sc = int(item.get("score") or 0)
        item["herb_count"] = len(item.get("ingredients") or item.get("herbs") or [])
        item["match_pct"] = min(98, max(52, int(round(52 + (sc / max(top_score, 60)) * 44)))) if sc > 0 else 0
        item["matched_tongues"] = c.get("matched_tongues", [])
        matched_formulas.append(item)
    suppressed_formulas = [
        {
            "name": c.get("name"),
            "reasons": c.get("conflict_reasons", []),
        }
        for c in (composed.get("candidate_formulas") or [])
        if c.get("suppressed")
    ][:4]

    acupoints = (composed.get("acupoint_protocol") or {}).get("primary") or []
    triage = composed.get("triage_summary") or {}
    diff_notes: list[str] = []
    if triage.get("headline"):
        diff_notes.append(triage["headline"])
    for cr in (triage.get("crossroads") or [])[:3]:
        q_txt = cr.get("question", "")
        why = cr.get("why", "")
        diff_notes.append(f"{q_txt}：{why}".strip("："))
    for dn in (composed.get("differential_notes") or [])[:3]:
        txt = dn if isinstance(dn, str) else str(dn.get("note") or dn.get("summary") or dn)
        if txt and txt not in diff_notes:
            diff_notes.append(txt)

    inquiries = [
        fq.get("question") if isinstance(fq, dict) else str(fq)
        for fq in (composed.get("followup_questions") or [])[:5]
    ]

    ai_pkt = composed.get("ai_ready_case_packet") or {}
    primary_six = matched_formulas[0].get("six_meridian", "") if matched_formulas else ""

    # Enrich compound regimens with individual formula compositions so user gets complete joint Rx.
    compounds = []
    for reg in (composed.get("compound_regimens") or [])[:2]:
        sub_formulas = [
            _enrich_formula_item({"formula_id": fid})
            for fid in (reg.get("formula_ids") or [])
        ]
        compounds.append({**reg, "formulas_detail": [f for f in sub_formulas if f.get("name")]})

    return {
        "primary_six_channel": primary_six,
        "triage_headline": triage.get("headline", ""),
        "extracted_symptoms": composed.get("recognized_symptoms") or [],
        "recognized_negations": composed.get("recognized_negations") or [],
        "extracted_pulses": composed.get("recognized_pulses") or [],
        "extracted_tongues": composed.get("recognized_tongues") or [],
        "contradiction_notes": triage.get("tongue_notes") or [],
        "matched_formulas": matched_formulas,
        "suppressed_formulas": suppressed_formulas,
        "compound_regimens": compounds,
        "matched_acupoints": acupoints[:6],
        "matched_herbs": ai_pkt.get("related_herbs") or [],
        "differential_points": diff_notes,
        "missing_inquiry": inquiries,
        "classical_redlines": (composed.get("classical_redlines") or [])[:4],
        "decoction_and_safety": composed.get("decoction_and_safety") or [],
    }


def build_clinical_context(
    query: str,
    *,
    pulse: str = "",
    tongue: str = "",
    entity_focus: dict[str, Any] | None = None,
    sqlite_conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Assemble full Stage 1-5 grounded evidence packet before invoking any LLM."""
    pinned, extra_terms = _resolve_pinned_entity(entity_focus)
    combined_parts = [query.strip()]
    if pulse.strip():
        combined_parts.append(f"脉{pulse.strip()}")
    if tongue.strip():
        combined_parts.append(f"舌{tongue.strip()}")
    combined_query = " ".join(p for p in combined_parts if p).strip()

    composed = syndrome_composer.compose_differentiation(q=combined_query, pulse=pulse.strip())
    search_q = _extract_search_query(combined_query, composed, extra_terms)
    ground_res = grounded_study.ground_study_query(q=search_q, limit_citations=10)
    hantang_clues = composed.get("hantang_context") or hantang_catalog.match_clinical_context(
        q=search_q,
        symptoms=composed.get("recognized_symptoms"),
        pulses=composed.get("recognized_pulses"),
    )

    safety = _enhance_safety_boundary(combined_query, ground_res.get("safety_boundary") or composed.get("safety_boundary") or {})
    citations = _merge_citations(ground_res, sqlite_conn, [search_q, *extra_terms], limit=10)
    case_packet = _normalize_case_packet(composed)
    lead_formula = (case_packet.get("matched_formulas") or [None])[0]
    if not safety.get("triggered") and lead_formula and lead_formula.get("high_risk_herbs"):
        safety = {
            **safety,
            "triggered": True,
            "mode": "toxic_herb_caution",
            "risk_level": "caution",
            "title": "处方含峻猛/需严格炮制先煎药物提示",
            "message": (
                f"首推方剂「{lead_formula['name']}」含高注意度药味：{'、'.join(lead_formula['high_risk_herbs'])}。"
                "煎服前须严守炮制、先煎时间及禁忌，并由执业医师核对剂量；如出现麻木、头晕、心悸立即停用就医。"
            ),
        }

    return {
        "query": query.strip(),
        "combined_query": combined_query,
        "search_query": search_q,
        "safety_boundary": safety,
        "pinned_entity": pinned,
        "case_packet": case_packet,
        "hantang_clues": hantang_clues,
        "layers": ground_res.get("layers") or {},
        "matched_syndromes": ground_res.get("matched_syndromes") or [],
        "citations": citations,
        "insufficiencies_and_gaps": ground_res.get("insufficiencies_and_gaps") or [],
    }


def prepare_llm_request(
    query: str,
    *,
    pulse: str = "",
    tongue: str = "",
    style: str = "master_balanced",
    history: list[dict[str, str]] | None = None,
    entity_focus: dict[str, Any] | None = None,
    images: list[Any] | None = None,
    sqlite_conn: sqlite3.Connection | None = None,
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Build packet, system prompt, and messages tuple for streaming LLM execution."""
    packet = build_clinical_context(
        query,
        pulse=pulse,
        tongue=tongue,
        entity_focus=entity_focus,
        sqlite_conn=sqlite_conn,
    )
    system_prompt = build_system_prompt(style)
    messages = build_chat_messages(query, packet, history=history, images=images)
    return packet, system_prompt, messages


def extract_cited_refs(text: str, citations: list[dict[str, Any]]) -> dict[str, Any]:
    """Tolerantly map inline `[ref:N]` citations back to verified source objects without raising."""
    by_id = {int(c["ref_id"]): c for c in citations if c.get("ref_id")}
    found_ids: list[int] = []
    invalid_ids: list[int] = []
    for match in _REF_MARKER_RE.finditer(text or ""):
        num = int(match.group(1))
        if num in by_id and num not in found_ids:
            found_ids.append(num)
        elif num not in by_id and num not in invalid_ids:
            invalid_ids.append(num)
    return {
        "referenced_ids": found_ids,
        "referenced_citations": [by_id[i] for i in found_ids],
        "unverified_ref_ids": invalid_ids,
    }


def _format_rx_markdown(formula: dict[str, Any]) -> str:
    lines: list[str] = [f"**建议主方处方：{formula['name']}**（{formula.get('book') or '经方典籍'} · {formula.get('six_meridian', '')}）"]
    if formula.get("composition_raw"):
        lines.append(f"- **原典原方**：{formula['composition_raw']}")
    elif formula.get("ingredients"):
        parts = [
            f"{ing['name']}（{ing['dose']}{' · ' + ing['processing'] if ing['processing'] else ''}）"
            for ing in formula["ingredients"]
        ]
        lines.append(f"- **组成与原量**：{' '.join(parts)}")
    elif formula.get("herbs"):
        lines.append(f"- **参考药味**：{'、'.join(formula['herbs'])}")
    if formula.get("usage_plain"):
        lines.append(f"- **煎煮服法**：{formula['usage_plain']}")
    if formula.get("high_risk_herbs"):
        lines.append(f"- **炮制与安全提醒**：含 {'、'.join(formula['high_risk_herbs'])}，抓药及煎煮剂量须当面复核炮制规范与禁忌。")
    return "\n".join(lines)


def build_offline_ni_reply(packet: dict[str, Any], style: str = "master_balanced") -> str:
    """Synthesize a clean, prescription-ready Ni-style grounded response when offline."""
    parts: list[str] = []
    safety = packet.get("safety_boundary") or {}
    if safety.get("triggered"):
        parts.append(f"> ⚠️ **{safety.get('title', '安全提醒')}**\n> {safety.get('message', '')}")

    case = packet.get("case_packet") or {}
    cands = case.get("matched_formulas") or []
    lead = cands[0] if cands else None

    if style == "academic_strict":
        parts.append("【离线推演模式 · 中医大脑经方辨证与处方参考】")
    else:
        parts.append("我跟你讲嚎，先别慌，按《伤寒》《金匮》六经的路数把寒热表里抓准，处方就在这里（当前未连云端大模型，由本地中医大脑实证引擎直接生成）：")

    if lead:
        parts.append(f"**辨证焦点**：{lead.get('six_meridian', '经方方向')}（{lead.get('pathogenesis', '')} · 主方：**{lead['name']}**）")
        parts.append(_format_rx_markdown(lead))
        compounds = case.get("compound_regimens") or []
        if compounds:
            reg = compounds[0]
            parts.append(f"**备选合方方案**：{reg.get('title', '')}\n- {reg.get('overlap_note', '')}")
    elif case.get("triage_headline"):
        parts.append(f"**辨证焦点**：{case['triage_headline']}")
    else:
        parts.append("当前输入症状较少，中医大脑暂未锁定单一主方——**看病不能猜，先把恶寒发热、有没有汗、口渴饮冷热、手脚温凉、二便补齐，马上就能定方。**")

    diffs = case.get("differential_points") or []
    if diffs:
        parts.append("**鉴别与转方要点**：\n" + "\n".join(f"- {d}" for d in diffs[:4]))

    inquiries = case.get("missing_inquiry") or []
    if inquiries:
        parts.append("**开方前最后确认的四诊问题**：\n" + "\n".join(f"- {q}" for q in inquiries[:4]))

    acups = case.get("matched_acupoints") or []
    if acups:
        pts = "；".join(f"**{p['name']}**（{p.get('role', '')}：{p.get('reason', '')}）" for p in acups[:4])
        parts.append(f"**针灸配穴处方**：{pts}")

    layers = packet.get("layers") or {}
    if layers.get("ni_layer"):
        parts.append(f"**倪师体系阐释**：{layers['ni_layer']}")

    citations = packet.get("citations") or []
    if citations:
        c_lines = []
        for c in citations[:4]:
            snippet = str(c.get("quote") or "").replace("\n", " ")[:120]
            c_lines.append(f"> 📜 **[ref:{c['ref_id']}] {c['book_title']} · {c['unit_label']}**：{snippet}…")
        parts.append("\n".join(c_lines))

    parts.append("---\n*说明：以上为基于经典原典与中医大脑的辨证处方参考；配置 DeepSeek / OpenAI / Gemini / Claude / 本地 Ollama 后，可由“倪师角色”实时推演完整随症加减与医案问答。*")
    return "\n\n".join(parts)
