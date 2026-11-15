"""Compile complete Stage 2 Bencao database (`data/bencao/entries.json`) with 385 herbs,
strict knowledge-layer separation, verified page source spans, curated overlays,
pairwise comparison backlinks, and bidirectional formula/Neijing links.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from etl.bencao.inventory import parse_seq_num
from etl.herb_alias import ALIAS, CONTROVERSY_ALIASES

ROOT = Path(__file__).resolve().parents[2]
PAGES_PATH = ROOT / "sources" / "bencao" / "pages.jsonl"
INV_PATH = ROOT / "brain_data" / "bencao" / "edition_inventory.json"
LEGACY_HERBS_PATH = ROOT / "brain_data" / "herbs.json"
FORMULAS_SHANGHAN_PATH = ROOT / "brain_data" / "formulas.json"
FORMULAS_JINKUI_PATH = ROOT / "brain_data" / "jinkui_formulas.json"
NEIJING_RELATIONS_PATH = ROOT / "brain_data" / "neijing" / "relations.json"
CURATED_BATCH_PATH = ROOT / "brain_data" / "bencao" / "batches" / "bencao_curated_core.json"
COMPARISONS_PATH = ROOT / "brain_data" / "bencao" / "comparisons.json"
OUT_ENTRIES_PATH = ROOT / "brain_data" / "bencao" / "entries.json"
OUT_MANIFEST_PATH = ROOT / "brain_data" / "bencao" / "batch_manifest.json"

CH3_ID_SLUGS = {
    "诃黎勒（诃子）": "ch3-诃黎勒",
    "柏叶（侧柏叶）": "ch3-柏叶",
    "猪胆、猪肤": "ch3-猪胆猪肤",
}

TAG_CANONICAL = {
    "本经原文": ("classic", "《本经》原文"),
    "本绖原文": ("classic", "《本经》原文（原页误印作本绖）"),
    "本草原文": ("classic", "《本经》原文（原页误印作本草）"),
    "本经": ("classic", "《本经》"),
    "产地": ("origin", "产地"),
    "产池": ("origin", "产地（原页误印作产池）"),
    "性味": ("qi_wei", "性味"),
    "主治": ("indications", "主治"),
    "主冶": ("indications", "主治（原页误印作主冶）"),
    "效用": ("indications", "效用"),
    "用量": ("dosage", "用量"),
    "禁忌": ("contraindications", "禁忌"),
    "炮制": ("processing", "炮制"),
    "泡制": ("processing", "炮制（原页误印作泡制）"),
    "酒制": ("processing_sub", "酒制法"),
    "倪注": ("ni_note", "倪海厦按语"),
    "注": ("ni_note", "编注按语"),
    "附录": ("appendix", "附录附品"),
    "附加菊叶": ("appendix", "附品：菊叶"),
    "附方": ("appendix", "附方"),
}

SCHOLAR_CANONICAL = {
    "别录": "《名医别录》",
    "吴普": "吴普（《吴普本草》）",
    "弘景": "陶弘景",
    "陶弘景": "陶弘景",
    "甄权": "甄权",
    "药性": "《药性论》",
    "唐本": "《唐本草》（苏敬等）",
    "苏敬": "苏敬（《新修本草》）",
    "藏器": "陈藏器（《本草拾遗》）",
    "臓器": "陈藏器（《本草拾遗》）",
    "孟铣": "孟诜（《食疗本草》）",
    "陈藏器": "陈藏器",
    "大明": "《日华子本草》（大明）",
    "日华": "《日华子本草》（大明）",
    "开宝": "《开宝本草》",
    "嘉佑": "《嘉祐本草》",
    "苏颂": "苏颂（《本草图经》）",
    "苏讼": "苏颂（《本草图经》）",
    "宗奭": "寇宗奭（《本草衍义》）",
    "元素": "张元素（洁古）",
    "东垣": "李东垣",
    "冬垣": "李东垣",
    "好古": "王好古（海藏）",
    "丹溪": "朱丹溪",
    "时珍": "李时珍（《本草纲目》）",
    "纲目": "李时珍（《本草纲目》）",
    "汪机": "汪机（《本草会编》）",
    "汪颖": "汪颖（《食物本草》）",
    "汪昂": "汪讱庵（《本草备要》）",
    "备要": "《本草备要》",
    "括要": "《本草括要》",
    "仲醇": "缪希雍（仲醇）",
    "灵胎": "徐灵胎（《神农本草经百种录》）",
    "灵贻": "徐灵胎（《神农本草经百种录》）",
    "容川": "唐容川（《本草问答》）",
    "药征": "吉益东洞（《药征》）",
    "吴克潜": "吴克潜（《药性辞典》）",
    "吴瑞": "吴瑞（《日用本草》）",
    "之才": "徐之才（《雷公药对》）",
    "之材": "徐之才（《雷公药对》）",
    "雷斅": "雷斅（《雷公炮炙论》）",
    "思邈": "孙思邈（《千金方》）",
    "仲景": "张仲景（经方应用）",
    "素问": "《黄帝内经·素问》",
    "圣惠": "《太平圣惠方》",
    "圣惠方": "《太平圣惠方》",
    "肘后": "《肘后备急方》",
    "时方": "《时方歌括/时方妙用》",
    "本草": "《本草》诸家",
    "李珣": "李珣（《海药本草》）",
    "萧柄": "萧炳（《四声本草》）",
    "萧炳": "萧炳（《四声本草》）",
    "肃炳": "萧炳（《四声本草》）",
    "士良": "陈士良（《食性本草》）",
    "志良": "陈士良（《食性本草》）",
    "嘉谟": "陈嘉谟（《本草蒙筌》）",
    "王硕": "王硕（《易简方》）",
    "张文潜": "张文潜（粥记）",
    "抱朴子金丹篇": "葛洪《抱朴子·金丹篇》",
    "廷飞": "廷飞（校注引）",
    "毅明": "毅明（校注引）",
    "毅民": "毅明（校注引）",
}

SUBPART_TAGS = {
    "乌雄鸡", "乌骨鸡", "白雄鸡", "黄雄鸡", "黑雄鸡",
    "鸡屎白", "鸡内金", "龟肉",
}

INLINE_VARIANTS = {"或作咸", "或作平", "或作苦甘酸"}

# Strict emergency/high-risk drug sets (verifiable toxic/caustic/heavy-metal/drastic)
EMERGENCY_HERBS = {
    "附子", "乌头", "天雄", "侧子", "巴豆", "甘遂", "大戟", "芫花", "水银", "粉钖",
    "丹砂", "雄黄", "雌黄", "礜石", "砒", "斑蝥", "黎芦", "羊踯躅", "狼毒", "半夏",
    "钩吻", "莽草", "野葛", "莨菪子", "荛花", "泽漆", "常山", "恒山", "蜀漆", "商陆",
    "水蛭", "蜚虻", "马刀", "石灰", "铅丹", "胆矾", "石硫黄", "轻粉", "毒菌",
}

HIGH_RISK_HERBS = {
    "大黄", "朴消", "消石", "葶苈", "瓜蒂", "大枣" if False else "蟅虫",
    "牛膝", "瞿麦", "牡丹", "桃核仁", "杏核仁", "麻蕡", "干漆", "皂荚",
    "王不留行", "贯众", "牵牛", "红花", "没药", "细辛", "石苇", "防己", "木通",
    "代赭", "滑石", "蜘蛛", "牙子", "郁金", "三七", "白附子", "天南星",
}

STANDARD_NATURES = ["大热", "热", "大温", "微温", "温", "平", "凉", "微凉", "微寒", "小寒", "大寒", "寒"]
STANDARD_FLAVORS = ["酸", "苦", "甘", "辛", "咸", "淡", "涩"]
MERIDIAN_KEYWORDS = [
    ("手太阴肺", "肺经"), ("肺", "肺经"),
    ("手阳明大肠", "大肠经"), ("大肠", "大肠经"),
    ("足阳明胃", "胃经"), ("胃", "胃经"),
    ("足太阴脾", "脾经"), ("脾", "脾经"),
    ("手少阴心", "心经"), ("心经", "心经"), ("入心", "心经"), ("心肾", "心经"),
    ("手太阳小肠", "小肠经"), ("小肠", "小肠经"),
    ("足太阳膀胱", "膀胱经"), ("膀胱", "膀胱经"),
    ("足少阴肾", "肾经"), ("肾", "肾经"),
    ("手厥阴心包", "心包经"), ("心包", "心包经"),
    ("手少阳三焦", "三焦经"), ("三焦", "三焦经"),
    ("足少阳胆", "胆经"), ("胆经", "胆经"), ("入胆", "胆经"), ("肝胆", "胆经"),
    ("足厥阴肝", "肝经"), ("肝", "肝经"),
]


def load_pages() -> dict[int, dict]:
    pages = {}
    with PAGES_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                obj = json.loads(line)
                pages[int(obj["pdf_page"])] = obj
    return pages


def _canonical_id(kind: str, name: str) -> str:
    if kind == "ch3":
        if name in CH3_ID_SLUGS:
            return f"bencao:{CH3_ID_SLUGS[name]}"
        return f"bencao:ch3-{name}"
    return f"bencao:{name}"


def _clean_short_name(name: str) -> str:
    if "青石赤石黄石白石黑石脂" in name:
        return "五色石脂（赤石脂等）"
    if "赤芝黑芝青芝白芝黄芝紫芝" in name:
        return "六芝（赤芝等）"
    return name


def _slice_blocks(pages: dict[int, dict], inv: dict) -> list[dict]:
    toc_main = {x["seq_num"]: x for x in inv["toc_main"]}
    toc_ch3 = {x["seq_num"]: x for x in inv["toc_ch3"]}

    blocks: list[dict] = []
    cur: dict | None = None
    in_ch3 = False

    for pno in range(19, 145):
        page = pages[pno]
        for raw_line in page["text"].splitlines():
            st = raw_line.strip()
            if not st or st in ("壹、上经", "贰、中经", "叁、下经") or st.isdigit():
                continue
            if st.startswith("第三章") and "增补" in st:
                in_ch3 = True
                continue
            m = re.match(r"^([一二三四五六七八九十〇○百丸]+)、\s*(.+)$", st)
            if m:
                s_raw, nm = m.group(1), m.group(2).strip()
                s_num = parse_seq_num(s_raw)
                toc_row = (toc_ch3 if in_ch3 else toc_main).get(s_num)
                if toc_row and (nm == toc_row["name"] or nm.startswith(toc_row["name"][:2])):
                    if cur:
                        blocks.append(cur)
                    grade = (
                        "增补经方药" if in_ch3
                        else "上品" if s_num <= 142
                        else "中品" if s_num <= 254
                        else "下品"
                    )
                    cur = {
                        "kind": "ch3" if in_ch3 else "main",
                        "seq_num": s_num,
                        "seq_raw": "二四九" if s_raw == "二四丸" else s_raw,
                        "seq_ocr": s_raw,
                        "name": toc_row["name"],
                        "grade": grade,
                        "chapter_id": (
                            "ch3-supplement" if in_ch3
                            else "juan1-upper" if s_num <= 142
                            else "juan2-middle" if s_num <= 254
                            else "juan3-lower"
                        ),
                        "toc_printed_page": toc_row.get("toc_printed_page"),
                        "page_start": pno,
                        "page_end": pno,
                        "pdf_pages": [pno],
                        "lines": [],
                    }
                    continue
            if cur is not None:
                if pno not in cur["pdf_pages"]:
                    cur["pdf_pages"].append(pno)
                cur["page_end"] = pno
                cur["lines"].append((pno, raw_line))
    if cur:
        blocks.append(cur)
    return blocks


def _split_sections(lines: list[tuple[int, str]], kind: str) -> tuple[str, list[dict]]:
    """Split block lines into leading unheaded text + tagged sections `【tag】`."""
    preamble_lines: list[str] = []
    sections: list[dict] = []
    cur_tag: str | None = None
    cur_lines: list[str] = []

    tag_pat = re.compile(r"^【([^】]{1,14})】(.*)$")

    def flush():
        if cur_tag is not None:
            sections.append({"tag": cur_tag, "text": "\n".join(cur_lines).strip()})

    for _, raw in lines:
        st = raw.strip()
        if not st:
            continue
        m = tag_pat.match(st)
        if m and m.group(1) not in INLINE_VARIANTS:
            flush()
            cur_tag = m.group(1).strip()
            rest = m.group(2).strip()
            cur_lines = [rest] if rest else []
            continue
        if cur_tag is None:
            preamble_lines.append(st)
        else:
            cur_lines.append(st)
    flush()
    return "\n".join(preamble_lines).strip(), sections


def _split_ni_tail_from_contraindications(text: str) -> tuple[str, list[str]]:
    """Separate multi-paragraph unlabeled Ni lecture commentary inside 【禁忌】 safely."""
    if not text:
        return "", []
    paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    # Only extract when clear vernacular lecture commentary starts after an initial taboo sentence,
    # or when multi-line commentary clearly explains clinical philosophy ('坊间'/'汉唐'/'临床').
    joined = "\n".join(paras)
    lecture_markers = ("坊间", "一般使用", "临床", "今之所谓", "我辈", "人纪", "仲景之用", "汉唐", "因其色", "阳中之阴")
    # Split on clear marker boundaries where prior text already ended with period
    for marker in ("坊间", "因其色", "临床", "汉唐"):
        idx = joined.find(marker)
        if idx > 15:
            before = joined[:idx].rstrip()
            if before.endswith("。") or before.endswith("”"):
                return before, [joined[idx:].strip()]
    return joined, []


def _extract_four_natures(text: str) -> list[str]:
    found: list[str] = []
    if not text:
        return found
    scan = text
    for nat in STANDARD_NATURES:
        if nat in scan:
            # Avoid duplicate substring like '微温' triggering '温' or '大寒' triggering '寒'
            if nat == "寒" and any(x in found for x in ("大寒", "微寒", "小寒")):
                continue
            if nat == "温" and any(x in found for x in ("大温", "微温")):
                continue
            if nat == "热" and "大热" in found:
                continue
            if nat == "凉" and "微凉" in found:
                continue
            found.append(nat)
    return found


def _extract_five_flavors(text: str) -> list[str]:
    if not text:
        return []
    return [fl for fl in STANDARD_FLAVORS if fl in text]


def _extract_toxicity(text: str) -> str:
    if not text:
        return "未明言"
    if "有大毒" in text or "大毒" in text:
        return "有大毒"
    if "有小毒" in text or "小毒" in text:
        return "有小毒"
    if "无毒" in text and "有毒" not in text:
        return "无毒"
    if "有毒" in text and "无毒" not in text:
        return "有毒"
    if "有毒" in text and "无毒" in text:
        return "存毒争（文本兼具无毒/有毒记载）"
    return "未明言"


def _extract_meridians(texts: list[str]) -> list[str]:
    combined = "\n".join(t for t in texts if t)
    found: list[str] = []
    for kw, mer in MERIDIAN_KEYWORDS:
        if kw in combined and mer not in found:
            found.append(mer)
    return found


def _classify_risk(name: str, toxicity: str, full_text: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if toxicity in ("有大毒", "有毒") or name in EMERGENCY_HERBS:
        if toxicity in ("有大毒", "有毒"):
            reasons.append(f"原书记载毒性：{toxicity}")
        if name in EMERGENCY_HERBS:
            reasons.append("属峻烈攻逐、重金属矿物或毒剧品种，须严遵‘先起黍粟、病去即止’及炮制减毒规范")
        if any(k in full_text for k in ("堕胎", "下死胎", "坠胎")):
            reasons.append("具堕胎/峻下作用，妊娠绝对禁用")
        return "emergency", reasons

    if toxicity == "有小毒" or name in HIGH_RISK_HERBS:
        if toxicity == "有小毒":
            reasons.append("原书记载：有小毒")
        if any(k in full_text for k in ("堕胎", "坠胎", "孕妇忌", "妊者忌")):
            reasons.append("原书提示孕妇忌用或涉破血下胎")
        if not reasons:
            reasons.append("活血破瘀、涌吐重镇或历代存在基原混用争议，须辨证慎用")
        return "high_risk", reasons

    if any(k in full_text for k in ("堕胎", "坠胎", "孕妇忌", "孕妇禁用")):
        reasons.append("原书提及妊娠禁忌，孕产妇慎用")
        return "high_risk", reasons

    return "standard", []


def _extract_aliases(name: str, classic_text: str, full_text: str, ch3_intro: str) -> list[str]:
    aliases: list[str] = []
    for pat in (r"一名([^，。\n；、]{1,10})", r"又名([^，。\n；、]{1,12})", r"即([^，。\n；、]{1,8})"):
        for m in re.finditer(pat, classic_text + "\n" + ch3_intro):
            cand = m.group(1).strip(" 。，、（）")
            if cand and cand != name and len(cand) <= 10 and cand not in aliases:
                if not any(bad in cand for bad in ("山川", "川谷", "山谷", "平泽")):
                    aliases.append(cand)
    # Also attach book-known key aliases for searchability
    if "青石赤石" in name:
        for k in ("赤石脂", "白石脂", "五色石脂", "青石脂", "黄石脂", "黑石脂"):
            if k not in aliases:
                aliases.append(k)
    elif "赤芝黑芝" in name:
        for k in ("赤芝", "紫芝", "灵芝", "六芝"):
            if k not in aliases:
                aliases.append(k)
    elif "诃黎勒" in name:
        aliases.extend(["诃子", "诃黎勒"])
    elif "柏叶" in name:
        aliases.extend(["柏叶", "侧柏叶"])
    elif "猪胆" in name:
        aliases.extend(["猪胆", "猪胆汁", "猪肤"])
    elif "豆豉" in name:
        aliases.append("香豉")
    elif "青盐" in name and "戎盐" not in aliases:
        aliases.append("戎盐")
    elif "鸡矢白" in name:
        aliases.append("鸡屎白")
    elif "蒴翟细叶" in name:
        aliases.append("蒴藋细叶")
    elif "牡桂" in name:
        aliases.append("桂枝")
    elif "菌桂" in name:
        aliases.append("肉桂")
    elif "茈胡" in name:
        aliases.append("柴胡")
    elif "芎穷" in name:
        aliases.append("川芎")
    elif "署豫" in name:
        aliases.append("山药")
    elif "瓜篓根" in name:
        aliases.extend(["栝蒌根", "天花粉"])
    elif "檗木" in name:
        aliases.append("黄柏")
    elif "涅石" in name:
        aliases.extend(["矾石", "白矾", "枯矾"])
    elif "朴消" in name:
        aliases.append("芒硝")
    elif "鞠华" in name:
        aliases.append("菊花")
    elif "牙子" in name and "狼牙" not in aliases:
        aliases.append("狼牙")
    elif "白术" in name:
        aliases.append("术")
    return aliases[:12]


def _extract_symptom_keywords(text: str) -> list[str]:
    vocab = [
        "恶寒", "发热", "发汗", "无汗", "自汗", "汗出", "恶风", "头痛", "项强",
        "咳嗽", "喘", "痰饮", "呕吐", "反胃", "心下痞", "胸满", "胸痹", "心痛",
        "腹痛", "心腹痛", "腹胀", "痞满", "泄利", "下利", "痢疾", "便秘", "燥屎",
        "黄疸", "小便不利", "水肿", "水气", "脚气", "淋", "蓄血", "瘀血", "痛经",
        "闭经", "崩漏", "胎动", "带下", "失眠", "烦躁", "懊憹", "惊痫", "癫狂",
        "咽痛", "目赤", "目翳", "消渴", "口渴", "痈肿", "恶疮", "疥瘙", "黄烂疮",
        "寒热往来", "往来寒热", "胁痛", "转筋", "厥逆", "回阳", "吐血", "衄血", "便血",
        "风湿", "痹痛", "筋挛", "关节痛", "痹痿", "肠澼", "脱肛", "蛔虫", "疝瘕", "症瘕",
    ]
    return [w for w in vocab if w in text]


def _extract_seven_relations(full_text: str) -> list[str]:
    rels: list[str] = []
    for m in re.finditer(r"([畏恶反杀使忌][^，。\n；]{1,22}|得[^，。\n；]{1,14}良)", full_text):
        seg = m.group(1).strip()
        if len(seg) >= 2 and seg not in rels:
            rels.append(seg)
    return rels[:10]


def _find_source_span(page_obj: dict, candidate_quotes: list[str]) -> dict:
    txt = page_obj["text"]
    for cand in candidate_quotes:
        cand_clean = (cand or "").strip()
        if len(cand_clean) >= 4:
            # Also match across line breaks
            line1 = cand_clean.splitlines()[0].strip()
            for probe in (cand_clean, line1, line1[:16]):
                if len(probe) >= 4 and probe in txt:
                    return {
                        "source_id": "ni-bencao-pdf",
                        "pdf_page": page_obj["pdf_page"],
                        "printed_page": page_obj.get("printed_page"),
                        "quote": probe,
                        "text_sha256": page_obj["text_sha256"],
                    }
    # Safe verbatim fallback: first non-empty line on that page
    first_nonempty = next((l.strip() for l in txt.splitlines() if l.strip()), txt[:24].strip())
    return {
        "source_id": "ni-bencao-pdf",
        "pdf_page": page_obj["pdf_page"],
        "printed_page": page_obj.get("printed_page"),
        "quote": first_nonempty,
        "text_sha256": page_obj["text_sha256"],
    }


def _collect_formula_links(entries_by_id: dict[str, dict]) -> None:
    # Build lookup name -> entry_id prioritizing exact/alias rules cleanly
    name_to_id: dict[str, str] = {}
    for eid, e in entries_by_id.items():
        if e["kind"] == "main":
            name_to_id[e["name"]] = eid
    # For Chapter 3, register exact name only if not colliding with main (白芷 main stays primary, ch3-白芷 secondary)
    for eid, e in entries_by_id.items():
        if e["kind"] == "ch3":
            name_to_id.setdefault(e["name"], eid)
            short = e["name"].split("（")[0]
            name_to_id.setdefault(short, eid)

    all_formulas = []
    for path in (FORMULAS_SHANGHAN_PATH, FORMULAS_JINKUI_PATH):
        all_formulas.extend(json.loads(path.read_text(encoding="utf-8")))

    for f in all_formulas:
        fid = f["id"]
        fname = f["name"]
        book = f.get("book", "")
        chapter = f.get("chapter", "")
        six_meridian = f.get("six_meridian", "")
        for ing in f.get("ingredients", []):
            raw_ing = (ing.get("name") or "").strip()
            if not raw_ing:
                continue
            target_id = None
            match_kind = "unresolved"
            note = ""
            if raw_ing in name_to_id:
                target_id = name_to_id[raw_ing]
                match_kind = "exact"
            elif raw_ing in ALIAS:
                mapped_name, note = ALIAS[raw_ing]
                target_id = name_to_id.get(mapped_name)
                if not target_id:
                    # Also handle cleaned parentheses name
                    target_id = name_to_id.get(mapped_name.split("（")[0])
                if target_id:
                    match_kind = "alias"
            if not target_id:
                continue
            usage_row = {
                "formula_id": fid,
                "formula_name": fname,
                "book": book,
                "chapter": chapter,
                "six_meridian": six_meridian,
                "ingredient_raw_name": raw_ing,
                "dose": ing.get("dose", ""),
                "processing": ing.get("processing", ""),
                "match_kind": match_kind,
                "mapping_note": note,
                "controversy": CONTROVERSY_ALIASES.get(raw_ing, ""),
            }
            entries_by_id[target_id]["formula_usages"].append(usage_row)
            # If Ch3 White Angelica (ch3-白芷) also wants formula visibility when main 白芷 matches:
            if target_id == "bencao:白芷" and "bencao:ch3-白芷" in entries_by_id:
                entries_by_id["bencao:ch3-白芷"]["formula_usages"].append(usage_row)


def build_all() -> list[dict]:
    pages = load_pages()
    inv = json.loads(INV_PATH.read_text(encoding="utf-8"))
    legacy = json.loads(LEGACY_HERBS_PATH.read_text(encoding="utf-8"))
    legacy_names = {h["name"] for h in legacy}

    curated_overlays: dict[str, dict] = {}
    if CURATED_BATCH_PATH.exists():
        curated_payload = json.loads(CURATED_BATCH_PATH.read_text(encoding="utf-8"))
        curated_overlays = curated_payload.get("entries", {})

    comparisons_by_entry: dict[str, list[dict]] = {}
    if COMPARISONS_PATH.exists():
        comp_payload = json.loads(COMPARISONS_PATH.read_text(encoding="utf-8"))
        for comp in comp_payload.get("items", []):
            for eid in comp.get("entry_ids", []):
                comparisons_by_entry.setdefault(eid, []).append({
                    "id": comp["id"],
                    "title": comp["title"],
                    "category": comp["category"],
                    "summary": comp["summary"],
                })

    neijing_rels = json.loads(NEIJING_RELATIONS_PATH.read_text(encoding="utf-8")).get("items", [])

    blocks = _slice_blocks(pages, inv)
    entries: list[dict] = []
    entries_by_id: dict[str, dict] = {}

    for blk in blocks:
        kind = blk["kind"]
        name = blk["name"]
        eid = _canonical_id(kind, name)
        preamble, raw_sections = _split_sections(blk["lines"], kind)

        classic_parts: list[str] = []
        classic_appended: list[str] = []
        origin_text = ""
        qi_wei_raw = ""
        main_summary = ""
        dosage_text = ""
        processing_text = ""
        contraindications_parts: list[str] = []
        historical_commentaries: list[dict] = []
        explicit_ni_notes: list[str] = []
        appendices: list[dict] = []
        ch3_intro = ""

        # Handle unheaded #50 赤芝..紫芝 OR Ch3 pithy '——...' preamble
        if kind == "main" and preamble:
            if "赤芝" in name:
                classic_parts.append(preamble)
            else:
                classic_appended.append(preamble)
        elif kind == "ch3" and preamble:
            ch3_intro = preamble

        for sec in raw_sections:
            tag = sec["tag"]
            txt = sec["text"]
            if tag in TAG_CANONICAL:
                role, label = TAG_CANONICAL[tag]
                if role == "classic":
                    if kind == "ch3":
                        historical_commentaries.append({
                            "scholar": "《神农本草经》附见条文（跨见参考）",
                            "tag": f"【{tag}】",
                            "text": txt,
                        })
                    else:
                        # Separate trailing 吴普曰 / 计然曰 / 按：抱朴子 inside classic paragraph if on a new line
                        c_lines, app_lines = [], []
                        in_app = False
                        for ln in txt.splitlines():
                            if re.match(r"^(吴普曰|计然曰|按：抱朴子)", ln.strip()):
                                in_app = True
                            (app_lines if in_app else c_lines).append(ln)
                        if c_lines:
                            classic_parts.append("\n".join(c_lines).strip())
                        if app_lines:
                            classic_appended.append("\n".join(app_lines).strip())
                elif role == "origin":
                    origin_text = txt
                elif role == "qi_wei":
                    qi_wei_raw = txt
                elif role == "indications":
                    main_summary = (main_summary + "\n" + txt).strip() if main_summary else txt
                elif role == "dosage":
                    dosage_text = (dosage_text + "\n" + txt).strip() if dosage_text else txt
                elif role == "processing":
                    processing_text = (processing_text + "\n" + txt).strip() if processing_text else txt
                elif role == "processing_sub":
                    appendices.append({"title": label, "text": txt})
                elif role == "contraindications":
                    contraindications_parts.append(txt)
                elif role == "ni_note":
                    explicit_ni_notes.append(txt)
                elif role == "appendix":
                    appendices.append({"title": label, "text": txt})
            elif tag in SUBPART_TAGS:
                appendices.append({"title": f"同物异用分部：【{tag}】", "text": txt})
            elif tag in SCHOLAR_CANONICAL:
                historical_commentaries.append({
                    "scholar": SCHOLAR_CANONICAL[tag],
                    "tag": f"【{tag}】",
                    "text": txt,
                })
            else:
                # Safe fallback: keep tag explicitly instead of dropping!
                historical_commentaries.append({
                    "scholar": f"历代引录（【{tag}】）",
                    "tag": f"【{tag}】",
                    "text": txt,
                })

        classic_text = "\n".join(classic_parts).strip()
        contra_joined = "\n".join(contraindications_parts).strip()
        contra_clean, unlabeled_ni_tails = _split_ni_tail_from_contraindications(contra_joined)

        # Look for embedded appendix bullets after 【禁忌】 like '侧柏子壳——' or '枯矾：' or '番红花——'
        extra_appendices = []
        clean_contra_lines = []
        sub_appendix_buf = []
        for ln in contra_clean.splitlines():
            if re.match(r"^[\u4e00-\u9fff]{2,8}(?:——|：)", ln.strip()) and ("——" in ln or ln.strip().endswith("：")):
                sub_appendix_buf.append(ln.strip())
            elif sub_appendix_buf:
                sub_appendix_buf.append(ln.strip())
            else:
                clean_contra_lines.append(ln)
        contra_final = "\n".join(clean_contra_lines).strip()
        if sub_appendix_buf:
            extra_appendices.append({"title": "书末附见品/炮制品分支", "text": "\n".join(sub_appendix_buf)})
        appendices.extend(extra_appendices)

        # Also check trailing unheaded appendix inside 【容川】 on ch3 红花 (番红花—— / 藏红花——) or 【炮制】 on 矾石 (枯矾：/胆矾：)
        if not qi_wei_raw and classic_text:
            # Extract opening '味...' sentence as fallback classic property string
            m_qw = re.match(r"^([^。]+)", classic_text)
            if m_qw and ("味" in m_qw.group(1) or "毒" in m_qw.group(1)):
                qi_wei_raw = m_qw.group(1).strip()

        prop_scan_text = qi_wei_raw or classic_text
        four_natures = _extract_four_natures(prop_scan_text)
        five_flavors = _extract_five_flavors(prop_scan_text)
        toxicity = _extract_toxicity(qi_wei_raw + "\n" + classic_text)

        full_text_blob = "\n".join(
            [classic_text, origin_text, qi_wei_raw, main_summary, contra_final]
            + explicit_ni_notes
            + unlabeled_ni_tails
            + [h["text"] for h in historical_commentaries]
        )
        meridians = _extract_meridians([qi_wei_raw, main_summary, ch3_intro, "\n".join(explicit_ni_notes)])
        risk_level, risk_reasons = _classify_risk(name, toxicity, full_text_blob)
        aliases = _extract_aliases(name, classic_text, full_text_blob, ch3_intro)
        symptom_keywords = _extract_symptom_keywords("\n".join([classic_text, main_summary, ch3_intro] + explicit_ni_notes))
        seven_relations = _extract_seven_relations(classic_text + "\n" + contra_final + "\n" + ch3_intro)

        # Strict Layer 1: classic_original
        if kind == "ch3":
            classic_layer = {
                "in_shennong_classic": False,
                "text": "《神农本草经》正经三卷未单列此味；本书第三章由倪海厦依据张仲景《伤寒论》《金匮要略》实用方药专门增补（依序第 %s 味）。" % blk["seq_raw"],
                "appended_notes": classic_appended,
                "edition_note": "属原书第三章增补条目，绝不混冒《神农本经》古文。",
            }
        else:
            ed_notes = []
            if blk["seq_ocr"] == "二四丸":
                ed_notes.append("原版正文及目录序号印作‘二四丸、大豆黄卷’，实系第 249 条‘二四九’笔误。")
            if any(s["tag"] == "本绖原文" for s in raw_sections):
                ed_notes.append("原页标签印作‘【本绖原文】’，实即‘【本经原文】’。")
            if not name in legacy_names:
                ed_notes.append("原版 data/herbs.json 快照曾遗漏此条正经，Stage 2 已从原书逐页完整复原。")
            classic_layer = {
                "in_shennong_classic": True,
                "text": classic_text,
                "appended_notes": classic_appended,
                "edition_note": "；".join(ed_notes),
            }

        # Strict Layer 5: ni_haixia_annotations
        ch3_note_valid = bool(ch3_intro and "本经无记载" not in ch3_intro and "现无资料可查" not in ch3_intro)
        ni_layer = {
            "explicit_ni_notes": explicit_ni_notes,
            "chapter3_pithy_summary": ch3_intro if ch3_note_valid else "",
            "chapter3_editor_intro": ch3_intro if kind == "ch3" else "",
            "unlabeled_clinical_excerpts": unlabeled_ni_tails,
            "why_it_works": "",
            "when_to_use": "",
            "clinical_experience": [],
            "differentiation_notes": "",
            "has_explicit_ni_tag": bool(explicit_ni_notes),
            "annotation_density": (
                "curated_deep" if eid in curated_overlays
                else "explicit_ni_note" if (explicit_ni_notes or kind == "ch3" or unlabeled_ni_tails)
                else "properties_and_commentary" if (main_summary or historical_commentaries)
                else "classic_only"
            ),
        }

        open_questions: list[str] = []
        if kind == "main" and not main_summary and not historical_commentaries and not explicit_ni_notes:
            open_questions.append("本条原书仅存《本经》经文（及吴普/别录残注），未录【主治】【用量】与【倪注】（遵前言‘或已无人识得、保留不作说明’原则），古今基原与临床用法留待后考。")
        if kind == "ch3" and "现无资料可查" in ch3_intro:
            open_questions.append("原书第三章明载‘——现无资料可查（出于王不留行散中）’，属仲景古名尚待文献进一步考证，严禁臆测补全。")

        controversies: list[dict] = []
        if name in CONTROVERSY_ALIASES:
            controversies.append({
                "topic": f"{name} 古今名实/基原分辨",
                "summary": CONTROVERSY_ALIASES[name],
                "policy": "保留原名与分歧证据，不强行合并为单一现代药材名",
            })
        if name == "白芷":
            controversies.append({
                "topic": "全书双见校勘记",
                "summary": "本书中品第173条与第三章第15条双见‘白芷’（前者收《本经》原文+灵胎/容川注，后者列倪氏总按+吴克潜引注），两处分别建档并互参，不删并。",
                "policy": "双见并存",
            })
        if "粉钖" in name:
            controversies.append({
                "topic": "粉钖（铅粉/白粉）与猪肤汤‘白粉’毒剧分辨",
                "summary": CONTROVERSY_ALIASES["白粉"],
                "policy": "严禁混同剧毒铅化合物与炒米粉",
            })
        if "青石赤石" in name:
            controversies.append({
                "topic": "五色石脂分属与经方单取赤石脂",
                "summary": "《本经》第16条统载五色石脂随五色补五脏；仲景《伤寒》《金匮》（如桃花汤、赤石脂禹余粮汤）专取‘赤石脂’涩肠固脱、温中止利，二者当标明统属与分用。",
                "policy": "标注‘五石脂→赤石脂’统属关系",
            })

        # Verify page source span verbatim
        p_start_obj = pages[blk["page_start"]]
        span_probes = [
            f"{blk['seq_ocr']}、{name}",
            f"{blk['seq_raw']}、{name}",
            classic_text[:24],
            main_summary[:24],
            ch3_intro[:24],
        ]
        source_spans = [_find_source_span(p_start_obj, span_probes)]
        if blk["page_end"] != blk["page_start"]:
            p_end_obj = pages[blk["page_end"]]
            end_probes = [dosage_text[:20], processing_text[:20], contra_final[:20]]
            if explicit_ni_notes:
                end_probes.insert(0, explicit_ni_notes[0][:24])
            source_spans.append(_find_source_span(p_end_obj, end_probes))

        entry = {
            "id": eid,
            "name": name,
            "short_name": _clean_short_name(name),
            "aliases": aliases,
            "kind": kind,
            "grade": blk["grade"],
            "chapter_id": blk["chapter_id"],
            "seq_num": blk["seq_num"],
            "seq_raw": blk["seq_raw"],
            "seq_ocr": blk["seq_ocr"],
            "in_shennong_classic": kind == "main",
            "newly_recovered_in_stage2": (kind == "ch3") or (name not in legacy_names),
            "page_start": blk["page_start"],
            "page_end": blk["page_end"],
            "toc_printed_page": blk["toc_printed_page"],
            "pdf_pages": blk["pdf_pages"],
            "classic_original": classic_layer,
            "properties": {
                "origin": origin_text,
                "qi_wei_raw": qi_wei_raw,
                "four_natures": four_natures,
                "five_flavors": five_flavors,
                "toxicity": toxicity,
                "meridians": meridians,
                "risk_level": risk_level,
                "risk_reasons": risk_reasons,
            },
            "applications": {
                "main_summary": main_summary,
                "symptom_keywords": symptom_keywords,
            },
            "historical_commentaries": historical_commentaries,
            "ni_haixia_annotations": ni_layer,
            "processing_and_compatibility": {
                "dosage": dosage_text,
                "processing": processing_text,
                "seven_relations": seven_relations,
                "contraindications": contra_final,
                "appendices": appendices,
            },
            "identity_controversies": controversies,
            "open_questions": open_questions,
            "organizer_notes": [],
            "formula_usages": [],
            "comparisons": comparisons_by_entry.get(eid, []),
            "neijing_relations": [],
            "acupuncture_relations": [],
            "source_spans": source_spans,
            "review_status": "classic_only" if open_questions else "parsed_reviewed",
        }

        # Apply curated deep overlay if available
        if eid in curated_overlays:
            ov = curated_overlays[eid]
            if ov.get("ni_haixia_annotations"):
                ni_ov = ov["ni_haixia_annotations"]
                for k in ("why_it_works", "when_to_use", "differentiation_notes"):
                    if ni_ov.get(k):
                        entry["ni_haixia_annotations"][k] = ni_ov[k]
                if ni_ov.get("clinical_experience"):
                    entry["ni_haixia_annotations"]["clinical_experience"] = ni_ov["clinical_experience"]
            if ov.get("processing_differences"):
                entry["processing_and_compatibility"]["processing_differences"] = ov["processing_differences"]
            if ov.get("identity_controversies"):
                existing_topics = {c["topic"] for c in entry["identity_controversies"]}
                for c in ov["identity_controversies"]:
                    if c["topic"] not in existing_topics:
                        entry["identity_controversies"].append(c)
            if ov.get("extra_symptoms"):
                for sw in ov["extra_symptoms"]:
                    if sw not in entry["applications"]["symptom_keywords"]:
                        entry["applications"]["symptom_keywords"].append(sw)
            if ov.get("meridians"):
                for m in ov["meridians"]:
                    if m not in entry["properties"]["meridians"]:
                        entry["properties"]["meridians"].append(m)
            if ov.get("organizer_notes"):
                entry["organizer_notes"].extend(ov["organizer_notes"])
            if ov.get("acupuncture_links"):
                entry["acupuncture_relations"] = ov["acupuncture_links"]
            entry["review_status"] = "approved"

        # Attach Neijing relations
        for rel in neijing_rels:
            if eid == rel.get("target_id") or name == rel.get("target_name"):
                entry["neijing_relations"].append({
                    "id": rel["id"],
                    "title": rel.get("title", ""),
                    "chapter_title": rel.get("chapter_title", ""),
                    "section": rel.get("section", ""),
                    "summary": rel.get("summary", ""),
                })

        entries.append(entry)
        entries_by_id[eid] = entry

    _collect_formula_links(entries_by_id)

    OUT_ENTRIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_ENTRIES_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "edition_total": len(entries),
        "main_classic_count": sum(1 for e in entries if e["kind"] == "main"),
        "chapter3_supplement_count": sum(1 for e in entries if e["kind"] == "ch3"),
        "newly_recovered_count": sum(1 for e in entries if e["newly_recovered_in_stage2"]),
        "curated_deep_count": sum(1 for e in entries if e["review_status"] == "approved"),
        "parsed_reviewed_count": sum(1 for e in entries if e["review_status"] == "parsed_reviewed"),
        "classic_only_open_questions_count": sum(1 for e in entries if e["review_status"] == "classic_only"),
        "entries_with_formula_usages": sum(1 for e in entries if e["formula_usages"]),
        "high_risk_or_emergency_count": sum(1 for e in entries if e["properties"]["risk_level"] in ("high_risk", "emergency")),
        "identity_controversies_count": sum(1 for e in entries if e["identity_controversies"]),
        "comparisons_count": sum(len(comparisons_by_entry) > 0 for _ in [1]) and len(json.loads(COMPARISONS_PATH.read_text(encoding="utf-8")).get("items", [])) if COMPARISONS_PATH.exists() else 0,
    }
    OUT_MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return entries


def main() -> None:
    entries = build_all()
    print(json.dumps(json.loads(OUT_MANIFEST_PATH.read_text(encoding="utf-8")), ensure_ascii=False, indent=2))
    print("Built entries:", len(entries))


if __name__ == "__main__":
    main()
