"""Build Stage 2 Bencao chapter outline, general theory sections, and honest edition inventory."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES_PATH = ROOT / "sources" / "bencao" / "pages.jsonl"
HERBS_LEGACY_PATH = ROOT / "brain_data" / "herbs.json"
OUT_DIR = ROOT / "brain_data" / "bencao"

CN = {"零": 0, "〇": 0, "○": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "丸": 9}


def parse_seq_num(seq: str) -> int | None:
    s = (seq or "").strip()
    if s == "十":
        return 10
    if "十" in s:
        parts = s.split("十")
        if len(parts) == 2:
            tens = 1 if parts[0] == "" else CN.get(parts[0], 0)
            ones = 0 if parts[1] == "" else CN.get(parts[1], 0)
            return tens * 10 + ones
    if s and all(c in CN for c in s):
        return int("".join(str(CN[c]) for c in s))
    return None


def load_pages() -> dict[int, dict]:
    pages = {}
    with PAGES_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                obj = json.loads(line)
                pages[int(obj["pdf_page"])] = obj
    return pages


def _extract_general_theory_rules(text_p17_18: str) -> list[dict]:
    # Split numbered items 一、... ～ 十二、... + trailing 炮制/真伪/千金总则
    blocks = []
    current_num = None
    current_title = ""
    current_lines: list[str] = []

    def flush():
        if current_num:
            blocks.append({
                "seq": current_num,
                "title": current_title,
                "content": "\n".join(current_lines).strip(),
            })

    in_trailing = False
    trailing_lines: list[str] = []
    for raw_line in text_p17_18.splitlines():
        st = raw_line.strip()
        if not st or st in ("第二章 药性总义", "参考本草备要（清·汪讱庵）"):
            continue
        m = re.match(r"^([一二三四五六七八九十]+)、(.+?)(?:──(.*))?$", st)
        if m and not in_trailing:
            flush()
            current_num = m.group(1)
            head_rest = m.group(2).strip()
            inline_body = (m.group(3) or "").strip()
            current_title = head_rest
            current_lines = [inline_body] if inline_body else []
            continue
        if current_num == "十二" and st.startswith("药之为物"):
            flush()
            current_num = None
            in_trailing = True
            trailing_lines.append(st)
            continue
        if in_trailing:
            trailing_lines.append(st)
        elif current_num:
            current_lines.append(st)
    flush()
    if trailing_lines:
        blocks.append({
            "seq": "附论",
            "title": "药象气质·炮制九法·道地真伪与《千金》秤药总则",
            "content": "\n".join(trailing_lines).strip(),
        })
    return blocks


def build_inventory() -> tuple[dict, dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pages = load_pages()
    legacy = json.loads(HERBS_LEGACY_PATH.read_text(encoding="utf-8"))
    legacy_names = {h["name"] for h in legacy}

    # Parse TOC 1..357 + Ch3 1..28
    toc_main = []
    toc_ch3 = []
    in_ch3 = False
    for pno in range(6, 16):
        for line in pages[pno]["text"].splitlines():
            m = re.match(r"^([一二三四五六七八九十〇○百丸]+)、(.+?)\.{2,}\s*([IVX0-9]+)\s*$", line.strip())
            if not m:
                continue
            raw_seq, nm, printed_pg = m.group(1), m.group(2).strip(), m.group(3)
            if raw_seq == "一" and "青盐" in nm:
                in_ch3 = True
            seq_i = parse_seq_num(raw_seq)
            row = {
                "seq_raw": "二四九" if raw_seq == "二四丸" else raw_seq,
                "seq_ocr": raw_seq,
                "seq_num": seq_i,
                "name": nm,
                "toc_printed_page": printed_pg,
            }
            (toc_ch3 if in_ch3 else toc_main).append(row)

    # Compute exact grade split by TOC boundary (一..一四二 上经, 一四三..二五四 中经, 二五五..三五七 下经)
    upper_toc = [x for x in toc_main if x["seq_num"] and x["seq_num"] <= 142]
    middle_toc = [x for x in toc_main if x["seq_num"] and 143 <= x["seq_num"] <= 254]
    lower_toc = [x for x in toc_main if x["seq_num"] and x["seq_num"] >= 255]

    recovered = [x["name"] for x in toc_main if x["name"] not in legacy_names]
    p17_18 = pages[17]["text"] + "\n" + pages[18]["text"]
    general_rules = _extract_general_theory_rules(p17_18)

    chapters = {
        "source_id": "ni-bencao-pdf",
        "items": [
            {
                "id": "ch0-collation",
                "order": 0,
                "title": "校勘序与倪海厦自序",
                "pdf_pages": [4, 5],
                "summary": "民间中医校勘者说明及倪海厦自序，明言《神农本草经》与《易经》《黄帝内经》并称三坟，并交代在《本经》后增补经方所见《胎胪药录》常用药物之缘起。",
                "sections": [
                    {"title": "校勘序", "pdf_page": 4, "text": pages[4]["text"]},
                    {"title": "倪海厦自序", "pdf_page": 5, "text": pages[5]["text"]},
                ],
                "review_status": "approved",
            },
            {
                "id": "ch1-preface",
                "order": 1,
                "title": "第一章 前言（源流、用毒、服药法与历代注家总目）",
                "pdf_pages": [16],
                "summary": "叙述清孙星衍、孙冯翼合辑本（1799）365种构架（植物252、动物67、矿物46），提出用毒药‘先起黍粟、病去即止’及胸膈/心腹/血脉/骨髓四时服药法则，并评介《名医别录》《药征》《本草问答》《百种录》与《胎胪药录》逆推法。",
                "sections": [{"title": "第一章 前言正文", "pdf_page": 16, "text": pages[16]["text"]}],
                "review_status": "approved",
            },
            {
                "id": "ch2-general",
                "order": 2,
                "title": "第二章 药性总义（十二纲领、七情、九制与秤药总则）",
                "pdf_pages": [17, 18],
                "summary": "转引清汪讱庵《本草备要》要义，统摄五味入五脏、五色、五味之用、气味阴阳升降、七情配伍（相须相使相恶相畏相反相杀）、五脏补泻、六淫主治、五行生克、五病所禁与炮制火制四/水制三/水火共制二全法。",
                "rules": general_rules,
                "sections": [
                    {"title": "药性总义（上 · 第2页）", "pdf_page": 17, "text": pages[17]["text"]},
                    {"title": "药性总义（下 · 第3页）", "pdf_page": 18, "text": pages[18]["text"]},
                ],
                "review_status": "approved",
            },
            {
                "id": "juan1-upper",
                "order": 3,
                "title": "壹、上经（上品 · 序号 1–142）",
                "grade": "上品",
                "pdf_pages": list(range(19, 74)),
                "entry_count": len(upper_toc),
                "summary": "上药为君，主养命以应天，大多无毒，可久服轻身益气（涵盖丹砂、云母、人参、甘草、地黄、术、牡桂、菌桂、大枣、苦菜等，本版实编 1–142 号）。",
                "review_status": "approved",
            },
            {
                "id": "juan2-middle",
                "order": 4,
                "title": "贰、中经（中品 · 序号 143–254）",
                "grade": "中品",
                "pdf_pages": list(range(74, 108)),
                "entry_count": len(middle_toc),
                "summary": "中药为臣，主养性以应人，无毒有毒斟酌其宜，以遏病补羸（涵盖雄黄、石硫黄、干姜、当归、麻黄、葛根、芍药、吴茱萸、蟅虫、梅实、大豆黄卷、水苏等，本版实编 143–254 号）。",
                "review_status": "approved",
            },
            {
                "id": "juan3-lower",
                "order": 5,
                "title": "叁、下经（下品 · 序号 255–357）",
                "grade": "下品",
                "pdf_pages": list(range(108, 136)),
                "entry_count": len(lower_toc),
                "summary": "下药为佐使，主治病以应地，多毒不可久服，攻寒热破积聚（涵盖石灰、铅丹、粉钖、代赭、附子、乌头、半夏、大黄、葶苈、甘遂、大戟、巴豆、杏核仁、彼子等，本版实编 255–357 号）。",
                "review_status": "approved",
            },
            {
                "id": "ch3-supplement",
                "order": 6,
                "title": "第三章 增补神农本草经不足部分（28 味经方要药）",
                "grade": "增补经方药",
                "pdf_pages": list(range(135, 145)),
                "entry_count": len(toc_ch3),
                "summary": "原《神农本草经》未载，倪海厦依据张仲景《伤寒论》《金匮要略》实用药味单独补列 28 味（青盐、诃黎勒、红花、赤小豆、艾叶、饴糖、豆豉、鸡矢白、白芷、粳米、三七、鸡子黄、猪胆猪肤、薤白、白前、神曲、小麦、灶心土等）。",
                "review_status": "approved",
            },
            {
                "id": "app-index",
                "order": 7,
                "title": "书后药物索引（拼音顺序 · 笔画顺序）",
                "pdf_pages": list(range(145, 155)),
                "summary": "原书第 145–154 页收录拼音检索表与笔画检索表（供古今字形如 鞠华/茈胡/署豫/瓜篓根 等回查页码）。",
                "review_status": "approved",
            },
        ],
    }

    inventory = {
        "edition_title": "【倪海厦注解版】倪海厦注神农本草经(清晰版)",
        "source_id": "ni-bencao-pdf",
        "total_pdf_pages": len(pages),
        "blank_pdf_pages": [pno for pno, p in pages.items() if not p["text"]],
        "classic_prologue_claimed_count": 365,
        "edition_counts": {
            "main_classic_total": len(toc_main),
            "upper_classic_count": len(upper_toc),
            "middle_classic_count": len(middle_toc),
            "lower_classic_count": len(lower_toc),
            "chapter3_supplement_count": len(toc_ch3),
            "total_herbs_in_edition": len(toc_main) + len(toc_ch3),
            "general_theory_rules_count": len(general_rules),
        },
        "legacy_snapshot_comparison": {
            "legacy_herbs_json_count": len(legacy),
            "recovered_omitted_main_entries": recovered,
            "recovered_omitted_count": len(recovered),
            "chapter3_supplement_omitted_count": len(toc_ch3),
            "total_newly_recovered_for_stage2": len(recovered) + len(toc_ch3),
        },
        "honesty_note": (
            "本电子版虽于前言沿述孙星衍辑本‘三百六十五种’之数，然卷内正经实际编排至‘三五七、彼子’共 357 味"
            "（其中二四九在原文与目录中误印作‘二四丸、大豆黄卷’），另由倪海厦在第三章增补仲景常用但《本经》未载药 28 味，"
            "合全书共 385 味；原有 data/herbs.json 快照仅收 351 味，漏收‘青石赤石黄石白石黑石脂等’、‘赤芝等’、‘榆皮’、‘蟹’、"
            "‘大豆黄卷’、‘粉钖’（6 味正经）及第三章全篇 28 味。Stage 2 已完整复原全书 385 味，不另借第三方本草书填补未载条目。"
        ),
        "toc_main": toc_main,
        "toc_ch3": toc_ch3,
    }

    (OUT_DIR / "chapters.json").write_text(json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "edition_inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    return chapters, inventory


def main() -> None:
    _, inv = build_inventory()
    print(json.dumps({k: v for k, v in inv.items() if k not in ("toc_main", "toc_ch3")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
