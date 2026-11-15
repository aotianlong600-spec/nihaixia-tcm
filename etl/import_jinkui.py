"""Normalize the source-traceable Jinkui extraction into the app schema.

No extracted formula is dropped. Records that lack a count anchor, have a
count mismatch, or contain missing doses stay in the catalog and are marked.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources" / "jinkui_recipes_source.json"
OUTPUT = ROOT / "brain_data" / "jinkui_formulas.json"
REPORT = ROOT / "brain_data" / "jinkui_report.json"

ALIASES = {
    "灸甘草汤": ["炙甘草汤"],
    "栝篓桂枝汤": ["栝蒌桂枝汤", "瓜蒌桂枝汤"],
    "桂枝龙骨牡蛎汤": ["桂枝加龙骨牡蛎汤"],
    "桅子大黄汤": ["栀子大黄汤"],
    "猪膏髪煎": ["猪膏发煎"],
    "膏髪煎": ["膏发煎"],
    "烧裩散": ["烧裈散"],
    "大黄蟅虫丸": ["大黄䗪虫丸"],
}

KNOWN_SINGLE_HERB = {
    "一物瓜蒂汤",
    "矾石汤",
    "文蛤散",
    "诃黎勒散",
    "狼牙汤",
    "甘草汤",
    "鸡矢白散",
    "蛇床子散",
    "烧裩散",
}

STATUS_LABELS = {
    "complete": "味数已核",
    "partial": "有缺口",
    "mismatch": "味数不符",
    "unchecked": "未找到校验锚点",
    "derived": "加味方",
    "missing": "原文缺",
}

CORRECTIONS = {
    "通脉四逆加猪胆汁汤": {
        "remove": ["四两"],
        "rename": {"猪胆": "猪胆汁"},
        "note": "旧解析把“强人可四两”拆成药味；已回并干姜剂量。",
    },
    "赤豆当归散": {
        "remove": ["芽出"],
        "note": "“芽出，曝干”是赤小豆炮制，不是独立药味。",
    },
    "升麻鳖甲汤": {
        "add": [{"name": "鳖甲", "dose": "手指大一片", "processing": "", "raw": "鳖甲手指大一片"}],
        "note": "旧解析漏鳖甲；按金匮原文首味补入。",
    },
    "鳖甲煎丸": {
        "add": [{"name": "射干", "dose": "三分", "processing": "", "raw": "射干三分"}],
        "note": "旧解析把“柴胡六分射干”粘成一味；按方义和原文顺序拆为柴胡、射干。",
    },
    "厚朴麻黄汤": {
        "add": [{"name": "石膏", "dose": "如鸡子大", "processing": "", "raw": "石膏如鸡子大"}],
        "note": "旧解析漏石膏；按金匮原文补入。",
    },
    "泽漆汤": {
        "remove": ["五斗"],
        "note": "“五斗”是东流水煎法，不是药味。",
    },
    "大青龙汤": {
        "add": [{"name": "石膏", "dose": "如鸡子大一枚", "processing": "", "raw": "石膏如鸡子大一枚"}],
        "note": "旧解析漏石膏；按金匮原文补入。",
    },
    "木防己汤": {
        "add": [{"name": "石膏", "dose": "如鸡子大十二枚", "processing": "", "raw": "石膏如鸡子大十二枚"}],
        "note": "旧解析漏石膏；按金匮原文补入。",
    },
    "猪膏髪煎": {
        "add": [{"name": "乱髪", "dose": "如鸡子大三枚", "processing": "烧", "raw": "乱髪如鸡子大三枚"}],
        "note": "旧解析漏乱髪；按金匮原文补入。",
    },
    "膏髪煎": {
        "add": [{"name": "乱髪", "dose": "如鸡子大三枚", "processing": "烧", "raw": "乱髪如鸡子大三枚"}],
        "note": "旧解析漏乱髪；按金匮原文补入。",
    },
    "桃花汤": {
        "remove": ["用一"],
        "note": "“一半全用，一半研末”属于赤石脂用法，不是独立药味。",
    },
    "王不留行散": {
        "replace": [
            {"name": "王不留行", "dose": "十分", "processing": "八月八日采", "raw": "王不留行十分，八月八日采"},
            {"name": "蒴藋细叶", "dose": "十分", "processing": "七月七日采", "raw": "蒴藋细叶十分，七月七日采"},
            {"name": "桑东南根白皮", "dose": "十分", "processing": "三月三日采", "raw": "桑东南根白皮十分，三月三日采"},
            {"name": "甘草", "dose": "十八分", "processing": "", "raw": "甘草十八分"},
            {"name": "黄芩", "dose": "二分", "processing": "", "raw": "黄芩二分"},
            {"name": "川椒", "dose": "三分", "processing": "", "raw": "川椒三分"},
            {"name": "厚朴", "dose": "二分", "processing": "", "raw": "厚朴二分"},
            {"name": "干姜", "dose": "二分", "processing": "", "raw": "干姜二分"},
            {"name": "芍药", "dose": "二分", "processing": "", "raw": "芍药二分"},
        ],
        "note": "采药日期属于炮制注文；补回被切掉的桑东南根白皮，并保留九味及剂量。",
    },
    "排脓汤": {
        "replace": [
            {"name": "甘草", "dose": "二两", "processing": "", "raw": "甘草二两"},
            {"name": "桔梗", "dose": "二两", "processing": "", "raw": "桔梗二两"},
            {"name": "生姜", "dose": "一两", "processing": "", "raw": "生姜一两"},
            {"name": "大枣", "dose": "十枚", "processing": "", "raw": "大枣十枚"},
        ],
        "note": "旧解析因原文无空格将四味粘成一味；按原文剂量拆开。",
    },
    "枳实芍药散": {
        "replace": [
            {"name": "枳实", "dose": "等分", "processing": "烧令黑，勿太过", "raw": "枳实烧令黑，勿太过"},
            {"name": "芍药", "dose": "等分", "processing": "", "raw": "芍药各等分"},
        ],
        "note": "旧解析漏芍药并把“等分”并入枳实；按原文补回。",
    },
    "牡蛎泽泻散": {
        "add": [
            {"name": "蜀漆", "dose": "等分", "processing": "洗去腥", "raw": "蜀漆洗去腥"},
            {"name": "海藻", "dose": "等分", "processing": "洗去咸", "raw": "海藻洗去咸"},
        ],
        "rename": {"葶苈子以上": "葶苈子"},
        "note": "旧解析漏蜀漆、海藻；按原文七味补齐，全部等分。",
    },
    "栝蒌牡蛎散": {
        "replace": [
            {"name": "栝蒌根", "dose": "等分", "processing": "", "raw": "栝蒌根各等分"},
            {"name": "牡蛎", "dose": "等分", "processing": "熬", "raw": "牡蛎熬，等分"},
        ],
        "note": "原文两味同用等分；旧解析没有把等分分配给前味。",
    },
    "葶苈大枣泻肺汤": {
        "replace": [
            {"name": "葶苈", "dose": "如弹子大", "processing": "熬令黄色，捣丸", "raw": "葶苈熬令黄色，捣丸如弹子大"},
            {"name": "大枣", "dose": "十二枚", "processing": "", "raw": "大枣十二枚"},
        ],
        "note": "葶苈的剂量原文写作“捣丸如弹子大”，不是数字重量。",
    },
    "旋覆花汤": {
        "replace": [
            {"name": "旋覆花", "dose": "三两", "processing": "即金沸草", "raw": "旋覆花三两，即金沸草"},
            {"name": "葱", "dose": "十四茎", "processing": "", "raw": "葱十四茎"},
            {"name": "新绛", "dose": "少许", "processing": "今之茜草", "raw": "新绛（今之茜草）少许"},
        ],
        "note": "旧解析把葱名和剂量粘错，并把“少许”拆成独立药味；按原文三味修正。",
    },
    "硝石矾石散": {
        "replace": [
            {"name": "硝石", "dose": "等分", "processing": "熬黄", "raw": "硝石熬黄"},
            {"name": "矾石", "dose": "等分", "processing": "烧", "raw": "矾石烧，等分"},
        ],
        "note": "两味等分；旧解析把炮制文字并入了药名。",
    },
    "甘草汤": {
        "replace": [
            {"name": "甘草", "dose": "二两", "processing": "", "raw": "甘草二两"},
        ],
        "note": "金匮附方此处只列甘草未载量；剂量借用同书《伤寒论辑义》甘草汤“甘草二两”，并保留跨书校注。",
    },
    "鸡矢白散": {
        "replace": [
            {"name": "鸡矢白", "dose": "方寸匕", "processing": "为末", "raw": "鸡矢白为末，取方寸匕"},
        ],
        "note": "原文为单味药，服用量写作方寸匕；不是以重量计的药材剂量。",
    },
    "蛇床子散": {
        "replace": [
            {"name": "蛇床子", "dose": "如枣大", "processing": "末之，和少量白粉，绵裹", "raw": "蛇床子，末之，和少量白粉，如枣大"},
        ],
        "note": "原文单味药无重量；以“如枣大”为坐药成品用量。",
    },
    "烧裩散": {
        "replace": [
            {"name": "中裩", "dose": "适量", "processing": "近隐处剪烧灰", "raw": "妇人中裩，近隐处，剪烧灰"},
        ],
        "note": "原文药名和剂量存在缺字；保留为原方占位，不补造重量。",
    },
    "蜀漆散": {
        "replace": [
            {"name": "蜀漆", "dose": "等分", "processing": "洗去腥", "raw": "蜀漆洗去腥"},
            {"name": "云母", "dose": "等分", "processing": "烧二日夜", "raw": "云母烧二日夜"},
            {"name": "龙骨", "dose": "等分", "processing": "", "raw": "龙骨各等分"},
        ],
        "note": "旧解析漏蜀漆并把等分并入龙骨；按原文三味等分补齐。",
    },
    "乌头桂枝汤": {
        "add": [
            {"name": "桂枝", "dose": "三两", "processing": "去皮", "raw": "桂枝三两"},
            {"name": "芍药", "dose": "三两", "processing": "", "raw": "芍药三两"},
            {"name": "甘草", "dose": "二两", "processing": "炙", "raw": "甘草二两炙"},
            {"name": "生姜", "dose": "三两", "processing": "切", "raw": "生姜三两"},
            {"name": "大枣", "dose": "十二枚", "processing": "擘", "raw": "大枣十二枚"},
        ],
        "note": "金匮原文说“以桂枝汤五合解之”；按桂枝汤方补全被抽取漏掉的五味。",
    },
}


DOSE_PATTERN = re.compile(
    r"(?P<dose>(?:各)?(?:等分|如鸡子大(?:[一二三四五六七八九十]+枚)?|"
    r"[一二三四五六七八九十百千半\d]+"
    r"(?:两半|枚半|两|枚|升|合|铢|斤|分|尺|寸|个|片|把|握|具|茎|钱匕|方寸匕)))"
)


def extract_dose(raw: str) -> str:
    if "等分" in raw:
        return "等分"
    match = DOSE_PATTERN.search(raw or "")
    return match.group("dose").lstrip("各") if match else ""


def apply_correction(name: str, ingredients: list[dict], item: dict) -> tuple[list[dict], str]:
    correction = CORRECTIONS.get(name)
    if not correction:
        return ingredients, ""
    ingredients = [row for row in ingredients if row["name"] not in correction.get("remove", [])]
    for old, new in correction.get("rename", {}).items():
        for row in ingredients:
            if row["name"] == old:
                row["name"] = new
    if correction.get("replace") is not None:
        ingredients = deepcopy(correction["replace"])
    ingredients.extend(deepcopy(correction.get("add", [])))
    item["_count_corrected"] = True
    return ingredients, correction.get("note", "")


def fill_shared_doses(ingredients: list[dict]) -> None:
    for row in ingredients:
        if not row.get("dose"):
            row["dose"] = extract_dose(row.get("raw", ""))
        if row.get("dose", "").startswith("各"):
            row["dose"] = row["dose"].lstrip("各")
    for index, row in enumerate(ingredients):
        raw = row.get("raw", "")
        if "各" not in raw and row.get("dose") != "等分":
            continue
        if not row.get("dose"):
            continue
        for previous in range(index - 1, -1, -1):
            if ingredients[previous].get("dose"):
                break
            ingredients[previous]["dose"] = row["dose"]


def write_json(path: Path, value) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def status_for(item: dict, ingredients: list[dict]) -> tuple[str, list[str]]:
    issues = []
    if not ingredients:
        return "missing", ["没有解析出组成"]
    if item.get("derivative"):
        derivative = item["derivative"]
        additions = "、".join(part.get("name", "") for part in derivative.get("additions", []))
        issues.append(f"加味方：基础方{derivative.get('base')}，加{additions}")
        return "derived", issues
    if item.get("_count_corrected"):
        count_ok = True
    else:
        count_ok = item.get("count_ok")
    if count_ok is False:
        issues.append(f"原文上{item.get('expected_count')}味，已解析{len(ingredients)}味")
        return "mismatch", issues
    if count_ok is None:
        issues.append("原文未找到“上X味/右X味”校验锚点")
        return "unchecked", issues

    missing_doses = sum(not row.get("dose") for row in ingredients)
    suspects = sum(bool(row.get("suspect")) for row in ingredients)
    if missing_doses:
        issues.append(f"{missing_doses}味缺剂量")
    if suspects:
        issues.append(f"{suspects}味药名待核")
    if item["name"] not in KNOWN_SINGLE_HERB and len(ingredients) == 1 and item.get("expected_count") == 1:
        issues.append("单味记录可能来自加减法，需核对是否应展开基础方")
        return "partial", issues
    return ("partial" if issues else "complete"), issues


def convert(item: dict) -> dict:
    ingredients = []
    for row in item.get("ingredients") or []:
        ingredients.append(
            {
                "name": row.get("name") or row.get("herb_ref") or "",
                "dose": row.get("dose") or "",
                "processing": row.get("prep") or "",
                "raw": row.get("raw") or "",
                "herb_ref": row.get("herb_ref") or "",
                "suspect": bool(row.get("suspect")),
            }
        )
    ingredients, correction_note = apply_correction(item["name"], ingredients, item)
    fill_shared_doses(ingredients)
    status, issues = status_for(item, ingredients)
    source_excerpt = "\n".join(
        part.strip()
        for part in (item.get("composition_raw", ""), item.get("decoction", ""))
        if part and part.strip()
    )
    return {
        "id": item["id"],
        "name": item["name"],
        "aliases": ALIASES.get(item["name"], []),
        "book": "金匮要略",
        "type": item["type"],
        "six_meridian": "",
        "status": status,
        "status_label": STATUS_LABELS[status],
        "chapter": item.get("chapter", ""),
        "indication": item.get("notes", "").split("\n", 1)[0][:180],
        "ingredients": ingredients,
        "source_ingredients": deepcopy(ingredients),
        "expected_count": len(ingredients),
        "source_expected_count": item.get("expected_count") or 0,
        "composition_raw": item.get("composition_raw", ""),
        "decoction": item.get("decoction", ""),
        "notes": item.get("notes", ""),
        "adjuncts": [],
        "derivative": deepcopy(item.get("derivative")),
        "quality": {
            "count_ok": True if item.get("_count_corrected") else item.get("count_ok"),
            "source_count_ok": item.get("count_ok"),
            "correction": correction_note,
            "missing_doses": sum(not row["dose"] for row in ingredients),
            "suspects": sum(bool(row.get("suspect")) for row in ingredients),
            "issues": issues,
        },
        "source": {
            "title": item.get("source", "倪海厦注金匮要略"),
            "page": item.get("page"),
            "chapter": item.get("chapter", ""),
            "path": "sources/jinkui_recipes_source.json",
            "excerpt": source_excerpt,
            "note": "；".join(part for part in [correction_note, *issues] if part)
            if (correction_note or issues)
            else "同条“上X味/右X味”与解析味数一致。",
        },
    }


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    formulas = [convert(item) for item in source]
    by_name = {item["name"]: item for item in formulas}
    for formula in formulas:
        derivative = formula.get("derivative")
        if not derivative:
            continue
        base = by_name.get(derivative.get("base", ""))
        if not base:
            continue
        additions = [
            row
            for row in formula["ingredients"]
            if row["name"] not in {part["name"] for part in base["ingredients"]}
        ]
        formula["ingredients"] = deepcopy(base["ingredients"]) + additions
        formula["expected_count"] = len(formula["ingredients"])
        formula["quality"]["missing_doses"] = sum(not row.get("dose") for row in formula["ingredients"])
        formula["quality"]["issues"].append(
            f"已展开基础方{base['name']}（{len(base['ingredients'])}味）并加入加味药"
        )
        formula["source"]["note"] = "；".join(formula["quality"]["issues"])
    counts: dict[str, int] = {}
    for item in formulas:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    write_json(OUTPUT, formulas)
    write_json(
        REPORT,
        {
            "source_records": len(source),
            "accepted_records": len(formulas),
            "status_counts": counts,
            "missing_doses": sum(
                sum(not row["dose"] for row in item["ingredients"]) for item in formulas
            ),
            "corrected": [
                {"name": item["name"], "note": item["quality"]["correction"]}
                for item in formulas
                if item["quality"].get("correction")
            ],
            "mismatch": [item["name"] for item in formulas if item["status"] == "mismatch"],
            "unchecked": [item["name"] for item in formulas if item["status"] == "unchecked"],
            "derived": [item["name"] for item in formulas if item["status"] == "derived"],
        },
    )
    print(f"jinkui accepted={len(formulas)} status={counts} output={OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
