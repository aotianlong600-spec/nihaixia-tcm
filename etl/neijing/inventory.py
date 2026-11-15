"""Reconcile the Vol.1 8-page master TOC against Vol.1 + Vol.2 body headings.

Builds ``data/neijing/chapters.json`` containing:
- Exact edition metadata (守候诚实国学书店 2014 排印本，301 印刷页 / 306 PDF 页)
- Honest Suwen/Lingshu coverage accounting (73 Suwen TOC entries + 前言; Lingshu absent; missing ch.51, 66-71, 73-74; appended ch.72 & p.289 mislabeled ch.75)
- All 74 chapters mapped to exact volume, source_id, pdf_page ranges, printed_page ranges, and all 283 sections.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PAGES_PATH = ROOT / "sources" / "neijing" / "pages.jsonl"
OUTPUT_PATH = ROOT / "brain_data" / "neijing" / "chapters.json"

CHINESE_NUMS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# Standard canonical Suwen chapter names where the video-sync transcript differs in wording/typos
CLASSIC_STANDARD_OVERRIDES: dict[int, tuple[str, str]] = {
    10: ("《素问·五脏生成》", "统本多作《五脏生成篇》"),
    11: ("《素问·五脏别论》", "目录及正文沿用古字作“五藏别论”"),
    22: ("《素问·脏气法时论》", "原书沿用“藏气法时论”"),
    24: ("《素问·血气形志》", "听写整理本作“血气行志论”，“形”误作“行”"),
    25: ("《素问·宝命全形论》", "听写整理本作“宝命全角论”，“形”误作“角”"),
    30: ("《素问·阳明脉解》", "部分通本作《阳明脉解篇》"),
    38: ("《素问·咳论》", "沿用异体“欬论”"),
    40: ("《素问·腹中论》", "目录与正文写作“第四十十篇”，实为第四十篇"),
    41: ("《素问·刺腰痛》", "简作“刺腰论”"),
    53: ("《素问·刺志论》", "整理本标为“刺志论反症”"),
    54: ("《素问·针解》", "即《针解篇》"),
    59: ("《素问·气府论》", "听写本多作“气腑论”，“府”作“腑”"),
    61: ("《素问·水热穴论》", "正文标题带逗号“第六十一篇，水热穴论”"),
    65: ("《素问·标本病传论》", "简作“标本病论”，缺“传”字"),
    72: ("《素问·刺法论（遗篇）》", "宋本以后所传《黄帝内经遗篇》，在八十一篇《解精微论》之后第 283 页附载"),
    75: ("《素问·著至教论》", "听写本多写作“着至教论”"),
    78: ("《素问·征四失论》", "即《徵四失论》"),
    81: ("《素问·解精微论》", "听写整理本作“解经微论”，“精”误作“经”"),
}

MISSING_SUWEN = [
    {"suwen_number": 51, "classic_title": "《素问·刺禁论》", "note": "上、下册目录及正文均未收录（第 50 篇直跳第 52 篇）"},
    {"suwen_number": 66, "classic_title": "《素问·天元纪大论》", "note": "运气七大论之一；据第 75 篇首节倪师自述，66–74 篇未入讲记正文"},
    {"suwen_number": 67, "classic_title": "《素问·五运行大论》", "note": "运气七大论之一，讲记未收"},
    {"suwen_number": 68, "classic_title": "《素问·六微旨大论》", "note": "运气七大论之一，讲记未收"},
    {"suwen_number": 69, "classic_title": "《素问·气交变大论》", "note": "运气七大论之一，讲记未收"},
    {"suwen_number": 70, "classic_title": "《素问·五常政大论》", "note": "运气七大论之一，讲记未收"},
    {"suwen_number": 71, "classic_title": "《素问·六元正纪大论》", "note": "运气七大论之一，讲记未收"},
    {"suwen_number": 73, "classic_title": "《素问·本病论（遗篇）》", "note": "讲记未收；王冰注本原亡，后世仅附见第 72 篇《刺法论》于 p.283"},
    {"suwen_number": 74, "classic_title": "《素问·至真要大论》", "note": "运气七大论最末篇，讲记未收（由第 65 篇直跳第 75 篇）"},
]


def parse_cn_int(token: str) -> int | None:
    """Parse Chinese chapter number tokens including typos like '四十十' and '七五'."""
    token = token.strip()
    if token.isdigit():
        return int(token)
    if token == "四十十":
        return 40
    if len(token) == 2 and token[0] in CHINESE_NUMS and token[1] in CHINESE_NUMS and token[0] != "十" and token[1] != "十":
        # e.g. "七五" -> 75
        return CHINESE_NUMS[token[0]] * 10 + CHINESE_NUMS[token[1]]
    total = 0
    cur = 0
    for ch in token:
        if ch not in CHINESE_NUMS:
            return None
        val = CHINESE_NUMS[ch]
        if val == 10:
            total += (cur if cur else 1) * 10
            cur = 0
        else:
            cur = val
    return total + cur


def load_pages() -> list[dict[str, Any]]:
    with PAGES_PATH.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def parse_toc_items(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for pg in pages:
        if pg["page_role"] != "toc":
            continue
        for line in pg["body_text"].splitlines():
            s = line.strip()
            if not s or s == "目 录":
                continue
            m = re.match(r"^(.*?)\.+(\d+)$", s)
            if not m:
                continue
            title = m.group(1).strip()
            printed_start = int(m.group(2))
            is_ch = bool(title == "前言" or re.match(r"^第.{1,6}篇", title))
            items.append(
                {
                    "title": title,
                    "printed_start": printed_start,
                    "kind": "chapter" if is_ch else "section",
                    "toc_pdf_page": pg["pdf_page"],
                }
            )
    return items


def build_inventory() -> dict[str, Any]:
    pages = load_pages()
    toc_items = parse_toc_items(pages)
    by_printed = {p["printed_page"]: p for p in pages if p["printed_page"] is not None}

    def printed_to_ref(printed: int) -> dict[str, Any]:
        row = by_printed[printed]
        return {
            "source_id": row["source_id"],
            "volume": row["volume"],
            "volume_label": row["volume_label"],
            "pdf_page": row["pdf_page"],
            "printed_page": printed,
            "page_id": row["page_id"],
        }

    chapters: list[dict[str, Any]] = []
    seen_suwen: dict[int, int] = {}

    ch_indices = [i for i, item in enumerate(toc_items) if item["kind"] == "chapter"]
    for pos, idx in enumerate(ch_indices):
        item = toc_items[idx]
        next_ch_idx = ch_indices[pos + 1] if pos + 1 < len(ch_indices) else len(toc_items)
        title = item["title"]
        pr_start = item["printed_start"]

        if title == "前言":
            pr_end = pr_start  # p.9 shares page 9 with 第一篇
        elif pos + 1 < len(ch_indices):
            next_start = toc_items[ch_indices[pos + 1]]["printed_start"]
            pr_end = max(pr_start, next_start - 1 if next_start > pr_start else pr_start)
        else:
            pr_end = 301

        suwen_num: int | None = None
        m_num = re.match(r"^第(.{1,6}?)篇", title)
        if m_num:
            suwen_num = parse_cn_int(m_num.group(1))

        if title == "前言":
            cid = "nj:preface"
            std_title = "前言（课程导读）"
            coll_note = "讲记开篇说明课程讲授重点与参考底本"
        elif suwen_num is not None:
            seen_suwen[suwen_num] = seen_suwen.get(suwen_num, 0) + 1
            if seen_suwen[suwen_num] > 1:
                cid = f"nj:suwen:{suwen_num:02d}_bis"
                std_title = "《黄帝内经》全课收尾（版面误标“第七五篇：着至教论”）"
                coll_note = (
                    "校勘事实：第 289 页标题印刷为“第七五篇：着至教论”，实为第 283 页第 72 篇《刺法论》之后的"
                    "「第八节 万源归宗」全课收尾、易学五行/天干地支与答疑记录，并非重讲《著至教论》。"
                )
            else:
                cid = f"nj:suwen:{suwen_num:02d}"
                std_title, coll_note = CLASSIC_STANDARD_OVERRIDES.get(suwen_num, (f"《素问·{title.split()[-1]}》", ""))
        else:
            cid = f"nj:extra:{pos:02d}"
            std_title = title
            coll_note = ""

        child_items = toc_items[idx + 1 : next_ch_idx]
        if child_items:
            pr_end = max(pr_end, max(sec["printed_start"] for sec in child_items))
        start_ref = printed_to_ref(pr_start)
        end_ref = printed_to_ref(pr_end)

        sections: list[dict[str, Any]] = []
        for s_idx, sec in enumerate(child_items, 1):
            s_pr_start = sec["printed_start"]
            if s_idx < len(child_items):
                next_s_pr = child_items[s_idx]["printed_start"]
                s_pr_end = max(s_pr_start, next_s_pr - 1 if next_s_pr > s_pr_start else s_pr_start)
            else:
                s_pr_end = max(s_pr_start, pr_end)
            s_start_ref = printed_to_ref(s_pr_start)
            s_end_ref = printed_to_ref(s_pr_end)
            sec_id = f"{cid}:s{s_idx:02d}"
            sections.append(
                {
                    "id": sec_id,
                    "chapter_id": cid,
                    "title": sec["title"],
                    "source_id": s_start_ref["source_id"],
                    "volume": s_start_ref["volume"],
                    "volume_label": s_start_ref["volume_label"],
                    "pdf_page_start": s_start_ref["pdf_page"],
                    "pdf_page_end": s_end_ref["pdf_page"],
                    "printed_page_start": s_pr_start,
                    "printed_page_end": s_pr_end,
                    "review_status": "pending",
                }
            )

        chapters.append(
            {
                "id": cid,
                "order": pos + 1,
                "suwen_number": suwen_num,
                "title": title,
                "classic_standard_title": std_title,
                "collation_note": coll_note,
                "volume": start_ref["volume"],
                "volume_label": start_ref["volume_label"],
                "source_id": start_ref["source_id"],
                "end_source_id": end_ref["source_id"],
                "pdf_page_start": start_ref["pdf_page"],
                "pdf_page_end": end_ref["pdf_page"],
                "printed_page_start": pr_start,
                "printed_page_end": pr_end,
                "total_sections": len(sections),
                "approved_sections": 0,
                "review_status": "pending",
                "sections": sections,
            }
        )

    included_nums = sorted({c["suwen_number"] for c in chapters if c["suwen_number"] is not None})
    return {
        "schema_version": "1.0.0",
        "collection_title": "《黄帝内经》上、下册（视频同步整理文稿 · 守候诚实国学书店 2014 版）",
        "sources": ["ni-neijing-vol1-pdf", "ni-neijing-vol2-pdf"],
        "edition_inventory": {
            "classic_scope": "仅含《素问》讲记（未收录《灵枢》）",
            "lingshu_included": False,
            "total_pdf_pages": len(pages),
            "vol1_pdf_pages": sum(1 for p in pages if p["volume"] == "vol1"),
            "vol2_pdf_pages": sum(1 for p in pages if p["volume"] == "vol2"),
            "total_printed_pages": 301,
            "toc_chapter_entries": len(chapters),
            "unique_suwen_numbers_included": len(included_nums),
            "included_suwen_numbers": included_nums,
            "missing_suwen_count": len(MISSING_SUWEN),
            "missing_suwen_chapters": MISSING_SUWEN,
            "reordered_and_artifact_notes": [
                "第 72 篇《刺法论（遗篇）》未依序号排在 72 位，而附于第 81 篇之后（印刷第 283–288 页）。",
                "印刷第 289 页误植标题“第七五篇：着至教论”，内容实承《刺法论》之后的「第八节 万源归宗」课终总结与答疑（非《素问·著至教论》正文）。",
                "目录下第十七篇《脉要精微论》内嵌 1 条题图行“第十八难三部四经图（p.93）”，其余 282 条均以“第X节”标出，合计 283 节。",
            ],
        },
        "stats": {
            "total_chapters": len(chapters),
            "approved_chapters": 0,
            "total_sections": sum(c["total_sections"] for c in chapters),
            "approved_sections": 0,
        },
        "chapters": chapters,
    }


def main() -> int:
    payload = build_inventory()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    st = payload["stats"]
    inv = payload["edition_inventory"]
    print(
        f"Neijing inventory built -> {OUTPUT_PATH.relative_to(ROOT)}: "
        f"chapters={st['total_chapters']} (unique_suwen={inv['unique_suwen_numbers_included']}), "
        f"sections={st['total_sections']}, missing_suwen={inv['missing_suwen_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
