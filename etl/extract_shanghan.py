"""Extract source-traceable Shanghan formulas from the local Juyi text.

The input is GB18030 plain text. Formula candidates are accepted only when a
nearby "上X味" or "右X味" count can be checked against the parsed ingredients.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "sources" / "shanghan_juyi.txt"
DEFAULT_OUTPUT = ROOT / "brain_data" / "formulas.json"

TYPE_RE = re.compile(r"^(?P<name>[\u4e00-\u9fa5]{1,40}(?:汤|散|丸|膏|煎|酒|饮|丹))方")
COUNT_RE = re.compile(r"(?:上|右)([一二三四五六七八九十]+)味")
INGREDIENT_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fa5]{1,8})"
    r"(?:（(?P<detail>[^）]{0,100})）|\\((?P<ascii_detail>[^)]{0,100})\\))?"
)
CHAPTER_RE = re.compile(r"^辨(?P<meridian>太阳|阳明|少阳|太阴|少阴|厥阴)病")
BLOCK_STOP_RE = re.compile(r"(?:上|右)[一二三四五六七八九十]+味")

NAME_FIXES = {
    "桂枝加浓朴杏子汤": "桂枝加厚朴杏仁汤",
    "桂枝加芍药生姜各一两人参三两新加汤": "桂枝加芍药生姜人参新加汤",
    "去桂加白术汤": "白术附子汤",
    "胡加芒硝汤": "柴胡加芒硝汤",
    "桂枝去芍药加蜀漆牡蛎龙骨救逆汤": "桂枝去芍药加蜀漆牡蛎龙骨救逆汤",
    "旋复代赭汤": "旋覆代赭石汤",
    "栀子柏皮汤": "栀子蘗皮汤",
    "麻黄细辛附子汤": "麻黄附子细辛汤",
    "通脉四逆加猪胆汤": "通脉四逆加猪胆汁汤",
    "干姜黄芩黄连人参汤": "干姜黄连黄芩人参汤",
    "枳实栀子汤": "枳实栀子豉汤",
    "浓朴": "厚朴",
}

INGREDIENT_FIXES = {
    "浓朴": "厚朴",
    "杏子": "杏仁",
    "茱萸": "吴茱萸",
    "白芍药": "芍药",
    "香豉": "豆豉",
    "豉": "豆豉",
    "胶饴": "饴糖",
    "虫虻": "虻虫",
    "太一禹余粮": "禹余粮",
    "旋复花": "旋覆花",
    "代赭": "代赭石",
    "姜": "生姜",
}

DOSE_OVERRIDES = {
    "大青龙汤": {"石膏": "如鸡子大"},
    "桂枝二越婢一汤": {"麻黄": "十八铢"},
    "麻黄汤": {"杏仁": "七十个"},
    "柴胡加龙骨牡蛎汤": {"人参": "一两半", "龙骨": "一两半"},
    "柴胡桂枝汤": {"桂枝": "一两半"},
    "猪苓汤": {
        "猪苓": "一两",
        "滑石": "一两",
        "茯苓": "一两",
        "阿胶": "一两",
        "泽泻": "一两",
    },
}

CURATION = {
    "桂枝加葛根汤": {
        "remove": ["麻黄"],
        "note": "辑义正文列麻黄；同条校注称成本、玉函并无麻黄。",
    },
    "大柴胡汤": {
        "add": [{"name": "大黄", "dose": "二两", "processing": "", "raw": "大黄（二两）"}],
        "note": "辑义正文七味；同条校注称成本、玉函本方有大黄二两。",
    },
    "甘草泻心汤": {
        "add": [{"name": "人参", "dose": "三两", "processing": "", "raw": "人参（三两）"}],
        "note": "辑义正文六味；同条校注认为人参脱落，千金、外台有。",
    },
}

ADJUNCTS = {
    "大陷胸丸": [
        {"name": "甘遂", "dose": "一钱匕", "role": "别捣末"},
        {"name": "白蜜", "dose": "二合", "role": "煎服"},
    ],
    "十枣汤": [{"name": "大枣", "dose": "十枚", "role": "先煮"}],
    "苦酒汤": [{"name": "苦酒", "dose": "适量", "role": "煎服溶剂"}],
    "猪肤汤": [
        {"name": "白蜜", "dose": "一升", "role": "后下"},
        {"name": "白粉", "dose": "五合", "role": "后下"},
    ],
}

PROCESSING_OVERRIDES = {
    "大青龙汤": {"石膏": "碎"},
}

MANUAL_FORMULAS = [
    {
        "id": "shanghan:猪胆汁方",
        "name": "猪胆汁方",
        "book": "伤寒论",
        "type": "导",
        "status": "manual",
        "status_label": "同段原文补",
        "six_meridian": "阳明",
        "indication": "阳明病津液内竭，大便硬而不可攻，宜导而通之。",
        "ingredients": [
            {
                "name": "大猪胆",
                "dose": "一枚",
                "processing": "取汁，和少许法醋，灌谷道",
                "raw": "大猪胆一枚",
            }
        ],
        "expected_count": 1,
        "source_expected_count": 1,
        "source_ingredients": [
            {
                "name": "大猪胆",
                "dose": "一枚",
                "processing": "取汁，和少许法醋，灌谷道",
                "raw": "大猪胆一枚",
            }
        ],
        "composition_raw": "大猪胆一枚，泻汁，和少许法醋。",
        "decoction": "以灌谷道内，如一食顷，当大便出宿食恶物。",
        "adjuncts": [],
        "source": {
            "title": "伤寒论辑义",
            "line": 4801,
            "path": "sources/shanghan_juyi.txt",
            "excerpt": "又大猪胆一枚。泻汁。和少许法醋。以灌谷道内。如一食顷。当大便出宿食恶物。甚效。",
            "note": "辑义附于蜜煎方后，无独立“上X味”计数锚点；本条按同段原文补入。",
        },
    },
    {
        "id": "shanghan:烧裈散",
        "name": "烧裈散",
        "book": "伤寒论",
        "type": "散",
        "status": "manual",
        "status_label": "缺字校补",
        "six_meridian": "阴阳易",
        "indication": "伤寒阴阳易之为病，身体重，少气，少腹里急，或引阴中拘挛。",
        "ingredients": [
            {
                "name": "妇人中裈近隐处",
                "dose": "适量",
                "processing": "取烧作灰",
                "raw": "妇人中裈近隐处，取烧作灰",
            }
        ],
        "expected_count": 1,
        "source_expected_count": 1,
        "source_ingredients": [
            {
                "name": "妇人中裈近隐处",
                "dose": "适量",
                "processing": "取烧作灰",
                "raw": "妇人中裈近隐处，取烧作灰",
            }
        ],
        "composition_raw": "妇人中裈近隐处，取烧作灰。",
        "decoction": "上一味。水服方寸匕，日三服。小便即利，阴头微肿，此为愈矣。",
        "adjuncts": [],
        "source": {
            "title": "伤寒论辑义",
            "line": 6873,
            "path": "sources/shanghan_juyi.txt",
            "excerpt": "烧 散方妇人中 近隐处。取烧作灰。上一味。水服方寸匕。日三服。",
            "note": "原文该条有缺字；方名按通行名录作“烧裈散”，组成按同条上下文保留。",
        },
    },
    {
        "id": "shanghan:土瓜根方",
        "name": "土瓜根方",
        "book": "伤寒论",
        "type": "导",
        "status": "missing",
        "status_label": "原文缺",
        "six_meridian": "阳明",
        "indication": "阳明病津液内竭，大便硬而不可攻，宜导而通之。",
        "ingredients": [],
        "expected_count": 0,
        "source_expected_count": 0,
        "source_ingredients": [],
        "composition_raw": "",
        "decoction": "",
        "adjuncts": [],
        "source": {
            "title": "伤寒论辑义",
            "line": 4809,
            "path": "sources/shanghan_juyi.txt",
            "excerpt": "土瓜根方缺。肘后方。治大便不通。土瓜根。采根捣汁。筒吹入肛门内。取通。此与上猪胆方同义。",
            "note": "辑义原文明确标注“土瓜根方缺”；未用后世肘后方用法冒充仲景原方。",
        },
    },
]

PENDING_FORMULAS = [
    {
        "name": "土瓜根方",
        "line": 4809,
        "reason": "辑义明言“土瓜根方缺”；仅存后世肘后方用法，不能冒充仲景原方。",
    }
]

TYPE_OVERRIDES = {
    "四逆散": "散",
    "五苓散": "散",
    "文蛤散": "散",
    "白散": "散",
    "瓜蒂散": "散",
    "半夏散及汤": "散",
    "烧裈散": "散",
    "牡蛎泽泻散": "散",
}

SKIP_NAMES = {
    # Formula variants quoted inside commentary, not separate canonical entries.
    "葛根黄连汤",
    "人参汤",
    "黄芩人参汤",
}


def cn_number(value: str) -> int:
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + digits.get(value[1], 0)
    if "十" in value:
        head, _, tail = value.partition("十")
        return digits.get(head, 1) * 10 + (digits.get(tail, 0) if tail else 0)
    return digits.get(value, 0)


def clean_name(name: str) -> str:
    name = name.replace("浓朴", "厚朴").replace("杏子", "杏仁")
    return NAME_FIXES.get(name, name)


def source_lines(path: Path) -> list[str]:
    return path.read_bytes().decode("gb18030").splitlines()


def write_json(path: Path, value) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def chapter_at(lines: list[str], index: int) -> str:
    for cursor in range(index, -1, -1):
        match = CHAPTER_RE.match(lines[cursor].strip())
        if match:
            return match.group("meridian")
    return ""


def candidate_starts(lines: list[str]) -> list[tuple[int, str, str]]:
    candidates = []
    for index, raw in enumerate(lines):
        line = raw.strip()
        match = TYPE_RE.match(line)
        if not match or line.endswith("汤方后。"):
            continue
        source_name = match.group("name")
        name = clean_name(source_name)
        if name in SKIP_NAMES:
            continue
        candidates.append((index, name, line[match.end() :]))
    return candidates


def find_count(line: str) -> re.Match[str] | None:
    depth = 0
    for index, char in enumerate(line):
        if char == "（":
            depth += 1
        elif char == "）":
            depth = max(0, depth - 1)
        elif depth == 0:
            match = COUNT_RE.match(line, index)
            if match:
                return match
    return None


def find_stop(lines: list[str], start: int, end: int) -> tuple[int, int, re.Match[str]] | None:
    for index in range(start, min(end, start + 30)):
        match = find_count(lines[index])
        if match:
            return index, match.start(), match
    return None


def indication_before(lines: list[str], start: int, name: str) -> str:
    text = "\n".join(lines[max(0, start - 14) : start])
    compact = re.sub(r"\s+", "", text)
    marker = f"{name}主之"
    at = compact.rfind(marker)
    if at < 0:
        return ""
    sentence = re.split(r"[。！？]", compact[: at + len(marker)])[-1]
    return sentence[-220:] if len(sentence) >= 8 else ""


def tokenize_composition(text: str) -> list[str]:
    text = text.replace("\n", "")
    text = re.sub(
        r"（[^）]*）",
        lambda match: match.group(0).replace(" ", "").replace("\u3000", ""),
        text,
    )
    depth = 0
    cut = None
    for index, char in enumerate(text):
        if char == "（":
            depth += 1
        elif char == "）":
            depth = max(0, depth - 1)
        elif depth == 0 and COUNT_RE.match(text, index):
            cut = index
            break
    if cut is not None:
        text = f"{text[:cut]} {text[cut:]}"
    text = text.replace("）", "） ").replace(")", ") ")
    tokens = [token.strip("，,、;；。 ") for token in re.split(r"\s+", text)]
    return [token for token in tokens if token]


def parse_ingredients(text: str) -> list[dict]:
    tokens = tokenize_composition(text)
    items: list[dict] = []
    for token in tokens:
        if BLOCK_STOP_RE.match(token) or token.startswith("○"):
            break
        match = INGREDIENT_RE.match(token)
        if not match:
            continue
        name = INGREDIENT_FIXES.get(match.group("name"), match.group("name"))
        if name in {"上", "右", "方", "本云", "成本", "玉函", "又", "案", "若"}:
            continue
        detail = (match.group("detail") or match.group("ascii_detail") or "").strip()
        detail = detail.split("○", 1)[0].strip()
        raw = token
        items.append(
            {
                "name": name,
                "dose": "",
                "processing": detail,
                "raw": raw,
            }
        )
        if "各等分" in detail:
            for previous in items:
                previous["dose"] = previous["dose"] or "等分"
            items[-1]["processing"] = detail.replace("各等分", "").strip("。，, ")

    # An empty detail means the source used a shared dose from a later "各" item.
    for index, item in enumerate(items):
        detail = item["processing"]
        if not detail:
            continue
        if not re.search(r"[一二三四五六七八九十百半\d].*(?:两|枚|升|合|铢|斤|分|尺|寸|个|片|把|握|具|茎|枚半|钱匕|方寸匕)", detail):
            continue
        dose_match = re.search(
            r"(各)?((?:[一二三四五六七八九十百千半\d]+"
            r"(?:两半|枚半|两|枚|升|合|铢|斤|分|尺|寸|个|片|把|握|具|茎|钱匕|方寸匕))+)",
            detail,
        )
        if not dose_match:
            continue
        dose = dose_match.group(2).strip()
        if dose_match.group(1):
            cursor = index - 1
            while cursor >= 0:
                if items[cursor]["dose"]:
                    cursor -= 1
                    continue
                items[cursor]["dose"] = dose
                cursor -= 1
        item["dose"] = dose
        item["processing"] = detail.replace(dose_match.group(0), "").strip("。，, ")

    return items


def parse_decoction(lines: list[str], stop_line: int, stop_at: int, block_end: int) -> str:
    first = lines[stop_line][stop_at:].strip()
    collected = [first] if first else []
    for index in range(stop_line + 1, min(block_end, stop_line + 8)):
        line = lines[index].strip()
        if not line:
            break
        if TYPE_RE.match(line):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def apply_common_dose(ingredients: list[dict], decoction: str) -> None:
    match = re.search(
        r"(?:上|右)[一二三四五六七八九十]+味[。，,\s]*(?:各)?"
        r"(?P<dose>等分|(?:[一二三四五六七八九十百千半\d]+"
        r"(?:两半|枚半|两|枚|升|合|铢|斤|分|尺|寸|个|片|把|握|具|茎|钱匕|方寸匕))+)",
        decoction,
    )
    if not match:
        return
    dose = match.group("dose")
    for item in ingredients:
        item["dose"] = item["dose"] or dose


def extract(source: Path) -> tuple[list[dict], list[dict]]:
    lines = source_lines(source)
    candidates = candidate_starts(lines)
    accepted: dict[str, dict] = {}
    rejected: list[dict] = []

    for position, (start, name, remainder) in enumerate(candidates):
        next_start = candidates[position + 1][0] if position + 1 < len(candidates) else len(lines)
        found = find_stop(lines, start, next_start)
        if not found:
            rejected.append({"line": start + 1, "name": name, "reason": "未找到味数锚点"})
            continue
        stop_line, stop_at, count_match = found
        expected = cn_number(count_match.group(1)) if count_match else 0

        composition_parts = [remainder]
        for index in range(start + 1, stop_line + 1):
            line = lines[index]
            composition_parts.append(line[:stop_at] if index == stop_line else line)
        composition_raw = "\n".join(part.strip() for part in composition_parts if part.strip())
        ingredients = parse_ingredients(composition_raw)
        source_ingredients = deepcopy(ingredients)

        if not ingredients:
            rejected.append({"line": start + 1, "name": name, "reason": "未解析出组成"})
            continue
        recovered_from = ""
        if expected and expected != len(ingredients) and "加" in name:
            prefix = name.split("加", 1)[0]
            base_name = prefix if prefix.endswith(("汤", "散", "丸", "煎")) else f"{prefix}{name[-1]}"
            base = accepted.get(base_name)
            if base:
                additions = [item for item in ingredients if item["name"] not in {i["name"] for i in base["ingredients"]}]
                merged = list(base["ingredients"]) + additions
                if len(merged) == expected:
                    ingredients = merged
                    recovered_from = f"{base_name}加味组成校补"
        if expected and expected != len(ingredients):
            rejected.append(
                {
                    "line": start + 1,
                    "name": name,
                    "reason": f"味数不符：上{expected}味，解析{len(ingredients)}味",
                    "composition": composition_raw[:240],
                }
            )
            continue

        curation = CURATION.get(name, {})
        if curation.get("remove"):
            ingredients = [item for item in ingredients if item["name"] not in curation["remove"]]
        for addition in curation.get("add", []):
            item = deepcopy(addition)
            item["origin"] = "同页校注补"
            ingredients.append(item)

        type_match = re.search(r"(汤|散|丸|膏|煎|酒|饮|丹)$", name)
        formula_type = TYPE_OVERRIDES.get(name) or (type_match.group(1) if type_match else "")
        decoction = parse_decoction(lines, stop_line, stop_at, next_start)
        apply_common_dose(ingredients, decoction)
        for item in ingredients:
            item["dose"] = DOSE_OVERRIDES.get(name, {}).get(item["name"], item["dose"])
            item["processing"] = PROCESSING_OVERRIDES.get(name, {}).get(item["name"], item["processing"])

        formula = {
            "id": f"shanghan:{name}",
            "name": name,
            "book": "伤寒论",
            "type": formula_type,
            "status": "complete",
            "status_label": "味数已核",
            "six_meridian": chapter_at(lines, start),
            "indication": indication_before(lines, start, name),
            "ingredients": ingredients,
            "source_ingredients": source_ingredients,
            "expected_count": len(ingredients),
            "source_expected_count": expected,
            "composition_raw": composition_raw,
            "decoction": decoction,
            "adjuncts": deepcopy(ADJUNCTS.get(name, [])),
            "source": {
                "title": "伤寒论辑义",
                "line": start + 1,
                "path": "sources/shanghan_juyi.txt",
                "excerpt": "\n".join(lines[start : min(stop_line + 3, next_start)]).strip(),
            },
        }
        if curation.get("note"):
            formula["source"]["note"] = curation["note"]
        if recovered_from:
            formula["source"]["recovery"] = recovered_from
        if (
            formula["source_expected_count"] != len(formula["source_ingredients"])
            or formula["source_expected_count"] != len(formula["ingredients"])
            or recovered_from
        ):
            formula["status"] = "variant"
            formula["status_label"] = "版本有差异"
        existing = accepted.get(name)
        if existing is None or len(formula["ingredients"]) > len(existing["ingredients"]):
            accepted[name] = formula

    for item in MANUAL_FORMULAS:
        accepted.setdefault(item["name"], item)
    return sorted(accepted.values(), key=lambda item: item["source"]["line"]), rejected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=ROOT / "brain_data" / "formulas_report.json")
    args = parser.parse_args()

    formulas, rejected = extract(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, formulas)
    write_json(
        args.report,
        {
            "accepted": len(formulas),
            "rejected": rejected,
            "pending": PENDING_FORMULAS,
            "type_counts": {
                kind: sum(1 for item in formulas if item["type"] == kind)
                for kind in ("汤", "散", "丸", "膏", "煎", "导")
            },
        },
    )
    print(f"accepted={len(formulas)} rejected={len(rejected)} output={args.output}")
    for item in rejected:
        print(f"  line {item['line']:>4} {item['name']}: {item['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
