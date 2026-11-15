"""Compile accepted acupuncture batches + full TOC denominator into entity catalogs."""
from __future__ import annotations

import json
from pathlib import Path

from etl.review_ledger import load_pages_index, sha256_text


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "brain_data" / "acupuncture"
CHAPTERS_PATH = DATA_DIR / "chapters.json"
MANIFEST_PATH = DATA_DIR / "batch_manifest.json"
BATCHES_DIR = DATA_DIR / "review_batches"
PAGES_PATH = ROOT / "sources" / "acupuncture" / "pages.jsonl"
SOURCE_ID = "ni-acupuncture-v2-20100703"

PAIRED_MERIDIAN = {
    "meridian:lu": "meridian:li",
    "meridian:li": "meridian:lu",
    "meridian:st": "meridian:sp",
    "meridian:sp": "meridian:st",
    "meridian:ht": "meridian:si",
    "meridian:si": "meridian:ht",
    "meridian:bl": "meridian:ki",
    "meridian:ki": "meridian:bl",
    "meridian:pc": "meridian:sj",
    "meridian:sj": "meridian:pc",
    "meridian:gb": "meridian:lv",
    "meridian:lv": "meridian:gb",
    "meridian:ren": "meridian:du",
    "meridian:du": "meridian:ren",
}

EMERGENCY_TITLE_KEYWORDS = ("血症", "出血", "回阳九针", "十三鬼穴", "癫痫", "脑瘤")
HIGH_RISK_TITLE_KEYWORDS = (
    "癌",
    "肿瘤",
    "瘤",
    "肺",
    "放血",
    "梅花针",
    "睛中",
    "禁忌",
    "怀孕",
    "堕胎",
    "扁桃腺",
    "耳针",
    "血痢",
    "积水",
)

PENDING_HIGH_RISK_WARNING = (
    "【高风险待审教学目录】本条目尚未完成逐段校对，但原文标题涉及肿瘤、出血、怀孕禁忌、放血、"
    "眼科或深刺风险内容；严禁作个人操作参考。"
)
PENDING_EMERGENCY_WARNING = (
    "【急症及高风险待审目录】本条目涉及急症、出血、癫痫或颅内病变教学目录，"
    "尚待逐章精读审校，临床急救与重疾须由专业医疗体系处理。"
)


def find_quote_on_page(page_row: dict, bare_title: str, title: str) -> str:
    lines = [ln.strip() for ln in page_row.get("body_text", "").splitlines() if ln.strip()]
    for ln in lines:
        if (bare_title and bare_title in ln) or (title and title in ln):
            return ln
    return lines[0] if lines else page_row.get("raw_text", "").splitlines()[0].strip()


def make_span(span_id: str, page_row: dict, quote: str, chapter_path: str) -> dict:
    return {
        "span_id": span_id,
        "source_id": SOURCE_ID,
        "page_id": page_row["page_id"],
        "pdf_page": page_row["pdf_page"],
        "printed_page": page_row.get("printed_page"),
        "chapter_path": chapter_path,
        "quote": quote,
        "quote_sha256": sha256_text(quote),
        "role": "collation_notes",
    }


def classify_pending_risk(title: str) -> tuple[str, str]:
    if any(k in title for k in EMERGENCY_TITLE_KEYWORDS):
        return "emergency", PENDING_EMERGENCY_WARNING
    if any(k in title for k in HIGH_RISK_TITLE_KEYWORDS):
        return "high_risk", PENDING_HIGH_RISK_WARNING
    return "standard", ""


def load_accepted_batches() -> tuple[list[str], dict]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    accepted_names = manifest.get("accepted", [])
    merged = {
        "meridians": {},
        "acupoints": {},
        "techniques": {},
        "conditions": {},
    }
    for fname in accepted_names:
        batch = json.loads((BATCHES_DIR / fname).read_text(encoding="utf-8"))
        for key in merged:
            for item in batch.get(key, []):
                eid = item["id"]
                existing = merged[key].get(eid)
                if existing and existing.get("review_status") == "approved" and item.get("review_status") != "approved":
                    continue
                merged[key][eid] = item
    return accepted_names, merged


def build_meridians(chapters_data: dict, pages_by_num: dict[int, dict], accepted_meridians: dict, acupoints_list: list[dict]) -> list[dict]:
    ch4 = next(ch for ch in chapters_data["chapters"] if ch["id"] == "ch4")
    majors = [
        sec for sec in ch4["sections"]
        if sec.get("level") == "meridian" and sec.get("meridian_id") not in {None, "meridian:ren_du_intro"}
    ]

    points_by_meridian: dict[str, list[str]] = {}
    for pt in acupoints_list:
        points_by_meridian.setdefault(pt["meridian_id"], []).append(pt["id"])

    items: list[dict] = []
    for idx, sec in enumerate(majors):
        mid = sec["meridian_id"]
        if mid in accepted_meridians:
            items.append(accepted_meridians[mid])
            continue
        p_start = sec["page_start"]
        if idx + 1 < len(majors):
            nxt = majors[idx + 1]
            p_end = nxt["page_start"]
            first_line = (pages_by_num[p_end].get("body_text", "").splitlines() or [""])[0]
            if p_end > p_start and nxt["bare_title"] in first_line:
                p_end -= 1
        else:
            p_end = ch4["page_end"]
        page_row = pages_by_num[p_start]
        quote = find_quote_on_page(page_row, sec["bare_title"], sec["title"])
        name = sec["bare_title"].replace("经穴篇", "").replace("经穴", "")
        if not name.endswith("脉") and not name.endswith("经"):
            name = sec["bare_title"]
        items.append(
            {
                "id": mid,
                "record_type": "meridian",
                "canonical_name": name,
                "aliases": [sec["bare_title"]],
                "chapter_id": "ch4",
                "section_id": sec["id"],
                "page_range": [p_start, p_end],
                "zang_fu": "尚待第四章逐经审校",
                "yin_yang_five_element": "尚待第四章逐经审校",
                "flow_hour": "尚待对照第三章十二经纳地支与第四章正文核校",
                "pathway_source": f"全书目录锚定于第{p_start}–{p_end}页（{sec['title']}），经脉详情待逐经精读审校。",
                "paired_meridian_id": PAIRED_MERIDIAN.get(mid, ""),
                "acupoint_ids": points_by_meridian.get(mid, []),
                "five_shu_table": {},
                "summary": f"目录登记条（第{p_start}–{p_end}页），当前仅挂接样板跨经联动穴位锚点，本经全文尚待分批审校。",
                "source_spans": [make_span(f"sp:{mid}:toc", page_row, quote, f"第四章 {sec['title']}")],
                "content_layers": {
                    "source_quote": [],
                    "ni_teaching": [],
                    "other_annotations": [],
                    "collation_notes": [f"由目录自动锚定于第{p_start}–{p_end}页；已挂接样板中涉及之跨经锚点 {len(points_by_meridian.get(mid, []))} 个。"],
                    "organizer_summary": ["全书14经分母条目，等待按手阳明大肠经至足厥阴肝经及任督顺序逐经精读入库。"],
                },
                "open_questions": [f"{name}正文第{p_start}–{p_end}页之逐穴定位、五俞子母与特殊治症尚待后续审校批次逐条整理。"],
                "generation_status": "auto",
                "evidence_status": "anchored",
                "review_status": "pending",
                "risk_level": "standard",
                "safety_warning": "",
                "version": "2.0.0",
            }
        )

    extra_points = points_by_meridian.get("meridian:extra", [])
    if "meridian:extra" in accepted_meridians:
        extra_item = dict(accepted_meridians["meridian:extra"])
        existing_ids = list(extra_item.get("acupoint_ids", []))
        for pid in extra_points:
            if pid not in existing_ids:
                existing_ids.append(pid)
        extra_item["acupoint_ids"] = existing_ids
        items.append(extra_item)
    else:
        # Extra-meridian points container (for 太阳 / 肾关 / 痞根 / 内迎香 / 十宣)
        p171 = pages_by_num[171]
        extra_quote = "我们扎奇穴，在对侧的阴陵泉下一寸的肾关穴。"
        items.append(
            {
                "id": "meridian:extra",
                "record_type": "meridian",
                "canonical_name": "经外奇穴",
                "aliases": ["奇穴", "EXTRA"],
                "chapter_id": "ch4",
                "section_id": "ch4:extra",
                "page_range": [13, 195],
                "zang_fu": "不单归属一脏腑（散见第四章各经附记及第六章治症）",
                "yin_yang_five_element": "奇穴不按十二经五俞五行配属",
                "flow_hour": "无固定时辰流注",
                "pathway_source": "散见教材各章的经外奇穴汇总容器（当前收录急救十宣及头部/鼻病样板之太阳、肾关、痞根、内迎香）。",
                "paired_meridian_id": "",
                "acupoint_ids": extra_points,
                "five_shu_table": {},
                "summary": "汇总教材各章所授经外奇穴的导航分类容器；现收录样板涉及的十宣、太阳、肾关、痞根、内迎香。",
                "source_spans": [make_span("sp:meridian:extra:p171", p171, extra_quote, "第六章 头部与脑瘤治症")],
                "content_layers": {
                    "source_quote": [],
                    "ni_teaching": ["全书多处称“奇穴”，如阑尾穴、胆石点、定喘、肾关、痞根、十宣等。"],
                    "other_annotations": [],
                    "collation_notes": ["结构性导航容器，具体奇穴细节随各章批次逐批充实。"],
                    "organizer_summary": ["避免将经外奇穴误归某单一正经。"],
                },
                "open_questions": ["全书散见经外奇穴（如安眠穴、阑尾穴、华佗夹脊、胆石点、定喘穴等）尚待第四、六章全面校对汇总。"],
                "generation_status": "auto",
                "evidence_status": "anchored",
                "review_status": "pending",
                "risk_level": "standard",
                "safety_warning": "",
                "version": "2.0.0",
            }
        )
    return items


def build_conditions(chapters_data: dict, pages_by_num: dict[int, dict], accepted_conditions: dict) -> list[dict]:
    ch6 = next(ch for ch in chapters_data["chapters"] if ch["id"] == "ch6")
    by_section = {item.get("section_id"): item for item in accepted_conditions.values() if item.get("section_id")}
    items: list[dict] = []
    for sec in ch6["sections"]:
        if sec["id"] in by_section:
            items.append(by_section[sec["id"]])
            continue
        p_start = sec["page_start"]
        p_end = sec["page_end"]
        page_row = pages_by_num[p_start]
        quote = find_quote_on_page(page_row, sec["bare_title"], sec["title"])
        risk_level, safety_warning = classify_pending_risk(sec["title"])
        cid = f"cond:ch6:{sec['id'].split(':')[1]}"
        items.append(
            {
                "id": cid,
                "record_type": "condition_teaching",
                "canonical_name": sec["title"],
                "aliases": [sec["bare_title"]],
                "chapter_id": "ch6",
                "section_id": sec["id"],
                "page_range": [p_start, p_end],
                "summary": f"第六章原书专题目录（第{p_start}–{p_end}页），尚未完成逐节精读与证候拆条。",
                "sub_patterns": [],
                "source_spans": [make_span(f"sp:{cid}", page_row, quote, f"第六章 {sec['title']}")],
                "content_layers": {
                    "source_quote": [],
                    "ni_teaching": [],
                    "other_annotations": [],
                    "collation_notes": [f"锚定于原书第{p_start}–{p_end}页标题段落，时间戳 {sec.get('timestamp') or '无'}。"],
                    "organizer_summary": ["作为第六章 34 节全书治症分母条目保留，等待按批审校。"],
                },
                "open_questions": [f"《{sec['title']}》（p.{p_start}–{p_end}）之具体症状表现、辨证思路、取穴理由及高风险标注尚待后续批次逐条校对。"],
                "generation_status": "auto",
                "evidence_status": "anchored",
                "review_status": "pending",
                "risk_level": risk_level,
                "safety_warning": safety_warning,
                "version": "2.0.0",
            }
        )
    return items


def write_compiled(name: str, items: list[dict], batch_names: list[str]) -> None:
    out_path = DATA_DIR / name
    payload = {
        "source_id": SOURCE_ID,
        "accepted_batches": batch_names,
        "stats": {
            "total": len(items),
            "approved": sum(1 for x in items if x.get("review_status") == "approved"),
            "pending": sum(1 for x in items if x.get("review_status") == "pending"),
            "high_risk_or_emergency": sum(1 for x in items if x.get("risk_level") in {"high_risk", "emergency"}),
        },
        "items": items,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def sync_chapters_status(
    chapters_data: dict,
    meridians: list[dict],
    techniques: list[dict],
    conditions: list[dict],
) -> None:
    approved_meridians = {m["id"] for m in meridians if m.get("review_status") == "approved"}
    approved_conditions = {c["section_id"] for c in conditions if c.get("review_status") == "approved" and c.get("section_id")}
    approved_section_ids: set[str] = set(approved_conditions)
    for tech in techniques:
        if tech.get("review_status") == "approved":
            for sid in tech.get("section_ids", []):
                approved_section_ids.add(sid)

    total_approved = 0
    for ch in chapters_data.get("chapters", []):
        cur_meridian = None
        ch_approved = 0
        for sec in ch.get("sections", []):
            if ch["id"] == "ch4":
                if sec.get("level") == "meridian":
                    cur_meridian = sec.get("meridian_id")
                is_app = (
                    sec["id"] in approved_section_ids
                    or (cur_meridian in approved_meridians)
                    or (
                        cur_meridian == "meridian:ren_du_intro"
                        and "meridian:ren" in approved_meridians
                        and "meridian:du" in approved_meridians
                    )
                )
            else:
                is_app = sec["id"] in approved_section_ids
            sec["pilot_status"] = "approved" if is_app else "pending"
            if is_app:
                ch_approved += 1
        ch["approved_sections"] = ch_approved
        total_approved += ch_approved
    chapters_data.setdefault("stats", {})["approved_sections"] = total_approved
    CHAPTERS_PATH.write_text(json.dumps(chapters_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    chapters_data = json.loads(CHAPTERS_PATH.read_text(encoding="utf-8"))
    pages_by_id = load_pages_index(PAGES_PATH)
    pages_by_num = {row["pdf_page"]: row for row in pages_by_id.values()}
    batch_names, accepted = load_accepted_batches()

    acupoints = list(accepted["acupoints"].values())
    techniques = list(accepted["techniques"].values())
    meridians = build_meridians(chapters_data, pages_by_num, accepted["meridians"], acupoints)
    conditions = build_conditions(chapters_data, pages_by_num, accepted["conditions"])
    sync_chapters_status(chapters_data, meridians, techniques, conditions)

    write_compiled("meridians.json", meridians, batch_names)
    write_compiled("acupoints.json", acupoints, batch_names)
    write_compiled("techniques.json", techniques, batch_names)
    write_compiled("conditions.json", conditions, batch_names)

    print(
        json.dumps(
            {
                "meridians": {"total": len(meridians), "approved": sum(1 for m in meridians if m["review_status"] == "approved")},
                "acupoints": {"total": len(acupoints), "approved": sum(1 for a in acupoints if a["review_status"] == "approved")},
                "techniques": {"total": len(techniques), "approved": sum(1 for t in techniques if t["review_status"] == "approved")},
                "conditions": {"total": len(conditions), "approved": sum(1 for c in conditions if c["review_status"] == "approved")},
                "chapters_approved_sections": chapters_data["stats"]["approved_sections"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
