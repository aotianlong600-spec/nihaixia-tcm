"""Pure-Python /api/* dispatcher mirroring app.main routes for static browser/Pyodide execution."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from ai import config_store, grounded_study, ni_consult, ni_persona
from app import (
    acupuncture_catalog,
    acupuncture_diagnose,
    bencao_catalog,
    catalog,
    formula_diagnose,
    formula_extras,
    hantang_catalog,
    library_catalog,
    neijing_catalog,
    stage5_service,
    syndrome_composer,
)


def _qs_str(qs: dict[str, list[str]], key: str, default: str = "") -> str:
    vals = qs.get(key)
    return vals[0] if vals else default


def _qs_int(qs: dict[str, list[str]], key: str, default: int, lo: int, hi: int) -> int:
    raw = _qs_str(qs, key, "")
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, val))


def _qs_bool(qs: dict[str, list[str]], key: str, default: bool = False) -> bool:
    raw = _qs_str(qs, key, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def resolve_pdf_source(url_or_path: str) -> dict[str, Any] | None:
    """Resolve an /api/.../image URL to its static book relative_path and 1-based PDF page."""
    path = urlsplit(url_or_path).path
    m = re.match(r"^/api/acupuncture/source-pages/(\d+)/image$", path)
    if m:
        p = int(m.group(1))
        if 1 <= p <= 216:
            return {
                "relative_path": acupuncture_catalog.SOURCE_PDF.relative_to(acupuncture_catalog.ROOT).as_posix(),
                "pdf_page": p,
                "title": f"针灸教程 第 {p} 页",
            }
        return None
    m = re.match(r"^/api/bencao/source-pages/(\d+)/image$", path)
    if m:
        p = int(m.group(1))
        if 1 <= p <= 154:
            return {
                "relative_path": bencao_catalog.SOURCE_PDF_PATH.relative_to(bencao_catalog.ROOT).as_posix(),
                "pdf_page": p,
                "title": f"神农本草经 第 {p} 页",
            }
        return None
    m = re.match(r"^/api/neijing/source-pages/([^/]+)/(\d+)/image$", path)
    if m:
        sid = unquote(m.group(1))
        p = int(m.group(2))
        pdf_path = neijing_catalog.SOURCE_PDFS.get(sid)
        if pdf_path and p >= 1:
            return {
                "relative_path": pdf_path.relative_to(neijing_catalog.ROOT).as_posix(),
                "pdf_page": p,
                "title": f"黄帝内经 第 {p} 页",
            }
        return None
    m = re.match(r"^/api/library/books/([^/]+)/pages/(\d+)/image$", path)
    if m:
        bid = unquote(m.group(1))
        p = int(m.group(2))
        meta = library_catalog.get_book(bid)
        if meta and meta.get("has_image_viewer") and 1 <= p <= int(meta.get("total_units", 0)):
            return {
                "relative_path": meta["relative_path"],
                "pdf_page": p,
                "title": f"{meta.get('short_title', bid)} 第 {p} 页",
            }
        return None
    return None


def _not_found(detail: str) -> tuple[int, dict[str, Any]]:
    return 404, {"detail": detail}


def dispatch_api(url: str) -> tuple[int, Any]:
    """Dispatch any /api/* GET request matching app.main semantics."""
    parsed = urlsplit(url)
    path = parsed.path
    # Normalize if hosted under a subpath like /tcm-study-brain-v2/api/...
    api_idx = path.find("/api/")
    if api_idx > 0:
        path = path[api_idx:]
    qs = parse_qs(parsed.query, keep_blank_values=True)

    if path == "/api/__pdf-source":
        target = _qs_str(qs, "url")
        info = resolve_pdf_source(target)
        return (200, info) if info else _not_found("未找到对应 PDF 原书页")

    if path == "/api/health":
        return 200, {"status": "ok", "module": "formula", "runtime": "browser-static"}

    if path == "/api/overview":
        payload = catalog.overview()
        payload["formula_summary"] = formula_extras.stage4_summary()
        if isinstance(payload.get("modules"), dict):
            payload["modules"]["six_channels"] = "complete"
            payload["modules"]["diagnosis"] = "ready"
            payload["modules"]["jinkui"] = "complete"
        return 200, payload

    # Formulas
    if path == "/api/formulas":
        return 200, catalog.list_formulas(
            _qs_str(qs, "q"),
            _qs_str(qs, "type"),
            _qs_str(qs, "meridian"),
            _qs_str(qs, "book"),
            _qs_str(qs, "status"),
            _qs_str(qs, "review"),
            _qs_int(qs, "page", 1, 1, 99999),
            _qs_int(qs, "page_size", 24, 1, 60),
        )
    if path == "/api/formulas/diagnose":
        return 200, formula_diagnose.diagnose_formulas(
            q=_qs_str(qs, "q"),
            book=_qs_str(qs, "book"),
            six_meridian=_qs_str(qs, "six_meridian"),
            chapter_id=_qs_str(qs, "chapter_id"),
        )
    if path.startswith("/api/formulas/"):
        fid = unquote(path[len("/api/formulas/") :])
        item = catalog.get_formula(fid)
        return (200, formula_extras.enrich_formula_payload(item)) if item else _not_found("未找到方剂")

    # Legacy Herbs
    if path == "/api/herbs":
        return 200, catalog.list_herbs(
            _qs_str(qs, "q"),
            _qs_str(qs, "category"),
            _qs_int(qs, "page", 1, 1, 99999),
            _qs_int(qs, "page_size", 24, 1, 60),
        )
    if path.startswith("/api/herbs/"):
        hid = unquote(path[len("/api/herbs/") :])
        item = catalog.get_herb(hid)
        return (200, item) if item else _not_found("未找到中药")

    # Six Channels & Jinkui
    if path == "/api/six-channels":
        return 200, catalog.list_six_channels()
    if path.startswith("/api/six-channels/"):
        cid = unquote(path[len("/api/six-channels/") :])
        item = catalog.get_six_channel(cid)
        return (200, formula_extras.enrich_six_channel_payload(item)) if item else _not_found("未找到六经条目")
    if path == "/api/jinkui-chapters":
        return 200, formula_extras.list_jinkui_chapters(q=_qs_str(qs, "q"), review_status=_qs_str(qs, "review_status"))
    if path.startswith("/api/jinkui-chapters/"):
        cid = unquote(path[len("/api/jinkui-chapters/") :])
        item = formula_extras.get_jinkui_chapter(cid)
        return (200, item) if item else _not_found("未找到金匮要略篇目")
    if path == "/api/formula-modifications":
        return 200, formula_extras.list_formula_modifications(
            q=_qs_str(qs, "q"),
            base_formula_id=_qs_str(qs, "base_formula_id"),
            target_formula_id=_qs_str(qs, "target_formula_id"),
        )
    if path == "/api/formula-variants":
        return 200, formula_extras.list_formula_variants(q=_qs_str(qs, "q"), diff_only=_qs_bool(qs, "diff_only"))
    if path == "/api/formula-acupuncture-links":
        return 200, formula_extras.list_formula_acupuncture_links(
            q=_qs_str(qs, "q"),
            formula_id=_qs_str(qs, "formula_id"),
            channel_id=_qs_str(qs, "channel_id"),
            chapter_id=_qs_str(qs, "chapter_id"),
        )

    # Acupuncture
    if path == "/api/acupuncture/overview":
        return 200, acupuncture_catalog.overview()
    if path == "/api/acupuncture/chapters":
        return 200, acupuncture_catalog.list_chapters()
    if path.startswith("/api/acupuncture/chapters/"):
        cid = unquote(path[len("/api/acupuncture/chapters/") :])
        item = acupuncture_catalog.get_chapter(cid)
        return (200, item) if item else _not_found("未找到针灸章节")
    if path == "/api/acupuncture/indexes":
        return 200, acupuncture_catalog.list_book_indexes(q=_qs_str(qs, "q"), kind=_qs_str(qs, "kind"))
    if path == "/api/acupuncture/meridians":
        return 200, acupuncture_catalog.list_meridians(
            q=_qs_str(qs, "q"),
            review_status=_qs_str(qs, "review_status"),
            risk_level=_qs_str(qs, "risk_level"),
        )
    if path.startswith("/api/acupuncture/meridians/"):
        mid = unquote(path[len("/api/acupuncture/meridians/") :])
        item = acupuncture_catalog.get_meridian(mid)
        return (200, item) if item else _not_found("未找到经络条目")
    if path == "/api/acupuncture/points":
        return 200, acupuncture_catalog.list_points(
            q=_qs_str(qs, "q"),
            meridian_id=_qs_str(qs, "meridian_id"),
            review_status=_qs_str(qs, "review_status"),
            risk_level=_qs_str(qs, "risk_level"),
        )
    if path.startswith("/api/acupuncture/points/"):
        pid = unquote(path[len("/api/acupuncture/points/") :])
        item = acupuncture_catalog.get_point(pid)
        return (200, item) if item else _not_found("未找到穴位条目")
    if path == "/api/acupuncture/techniques":
        return 200, acupuncture_catalog.list_techniques(
            q=_qs_str(qs, "q"),
            category=_qs_str(qs, "category"),
            review_status=_qs_str(qs, "review_status"),
            risk_level=_qs_str(qs, "risk_level"),
        )
    if path.startswith("/api/acupuncture/techniques/"):
        tid = unquote(path[len("/api/acupuncture/techniques/") :])
        item = acupuncture_catalog.get_technique(tid)
        return (200, item) if item else _not_found("未找到针灸技法条目")
    if path == "/api/acupuncture/conditions":
        return 200, acupuncture_catalog.list_conditions(
            q=_qs_str(qs, "q"),
            review_status=_qs_str(qs, "review_status"),
            risk_level=_qs_str(qs, "risk_level"),
        )
    if path.startswith("/api/acupuncture/conditions/"):
        cid = unquote(path[len("/api/acupuncture/conditions/") :])
        item = acupuncture_catalog.get_condition(cid)
        return (200, item) if item else _not_found("未找到针灸治症条目")
    if path == "/api/acupuncture/diagnose":
        return 200, acupuncture_diagnose.diagnose_symptoms(
            q=_qs_str(qs, "q"),
            risk_level=_qs_str(qs, "risk_level"),
            meridian_id=_qs_str(qs, "meridian_id"),
        )
    m_ap = re.match(r"^/api/acupuncture/source-pages/(\d+)$", path)
    if m_ap:
        item = acupuncture_catalog.get_source_page(int(m_ap.group(1)))
        return (200, item) if item else _not_found("未找到针灸原书页面")

    # Neijing
    if path == "/api/neijing/overview":
        return 200, neijing_catalog.overview()
    if path == "/api/neijing/chapters":
        return 200, neijing_catalog.list_chapters(
            q=_qs_str(qs, "q"),
            volume=_qs_str(qs, "volume"),
            review_status=_qs_str(qs, "review_status"),
            risk_level=_qs_str(qs, "risk_level"),
        )
    if path.startswith("/api/neijing/chapters/"):
        cid = unquote(path[len("/api/neijing/chapters/") :])
        item = neijing_catalog.get_chapter(cid)
        return (200, item) if item else _not_found("未找到内经篇目")
    if path == "/api/neijing/concepts":
        return 200, neijing_catalog.list_concepts(
            q=_qs_str(qs, "q"),
            submodule=_qs_str(qs, "submodule"),
            review_status=_qs_str(qs, "review_status"),
            risk_level=_qs_str(qs, "risk_level"),
        )
    if path.startswith("/api/neijing/concepts/"):
        cid = unquote(path[len("/api/neijing/concepts/") :])
        item = neijing_catalog.get_concept(cid)
        return (200, item) if item else _not_found("未找到内经专题")
    if path == "/api/neijing/diagnose":
        return 200, neijing_catalog.diagnose(
            q=_qs_str(qs, "q"),
            submodule=_qs_str(qs, "submodule"),
            risk_level=_qs_str(qs, "risk_level"),
        )
    if path == "/api/neijing/pages":
        return 200, neijing_catalog.search_pages(
            q=_qs_str(qs, "q"),
            volume=_qs_str(qs, "volume"),
            page_role=_qs_str(qs, "page_role"),
            limit=_qs_int(qs, "limit", 60, 1, 120),
        )
    m_nj = re.match(r"^/api/neijing/source-pages/([^/]+)/(\d+)$", path)
    if m_nj:
        item = neijing_catalog.get_source_page(unquote(m_nj.group(1)), int(m_nj.group(2)))
        return (200, item) if item else _not_found("未找到内经原书页面")
    if path.startswith("/api/neijing/page-by-id/"):
        pid = unquote(path[len("/api/neijing/page-by-id/") :])
        item = neijing_catalog.get_source_page_by_id(pid)
        return (200, item) if item else _not_found("未找到内经原书页面")

    # Bencao
    if path == "/api/bencao/overview":
        return 200, bencao_catalog.overview()
    if path == "/api/bencao/chapters":
        return 200, bencao_catalog.list_chapters()
    if path.startswith("/api/bencao/chapters/"):
        cid = unquote(path[len("/api/bencao/chapters/") :])
        item = bencao_catalog.get_chapter(cid)
        return (200, item) if item else _not_found("未找到本草经章节")
    if path == "/api/bencao/entries":
        return 200, bencao_catalog.list_entries(
            q=_qs_str(qs, "q"),
            grade=_qs_str(qs, "grade"),
            nature=_qs_str(qs, "nature"),
            flavor=_qs_str(qs, "flavor"),
            toxicity=_qs_str(qs, "toxicity"),
            risk_level=_qs_str(qs, "risk_level"),
            review_status=_qs_str(qs, "review_status"),
            has_formulas=_qs_bool(qs, "has_formulas"),
            recovered_only=_qs_bool(qs, "recovered_only"),
            meridian=_qs_str(qs, "meridian"),
            page=_qs_int(qs, "page", 1, 1, 99999),
            page_size=_qs_int(qs, "page_size", 24, 1, 400),
            include_detail=_qs_bool(qs, "include_detail"),
        )
    if path == "/api/bencao/comparisons":
        return 200, bencao_catalog.list_comparisons(q=_qs_str(qs, "q"), category=_qs_str(qs, "category"))
    if path.startswith("/api/bencao/comparisons/"):
        cid = unquote(path[len("/api/bencao/comparisons/") :])
        item = bencao_catalog.get_comparison(cid)
        return (200, item) if item else _not_found("未找到本草比较专题")
    if path == "/api/bencao/diagnose":
        return 200, bencao_catalog.diagnose(
            q=_qs_str(qs, "q"),
            grade=_qs_str(qs, "grade"),
            risk_level=_qs_str(qs, "risk_level"),
        )
    if path == "/api/bencao/pages":
        return 200, bencao_catalog.search_pages(
            q=_qs_str(qs, "q"),
            page_role=_qs_str(qs, "page_role"),
            limit=_qs_int(qs, "limit", 40, 1, 160),
        )
    m_bc = re.match(r"^/api/bencao/source-pages/(\d+)$", path)
    if m_bc:
        item = bencao_catalog.get_source_page(int(m_bc.group(1)))
        return (200, item) if item else _not_found("未找到本草经原书页面")
    if path.startswith("/api/bencao/entries/"):
        eid = unquote(path[len("/api/bencao/entries/") :])
        item = bencao_catalog.get_entry(eid)
        return (200, item) if item else _not_found("未找到神农本草经条目")

    # Library
    if path == "/api/library/overview":
        return 200, library_catalog.overview()
    if path == "/api/library/books":
        return 200, library_catalog.list_books(shelf=_qs_str(qs, "shelf"), q=_qs_str(qs, "q"))
    m_lp = re.match(r"^/api/library/books/([^/]+)/pages/(\d+)$", path)
    if m_lp:
        item = library_catalog.get_book_page(unquote(m_lp.group(1)), int(m_lp.group(2)))
        return (200, item) if item else _not_found("未找到指定书页或章节")
    if path == "/api/library/locate":
        item = library_catalog.locate_book_context(
            book_id=_qs_str(qs, "book_id"),
            page_no=_qs_int(qs, "page_no", 0, 0, 999999),
            line=_qs_int(qs, "line", 0, 0, 999999),
            q=_qs_str(qs, "q"),
            book_hint=_qs_str(qs, "book_hint"),
            before=_qs_int(qs, "before", 2, 0, 6),
            after=_qs_int(qs, "after", 4, 0, 8),
        )
        return (200, item) if item else _not_found("未能在书库中定位对应原书页码")
    m_lctx = re.match(r"^/api/library/books/([^/]+)/context$", path)
    if m_lctx:
        item = library_catalog.get_book_context(
            unquote(m_lctx.group(1)),
            page_no=_qs_int(qs, "page_no", 1, 1, 999999),
            before=_qs_int(qs, "before", 2, 0, 6),
            after=_qs_int(qs, "after", 4, 0, 8),
        )
        return (200, item) if item else _not_found("未找到指定书籍或上下文页面")
    m_lps = re.match(r"^/api/library/books/([^/]+)/pages$", path)
    if m_lps:
        item = library_catalog.list_book_pages(
            unquote(m_lps.group(1)),
            q=_qs_str(qs, "q"),
            offset=_qs_int(qs, "offset", 0, 0, 999999),
            limit=_qs_int(qs, "limit", 60, 1, 200),
        )
        return (200, item) if item else _not_found("未找到指定书籍")
    if path.startswith("/api/library/books/"):
        bid = unquote(path[len("/api/library/books/") :])
        item = library_catalog.get_book(bid)
        return (200, item) if item else _not_found("未找到指定书籍")
    if path == "/api/library/search":
        return 200, library_catalog.search(
            q=_qs_str(qs, "q"),
            shelf=_qs_str(qs, "shelf"),
            book_id=_qs_str(qs, "book_id"),
            limit=_qs_int(qs, "limit", 36, 1, 100),
        )
    if path.startswith("/api/library/entity-links/"):
        eid = unquote(path[len("/api/library/entity-links/") :])
        return 200, library_catalog.get_entity_links(eid)

    # Stage 5
    if path == "/api/stage5/overview":
        return 200, stage5_service.overview()
    if path == "/api/stage5/syndromes":
        return 200, stage5_service.list_syndromes(q=_qs_str(qs, "q"))
    if path.startswith("/api/stage5/syndromes/"):
        sid = unquote(path[len("/api/stage5/syndromes/") :])
        item = stage5_service.get_syndrome(sid)
        return (200, item) if item else _not_found("未找到跨书辨证证候群")
    if path == "/api/stage5/diagnose":
        return 200, stage5_service.diagnose_unified(q=_qs_str(qs, "q"))
    if path == "/api/stage5/compose":
        return 200, syndrome_composer.compose_differentiation(q=_qs_str(qs, "q"), pulse=_qs_str(qs, "pulse"))
    if path == "/api/stage5/ground":
        return 200, grounded_study.ground_study_query(
            q=_qs_str(qs, "q"),
            limit_citations=_qs_int(qs, "limit", 12, 1, 24),
        )

    # Hantang Formulas & Clinical System
    if path == "/api/hantang/overview":
        return 200, hantang_catalog.overview()
    if path == "/api/hantang/formulas":
        return 200, hantang_catalog.list_formulas(
            category=_qs_str(qs, "category"),
            safety=_qs_str(qs, "safety"),
            q=_qs_str(qs, "q"),
        )
    m = re.match(r"^/api/hantang/formulas/(.+)$", path)
    if m:
        item = hantang_catalog.get_formula(unquote(m.group(1)))
        return (200, item) if item else _not_found("未找到汉唐方剂")
    if path == "/api/hantang/match":
        return 200, hantang_catalog.match_clinical_context(
            q=_qs_str(qs, "q"),
            limit=_qs_int(qs, "limit", 4, 1, 8),
        )

    return _not_found(f"未知接口路径: {path}")


def dispatch_post_ai(path: str, payload: dict[str, Any]) -> tuple[int, Any]:
    """Handle /api/ai/* compute endpoints in pure-Python Pyodide static runtime."""
    api_idx = path.find("/api/")
    if api_idx > 0:
        path = path[api_idx:]

    if path == "/api/ai/presets-and-styles":
        return 200, {
            "presets": list(config_store.PROVIDER_PRESETS.values()),
            "styles": ni_persona.list_persona_styles(),
            "defaults": config_store._default_config(),
            "reasoning_tiers": config_store.REASONING_TIER_LIST,
            "reasoning_rules": config_store.REASONING_MODEL_RULES,
        }

    if path == "/api/ai/packet":
        pkt = ni_consult.build_clinical_context(
            str(payload.get("query") or ""),
            pulse=str(payload.get("pulse") or ""),
            tongue=str(payload.get("tongue") or ""),
            entity_focus=payload.get("entity_focus") if isinstance(payload.get("entity_focus"), dict) else None,
            sqlite_conn=None,
        )
        return 200, pkt

    if path == "/api/ai/prepare-prompt":
        style = str(payload.get("style") or "master_balanced")
        pkt, sys_prompt, messages = ni_consult.prepare_llm_request(
            str(payload.get("query") or ""),
            pulse=str(payload.get("pulse") or ""),
            tongue=str(payload.get("tongue") or ""),
            style=style,
            history=payload.get("history") if isinstance(payload.get("history"), list) else None,
            entity_focus=payload.get("entity_focus") if isinstance(payload.get("entity_focus"), dict) else None,
            images=payload.get("images") if isinstance(payload.get("images"), list) else None,
            sqlite_conn=None,
        )
        return 200, {
            "packet": pkt,
            "system_prompt": sys_prompt,
            "messages": messages,
            "offline_reply": ni_consult.build_offline_ni_reply(pkt, style=style),
        }

    if path == "/api/ai/vision-prepare":
        imgs = ni_persona.normalize_image_inputs(payload.get("images") if isinstance(payload.get("images"), list) else None)
        if not imgs:
            return 400, {"detail": "请先选择或粘贴至少 1 张有效的 JPG / PNG / WebP 图片（单张 ≤ 4MB）。"}
        sys_prompt, user_text = ni_persona.build_vision_intake_prompt(str(payload.get("hint") or ""))
        return 200, {"system_prompt": sys_prompt, "user_text": user_text, "images": imgs}

    if path == "/api/ai/vision-parse":
        parsed = ni_persona.parse_vision_intake_response(
            str(payload.get("text") or ""),
            image_count=int(payload.get("image_count") or 1),
        )
        return 200, parsed

    if path == "/api/ai/chat":
        style = str(payload.get("style") or "master_balanced")
        pkt = ni_consult.build_clinical_context(
            str(payload.get("query") or ""),
            pulse=str(payload.get("pulse") or ""),
            tongue=str(payload.get("tongue") or ""),
            entity_focus=payload.get("entity_focus") if isinstance(payload.get("entity_focus"), dict) else None,
            sqlite_conn=None,
        )
        reply = ni_consult.build_offline_ni_reply(pkt, style=style)
        return 200, {
            "mode": "offline",
            "reply": reply,
            "cited": ni_consult.extract_cited_refs(reply, pkt.get("citations") or []),
            "packet": pkt,
        }

    if path == "/api/ai/extract-refs":
        return 200, ni_consult.extract_cited_refs(
            str(payload.get("text") or ""),
            payload.get("citations") if isinstance(payload.get("citations"), list) else [],
        )

    return _not_found(f"未知静态 POST 接口: {path}")


def dispatch_json(url: str) -> str:
    """Serialize status + body as a single JSON envelope for Pyodide bridge."""
    status, body = dispatch_api(url)
    return json.dumps({"status": status, "body": body}, ensure_ascii=False)


def dispatch_request(url: str, method: str = "GET", body_json: str = "") -> str:
    """Unified GET/POST dispatcher for static Pyodide web worker."""
    m = (method or "GET").upper()
    if m == "GET":
        return dispatch_json(url)
    try:
        payload = json.loads(body_json) if body_json else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        return json.dumps({"status": 400, "body": {"detail": "JSON 请求体无效"}}, ensure_ascii=False)
    status, body = dispatch_post_ai(urlsplit(url).path, payload)
    return json.dumps({"status": status, "body": body}, ensure_ascii=False)
