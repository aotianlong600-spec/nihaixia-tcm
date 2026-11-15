"""Backend read-only catalog for Stage 3 Huangdi Neijing theories, chapters, and source pages."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data" / "neijing"
PAGES_PATH = ROOT / "sources" / "neijing" / "pages.jsonl"
IMAGE_CACHE_DIR = ROOT / ".tmp" / "neijing_pages"

SOURCE_PDFS = {
    "ni-neijing-vol1-pdf": ROOT / "books" / "ni-haixia-medicine" / "【视频同步文稿】倪海厦人纪系列书籍之《皇帝内经上册》 .pdf",
    "ni-neijing-vol2-pdf": ROOT / "books" / "ni-haixia-medicine" / "【视频同步文稿】倪海厦人纪系列书籍之《黄帝内经下册》.pdf",
}

SUBMODULE_META = [
    {
        "id": "yin_yang_wu_xing",
        "label": "阴阳五行",
        "subtitle": "阴阳离合·生克制化·寒热转化",
    },
    {
        "id": "zang_xiang",
        "label": "藏象理论",
        "subtitle": "十二官·奇恒之腑·精气神血津液",
    },
    {
        "id": "bing_yin_bing_ji",
        "label": "病因病机",
        "subtitle": "四时伏邪·热论六经·欬痛痹痿",
    },
    {
        "id": "zhen_fa",
        "label": "诊法理论",
        "subtitle": "平旦诊脉·胃气真脏·色脉尺肤",
    },
    {
        "id": "bian_zheng",
        "label": "辨证原则",
        "subtitle": "阴阳寒热虚实·标本先后急缓",
    },
    {
        "id": "yang_sheng",
        "label": "养生理论",
        "subtitle": "上古天真·四气调神·起居五味",
    },
]

SUBMODULE_LABELS = {m["id"]: m["label"] for m in SUBMODULE_META}


def _norm(value: str) -> str:
    return re.sub(r"[\s·・，,。；;：:（）()“”\"'、]+", "", value or "").lower()


@lru_cache(maxsize=1)
def _load_json(filename: str) -> dict:
    return json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _pages_list() -> list[dict]:
    rows: list[dict] = []
    with PAGES_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@lru_cache(maxsize=1)
def _pages_by_id() -> dict[str, dict]:
    return {row["page_id"]: row for row in _pages_list()}


@lru_cache(maxsize=1)
def _pages_by_vol_pdf() -> dict[tuple[str, int], dict]:
    return {(row["source_id"], int(row["pdf_page"])): row for row in _pages_list()}


@lru_cache(maxsize=1)
def _passages_by_chapter() -> dict[str, dict]:
    return {
        item["chapter_id"]: item
        for item in _load_json("passages.json").get("items", [])
        if item.get("chapter_id")
    }


@lru_cache(maxsize=1)
def _entities_by_id() -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for fname in ("passages.json", "concepts.json"):
        for item in _load_json(fname).get("items", []):
            mapping[item["id"]] = item
    return mapping


@lru_cache(maxsize=1)
def _external_entities_index() -> dict[str, tuple[str, str]]:
    """Map external sibling IDs -> (module_key, human_title)."""
    idx: dict[str, tuple[str, str]] = {}
    acu_dir = ROOT / "brain_data" / "acupuncture"
    for fname in ("meridians.json", "acupoints.json", "techniques.json", "conditions.json"):
        p = acu_dir / fname
        if p.is_file():
            for item in json.loads(p.read_text(encoding="utf-8")).get("items", []):
                idx[item["id"]] = ("acupuncture", item.get("canonical_name", item["id"]))
    six_p = ROOT / "brain_data" / "six_channels.json"
    if six_p.is_file():
        for item in json.loads(six_p.read_text(encoding="utf-8")).get("items", []):
            idx[item["id"]] = ("six_channels", item.get("name") or item.get("canonical_name") or item["id"])
    for mod, fname in (
        ("formulas", "formulas.json"),
        ("jinkui_formulas", "jinkui_formulas.json"),
        ("herbs", "herbs.json"),
    ):
        p = ROOT / "brain_data" / fname
        if p.is_file():
            for item in json.loads(p.read_text(encoding="utf-8")):
                idx[item["id"]] = (mod, item.get("name", item["id"]))
    return idx


def _peer_summary(peer_id: str, peer_module: str | None = None) -> dict:
    internal = _entities_by_id().get(peer_id)
    if internal:
        return {
            "id": internal["id"],
            "module": "neijing",
            "record_type": internal.get("record_type", ""),
            "canonical_name": internal.get("canonical_name", peer_id),
            "chapter_id": internal.get("chapter_id"),
            "submodule": internal.get("submodule"),
            "review_status": internal.get("review_status", "pending"),
            "risk_level": internal.get("risk_level", "standard"),
        }
    ext_mod, ext_name = _external_entities_index().get(peer_id, (peer_module or "", peer_id))
    return {
        "id": peer_id,
        "module": ext_mod,
        "record_type": ext_mod,
        "canonical_name": ext_name,
        "review_status": "verified",
        "risk_level": "standard",
    }


def _relations_for(entity_id: str) -> list[dict]:
    rels = _load_json("relations.json").get("items", [])
    resolved: list[dict] = []
    for rel in rels:
        if rel["from_id"] != entity_id and rel["to_id"] != entity_id:
            continue
        direction = "outgoing" if rel["from_id"] == entity_id else "incoming"
        peer_id = rel["to_id"] if direction == "outgoing" else rel["from_id"]
        peer_mod = rel.get("to_module") if direction == "outgoing" else "neijing"
        resolved.append(
            {
                "id": rel["id"],
                "relation_type": rel["relation_type"],
                "direction": direction,
                "label": rel.get("label", ""),
                "rationale": rel.get("rationale", ""),
                "peer": _peer_summary(peer_id, peer_mod),
                "source_spans": rel.get("source_spans", []),
                "review_status": rel.get("review_status", "pending"),
                "evidence_status": rel.get("evidence_status", "anchored"),
            }
        )
    return resolved


def overview() -> dict:
    chapters_data = _load_json("chapters.json")
    passages_data = _load_json("passages.json")
    concepts_data = _load_json("concepts.json")
    relations_data = _load_json("relations.json")

    by_sub = concepts_data.get("stats", {}).get("by_submodule", {})
    submodules = [
        {
            **meta,
            "count": by_sub.get(meta["id"], 0),
        }
        for meta in SUBMODULE_META
    ]

    return {
        "schema_version": chapters_data.get("schema_version", "1.0.0"),
        "collection_title": chapters_data.get("collection_title", ""),
        "sources": chapters_data.get("sources", []),
        "edition_inventory": chapters_data.get("edition_inventory", {}),
        "stats": {
            "total_chapters": chapters_data["stats"]["total_chapters"],
            "approved_chapters": passages_data["stats"]["approved"],
            "pending_chapters": passages_data["stats"]["pending"],
            "total_sections": chapters_data["stats"]["total_sections"],
            "approved_sections": chapters_data["stats"]["approved_sections"],
            "total_concepts": concepts_data["stats"]["total"],
            "approved_concepts": concepts_data["stats"]["approved"],
            "total_relations": relations_data["stats"]["total"],
            "by_submodule": by_sub,
            "by_target_module": relations_data["stats"].get("by_target_module", {}),
        },
        "submodules": submodules,
        "scope_note": (
            "本馆藏上下册合计 306 PDF页 / 301 印制页，实仅收录《黄帝内经·素问》讲记 72 篇"
            "（74 条篇目、283 节），缺《素问》第 51、66–71、73、74 篇，且未收录《灵枢》。"
            "当前已完成 24 篇核心基石与临床辨证支柱精校，并建立 6 大理论与辨证专题子模块（17 条）；"
            "其余 50 篇保持目录与原书页码诚实锚定（pending），不作AI虚构补全。"
        ),
    }


def list_chapters(
    q: str = "",
    volume: str = "",
    review_status: str = "",
    risk_level: str = "",
) -> dict:
    chapters_data = _load_json("chapters.json")
    passages_by_ch = _passages_by_chapter()
    qn = _norm(q)

    items: list[dict] = []
    for ch in chapters_data.get("chapters", []):
        if volume and ch.get("volume") != volume:
            continue
        passage = passages_by_ch.get(ch["id"], {})
        r_status = passage.get("review_status", ch.get("review_status", "pending"))
        k_level = passage.get("risk_level", "standard")
        if review_status and r_status != review_status:
            continue
        if risk_level and k_level != risk_level:
            continue
        if qn:
            hay = " ".join(
                [
                    ch.get("title", ""),
                    ch.get("classic_standard_title", ""),
                    ch.get("collation_note", ""),
                    passage.get("summary", ""),
                    " ".join(s.get("title", "") for s in ch.get("sections", [])),
                    json.dumps(passage.get("content_layers", {}), ensure_ascii=False),
                ]
            )
            if qn not in _norm(hay):
                continue
        items.append(
            {
                "id": ch["id"],
                "passage_id": passage.get("id", f"passage:{ch['id']}"),
                "order": ch["order"],
                "suwen_number": ch.get("suwen_number"),
                "title": ch["title"],
                "classic_standard_title": ch.get("classic_standard_title", ""),
                "collation_note": ch.get("collation_note", ""),
                "volume": ch["volume"],
                "volume_label": ch["volume_label"],
                "source_id": ch["source_id"],
                "pdf_page_start": ch["pdf_page_start"],
                "pdf_page_end": ch["pdf_page_end"],
                "printed_page_start": ch["printed_page_start"],
                "printed_page_end": ch["printed_page_end"],
                "total_sections": ch["total_sections"],
                "approved_sections": ch["approved_sections"],
                "review_status": r_status,
                "evidence_status": passage.get("evidence_status", "anchored"),
                "risk_level": k_level,
                "safety_warning": passage.get("safety_warning", ""),
                "summary": passage.get("summary", ""),
                "sections": ch.get("sections", []),
            }
        )
    return {
        "total": len(items),
        "edition_inventory": chapters_data.get("edition_inventory", {}),
        "items": items,
    }


def get_chapter(chapter_id: str) -> dict | None:
    chapters_data = _load_json("chapters.json")
    ch = next((c for c in chapters_data.get("chapters", []) if c["id"] == chapter_id), None)
    if not ch:
        return None
    passage = _passages_by_chapter().get(chapter_id, {})
    concepts = [
        {
            "id": c["id"],
            "submodule": c["submodule"],
            "submodule_label": SUBMODULE_LABELS.get(c["submodule"], c["submodule"]),
            "canonical_name": c["canonical_name"],
            "doctrine_key": c.get("doctrine_key", ""),
            "review_status": c.get("review_status", "pending"),
            "risk_level": c.get("risk_level", "standard"),
        }
        for c in _load_json("concepts.json").get("items", [])
        if chapter_id in c.get("chapter_ids", [])
    ]
    chapters = chapters_data.get("chapters", [])
    idx = next((i for i, c in enumerate(chapters) if c["id"] == chapter_id), -1)
    pages_preview: list[dict] = []
    pages_by_vp = _pages_by_vol_pdf()
    p_start = ch["pdf_page_start"]
    p_end = ch["pdf_page_end"]
    src = ch["source_id"]
    for p in range(p_start, p_end + 1):
        row = pages_by_vp.get((src, p))
        if row:
            pages_preview.append(
                {
                    "page_id": row["page_id"],
                    "source_id": row["source_id"],
                    "pdf_page": row["pdf_page"],
                    "printed_page": row.get("printed_page"),
                    "section_headings": row.get("section_headings", []),
                    "quoted_classic_fragments": row.get("quoted_classic_fragments", []),
                    "excerpt": (row.get("body_text") or "").strip()[:360],
                    "image_url": f"/api/neijing/source-pages/{row['source_id']}/{row['pdf_page']}/image",
                }
            )
    detail = dict(ch)
    detail["passage"] = passage
    detail["related_concepts"] = concepts
    detail["relations"] = _relations_for(passage.get("id", f"passage:{chapter_id}"))
    detail["pages_preview"] = pages_preview
    detail["prev_chapter"] = (
        {"id": chapters[idx - 1]["id"], "title": chapters[idx - 1]["title"], "order": chapters[idx - 1].get("order")}
        if idx > 0
        else None
    )
    detail["next_chapter"] = (
        {"id": chapters[idx + 1]["id"], "title": chapters[idx + 1]["title"], "order": chapters[idx + 1].get("order")}
        if 0 <= idx < len(chapters) - 1
        else None
    )
    return detail


def list_concepts(
    q: str = "",
    submodule: str = "",
    review_status: str = "",
    risk_level: str = "",
) -> dict:
    items = _load_json("concepts.json").get("items", [])
    qn = _norm(q)
    filtered: list[dict] = []
    for item in items:
        if submodule and item.get("submodule") != submodule:
            continue
        if review_status and item.get("review_status") != review_status:
            continue
        if risk_level and item.get("risk_level") != risk_level:
            continue
        if qn:
            hay = " ".join(
                [
                    item.get("canonical_name", ""),
                    item.get("doctrine_key", ""),
                    item.get("summary", ""),
                    json.dumps(item.get("differentiation_rules", []), ensure_ascii=False),
                    json.dumps(item.get("content_layers", {}), ensure_ascii=False),
                    json.dumps(item.get("classic_links", []), ensure_ascii=False),
                ]
            )
            if qn not in _norm(hay):
                continue
        filtered.append(
            {
                "id": item["id"],
                "submodule": item["submodule"],
                "submodule_label": SUBMODULE_LABELS.get(item["submodule"], item["submodule"]),
                "canonical_name": item["canonical_name"],
                "doctrine_key": item.get("doctrine_key", ""),
                "chapter_ids": item.get("chapter_ids", []),
                "summary": item.get("summary", ""),
                "rule_count": len(item.get("differentiation_rules", [])),
                "link_count": len(item.get("classic_links", [])),
                "review_status": item.get("review_status", "pending"),
                "evidence_status": item.get("evidence_status", "verified"),
                "risk_level": item.get("risk_level", "standard"),
                "safety_warning": item.get("safety_warning", ""),
            }
        )
    return {
        "total": len(filtered),
        "submodules": overview()["submodules"],
        "items": filtered,
    }


def get_concept(concept_id: str) -> dict | None:
    item = _entities_by_id().get(concept_id)
    if not item or item.get("record_type") != "theory":
        return None
    chapters_map = {c["id"]: c for c in _load_json("chapters.json").get("chapters", [])}
    detail = dict(item)
    detail["submodule_label"] = SUBMODULE_LABELS.get(item.get("submodule", ""), item.get("submodule", ""))
    detail["resolved_chapters"] = [
        {
            "id": cid,
            "title": chapters_map[cid]["title"],
            "classic_standard_title": chapters_map[cid]["classic_standard_title"],
            "volume_label": chapters_map[cid]["volume_label"],
            "printed_page_start": chapters_map[cid]["printed_page_start"],
            "printed_page_end": chapters_map[cid]["printed_page_end"],
            "source_id": chapters_map[cid]["source_id"],
            "pdf_page_start": chapters_map[cid]["pdf_page_start"],
        }
        for cid in item.get("chapter_ids", [])
        if cid in chapters_map
    ]
    resolved_links = []
    for lk in item.get("classic_links", []):
        peer = _peer_summary(lk["target_id"], lk.get("target_module"))
        resolved_links.append({**lk, "peer": peer})
    detail["classic_links"] = resolved_links
    detail["relations"] = _relations_for(concept_id)
    return detail


def search_pages(
    q: str = "",
    volume: str = "",
    page_role: str = "",
    limit: int = 60,
) -> dict:
    qn = _norm(q)
    matches: list[dict] = []
    for row in _pages_list():
        if volume and row.get("volume") != volume:
            continue
        if page_role and row.get("page_role") != page_role:
            continue
        body = row.get("body_text") or row.get("raw_text") or ""
        if qn:
            hay = " ".join(
                [
                    body,
                    row.get("header", ""),
                    " ".join(row.get("chapter_headings", [])),
                    " ".join(row.get("section_headings", [])),
                ]
            )
            if qn not in _norm(hay):
                continue
        snippet = ""
        if q.strip():
            lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
            q_clean = q.strip()
            snippet = next((ln for ln in lines if q_clean in ln or _norm(q_clean) in _norm(ln)), "")
        if not snippet:
            snippet = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        matches.append(
            {
                "page_id": row["page_id"],
                "source_id": row["source_id"],
                "volume": row["volume"],
                "volume_label": row["volume_label"],
                "pdf_page": row["pdf_page"],
                "printed_page": row.get("printed_page"),
                "page_role": row.get("page_role"),
                "header": row.get("header", ""),
                "chapter_headings": row.get("chapter_headings", []),
                "section_headings": row.get("section_headings", []),
                "quoted_count": len(row.get("quoted_classic_fragments", [])),
                "snippet": snippet[:160],
                "image_url": f"/api/neijing/source-pages/{row['source_id']}/{row['pdf_page']}/image",
            }
        )
    return {
        "total": len(matches),
        "items": matches[: max(1, min(limit, 120))],
    }


def get_source_page(source_id: str, pdf_page: int) -> dict | None:
    row = _pages_by_vol_pdf().get((source_id, int(pdf_page)))
    if not row:
        return None
    chapters = _load_json("chapters.json").get("chapters", [])
    covering_chapters: list[dict] = []
    for ch in chapters:
        if ch.get("source_id") == source_id and ch["pdf_page_start"] <= pdf_page <= ch["pdf_page_end"]:
            covering_chapters.append(
                {
                    "chapter_id": ch["id"],
                    "title": ch["title"],
                    "classic_standard_title": ch["classic_standard_title"],
                    "review_status": ch.get("review_status", "pending"),
                }
            )
    return {
        **row,
        "covering_chapters": covering_chapters,
        "image_url": f"/api/neijing/source-pages/{source_id}/{pdf_page}/image",
    }


def get_source_page_by_id(page_id: str) -> dict | None:
    row = _pages_by_id().get(page_id)
    if not row:
        return None
    return get_source_page(row["source_id"], int(row["pdf_page"]))


def render_page_image(source_id: str, pdf_page: int) -> Path | None:
    pdf_path = SOURCE_PDFS.get(source_id)
    if not pdf_path or not pdf_path.is_file():
        return None
    max_page = 152 if source_id == "ni-neijing-vol1-pdf" else 154
    if pdf_page < 1 or pdf_page > max_page:
        return None
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    vol_tag = "vol1" if source_id == "ni-neijing-vol1-pdf" else "vol2"
    out_path = IMAGE_CACHE_DIR / f"{vol_tag}_p{pdf_page:03d}.png"
    if not out_path.is_file():
        import pypdfium2 as pdfium  # noqa: PLC0415

        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            page = doc[pdf_page - 1]
            bitmap = page.render(scale=150 / 72)
            pil_image = bitmap.to_pil()
            pil_image.save(out_path, format="PNG")
        finally:
            doc.close()
    return out_path


DIAGNOSE_PROMPT_CHIPS = [
    "消渴 脾瘅",
    "寒厥 热厥 手足冷",
    "胃不和 不得卧 喘",
    "水肿 风水 卧蚕",
    "往来寒热 疟",
    "头痛 脑户 风",
    "腰痛 委中 刺血",
    "真脏脉 绝汗 危候",
]


@lru_cache(maxsize=1)
def _external_relations_index() -> dict[str, list[dict]]:
    entities = _entities_by_id()
    chapters_map = {c["id"]: c for c in _load_json("chapters.json").get("chapters", [])}
    out: dict[str, list[dict]] = {}
    seen: set[tuple[str, str, str]] = set()

    def _add(target_id: str, src: dict, relation_type: str, label: str, rationale: str, review_status: str) -> None:
        src_id = src["id"]
        sig = (target_id, src_id, relation_type)
        if sig in seen:
            return
        seen.add(sig)
        rec_type = src.get("record_type", "")
        is_concept = rec_type == "theory"
        ch_id = (src.get("chapter_ids") or [""])[0] if is_concept else src.get("chapter_id", "")
        ch_meta = chapters_map.get(ch_id, {})
        sub = src.get("submodule", "")
        out.setdefault(target_id, []).append(
            {
                "source_id": src_id,
                "target_kind": "concept" if is_concept else "chapter",
                "target_nav_id": src_id if is_concept else ch_id,
                "canonical_name": src.get("canonical_name", ch_meta.get("title", src_id)),
                "chapter_id": ch_id,
                "chapter_title": ch_meta.get("title", ""),
                "submodule": sub,
                "submodule_label": SUBMODULE_LABELS.get(sub, sub),
                "relation_type": relation_type,
                "label": label,
                "rationale": rationale,
                "review_status": review_status,
                "risk_level": src.get("risk_level", "standard"),
            }
        )

    for rel in _load_json("relations.json").get("items", []):
        to_mod = rel.get("to_module", "neijing")
        if to_mod == "neijing":
            continue
        src = entities.get(rel.get("from_id", ""))
        if not src:
            continue
        _add(
            rel["to_id"],
            src,
            rel.get("relation_type", "theoretical_origin"),
            rel.get("label", ""),
            rel.get("rationale", ""),
            rel.get("review_status", "pending"),
        )

    for concept in _load_json("concepts.json").get("items", []):
        for lk in concept.get("classic_links", []):
            tid = lk.get("target_id", "")
            if not tid or lk.get("target_module") == "neijing":
                continue
            _add(
                tid,
                concept,
                lk.get("relation_type", "theoretical_origin"),
                lk.get("target_label", lk.get("relation_type", "")),
                lk.get("rationale", ""),
                concept.get("review_status", "pending"),
            )

    return out


def relations_for_external(target_id: str) -> list[dict]:
    return [dict(item) for item in _external_relations_index().get(target_id, [])]


def _tokenize_diagnose_query(q: str) -> list[str]:
    raw_parts = [p.strip() for p in re.split(r"[\s,，、；;：:。]+", q or "") if p.strip()]
    tokens: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        n = _norm(part)
        if n and n not in seen:
            seen.add(n)
            tokens.append(n)
    if len(tokens) == 1 and len(tokens[0]) >= 4:
        base = tokens[0]
        for i in range(0, len(base) - 1):
            bg = base[i : i + 2]
            if bg not in seen:
                seen.add(bg)
                tokens.append(bg)
    return tokens


def _count_token_hits(text: str, tokens: list[str]) -> int:
    ntext = _norm(text)
    if not ntext or not tokens:
        return 0
    return sum(1 for tok in tokens if tok in ntext)


def diagnose(
    q: str = "",
    submodule: str = "",
    risk_level: str = "",
    limit_concepts: int = 8,
    limit_chapters: int = 6,
) -> dict:
    raw_q = (q or "").strip()
    tokens = _tokenize_diagnose_query(raw_q)
    primary_tokens = [p for p in (_norm(x) for x in re.split(r"[\s,，、；;：:。]+", raw_q) if x.strip()) if p]
    concepts = _load_json("concepts.json").get("items", [])
    chapters_data = _load_json("chapters.json").get("chapters", [])
    chapters_map = {c["id"]: c for c in chapters_data}
    passages_by_ch = _passages_by_chapter()

    matched_concepts: list[dict] = []
    for c in concepts:
        if submodule and c.get("submodule") != submodule:
            continue
        if risk_level and c.get("risk_level") != risk_level:
            continue
        if not tokens:
            score = 10 if c.get("review_status") == "approved" else 1
            scored_rules = list(c.get("differentiation_rules", []))[:4]
        else:
            score = 0
            score += 14 * _count_token_hits(c.get("canonical_name", ""), tokens)
            score += 10 * _count_token_hits(" ".join(c.get("aliases", [])), tokens)
            score += 7 * _count_token_hits(c.get("summary", ""), tokens)
            score += 7 * _count_token_hits(c.get("clinical_relevance", ""), tokens)
            score += 6 * _count_token_hits(c.get("classic_text", ""), tokens)
            score += 6 * _count_token_hits(c.get("ni_interpretation", ""), tokens)
            scored_rules: list[tuple[int, dict]] = []
            for r in c.get("differentiation_rules", []):
                r_text = " ".join(
                    [
                        r.get("condition", ""),
                        r.get("conclusion", ""),
                        r.get("classical_basis", ""),
                        " ".join(r.get("key_signs", [])),
                    ]
                )
                rhits = _count_token_hits(r_text, tokens)
                if rhits > 0:
                    score += 9 * rhits
                scored_rules.append((rhits, r))
            if primary_tokens:
                full_blob = _norm(json.dumps(c, ensure_ascii=False))
                primary_matched = sum(1 for pt in primary_tokens if pt in full_blob)
                if primary_matched == len(primary_tokens):
                    score += 18
                elif primary_matched > 0:
                    score += 6 * primary_matched
            if score <= 0:
                continue
            scored_rules.sort(key=lambda pair: -pair[0])
            scored_rules = [pair[1] for pair in scored_rules[:4]]

        rels = _relations_for(c["id"])
        classic_links = [{**lk, "peer": _peer_summary(lk["target_id"], lk.get("target_module"))} for lk in c.get("classic_links", [])]
        matched_concepts.append(
            {
                "id": c["id"],
                "canonical_name": c["canonical_name"],
                "submodule": c.get("submodule", ""),
                "submodule_label": SUBMODULE_LABELS.get(c.get("submodule", ""), c.get("submodule", "")),
                "doctrine_key": c.get("doctrine_key", ""),
                "summary": c.get("summary", ""),
                "clinical_relevance": c.get("clinical_relevance", ""),
                "classic_text": c.get("classic_text", ""),
                "ni_interpretation": c.get("ni_interpretation", ""),
                "risk_level": c.get("risk_level", "standard"),
                "safety_warning": c.get("safety_warning", ""),
                "historical_boundary_note": c.get("historical_boundary_note", ""),
                "matched_rules": scored_rules,
                "resolved_chapters": [
                    {"id": cid, "title": chapters_map[cid]["title"], "order": chapters_map[cid].get("order")}
                    for cid in c.get("chapter_ids", [])
                    if cid in chapters_map
                ],
                "classic_links": classic_links,
                "relations": rels,
                "_score": score,
            }
        )

    matched_concepts.sort(key=lambda item: (-item["_score"], item["id"]))
    top_concepts = [{k: v for k, v in item.items() if k != "_score"} for item in matched_concepts[:limit_concepts]]

    matched_chapters: list[dict] = []
    for ch in chapters_data:
        cid = ch["id"]
        passage = passages_by_ch.get(cid, {})
        if risk_level and passage.get("risk_level", ch.get("risk_level", "standard")) != risk_level:
            continue
        if not tokens:
            if not ch.get("is_featured") and len(matched_chapters) >= limit_chapters:
                continue
            score = 8 if ch.get("is_featured") else 2
            matched_sections = list(passage.get("section_notes", []))[:2]
        else:
            score = 0
            score += 12 * _count_token_hits(ch.get("title", "") + " " + ch.get("classic_standard_title", ""), tokens)
            score += 8 * _count_token_hits(" ".join(passage.get("core_theories", [])), tokens)
            score += 7 * _count_token_hits(passage.get("organizer_summary", ""), tokens)
            score += 6 * _count_token_hits(passage.get("source_quote", ""), tokens)
            score += 6 * _count_token_hits(passage.get("ni_teaching", ""), tokens)
            sec_scored: list[tuple[int, dict]] = []
            for sec in passage.get("section_notes", []):
                stext = " ".join([sec.get("heading", ""), sec.get("source_quote", ""), sec.get("ni_teaching", ""), sec.get("organizer_summary", "")])
                shits = _count_token_hits(stext, tokens)
                if shits > 0:
                    score += 5 * shits
                sec_scored.append((shits, sec))
            if primary_tokens:
                cblob = _norm(ch.get("title", "") + json.dumps(passage, ensure_ascii=False))
                pm = sum(1 for pt in primary_tokens if pt in cblob)
                if pm == len(primary_tokens):
                    score += 15
                elif pm > 0:
                    score += 5 * pm
            if score <= 0:
                continue
            sec_scored.sort(key=lambda pair: -pair[0])
            matched_sections = [pair[1] for pair in sec_scored if pair[0] > 0][:3] or list(passage.get("section_notes", []))[:2]

        pid = passage.get("id", f"passage:{cid}")
        matched_chapters.append(
            {
                "id": cid,
                "order": ch.get("order"),
                "title": ch.get("title", ""),
                "classic_standard_title": ch.get("classic_standard_title", ""),
                "volume_label": ch.get("volume_label", ""),
                "printed_page_start": ch.get("printed_page_start"),
                "printed_page_end": ch.get("printed_page_end"),
                "summary": passage.get("organizer_summary", ""),
                "core_theories": passage.get("core_theories", [])[:6],
                "risk_level": passage.get("risk_level", "standard"),
                "safety_warning": passage.get("safety_warning", ""),
                "matched_sections": matched_sections,
                "relations": _relations_for(pid),
                "_score": score,
            }
        )

    matched_chapters.sort(key=lambda item: (-item["_score"], item.get("order") or 999))
    top_chapters = [{k: v for k, v in item.items() if k != "_score"} for item in matched_chapters[:limit_chapters]]

    sibling_groups: dict[str, list[dict]] = {
        "formulas": [],
        "jinkui_formulas": [],
        "herbs": [],
        "acupuncture": [],
        "six_channels": [],
    }
    seen_ext: set[tuple[str, str]] = set()

    def _collect_ext(peer: dict, rel_type: str, label: str, rationale: str, from_title: str) -> None:
        mod = peer.get("module", "")
        if mod not in sibling_groups:
            return
        sig = (mod, peer.get("id", ""))
        if sig in seen_ext or not peer.get("id"):
            return
        seen_ext.add(sig)
        sibling_groups[mod].append(
            {
                "id": peer["id"],
                "module": mod,
                "canonical_name": peer.get("canonical_name", peer["id"]),
                "relation_type": rel_type,
                "label": label,
                "rationale": rationale,
                "from_title": from_title,
            }
        )

    for c in top_concepts:
        for lk in c.get("classic_links", []):
            _collect_ext(lk.get("peer", {}), lk.get("relation_type", ""), lk.get("target_label", ""), lk.get("rationale", ""), c["canonical_name"])
        for rel in c.get("relations", []):
            _collect_ext(rel.get("peer", {}), rel.get("relation_type", ""), rel.get("label", ""), rel.get("rationale", ""), c["canonical_name"])
    for ch in top_chapters:
        for rel in ch.get("relations", []):
            _collect_ext(rel.get("peer", {}), rel.get("relation_type", ""), rel.get("label", ""), rel.get("rationale", ""), ch["title"])

    matched_pages = search_pages(q=raw_q, limit=6)["items"] if raw_q else []
    has_high_risk = any(c.get("risk_level") == "high_risk" for c in top_concepts) or any(
        ch.get("risk_level") == "high_risk" for ch in top_chapters
    )
    safety_banner = (
        "命中条文或专题涉及真脏脉、绝汗、厥逆、喘满、呕血或危重症候，属古医籍病机与风险警示学习资料；出现急危症状请立即现代急救就医。"
        if has_high_risk
        else "以下推演严格依据《黄帝内经·素问》已校原文、倪注讲解及跨模块理论渊源映射，仅供中医辨证理论研习参考，不作为个体化处方或医疗诊断。"
    )

    return {
        "query": raw_q,
        "submodule": submodule,
        "risk_level": risk_level,
        "has_high_risk": has_high_risk,
        "safety_banner": safety_banner,
        "historical_boundary_note": "《黄帝内经》阐述传统中医藏象、病机、诊法与辨证纲领，不直接等同现代临床诊断；已严格区分经典原文、倪师讲授与整理归纳。",
        "prompt_chips": DIAGNOSE_PROMPT_CHIPS,
        "matched_concepts_count": len(matched_concepts),
        "matched_chapters_count": len(matched_chapters),
        "concepts": top_concepts,
        "chapters": top_chapters,
        "cross_module_links": sibling_groups,
        "matched_pages": matched_pages,
    }
