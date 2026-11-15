"""Stage 2 《神农本草经》 service layer: 385 layered herb entries, general theory
chapters, 38 differential comparisons, symptom-to-herb reasoning engine, and
verbatim 154-page PDF text + PNG image viewer.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import neijing_catalog

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data" / "bencao"
SOURCES_DIR = ROOT / "sources" / "bencao"
PAGES_PATH = SOURCES_DIR / "pages.jsonl"
SOURCE_PDF_PATH = (
    ROOT / "books" / "ni-haixia-medicine" / "【倪海厦注解版】倪海厦注神农本草经(清晰版).pdf"
)
IMAGE_CACHE_DIR = SOURCES_DIR / "rendered_pages"

DIAGNOSE_PROMPT_CHIPS = [
    "恶寒无汗 喘咳表实",
    "恶风自汗 营卫不和",
    "心中懊憹 失眠烦躁",
    "胸胁苦满 往来寒热",
    "四肢厥逆 脉微欲绝 里寒",
    "呕吐 痰饮 水肿 小便不利",
    "蓄血发狂 经闭 少腹硬痛",
    "便血 黑便 胃虚寒",
]


def _load_json(rel: str) -> dict | list:
    return json.loads((DATA_DIR / rel).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _inventory() -> dict:
    return _load_json("edition_inventory.json")


@lru_cache(maxsize=1)
def _chapters() -> list[dict]:
    return _load_json("chapters.json").get("items", [])


@lru_cache(maxsize=1)
def _entries() -> list[dict]:
    return _load_json("entries.json")


@lru_cache(maxsize=1)
def _entries_by_id() -> dict[str, dict]:
    return {e["id"]: e for e in _entries()}


@lru_cache(maxsize=1)
def _comparisons() -> list[dict]:
    return _load_json("comparisons.json").get("items", [])


@lru_cache(maxsize=1)
def _comparisons_by_id() -> dict[str, dict]:
    return {c["id"]: c for c in _comparisons()}


@lru_cache(maxsize=1)
def _pages() -> list[dict]:
    if not PAGES_PATH.is_file():
        return []
    out = []
    with PAGES_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
    return out


@lru_cache(maxsize=1)
def _pages_by_no() -> dict[int, dict]:
    return {int(p["pdf_page"]): p for p in _pages()}


def _searchable_blob(entry: dict) -> str:
    props = entry.get("properties", {})
    ni = entry.get("ni_haixia_annotations", {})
    proc = entry.get("processing_and_compatibility", {})
    parts = [
        entry.get("name", ""),
        entry.get("short_name", ""),
        " ".join(entry.get("aliases", [])),
        entry.get("grade", ""),
        entry.get("classic_original", {}).get("text", ""),
        props.get("qi_wei_raw", ""),
        props.get("origin", ""),
        " ".join(props.get("meridians", [])),
        entry.get("applications", {}).get("main_summary", ""),
        " ".join(entry.get("applications", {}).get("symptom_keywords", [])),
        " ".join(ni.get("explicit_ni_notes", [])),
        ni.get("chapter3_pithy_summary", ""),
        ni.get("why_it_works", ""),
        ni.get("when_to_use", ""),
        ni.get("differentiation_notes", ""),
        " ".join(ni.get("clinical_experience", [])),
        " ".join(ni.get("unlabeled_clinical_excerpts", [])),
        proc.get("processing", ""),
        proc.get("processing_differences", ""),
        proc.get("contraindications", ""),
        " ".join(c.get("text", "") for c in entry.get("historical_commentaries", [])),
        " ".join(fu.get("formula_name", "") + " " + fu.get("ingredient_raw_name", "") for fu in entry.get("formula_usages", [])),
    ]
    return "\n".join(p for p in parts if p)


def _entry_summary_card(entry: dict) -> dict:
    props = entry.get("properties", {})
    ni = entry.get("ni_haixia_annotations", {})
    classic = entry.get("classic_original", {})
    return {
        "id": entry["id"],
        "name": entry["name"],
        "short_name": entry.get("short_name", entry["name"]),
        "aliases": entry.get("aliases", []),
        "kind": entry["kind"],
        "grade": entry["grade"],
        "chapter_id": entry["chapter_id"],
        "seq_num": entry["seq_num"],
        "seq_raw": entry["seq_raw"],
        "in_shennong_classic": entry.get("in_shennong_classic", True),
        "newly_recovered_in_stage2": entry.get("newly_recovered_in_stage2", False),
        "page_start": entry["page_start"],
        "page_end": entry["page_end"],
        "qi_wei_raw": props.get("qi_wei_raw", ""),
        "four_natures": props.get("four_natures", []),
        "five_flavors": props.get("five_flavors", []),
        "toxicity": props.get("toxicity", ""),
        "meridians": props.get("meridians", []),
        "risk_level": props.get("risk_level", "standard"),
        "main_summary": entry.get("applications", {}).get("main_summary", ""),
        "classic_excerpt": (classic.get("text", "")[:90] + ("…" if len(classic.get("text", "")) > 90 else "")),
        "has_ni_note": bool(
            ni.get("explicit_ni_notes")
            or ni.get("why_it_works")
            or ni.get("chapter3_pithy_summary")
            or ni.get("unlabeled_clinical_excerpts")
        ),
        "formula_count": len(entry.get("formula_usages", [])),
        "comparison_count": len(entry.get("comparisons", [])),
        "controversy_count": len(entry.get("identity_controversies", [])),
        "open_questions_count": len(entry.get("open_questions", [])),
        "review_status": entry.get("review_status", "parsed_reviewed"),
    }


def overview() -> dict:
    inv = _inventory()
    entries = _entries()
    return {
        "edition_title": inv["edition_title"],
        "source_id": inv["source_id"],
        "total_pdf_pages": inv["total_pdf_pages"],
        "blank_pdf_pages": inv["blank_pdf_pages"],
        "classic_prologue_claimed_count": inv["classic_prologue_claimed_count"],
        "edition_counts": inv["edition_counts"],
        "legacy_snapshot_comparison": inv["legacy_snapshot_comparison"],
        "honesty_note": inv["honesty_note"],
        "edition_total": len(entries),
        "main_classic_total": sum(1 for e in entries if e["kind"] == "main"),
        "chapter3_supplement_count": sum(1 for e in entries if e["kind"] == "ch3"),
        "newly_recovered_count": sum(1 for e in entries if e.get("newly_recovered_in_stage2")),
        "curated_deep_count": sum(1 for e in entries if e.get("review_status") == "approved"),
        "classic_only_count": sum(1 for e in entries if e.get("open_questions")),
        "entries_with_formulas": sum(1 for e in entries if e.get("formula_usages")),
        "emergency_or_high_risk_count": sum(
            1 for e in entries if e.get("properties", {}).get("risk_level") in ("high_risk", "emergency")
        ),
        "identity_controversies_count": sum(1 for e in entries if e.get("identity_controversies")),
        "comparisons_count": len(_comparisons()),
        "chapters": [
            {
                "id": ch["id"],
                "order": ch["order"],
                "title": ch["title"],
                "grade": ch.get("grade", ""),
                "pdf_pages": ch.get("pdf_pages", []),
                "entry_count": ch.get("entry_count", 0),
                "rules_count": len(ch.get("rules", [])),
                "summary": ch.get("summary", ""),
            }
            for ch in _chapters()
        ],
        "prompt_chips": DIAGNOSE_PROMPT_CHIPS,
    }


def list_chapters() -> dict:
    return {
        "items": overview()["chapters"],
        "total": len(_chapters()),
    }


def get_chapter(chapter_id: str) -> dict | None:
    ch = next((c for c in _chapters() if c["id"] == chapter_id), None)
    if not ch:
        return None
    out = dict(ch)
    if ch.get("grade") or ch["id"] in ("juan1-upper", "juan2-middle", "juan3-lower", "ch3-supplement"):
        ch_entries = [_entry_summary_card(e) for e in _entries() if e["chapter_id"] == chapter_id]
        out["entries"] = ch_entries
        out["entry_count"] = len(ch_entries)
    else:
        out["entries"] = []
    return out


def list_entries(
    q: str = "",
    grade: str = "",
    nature: str = "",
    flavor: str = "",
    toxicity: str = "",
    risk_level: str = "",
    review_status: str = "",
    has_formulas: bool = False,
    recovered_only: bool = False,
    meridian: str = "",
    page: int = 1,
    page_size: int = 24,
) -> dict:
    entries = _entries()
    q_clean = (q or "").strip()

    filtered: list[tuple[int, dict]] = []
    for e in entries:
        props = e.get("properties", {})
        if grade and e.get("grade") != grade:
            continue
        if nature and nature not in props.get("four_natures", []):
            continue
        if flavor and flavor not in props.get("five_flavors", []):
            continue
        if toxicity and toxicity != props.get("toxicity", ""):
            continue
        if risk_level and risk_level != props.get("risk_level", "standard"):
            continue
        if review_status and review_status != e.get("review_status", ""):
            continue
        if has_formulas and not e.get("formula_usages"):
            continue
        if recovered_only and not e.get("newly_recovered_in_stage2"):
            continue
        if meridian and meridian not in props.get("meridians", []):
            continue

        score = 0
        if q_clean:
            blob = _searchable_blob(e)
            if q_clean not in blob:
                continue
            if q_clean == e["name"] or q_clean == e.get("short_name"):
                score = 100
            elif q_clean in e.get("aliases", []):
                score = 80
            elif q_clean in e["name"]:
                score = 60
            elif q_clean in e.get("applications", {}).get("main_summary", ""):
                score = 40
            else:
                score = 20
        filtered.append((score, e))

    if q_clean:
        filtered.sort(key=lambda pair: (-pair[0], -len(pair[1].get("formula_usages", [])), pair[1]["page_start"]))

    total = len(filtered)
    start = (page - 1) * page_size
    page_items = [_entry_summary_card(pair[1]) for pair in filtered[start : start + page_size]]

    grade_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for _, item in filtered:
        g = item.get("grade", "")
        grade_counts[g] = grade_counts.get(g, 0) + 1
        r = item.get("properties", {}).get("risk_level", "standard")
        risk_counts[r] = risk_counts.get(r, 0) + 1

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": page_items,
        "facets": {
            "grades": grade_counts,
            "risk_levels": risk_counts,
        },
    }


def _enrich_entry_detail(entry: dict) -> dict:
    out = dict(entry)
    eid = entry["id"]
    out["neijing_relations"] = neijing_catalog.relations_for_external(eid)
    comp_map = _comparisons_by_id()
    by_id = _entries_by_id()
    enriched_comps = []
    for stub in entry.get("comparisons", []):
        full = comp_map.get(stub["id"])
        if full:
            enriched_comps.append({
                **full,
                "herbs_meta": [
                    {
                        "id": hid,
                        "name": by_id[hid]["name"],
                        "short_name": by_id[hid].get("short_name", by_id[hid]["name"]),
                        "grade": by_id[hid]["grade"],
                        "risk_level": by_id[hid]["properties"]["risk_level"],
                    }
                    for hid in full.get("entry_ids", [])
                    if hid in by_id
                ],
            })
    out["comparisons_detailed"] = enriched_comps
    return out


def get_entry(entry_id: str) -> dict | None:
    by_id = _entries_by_id()
    entry = by_id.get(entry_id)
    if not entry and entry_id.startswith("bencao:"):
        bare = entry_id[len("bencao:") :]
        entry = by_id.get(f"bencao:ch3-{bare}") or next(
            (e for e in _entries() if e["name"] == bare or bare in e.get("aliases", [])),
            None,
        )
    if not entry:
        return None
    return _enrich_entry_detail(entry)


def resolve_name_to_entry(name: str) -> dict | None:
    raw = (name or "").strip()
    if not raw:
        return None
    for e in _entries():
        if e["kind"] == "main" and (e["name"] == raw or raw in e.get("aliases", [])):
            return e
    for e in _entries():
        if e["name"] == raw or e["name"].split("（")[0] == raw or raw in e.get("aliases", []):
            return e
    return None


def list_comparisons(q: str = "", category: str = "") -> dict:
    q_clean = (q or "").strip()
    by_id = _entries_by_id()
    items = []
    categories: dict[str, int] = {}
    for comp in _comparisons():
        cat = comp.get("category", "")
        categories[cat] = categories.get(cat, 0) + 1
        if category and cat != category:
            continue
        if q_clean:
            blob = json.dumps(comp, ensure_ascii=False)
            if q_clean not in blob:
                continue
        herbs_meta = [
            {
                "id": hid,
                "name": by_id[hid]["name"],
                "short_name": by_id[hid].get("short_name", by_id[hid]["name"]),
                "grade": by_id[hid]["grade"],
                "risk_level": by_id[hid]["properties"]["risk_level"],
                "formula_count": len(by_id[hid].get("formula_usages", [])),
                "page_start": by_id[hid]["page_start"],
            }
            for hid in comp.get("entry_ids", [])
            if hid in by_id
        ]
        items.append({**comp, "herbs_meta": herbs_meta})
    return {
        "total": len(items),
        "categories": [{"name": k, "count": v} for k, v in categories.items()],
        "items": items,
    }


def get_comparison(comp_id: str) -> dict | None:
    comp = _comparisons_by_id().get(comp_id)
    if not comp:
        return None
    by_id = _entries_by_id()
    return {
        **comp,
        "herbs_meta": [
            {
                "id": hid,
                "name": by_id[hid]["name"],
                "short_name": by_id[hid].get("short_name", by_id[hid]["name"]),
                "grade": by_id[hid]["grade"],
                "risk_level": by_id[hid]["properties"]["risk_level"],
                "qi_wei_raw": by_id[hid]["properties"].get("qi_wei_raw", ""),
                "formula_count": len(by_id[hid].get("formula_usages", [])),
                "page_start": by_id[hid]["page_start"],
            }
            for hid in comp.get("entry_ids", [])
            if hid in by_id
        ],
    }


def _tokenize_query(q: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[\s,，、；;：:。]+", q or "") if p.strip()]
    tokens: list[str] = []
    for p in parts:
        if p and p not in tokens:
            tokens.append(p)
        if len(p) >= 4:
            for i in range(0, len(p) - 1):
                bg = p[i : i + 2]
                if bg not in tokens and bg not in ("不和", "不得"):
                    tokens.append(bg)
    return tokens


def diagnose(q: str = "", grade: str = "", risk_level: str = "") -> dict:
    q_clean = (q or "").strip()
    if not q_clean:
        return {
            "query": "",
            "tokens": [],
            "total": 0,
            "items": [],
            "related_comparisons": [],
            "safety_alerts": [],
            "prompt_chips": DIAGNOSE_PROMPT_CHIPS,
        }
    tokens = _tokenize_query(q_clean)
    scored: list[tuple[int, list[str], dict]] = []

    for e in _entries():
        props = e.get("properties", {})
        if grade and e.get("grade") != grade:
            continue
        if risk_level and props.get("risk_level", "standard") != risk_level:
            continue

        ni = e.get("ni_haixia_annotations", {})
        apps = e.get("applications", {})
        high_signal = "\n".join([
            e.get("name", ""),
            " ".join(e.get("aliases", [])),
            " ".join(apps.get("symptom_keywords", [])),
            apps.get("main_summary", ""),
            ni.get("why_it_works", ""),
            ni.get("when_to_use", ""),
            ni.get("chapter3_pithy_summary", ""),
            " ".join(ni.get("explicit_ni_notes", [])),
        ])
        mid_signal = "\n".join([
            e.get("classic_original", {}).get("text", ""),
            " ".join(c.get("text", "") for c in e.get("historical_commentaries", [])),
            " ".join(fu.get("formula_name", "") + " " + fu.get("six_meridian", "") for fu in e.get("formula_usages", [])),
        ])

        score = 0
        matched: list[str] = []
        for tok in tokens:
            if tok == e["name"] or tok in e.get("aliases", []):
                score += 40
                if tok not in matched:
                    matched.append(tok)
            elif tok in high_signal:
                score += 18 if len(tok) >= 2 else 8
                if tok not in matched:
                    matched.append(tok)
            elif tok in mid_signal:
                score += 7 if len(tok) >= 2 else 3
                if tok not in matched:
                    matched.append(tok)

        if score <= 0:
            continue
        # Slight boost for approved deep entries & herbs proven in Shanghan/Jinkui
        if e.get("review_status") == "approved":
            score += 6
        if e.get("formula_usages"):
            score += min(10, len(e["formula_usages"]) // 3)
        scored.append((score, matched, e))

    scored.sort(key=lambda row: (-row[0], -len(row[2].get("formula_usages", [])), row[2]["seq_num"]))
    top_rows = scored[:15]

    rec_ids = {r[2]["id"] for r in top_rows}
    related_comps = [
        get_comparison(c["id"])
        for c in _comparisons()
        if any(hid in rec_ids for hid in c.get("entry_ids", []))
    ][:6]

    safety_alerts: list[str] = []
    if any(r[2]["properties"]["risk_level"] == "emergency" for r in top_rows):
        safety_alerts.append("推荐结果中包含‘高风险/毒剧/峻攻/重金属’品种，务必严遵《本经》‘若用毒药疗病，先起黍粟，病去即止’与炮制减毒规范，绝不可未经专业辨证擅自单服！")
    if any(r[2]["properties"]["risk_level"] == "high_risk" for r in top_rows):
        safety_alerts.append("部分药味标注有小毒、妊娠禁忌或古今基原争议（如木通/防己/粉锡混名红线），配伍前请核对鉴别对照与禁忌条文。")

    items = []
    for score, matched, e in top_rows:
        ni = e.get("ni_haixia_annotations", {})
        proc = e.get("processing_and_compatibility", {})
        why_reason = (
            ni.get("why_it_works")
            or ("；".join(ni.get("explicit_ni_notes", [])) if ni.get("explicit_ni_notes") else "")
            or e.get("applications", {}).get("main_summary", "")
            or e.get("classic_original", {}).get("text", "")[:140]
        )
        items.append({
            **_entry_summary_card(e),
            "score": score,
            "matched_terms": matched,
            "why_recommended": why_reason,
            "when_to_use": ni.get("when_to_use", ""),
            "contraindication_guard": proc.get("contraindications", ""),
            "risk_reasons": e.get("properties", {}).get("risk_reasons", []),
            "top_formulas": e.get("formula_usages", [])[:5],
        })

    return {
        "query": q_clean,
        "tokens": tokens,
        "total": len(scored),
        "items": items,
        "related_comparisons": [c for c in related_comps if c],
        "safety_alerts": safety_alerts,
        "prompt_chips": DIAGNOSE_PROMPT_CHIPS,
    }


def search_pages(q: str = "", page_role: str = "", limit: int = 40) -> dict:
    q_clean = (q or "").strip()
    pages = _pages()
    items = []
    for p in pages:
        if page_role and p.get("page_role") != page_role:
            continue
        txt = p.get("text", "")
        if q_clean and q_clean not in txt:
            continue
        snippet = ""
        if q_clean:
            idx = txt.find(q_clean)
            lo = max(0, idx - 36)
            hi = min(len(txt), idx + len(q_clean) + 84)
            snippet = ("…" if lo > 0 else "") + txt[lo:hi].replace("\n", " ") + ("…" if hi < len(txt) else "")
        else:
            snippet = txt[:110].replace("\n", " ") + ("…" if len(txt) > 110 else "")
        items.append({
            "pdf_page": p["pdf_page"],
            "printed_page": p.get("printed_page"),
            "page_role": p.get("page_role", "body"),
            "is_blank": not bool(txt.strip()),
            "snippet": snippet,
            "text_sha256": p.get("text_sha256", ""),
        })
    return {
        "total": len(items),
        "items": items[:limit],
    }


def get_source_page(pdf_page: int) -> dict | None:
    pg = _pages_by_no().get(pdf_page)
    if not pg:
        return None
    linked_herbs = [
        {"id": e["id"], "name": e["name"], "grade": e["grade"], "seq_raw": e["seq_raw"]}
        for e in _entries()
        if pdf_page in e.get("pdf_pages", [])
    ]
    return {
        **pg,
        "image_url": f"/api/bencao/source-pages/{pdf_page}/image",
        "linked_herbs": linked_herbs,
    }


def render_page_image(pdf_page: int) -> Path | None:
    if not SOURCE_PDF_PATH.is_file() or pdf_page < 1 or pdf_page > 154:
        return None
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = IMAGE_CACHE_DIR / f"bencao_p{pdf_page:03d}.png"
    if not out_path.is_file():
        import pypdfium2 as pdfium  # noqa: PLC0415

        doc = pdfium.PdfDocument(str(SOURCE_PDF_PATH))
        try:
            page = doc[pdf_page - 1]
            bitmap = page.render(scale=150 / 72)
            pil_image = bitmap.to_pil()
            pil_image.save(out_path, format="PNG")
        finally:
            doc.close()
    return out_path
