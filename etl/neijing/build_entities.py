"""Compile accepted Huangdi Neijing batches + full 74-chapter inventory into entity catalogs."""
from __future__ import annotations

import json
from pathlib import Path

from etl.review_ledger import load_pages_index, sha256_text


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "brain_data" / "neijing"
CHAPTERS_PATH = DATA_DIR / "chapters.json"
MANIFEST_PATH = DATA_DIR / "batch_manifest.json"
BATCHES_DIR = DATA_DIR / "review_batches"
PAGES_PATH = ROOT / "sources" / "neijing" / "pages.jsonl"

SUBMODULE_ORDER = (
    "yin_yang_wu_xing",
    "zang_xiang",
    "bing_yin_bing_ji",
    "zhen_fa",
    "bian_zheng",
    "yang_sheng",
)

CRITICAL_TITLE_KEYWORDS = ("玉机真藏", "平人气象", "大奇论", "通评虚实", "热论", "刺热", "评热病")
HIGH_RISK_TITLE_KEYWORDS = ("疟", "痹", "痿", "痛", "厥", "水肿", "喘", "腹中")


def make_anchor_span(span_id: str, page_row: dict, quote: str, chapter_path: str) -> dict:
    return {
        "span_id": span_id,
        "source_id": page_row["source_id"],
        "page_id": page_row["page_id"],
        "pdf_page": page_row["pdf_page"],
        "printed_page": page_row.get("printed_page"),
        "chapter_path": chapter_path,
        "quote": quote,
        "quote_sha256": sha256_text(quote),
        "role": "collation_notes",
    }


def find_chapter_anchor_quote(page_row: dict, chapter: dict) -> str:
    headings = page_row.get("chapter_headings") or []
    for h in headings:
        if h.strip():
            return h.strip()
    lines = [ln.strip() for ln in page_row.get("body_text", "").splitlines() if ln.strip()]
    title = chapter.get("title", "")
    short_title = title.split()[-1] if title else ""
    for ln in lines:
        if (title and title in ln) or (short_title and short_title in ln):
            return ln
    if lines:
        return lines[0]
    raw_lines = [ln.strip() for ln in page_row.get("raw_text", "").splitlines() if ln.strip()]
    return raw_lines[0] if raw_lines else chapter["title"]


def classify_pending_risk(title: str) -> tuple[str, str]:
    if any(k in title for k in CRITICAL_TITLE_KEYWORDS):
        return (
            "high_risk",
            "【危重病证与历史理论边界】本篇涉及急症、热病传变或真脏脉候等古典论述，属历史医理与教学原典文献，不替代现代急诊评估与临床诊断。",
        )
    if any(k in title for k in HIGH_RISK_TERMS_BY_TITLE(title)):
        return (
            "high_risk",
            "【古典病证教学文献】本篇涉及痹痿、厥逆或水气胀满等传统病机阐释，尚待逐段校对，切勿直接当作现代个人诊疗方案。",
        )
    return "standard", ""


def HIGH_RISK_TERMS_BY_TITLE(title: str) -> tuple[str, ...]:
    return HIGH_RISK_TITLE_KEYWORDS


def load_accepted_batches() -> tuple[list[str], dict]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    accepted_names = manifest.get("accepted", [])
    merged = {
        "passages": {},
        "concepts": {},
    }
    for fname in accepted_names:
        batch = json.loads((BATCHES_DIR / fname).read_text(encoding="utf-8"))
        for key in ("passages", "concepts"):
            for item in batch.get(key, []):
                merged[key][item["id"]] = item
    return accepted_names, merged


def _build_pending_passage(chapter: dict, pages_by_vol_pdf: dict[tuple[str, int], dict]) -> dict:
    cid = chapter["id"]
    p_key = (chapter["source_id"], chapter["pdf_page_start"])
    page_row = pages_by_vol_pdf[p_key]
    quote = find_chapter_anchor_quote(page_row, chapter)
    risk_level, safety_warning = classify_pending_risk(chapter["title"])
    section_titles = [s["title"] for s in chapter.get("sections", [])]

    collation = [
        f"原书分卷：{chapter['volume_label']}（PDF p.{chapter['pdf_page_start']}–{chapter['pdf_page_end']}，原书印制页 p.{chapter['printed_page_start']}–{chapter['printed_page_end']}）。",
        f"目录含 {len(section_titles)} 个讲记子节：" + ("；".join(section_titles[:8]) + ("……" if len(section_titles) > 8 else "") if section_titles else "整篇讲录未再分子节。"),
    ]
    if chapter.get("collation_note"):
        collation.append(chapter["collation_note"])

    return {
        "id": f"passage:{cid}",
        "record_type": "classic_chapter",
        "chapter_id": cid,
        "order": chapter["order"],
        "suwen_number": chapter.get("suwen_number"),
        "canonical_name": chapter["title"],
        "classic_standard_title": chapter["classic_standard_title"],
        "volume": chapter["volume"],
        "volume_label": chapter["volume_label"],
        "source_id": chapter["source_id"],
        "end_source_id": chapter["end_source_id"],
        "pdf_page_range": [chapter["pdf_page_start"], chapter["pdf_page_end"]],
        "printed_page_range": [chapter["printed_page_start"], chapter["printed_page_end"]],
        "summary": f"{chapter['classic_standard_title']}对应原书{chapter['volume_label']}印制第{chapter['printed_page_start']}–{chapter['printed_page_end']}页，已完成全书目录锚定与原书页码映射，待逐段精校经文与倪海厦讲记分层。",
        "key_points": [],
        "section_notes": [
            {
                "section_id": sec["id"],
                "title": sec["title"],
                "pdf_page_range": [sec["pdf_page_start"], sec["pdf_page_end"]],
                "printed_page_range": [sec["printed_page_start"], sec["printed_page_end"]],
                "status": "pending",
            }
            for sec in chapter.get("sections", [])
        ],
        "historical_boundary_note": "本记录仅保留《内经·素问》原书同步讲稿之目录锚点与版次注记，尚未进行经文与倪注人工逐段校核；古典医学理论不等同于现代临床诊疗规范。",
        "source_spans": [make_anchor_span(f"sp:passage:{cid}", page_row, quote, chapter["title"])],
        "content_layers": {
            "source_quote": [],
            "ni_teaching": [],
            "other_annotations": [],
            "collation_notes": collation,
            "organizer_summary": [
                "保留全书实际收录 72 篇《素问》（74 条篇目）真实分母，未因尚未精校而删减篇目，亦不虚构缺收之《素问》9 篇或《灵枢》内容。"
            ],
        },
        "open_questions": [
            f"尚待逐段核对《{chapter['title']}》（印制第{chapter['printed_page_start']}–{chapter['printed_page_end']}页）中之《素问》引文原文、倪海厦讲解观点与转录差异。"
        ],
        "generation_status": "auto",
        "evidence_status": "anchored",
        "review_status": "pending",
        "risk_level": risk_level,
        "safety_warning": safety_warning,
        "version": "1.0.0",
    }


def build_passages(
    chapters_data: dict,
    pages_by_vol_pdf: dict[tuple[str, int], dict],
    accepted_passages: dict[str, dict],
) -> list[dict]:
    by_chapter = {item.get("chapter_id"): item for item in accepted_passages.values() if item.get("chapter_id")}
    items: list[dict] = []
    for ch in chapters_data.get("chapters", []):
        cid = ch["id"]
        if cid in by_chapter:
            merged = dict(by_chapter[cid])
            merged.setdefault("order", ch["order"])
            merged.setdefault("suwen_number", ch.get("suwen_number"))
            merged.setdefault("canonical_name", ch["title"])
            merged.setdefault("classic_standard_title", ch["classic_standard_title"])
            merged.setdefault("volume", ch["volume"])
            merged.setdefault("volume_label", ch["volume_label"])
            merged.setdefault("source_id", ch["source_id"])
            merged.setdefault("end_source_id", ch["end_source_id"])
            merged.setdefault("pdf_page_range", [ch["pdf_page_start"], ch["pdf_page_end"]])
            merged.setdefault("printed_page_range", [ch["printed_page_start"], ch["printed_page_end"]])
            merged.setdefault("section_notes", [])
            items.append(merged)
        else:
            items.append(_build_pending_passage(ch, pages_by_vol_pdf))
    return items


def build_concepts(accepted_concepts: dict[str, dict]) -> list[dict]:
    order_map = {name: idx for idx, name in enumerate(SUBMODULE_ORDER)}
    return sorted(
        accepted_concepts.values(),
        key=lambda c: (order_map.get(c.get("submodule", ""), 99), c.get("id", "")),
    )


def write_compiled(name: str, items: list[dict], batch_names: list[str], extra_stats: dict | None = None) -> None:
    stats = {
        "total": len(items),
        "approved": sum(1 for x in items if x.get("review_status") == "approved"),
        "pending": sum(1 for x in items if x.get("review_status") == "pending"),
        "high_risk_or_emergency": sum(1 for x in items if x.get("risk_level") in {"high_risk", "emergency"}),
    }
    if extra_stats:
        stats.update(extra_stats)
    payload = {
        "schema_version": "1.0.0",
        "sources": ["ni-neijing-vol1-pdf", "ni-neijing-vol2-pdf"],
        "accepted_batches": batch_names,
        "stats": stats,
        "items": items,
    }
    (DATA_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sync_chapters_status(chapters_data: dict, passages: list[dict]) -> None:
    approved_ch_ids = {p["chapter_id"] for p in passages if p.get("review_status") == "approved"}
    approved_chapters = 0
    approved_sections = 0
    for ch in chapters_data.get("chapters", []):
        is_app = ch["id"] in approved_ch_ids
        ch["review_status"] = "approved" if is_app else "pending"
        sec_approved = 0
        for sec in ch.get("sections", []):
            sec["review_status"] = "approved" if is_app else "pending"
            if is_app:
                sec_approved += 1
        ch["approved_sections"] = sec_approved
        if is_app:
            approved_chapters += 1
        approved_sections += sec_approved

    chapters_data.setdefault("stats", {})["approved_chapters"] = approved_chapters
    chapters_data.setdefault("stats", {})["approved_sections"] = approved_sections
    CHAPTERS_PATH.write_text(
        json.dumps(chapters_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    chapters_data = json.loads(CHAPTERS_PATH.read_text(encoding="utf-8"))
    pages_by_id = load_pages_index(PAGES_PATH)
    pages_by_vol_pdf = {(row["source_id"], row["pdf_page"]): row for row in pages_by_id.values()}
    batch_names, accepted = load_accepted_batches()

    passages = build_passages(chapters_data, pages_by_vol_pdf, accepted["passages"])
    concepts = build_concepts(accepted["concepts"])
    sync_chapters_status(chapters_data, passages)

    by_submodule: dict[str, int] = {}
    for c in concepts:
        sm = c.get("submodule", "unknown")
        by_submodule[sm] = by_submodule.get(sm, 0) + 1

    write_compiled("passages.json", passages, batch_names)
    write_compiled("concepts.json", concepts, batch_names, extra_stats={"by_submodule": by_submodule})

    print(
        json.dumps(
            {
                "passages": {
                    "total": len(passages),
                    "approved": sum(1 for p in passages if p.get("review_status") == "approved"),
                    "pending": sum(1 for p in passages if p.get("review_status") == "pending"),
                },
                "concepts": {
                    "total": len(concepts),
                    "approved": sum(1 for c in concepts if c.get("review_status") == "approved"),
                    "by_submodule": by_submodule,
                },
                "chapters_approved": chapters_data["stats"]["approved_chapters"],
                "chapters_approved_sections": chapters_data["stats"]["approved_sections"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
