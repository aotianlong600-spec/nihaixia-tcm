"""Modular classical TCM clinical differentiation rules, redlines, and multi-school cross-references.

Sources grounded in the curated classical corpus and reference TCM skills:
- 《黄帝内经》《黄帝外经》《伤寒论》《金匮要略》《神农本草经》
- 倪海厦《人纪》《汉唐医案/经验方》
- 丹波元简《伤寒论辑义》、大冢敬节《伤寒论解说》、徐灵胎《慎疾刍言/兰台轨范/伤寒论类方》、陈士铎《石室秘录》、唐容川《血证论》、汪汝麟《证因方论》

All outputs carry strict 5-layer attribution and high-risk clinical safety boundaries
for educational syndrome-differentiation research only (non-prescribing).
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from app.syndrome_atoms_ext import EXPANDED_PATTERN_ATOMS, EXPANDED_SYMPTOM_CANONICAL_RULES
from retrieval.index import _locate_in_body


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data"
LIB_SOURCES_DIR = ROOT / "sources" / "library"


# ---------------------------------------------------------------------------
# 1. Explicit Polarity Map for Legacy Pattern Atoms (fixes implicit "balanced")
# ---------------------------------------------------------------------------
LEGACY_ATOM_POLARITIES: dict[str, str] = {
    "atom:zhenwu": "yang_def_cold",
    "atom:danggui-shaoyao": "balanced",
    "atom:chaihu-guizhi-ganjiang": "half_interior",
    "atom:wenjing": "balanced",
    "atom:maziren": "heat_excess",
    "atom:xiaochaihu": "half_interior",
    "atom:guizhi": "warm_exterior",
    "atom:gegengtang": "warm_exterior",
    "atom:wuling": "balanced",
    "atom:xiongbi": "yang_def_cold",
    "atom:sini": "yang_def_cold",
    "atom:lizhong": "yang_def_cold",
    "atom:xiaoqinglong": "warm_exterior",
    "atom:dachengqi": "heat_excess",
    "atom:suanzaoren": "yin_def_heat",
    "atom:wuzhuyu": "yang_def_cold",
    "atom:xiexin-huangtu": "balanced",
    "atom:linggui-zhugan": "yang_def_cold",
    "atom:banxia-xiexin": "balanced",
    "atom:sini-san": "half_interior",
    "atom:shenqi-wan": "yang_def_cold",
    "atom:guizhi-fuling": "blood_stasis",
    "atom:danggui-sini": "yang_def_cold",
}

# Formulas in the same close intensification family should not form redundant 2-formula compounds.
REDUNDANT_SIBLING_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"shanghan:白虎汤", "shanghan:白虎加人参汤", "shanghan:竹叶石膏汤", "jinkui:白虎加桂枝汤"}),
    frozenset({"shanghan:大承气汤", "shanghan:小承气汤", "shanghan:调胃承气汤", "jinkui:厚朴三物汤"}),
    frozenset({"shanghan:四逆汤", "shanghan:通脉四逆汤", "shanghan:干姜附子汤", "shanghan:茯苓四逆汤", "shanghan:四逆加人参汤", "shanghan:通脉四逆加猪胆汁汤"}),
    frozenset({"shanghan:理中丸", "jinkui:人参汤", "jinkui:甘草干姜汤"}),
    frozenset({"shanghan:小柴胡汤", "shanghan:大柴胡汤", "shanghan:柴胡桂枝汤", "shanghan:柴胡桂枝干姜汤", "shanghan:柴胡加芒硝汤", "jinkui:柴胡去半夏加栝蒌汤"}),
    frozenset({"shanghan:麻黄汤", "shanghan:大青龙汤", "shanghan:桂枝汤", "shanghan:葛根汤", "shanghan:桂枝麻黄各半汤", "shanghan:桂枝二麻黄一汤", "shanghan:桂枝二越婢一汤"}),
    frozenset({"shanghan:桂枝汤", "shanghan:桂枝加葛根汤", "shanghan:桂枝加附子汤", "shanghan:桂枝加厚朴杏仁汤", "shanghan:桂枝加芍药汤", "jinkui:阳旦汤", "jinkui:桂枝加黄耆汤"}),
    frozenset({"shanghan:栀子豉汤", "shanghan:栀子甘草豉汤", "shanghan:栀子生姜豉汤", "shanghan:栀子厚朴汤", "shanghan:栀子干姜汤", "shanghan:枳实栀子豉汤"}),
    frozenset({"shanghan:半夏泻心汤", "shanghan:生姜泻心汤", "shanghan:甘草泻心汤"}),
    frozenset({"shanghan:小建中汤", "jinkui:大建中汤", "jinkui:黄耆建中汤"}),
    frozenset({"jinkui:甘草干姜汤", "jinkui:桂苓五味甘草汤", "jinkui:苓甘五味姜辛汤", "jinkui:苓甘五味姜辛半夏汤", "jinkui:苓甘五味加姜辛半夏杏仁汤", "jinkui:苓甘五味加姜辛夏杏大黄汤"}),
    frozenset({"jinkui:小半夏汤", "jinkui:小半夏加茯苓汤", "jinkui:大半夏汤", "jinkui:干姜人参半夏丸", "jinkui:生姜半夏汤"}),
    frozenset({"jinkui:百合地黄汤", "jinkui:百合知母汤", "jinkui:百合滑石代赭汤", "jinkui:百合鸡子汤", "jinkui:百合滑石散"}),
    frozenset({"jinkui:防己黄耆汤", "jinkui:防己茯苓汤", "jinkui:木防己汤", "jinkui:木防己去石膏加茯苓芒硝汤"}),
    frozenset({"jinkui:大乌头煎", "jinkui:乌头桂枝汤"}),
    frozenset({"shanghan:黄芩汤", "shanghan:黄芩加半夏生姜汤"}),
    frozenset({"shanghan:白通汤", "shanghan:白通加猪胆汁汤"}),
    frozenset({"shanghan:当归四逆汤", "shanghan:当归四逆加吴茱萸生姜汤"}),
    frozenset({"shanghan:抵当汤", "shanghan:抵当丸"}),
    frozenset({"shanghan:大陷胸汤", "shanghan:大陷胸丸"}),
    # Cold-fluid wheezing siblings sharing 麻黄/细辛/半夏/五味子 core
    frozenset({"jinkui:射干麻黄汤", "shanghan:小青龙汤", "jinkui:厚朴麻黄汤", "jinkui:小青龙加石膏汤", "jinkui:泽漆汤"}),
    # Orthographic / cross-book identical base formulas
    frozenset({"jinkui:苓桂术甘汤", "shanghan:茯苓桂枝白术甘草汤"}),
    frozenset({"shanghan:柴胡桂枝干姜汤", "jinkui:柴胡桂姜汤"}),
    frozenset({"jinkui:肾气丸", "jinkui:八味肾气丸"}),
    frozenset({"shanghan:炙甘草汤", "jinkui:灸甘草汤"}),
    frozenset({"jinkui:猪膏髪煎", "jinkui:膏髪煎"}),
    frozenset({"jinkui:麻黄附子汤", "shanghan:麻黄附子细辛汤"}),
    # 真武汤 vs 附子汤 share 茯苓、芍药、白术、附子 4/5 herbs (differ only 生姜 vs 人参)
    frozenset({"shanghan:真武汤", "shanghan:附子汤", "jinkui:附子汤"}),
)

CANONICAL_FORMULA_ALIASES: dict[str, str] = {
    "茯苓桂枝白术甘草汤": "苓桂术甘汤",
    "柴胡桂姜汤": "柴胡桂枝干姜汤",
    "八味肾气丸": "肾气丸",
    "崔氏八味丸": "肾气丸",
    "灸甘草汤": "炙甘草汤",
    "膏髪煎": "猪膏髪煎",
    "猪膏发煎": "猪膏髪煎",
}


def canonical_formula_name(name: str) -> str:
    """Normalize known recension/typo variants to a single canonical formula name."""
    cleaned = (name or "").strip()
    return CANONICAL_FORMULA_ALIASES.get(cleaned, cleaned)


def _norm_herb_family(herb: str) -> str:
    h = re.sub(r"[炮制生炙酒醋盐蜜炒煅水洗去心皮尖]+", "", (herb or "").strip())
    if not h:
        return (herb or "").strip()
    if any(k in herb for k in ("乌头", "川乌", "草乌", "天雄")):
        return "乌头"
    if "附子" in herb:
        return "附子"
    if "半夏" in herb:
        return "半夏"
    if "栝蒌根" in herb or "瓜蒌根" in herb or "天花粉" in herb:
        return "天花粉"
    if any(k in herb for k in ("瓜蒌", "栝蒌", "栝篓")):
        return "瓜蒌"
    if "贝母" in herb:
        return "贝母"
    if "大戟" in herb:
        return "大戟"
    if "甘遂" in herb:
        return "甘遂"
    if "芫花" in herb:
        return "芫花"
    if "海藻" in herb:
        return "海藻"
    if "甘草" in herb:
        return "甘草"
    if "藜芦" in herb:
        return "藜芦"
    if "细辛" in herb:
        return "细辛"
    if "芍药" in herb or "白芍" in herb or "赤芍" in herb:
        return "芍药"
    if "人参" in herb or "党参" in herb:
        return "人参"
    if "丹参" in herb:
        return "丹参"
    if "玄参" in herb:
        return "玄参"
    if "沙参" in herb:
        return "沙参"
    if "苦参" in herb:
        return "苦参"
    if "白蔹" in herb:
        return "白蔹"
    if "白及" in herb:
        return "白及"
    if "芒硝" in herb or "朴硝" in herb or "牙硝" in herb:
        return "芒硝"
    if "三棱" in herb:
        return "三棱"
    if "硫黄" in herb or "硫磺" in herb:
        return "硫黄"
    if "五灵脂" in herb:
        return "五灵脂"
    if "郁金" in herb:
        return "郁金"
    if "丁香" in herb:
        return "丁香"
    if "巴豆" in herb:
        return "巴豆"
    if "牵牛" in herb:
        return "牵牛"
    if "狼毒" in herb:
        return "狼毒"
    if "密陀僧" in herb:
        return "密陀僧"
    if "肉桂" in herb or "官桂" in herb:
        return "肉桂"
    if "赤石脂" in herb:
        return "赤石脂"
    if "麻黄" in herb:
        return "麻黄"
    if "大黄" in herb:
        return "大黄"
    return (herb or "").strip()


_SHIBAFAN_RULES: tuple[tuple[frozenset[str], frozenset[str], str, bool], ...] = (
    (frozenset({"甘草"}), frozenset({"甘遂", "大戟", "芫花", "海藻"}), "十八反「藻戟遂芫俱战草」（甘草反甘遂/大戟/芫花/海藻）", True),
    (frozenset({"乌头"}), frozenset({"半夏", "瓜蒌", "天花粉", "贝母", "白蔹", "白及"}), "十八反「半蒌贝蔹及攻乌」（生/制乌头天雄反半夏/瓜蒌/天花粉/贝母/白蔹/白及）", True),
    (frozenset({"附子"}), frozenset({"半夏", "瓜蒌", "贝母", "白蔹", "白及"}), "十八反「半蒌贝蔹及攻乌」（现代药典附子反半夏/瓜蒌/贝母/白蔹/白及；跨方合方默认阻断，仅《金匮》单方附子粳米等自有古配特例）", True),
    (frozenset({"附子"}), frozenset({"天花粉"}), "药典十八反慎配「附子 × 天花粉（栝蒌根）」（提示：现代药典列附子反天花粉，而《金匮》栝蒌瞿麦丸及人纪柴胡桂枝干姜汤合真武汤亦有炮附配栝蒌根古例，临床须炮制久煎并严审师承法度）", False),
    (frozenset({"藜芦"}), frozenset({"人参", "沙参", "丹参", "玄参", "苦参", "细辛", "芍药"}), "十八反「诸参辛芍叛藜芦」", True),
)

_SHIJIUWEI_RULES: tuple[tuple[str, str, str], ...] = (
    ("硫黄", "芒硝", "十九畏「硫黄原是火中精，朴硝一见便相争」"),
    ("巴豆", "牵牛", "十九畏「巴豆性烈最为毒，偏与牵牛不顺情」"),
    ("丁香", "郁金", "十九畏「丁香莫与郁金见」"),
    ("芒硝", "三棱", "十九畏「牙硝难合京三棱」"),
    ("人参", "五灵脂", "十九畏「人参最怕五灵脂」"),
    ("狼毒", "密陀僧", "十九畏「狼毒最怕密陀僧」"),
    ("肉桂", "赤石脂", "十九畏「官桂善能调冷气，若逢石脂便相欺」"),
)

_POTENT_TOXIC_FAMILIES: frozenset[str] = frozenset({"乌头", "附子", "麻黄", "细辛", "甘遂", "大戟", "芫花", "巴豆", "大黄"})


def detect_compound_herb_conflicts(
    herbs1: list[str],
    herbs2: list[str],
    name1: str = "",
    name2: str = "",
) -> dict[str, Any]:
    """Detect 十八反 / 十九畏 incompatibilities and overlapping potent herbs when combining two formulas."""
    fam1 = {_norm_herb_family(h) for h in herbs1 if h}
    fam2 = {_norm_herb_family(h) for h in herbs2 if h}
    alerts: list[str] = []
    blocking_alerts: list[str] = []
    blocking = False

    for grp_a, grp_b, desc, is_block in _SHIBAFAN_RULES:
        hit1 = (fam1 & grp_a) and (fam2 & grp_b)
        hit2 = (fam2 & grp_a) and (fam1 & grp_b)
        if hit1 or hit2:
            left = "、".join(sorted((fam1 & grp_a) | (fam1 & grp_b)))
            right = "、".join(sorted((fam2 & grp_a) | (fam2 & grp_b)))
            msg = f"{name1 or '主方'}（含{left}）与{name2 or '配伍方'}（含{right}）触及{desc}"
            alerts.append(msg)
            if is_block:
                blocking = True
                blocking_alerts.append(msg)

    for ha, hb, desc in _SHIJIUWEI_RULES:
        if (ha in fam1 and hb in fam2) or (hb in fam1 and ha in fam2):
            msg = f"{name1 or '主方'}与{name2 or '配伍方'}（{ha} × {hb}）触及{desc}"
            alerts.append(msg)
            blocking = True
            blocking_alerts.append(msg)

    potent_overlap = sorted((fam1 & fam2) & _POTENT_TOXIC_FAMILIES)
    if potent_overlap:
        alerts.append(f"两方均含峻烈/有毒或峻汗药味：{'、'.join(potent_overlap)}，严禁机械叠加剂量")

    return {
        "blocking": blocking,
        "blocking_alerts": blocking_alerts,
        "alerts": alerts,
        "potent_overlap": potent_overlap,
    }


_POLARITY_TONGUE_WEIGHTS: dict[str, dict[str, int]] = {
    "yang_def_cold": {"舌淡胖滑": 10, "舌白厚湿": 10, "舌黄厚燥": -16},
    "heat_excess": {"舌黄厚燥": 10, "舌白厚湿": -16, "舌淡胖滑": -16},
    "yin_def_heat": {"舌红少苔": 12, "舌白厚湿": -12},
    "blood_stasis": {"舌紫暗瘀": 14},
    "half_interior": {"舌黄厚燥": 4, "舌淡胖滑": 4},
}

_ATOM_TONGUE_OVERRIDES: dict[str, dict[str, int]] = {
    "atom:zhenwu": {"舌淡胖滑": 16, "舌白厚湿": 12, "舌黄厚燥": -18},
    "atom:sini": {"舌淡胖滑": 14, "舌白厚湿": 14, "舌黄厚燥": -20},
    "atom:tongmai-sini": {"舌白厚湿": 14, "舌淡胖滑": 14, "舌黄厚燥": -20},
    "atom:lizhong": {"舌淡胖滑": 16, "舌白厚湿": 12, "舌黄厚燥": -18},
    "atom:linggui-zhugan": {"舌淡胖滑": 16, "舌白厚湿": 10},
    "atom:baihu": {"舌黄厚燥": 16, "舌白厚湿": -20, "舌淡胖滑": -18},
    "atom:baihu-jiarenshen": {"舌黄厚燥": 14, "舌红少苔": 10, "舌白厚湿": -20},
    "atom:dachengqi": {"舌黄厚燥": 18, "舌白厚湿": -20, "舌淡胖滑": -18},
    "atom:tiaowei-chengqi": {"舌黄厚燥": 16, "舌白厚湿": -18},
    "atom:jinkui-xiexin": {"舌黄厚燥": 14, "舌红少苔": 10, "舌白厚湿": -16},
    "atom:huanglian-ejiao": {"舌红少苔": 18, "舌白厚湿": -16},
    "atom:zhigancao": {"舌红少苔": 16, "舌白厚湿": -12},
    "atom:maimendong": {"舌红少苔": 18, "舌白厚湿": -14},
    "atom:baihe-dihuang": {"舌红少苔": 16, "舌白厚湿": -14},
    "atom:zhuye-shigao": {"舌红少苔": 16, "舌黄厚燥": 8, "舌白厚湿": -16},
    "atom:zhuling": {"舌红少苔": 14, "舌白厚湿": -12},
    "atom:taohe-chengqi": {"舌紫暗瘀": 16, "舌黄厚燥": 10},
    "atom:didang": {"舌紫暗瘀": 18},
    "atom:didang-wan": {"舌紫暗瘀": 18},
    "atom:guizhi-fuling": {"舌紫暗瘀": 16},
    "atom:dahuang-zhechong": {"舌紫暗瘀": 16},
    "atom:wenjing": {"舌紫暗瘀": 14, "舌红少苔": 8},
    "atom:xiayuxue-tang": {"舌紫暗瘀": 16},
    "atom:daxianxiong": {"舌黄厚燥": 12, "舌白厚湿": -26},
    "atom:banxia-xiexin": {"舌白厚湿": 8, "舌黄厚燥": 8},
}


def score_atom_tongue(atom: dict[str, Any], tongues: list[str]) -> tuple[int, list[str], str]:
    """Score structured tongue findings against an atom's tongue_weights, symptom_weights('舌*'), overrides, and polarity."""
    if not tongues:
        return 0, [], ""
    weights: dict[str, int] = dict(_POLARITY_TONGUE_WEIGHTS.get(atom.get("polarity", "balanced"), {}))
    weights.update(_ATOM_TONGUE_OVERRIDES.get(atom.get("atom_id", ""), {}))
    for sym_key, sym_w in atom.get("symptom_weights", {}).items():
        if sym_key.startswith("舌"):
            weights[sym_key] = sym_w
    weights.update(atom.get("tongue_weights", {}))
    delta = 0
    matched: list[str] = []
    conflict_note = ""
    for t in tongues:
        w = weights.get(t, 0)
        if not w:
            continue
        delta += w
        if w > 0:
            matched.append(t)
        elif w <= -16 and not conflict_note:
            conflict_note = f"舌象「{t}」偏离本方寒热燥润边界（{w}）"
    return delta, matched, conflict_note


def are_formulas_redundant_siblings(fid1: str, fid2: str) -> bool:
    """Return True if two formula IDs belong to the same close intensification family or base formula name."""
    if not fid1 or not fid2 or fid1 == fid2:
        return True
    base1 = fid1.split(":", 1)[-1]
    base2 = fid2.split(":", 1)[-1]
    if base1 == base2:
        return True
    return any(fid1 in grp and fid2 in grp for grp in REDUNDANT_SIBLING_GROUPS)


# ---------------------------------------------------------------------------
# 2. Expanded Canonical Symptom Axes & UI Helpers
# ---------------------------------------------------------------------------
EXTRA_SYMPTOM_CANONICAL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("热厥", ("热厥", "热深厥深", "厥深热深")),
    ("骨蒸盗汗", ("骨蒸盗汗", "骨蒸", "盗汗", "潮热盗汗", "睡着出汗", "手足心汗")),
    ("自利清水热", ("自利清水", "纯利清水", "色纯青", "热结旁流")),
    ("便溏", ("便溏", "大便溏", "大便不成形", "大便稀软", "大便时溏")),
    ("经期热入血室", ("经期感冒", "月经适来", "月经适断", "经水适来", "经水适断", "热入血室", "经期", "月经期间")),
    ("淋痛尿血", ("小便刺痛", "尿痛", "尿血", "血淋", "砂淋", "石淋", "膀胱结石", "尿路结石", "小便涩痛", "尿频尿急")),
    ("戴阳格阳", ("面赤如妆", "戴阳", "格阳", "真寒假热", "身反不恶寒", "面赤")),
    ("皮肤干燥", ("皮肤干燥", "皮肤干裂", "脱屑", "干痒", "血虚风燥")),
    ("皮肤湿疹", ("皮肤湿疹", "流黄水", "疮疡渗水", "湿疹", "皮肤瘙痒流液")),
    ("虚喘短气", ("虚喘", "不抬肩", "喘不抬肩", "张口短气", "少气", "气短乏力", "动则气喘", "气息微弱", "喘而气短")),
    ("大渴", ("大渴", "大渴引饮", "渴欲饮数升", "大渴烦躁")),
    ("背恶寒", ("背恶寒", "背冷", "背寒", "背部怕冷", "背凛凛寒")),
    ("口中和", ("口中和", "口不燥", "口不苦不渴")),
    ("饮食如故", ("饮食如故", "能食", "胃口正常", "食欲正常")),
    ("胸膈懊憹", ("懊憹", "胸中窒", "心中懊憹", "烦热胸闷")),
    ("心脏术后禁忌", ("心脏手术", "心脏术后", "搭桥", "心脏支架", "瓣膜手术", "心外科术后")),
    ("胆切除史", ("切胆", "胆囊切除", "胆切除")),
    ("放化疗史", ("化疗", "放疗", "切片", "穿刺")),
    ("妊娠禁忌", ("怀孕", "妊娠", "孕妇", "胎动不安")),
    # Disambiguated extensions of existing axes (deduplicated during extraction)
    ("下利清谷", ("下利", "自利清谷", "自利", "利不止")),
    ("腹满拒按", ("腹胀痛拒按", "胀痛拒按", "腹满痛", "拒按", "绕脐硬痛")),
    ("腹痛", ("腹胀痛", "胃脘痛", "心腹痛", "胸腹痛")),
    ("咳喘痰多", ("喘促", "喘急", "抬肩", "张口抬肩", "倚息", "痰鸣", "喘喝", "喘")),
    ("水鸡声", ("痰鸣", "喉鸣")),
    ("咽喉肿痛", ("咽喉肿痛", "咽中痛", "咽伤生疮")),
    ("失血", ("咯血", "咳血", "尿血", "肌衄")),
    ("水肿", ("悬饮", "支饮", "胸水", "胁下痛咳唾引痛")),
    *EXPANDED_SYMPTOM_CANONICAL_RULES,
]

EXTRA_INQUIRY_PILLS: list[dict[str, str]] = [
    {"group": "病史危象", "label": "经期感冒 / 适来适断", "token": "经期感冒"},
    {"group": "病史危象", "label": "盗汗骨蒸", "token": "骨蒸盗汗"},
    {"group": "寒热手足", "label": "四肢厥冷（需辨寒热）", "token": "四肢厥冷"},
    {"group": "寒热手足", "label": "面红如妆（戴阳）", "token": "面赤如妆"},
    {"group": "二便小水", "label": "小便刺痛 / 尿血", "token": "小便刺痛 尿血"},
    {"group": "二便小水", "label": "大便溏软", "token": "便溏"},
    {"group": "皮肤与饮食", "label": "皮肤干燥瘙痒", "token": "皮肤干燥"},
    {"group": "皮肤与饮食", "label": "饮食如故（辨脏结）", "token": "饮食如故"},
    {"group": "病史危象", "label": "心脏外科术后史", "token": "心脏术后"},
    {"group": "病史危象", "label": "胆囊切除术后", "token": "胆切除"},
    {"group": "病史危象", "label": "放化疗 / 穿刺切片史", "token": "放化疗 穿刺"},
    {"group": "寒热手足", "label": "背恶寒 / 背冷", "token": "背恶寒"},
    {"group": "寒热手足", "label": "口中和（口不燥渴）", "token": "口中和"},
    {"group": "二便小水", "label": "大渴无汗（忌石膏）", "token": "大渴 无汗"},
    {"group": "病史危象", "label": "虚喘短气不抬肩", "token": "虚喘 不抬肩 短气"},
]

EXTRA_PRESET_CASES: list[dict[str, str]] = [
    {
        "id": "case:xulao-tuxue",
        "title": "示范G：阴虚吐血骨蒸盗汗（禁小建中与麻黄红线）",
        "symptoms": "吐血，咳嗽，骨蒸，盗汗，手掌烦热",
        "pulse": "数 微细",
        "note": "徐灵胎《慎疾刍言》·唐容川《血证论》：古虚劳可用建中温脾，今阴虚内热咯血骨蒸脉数，若误用小建中、人参、麻黄发汗温补必致毙命！",
    },
    {
        "id": "case:rejue-chengqi",
        "title": "示范H：四肢厥冷伴腹痛拒按小便深黄（热厥 vs 寒厥）",
        "symptoms": "四肢厥冷，腹胀痛拒按，口渴，喜冷饮，小便深黄",
        "pulse": "滑 数",
        "note": "《伤寒》厥深热深之热厥：切忌见四肢厥冷便投四逆汤！滑数脉、口渴尿黄腹满拒按主里热内郁，宜白虎或大承气清泻。",
    },
    {
        "id": "case:jingqi-chaihu",
        "title": "示范I：女子经期外感发热恶寒（唯用小柴胡配期门）",
        "symptoms": "发热，恶寒，头痛，经期感冒，往来寒热",
        "pulse": "浮 弦",
        "note": "《伤寒》《金匮》《汉唐》：经水适来适断逢外感，严禁发汗攻下（防热入血室），唯用小柴胡汤加减配针期门穴。",
    },
    {
        "id": "case:wuhan-shigao",
        "title": "示范J：大渴无汗表闭高热（石室忌用生石膏红线）",
        "symptoms": "高热，大渴，无汗，恶寒，喘促",
        "pulse": "浮 紧",
        "note": "陈士铎《石室秘录》《伤寒》：阳明「有汗如雨」始可用白虎石膏，表闭「无汗大渴」忌早投石膏遏热内陷（须分大青龙散寒清里）。",
    },
    {
        "id": "case:beiehan-fuzi",
        "title": "示范K：背恶寒分流（口中和附子汤 vs 口燥渴白虎人参）",
        "symptoms": "背恶寒，口中和，身痛，脚冷",
        "pulse": "沉 微细",
        "note": "《伤寒》304 vs 168条：少阴背恶寒而「口中和」用附子汤温经，若汗出背微恶寒而「口燥渴」则用白虎加人参汤清气阴。",
    },
]


# ---------------------------------------------------------------------------
# 3. Classical Pattern Atoms Extension (verified IDs & dict pulse/conflict types)
# ---------------------------------------------------------------------------
EXTRA_PATTERN_ATOMS: list[dict[str, Any]] = [
    {
        "atom_id": "atom:tongmai-sini",
        "formula_id": "shanghan:通脉四逆汤",
        "name": "通脉四逆汤",
        "six_meridian": "少阴格阳真寒假热证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "下利清谷": 26,
            "脚冷": 22,
            "身冷": 18,
            "戴阳格阳": 24,
            "小便清白": 16,
            "口不渴": 12,
            "舌白厚湿": 16,
            "舌淡胖滑": 16,
        },
        "pair_bonus": [("下利清谷", "戴阳格阳", 18), ("脚冷", "戴阳格阳", 14)],
        "boost_pulses": {"微细": 16, "沉": 10, "迟": 10},
        "conflict_pulses": {"洪大": -22, "滑": -14},
        "conflict_symptoms": {
            "热厥": -30,
            "小便深黄": -16,
            "舌黄厚燥": -24,
        },
        "pathogenesis": "少阴阴寒极盛于内、逼迫微阳浮越于外，故见下利清谷、四肢厥逆、脉微欲绝而面反赤（戴阳）或身反不恶寒。",
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（重灸）", "reason": "回少阴垂绝之元阳、引火归元"},
            {"id": "acupoint:ki01:涌泉", "name": "涌泉", "role": "配穴", "reason": "交通心肾、引浮越虚阳下行归根"},
        ],
    },
    {
        "atom_id": "atom:zhizichi",
        "formula_id": "shanghan:栀子豉汤",
        "name": "栀子豉汤",
        "six_meridian": "太阳/阳明胸膈虚烦懊憹证",
        "polarity": "heat_excess",
        "symptom_weights": {
            "胸膈懊憹": 28,
            "心烦失眠": 22,
            "舌红少苔": 10,
            "小便深黄": 10,
            "高热": 8,
        },
        "pair_bonus": [("胸膈懊憹", "心烦失眠", 14)],
        "boost_pulses": {"数": 10, "浮": 8},
        "conflict_pulses": {"微细": -14, "迟": -16},
        "conflict_symptoms": {
            "身冷": -20,
            "下利清谷": -24,
            "便溏": -20,
        },
        "pathogenesis": "汗吐下后余热留扰胸膈，致心中懊憹不得眠、反复颠倒，以苦寒栀子配合轻清豆豉涌宣胸膈郁热（病人旧微溏者不可与）。",
        "acupoints": [
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "主穴", "reason": "宽胸宣郁、宁心止懊憹"},
            {"id": "acupoint:ren17:膻中", "name": "膻中", "role": "配穴", "reason": "清宣上焦胸中郁热"},
        ],
    },
    {
        "atom_id": "atom:dahuang-huanglian-xiexin",
        "formula_id": "shanghan:大黄黄连泻心汤",
        "name": "大黄黄连泻心汤",
        "six_meridian": "太阳误下热痞/迫血妄行证",
        "polarity": "heat_excess",
        "symptom_weights": {
            "心下痞": 24,
            "失血": 18,
            "心烦失眠": 14,
            "小便深黄": 14,
            "舌黄厚燥": 14,
        },
        "pair_bonus": [("心下痞", "舌黄厚燥", 12)],
        "boost_pulses": {"滑": 10, "数": 12, "洪大": 10},
        "conflict_pulses": {"微细": -18, "迟": -18},
        "conflict_symptoms": {
            "身冷": -22,
            "下利清谷": -24,
        },
        "pathogenesis": "无形热邪痞塞心下（关脉浮、按之濡）或热毒炽盛逼迫血脉吐血鼻衄，用麻沸汤浸渍大黄黄连以轻扬泄热而不猛攻其下。",
        "acupoints": [
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "主穴", "reason": "泄心下热痞、和胃降浊"},
            {"id": "acupoint:li11:曲池", "name": "曲池", "role": "配穴", "reason": "清泻阳明气血实热"},
        ],
    },
    {
        "atom_id": "atom:fuzi-xiexin",
        "formula_id": "shanghan:附子泻心汤",
        "name": "附子泻心汤",
        "six_meridian": "热痞兼表阳虚证",
        "polarity": "balanced",
        "symptom_weights": {
            "心下痞": 26,
            "身冷": 20,
            "有汗": 16,
            "口苦": 10,
        },
        "pair_bonus": [("心下痞", "身冷", 16)],
        "boost_pulses": {"沉": 8, "数": 6, "微细": 8},
        "conflict_pulses": {},
        "conflict_symptoms": {"高热": -18},
        "pathogenesis": "既有上焦心下无形热痞（三黄麻沸汤轻清泄痞），复兼卫表肾阳虚衰恶寒汗出（别煎附子汁温固阳气），寒热并用而取其不同煎法之巧。",
        "acupoints": [
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "主穴", "reason": "消心下寒热格拒之痞"},
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "配穴（温灸）", "reason": "固护下焦卫外之阳"},
        ],
    },
    {
        "atom_id": "atom:xuanfu-daizhe",
        "formula_id": "shanghan:旋覆代赭石汤",
        "name": "旋覆代赭石汤",
        "six_meridian": "伤寒汗吐下后胃虚痰阻证",
        "polarity": "balanced",
        "symptom_weights": {
            "呃逆胃虚": 30,
            "心下痞": 22,
            "呕吐": 20,
            "咳喘痰多": 8,
        },
        "pair_bonus": [("呃逆胃虚", "心下痞", 16)],
        "boost_pulses": {"弦": 10, "滑": 8, "沉": 6},
        "conflict_pulses": {"洪大": -14},
        "conflict_symptoms": {"腹满拒按": -18},
        "pathogenesis": "误治损伤胃气、痰浊上逆阻滞中焦，致心下痞硬、噫气不除、反胃呕吐，以参草姜枣补胃虚，旋覆代赭半夏降逆化痰。",
        "acupoints": [
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "主穴", "reason": "和胃降逆止噫气呕吐"},
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "配穴", "reason": "调中州而消心下痞硬"},
        ],
    },
    {
        "atom_id": "atom:zhufu",
        "formula_id": "shanghan:猪肤汤",
        "name": "猪肤汤",
        "six_meridian": "少阴阴虚客热咽痛证",
        "polarity": "yin_def_heat",
        "symptom_weights": {
            "咽喉肿痛": 26,
            "下利清谷": 12,
            "心烦失眠": 16,
            "舌红少苔": 18,
            "口渴": 10,
        },
        "pair_bonus": [("咽喉肿痛", "舌红少苔", 14)],
        "boost_pulses": {"微细": 12, "数": 10, "沉": 6},
        "conflict_pulses": {"洪大": -14, "紧": -12},
        "conflict_symptoms": {"高热": -16},
        "pathogenesis": "《伤寒》少阴病下利、咽痛、胸满心烦者，因肾阴亏虚、虚火上浮熏灼咽喉，猪肤甘寒润肾清浮热。",
        "acupoints": [
            {"id": "acupoint:ki06:照海", "name": "照海", "role": "主穴", "reason": "足少阴通阴跷脉，滋肾水而润咽喉"},
            {"id": "acupoint:lu07:列缺", "name": "列缺", "role": "配穴", "reason": "八脉交会通照海，宣肺利咽"},
        ],
    },
    {
        "atom_id": "atom:banxia-san",
        "formula_id": "shanghan:半夏散及汤",
        "name": "半夏散及汤",
        "six_meridian": "少阴客寒痰阻咽痛证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "咽喉肿痛": 26,
            "身冷": 16,
            "舌白厚湿": 14,
            "舌淡胖滑": 14,
            "呕吐": 10,
        },
        "pair_bonus": [("咽喉肿痛", "身冷", 14)],
        "boost_pulses": {"微细": 10, "紧": 12, "沉": 8},
        "conflict_pulses": {"洪大": -18},
        "conflict_symptoms": {"舌红少苔": -20, "小便深黄": -12},
        "pathogenesis": "《伤寒》少阴病咽中痛（寒客少阴、痰湿阻络，不肿不赤而痛剧），用半夏涤痰散结、桂枝温通阳气、甘草缓痛，少少咽之。",
        "acupoints": [
            {"id": "acupoint:ki03:太溪", "name": "太溪", "role": "主穴", "reason": "温煦少阴经气以化咽中客寒"},
            {"id": "acupoint:st40:丰隆", "name": "丰隆", "role": "配穴", "reason": "豁咽喉经隧冷痰滞结"},
        ],
    },
    {
        "atom_id": "atom:gancao-tang",
        "formula_id": "shanghan:甘草汤",
        "name": "甘草汤",
        "six_meridian": "少阴轻浅热郁咽痛证",
        "polarity": "yin_def_heat",
        "symptom_weights": {
            "咽喉肿痛": 22,
            "心烦失眠": 8,
            "咽干": 6,
        },
        "pair_bonus": [],
        "boost_pulses": {"微细": 8, "沉": 6, "数": 8},
        "conflict_pulses": {"洪大": -12},
        "conflict_symptoms": {},
        "pathogenesis": "少阴初起微热客咽，仅生甘草一味甘平泻火解毒缓急。",
        "acupoints": [
            {"id": "acupoint:ki06:照海", "name": "照海", "role": "主穴", "reason": "清利少阴虚热微肿"},
        ],
    },
    {
        "atom_id": "atom:jiegeng-tang",
        "formula_id": "shanghan:桔梗汤",
        "name": "桔梗汤",
        "six_meridian": "少阴痰热壅咽 / 肺痈吐脓证",
        "polarity": "heat_excess",
        "symptom_weights": {
            "咽喉肿痛": 26,
            "咳喘痰多": 20,
            "胸痹": 14,
        },
        "pair_bonus": [("咽喉肿痛", "咳喘痰多", 12)],
        "boost_pulses": {"滑": 10, "数": 10, "微细": 6},
        "conflict_pulses": {},
        "conflict_symptoms": {},
        "pathogenesis": "少阴病甘草汤证不愈、痰热阻闭咽喉，或肺痈胸满咳唾浊唾腥臭脓血，用桔梗开宣肺气排脓、甘草清解毒热。",
        "acupoints": [
            {"id": "acupoint:lu11:少商", "name": "少商", "role": "主穴（点刺放血）", "reason": "实热喉痹咽痛救急放血泄热"},
            {"id": "acupoint:li04:合谷", "name": "合谷", "role": "配穴", "reason": "宣散阳明少阴咽喉壅滞"},
        ],
    },
    {
        "atom_id": "atom:kujiu-tang",
        "formula_id": "shanghan:苦酒汤",
        "name": "苦酒汤",
        "six_meridian": "少阴咽伤生疮失音证",
        "polarity": "yin_def_heat",
        "symptom_weights": {
            "咽喉肿痛": 26,
            "舌红少苔": 14,
            "咽干": 6,
        },
        "pair_bonus": [],
        "boost_pulses": {"微细": 10, "数": 8, "沉": 6},
        "conflict_pulses": {"洪大": -14},
        "conflict_symptoms": {},
        "pathogenesis": "少阴病咽中伤、生疮、不能语言、声不出者，半夏鸡子清苦酒敛疮化痰开音。",
        "acupoints": [
            {"id": "acupoint:ren23:廉泉", "name": "廉泉", "role": "主穴", "reason": "利咽喉舌本、开音止疮痛"},
            {"id": "acupoint:ki06:照海", "name": "照海", "role": "配穴", "reason": "滋养少阴阴津以愈咽疮"},
        ],
    },
    {
        "atom_id": "atom:wumei-wan",
        "formula_id": "shanghan:乌梅丸",
        "name": "乌梅丸",
        "six_meridian": "厥阴寒热错杂 / 上热下寒证",
        "polarity": "balanced",
        "symptom_weights": {
            "口渴": 14,
            "气上冲胸": 20,
            "下利清谷": 16,
            "脚冷": 16,
            "呕吐": 14,
            "心下痞": 14,
        },
        "pair_bonus": [("气上冲胸", "脚冷", 16), ("口渴", "下利清谷", 12)],
        "boost_pulses": {"弦": 12, "微细": 8, "沉": 8},
        "conflict_pulses": {"洪大": -18},
        "conflict_symptoms": {"腹满拒按": -18},
        "pathogenesis": "厥阴主风木相火，病久寒热错杂，见消渴、气上撞心、心中疼热、饥而不欲食、手足厥冷或久利，用酸苦辛甘温凉并行安蛔止利、平调厥阴。",
        "acupoints": [
            {"id": "acupoint:lv03:太冲", "name": "太冲", "role": "主穴", "reason": "平调厥阴肝木寒热气机逆乱"},
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "配穴", "reason": "平冲降逆、解心中疼热"},
        ],
    },
    {
        "atom_id": "atom:tiaowei-chengqi",
        "formula_id": "shanghan:调胃承气汤",
        "name": "调胃承气汤",
        "six_meridian": "阳明胃热燥屎缓下证",
        "polarity": "heat_excess",
        "symptom_weights": {
            "大便干": 20,
            "心烦失眠": 14,
            "高热": 14,
            "小便深黄": 14,
            "舌黄厚燥": 18,
            "腹痛": 10,
        },
        "pair_bonus": [("大便干", "心烦失眠", 10)],
        "boost_pulses": {"滑": 12, "数": 12, "洪大": 12},
        "conflict_pulses": {"微细": -22, "迟": -16},
        "conflict_symptoms": {"身冷": -20, "脚冷": -20, "下利清谷": -26},
        "pathogenesis": "阳明胃中热结燥屎而不甚满痛（无痞满胀急之甚），伴蒸蒸发热、心烦、不恶寒反恶热，取大黄芒硝配炙甘草缓和软坚泻热。",
        "acupoints": [
            {"id": "acupoint:st25:天枢", "name": "天枢", "role": "主穴", "reason": "通调大肠燥热俯实"},
            {"id": "acupoint:st37:上巨虚", "name": "上巨虚", "role": "配穴", "reason": "大肠下合穴，导热下行"},
        ],
    },
    {
        "atom_id": "atom:zhuye-shigao",
        "formula_id": "shanghan:竹叶石膏汤",
        "name": "竹叶石膏汤",
        "six_meridian": "热病瘥后余热气津两伤证",
        "polarity": "yin_def_heat",
        "symptom_weights": {
            "口渴": 18,
            "心烦失眠": 16,
            "呕吐": 14,
            "呃逆胃虚": 16,
            "舌红少苔": 20,
            "虚喘短气": 16,
            "骨蒸盗汗": 12,
        },
        "pair_bonus": [("舌红少苔", "虚喘短气", 16)],
        "boost_pulses": {"数": 12, "微细": 8, "浮": 6},
        "conflict_pulses": {"沉": -10, "迟": -20, "紧": -16},
        "conflict_symptoms": {"身冷": -24, "下利清谷": -24, "便溏": -24, "舌白厚湿": -20},
        "pathogenesis": "大病新瘥或温热后期余热未尽、气津两伤，见赢瘦少气、气逆欲吐、心烦口渴、苔少舌红，以竹叶石膏清余热，麦冬人参半夏生津降逆。",
        "acupoints": [
            {"id": "acupoint:lu05:尺泽", "name": "尺泽", "role": "主穴", "reason": "清泄肺胃虚热、生津降逆"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "配穴", "reason": "扶胃气而助麦冬生津液"},
        ],
    },
    {
        "atom_id": "atom:shizao-tang",
        "formula_id": "shanghan:十枣汤",
        "name": "十枣汤",
        "six_meridian": "悬饮胸水胁痛证",
        "polarity": "heat_excess",
        "symptom_weights": {
            "水肿": 28,
            "咳喘痰多": 20,
            "口苦": 16,
            "头痛": 10,
            "小便不利": 12,
        },
        "pair_bonus": [("水肿", "咳喘痰多", 14)],
        "boost_pulses": {"沉": 10, "弦": 16, "滑": 10},
        "conflict_pulses": {"微细": -22},
        "conflict_symptoms": {"身冷": -12, "舌红少苔": -22},
        "pathogenesis": "《伤寒》表已解而水饮悬结胸胁、咳唾引痛、心下痞硬、短气、头痛汗出，属顽固悬饮胸腔积液实证，用芫花甘遂大戟配大枣峻逐水饮（中病即止，体虚慎用）。",
        "acupoints": [
            {"id": "acupoint:bl13:肺俞", "name": "肺俞", "role": "主穴", "reason": "宣开肺气以助行胸胁悬饮"},
            {"id": "acupoint:lv14:期门", "name": "期门", "role": "配穴", "reason": "疏泻胸胁停水结痛"},
        ],
    },
    {
        "atom_id": "atom:fuzi-tang",
        "formula_id": "shanghan:附子汤",
        "name": "附子汤",
        "six_meridian": "少阴寒湿痹痛 / 背恶寒证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "身冷": 26,
            "关节痹痛": 24,
            "脚冷": 18,
            "口不渴": 14,
            "舌淡胖滑": 14,
        },
        "pair_bonus": [("身冷", "关节痹痛", 16)],
        "boost_pulses": {"沉": 14, "微细": 12, "紧": 10},
        "conflict_pulses": {"洪大": -24, "数": -18},
        "conflict_symptoms": {"高热": -24, "热厥": -28},
        "pathogenesis": "《伤寒》少阴病背恶寒、口中和、身体痛、手足寒、骨节痛、脉沉者，属少阴阳虚寒湿深留筋骨，倍用炮附子配参苓术芍温阳除湿。",
        "acupoints": [
            {"id": "acupoint:du14:大椎", "name": "大椎", "role": "主穴（温灸）", "reason": "温通督脉背俞阳气以驱背恶寒"},
            {"id": "acupoint:bl23:肾俞", "name": "肾俞", "role": "配穴（灸）", "reason": "温补肾阳而除骨节寒湿痛"},
        ],
    },
    {
        "atom_id": "atom:jinkui-xiexin",
        "formula_id": "jinkui:泻心汤",
        "name": "泻心汤（三黄）",
        "six_meridian": "火热迫血吐血衄血证",
        "polarity": "heat_excess",
        "symptom_weights": {
            "失血": 28,
            "心烦失眠": 14,
            "小便深黄": 14,
            "骨蒸盗汗": 10,
            "舌黄厚燥": 14,
        },
        "pair_bonus": [("失血", "小便深黄", 12)],
        "boost_pulses": {"数": 14, "洪大": 12, "滑": 10},
        "conflict_pulses": {"微细": -14, "迟": -18},
        "conflict_symptoms": {"身冷": -22, "下利清谷": -22},
        "pathogenesis": "《金匮》心气不足（指阴血耗伤而邪火亢盛）、吐血衄血，用大黄黄连黄芩折其上冲炽烈之火而止血（血证论·徐灵胎皆尊为实火吐衄要方）。",
        "acupoints": [
            {"id": "acupoint:lu06:孔最", "name": "孔最", "role": "主穴（泻法）", "reason": "肺经郄穴，救急止咳血咯血"},
            {"id": "acupoint:bl17:膈俞", "name": "膈俞", "role": "配穴", "reason": "血会膈俞，清血分火热迫血"},
        ],
    },
    {
        "atom_id": "atom:chidou-danggui",
        "formula_id": "jinkui:赤豆当归散",
        "name": "赤豆当归散",
        "six_meridian": "下焦湿热近血 / 尿血热淋证",
        "polarity": "heat_excess",
        "symptom_weights": {
            "淋痛尿血": 28,
            "先血后便": 22,
            "小便深黄": 14,
            "失血": 8,
        },
        "pair_bonus": [("淋痛尿血", "小便深黄", 14)],
        "boost_pulses": {"数": 12, "滑": 10},
        "conflict_pulses": {"微细": -12, "迟": -14},
        "conflict_symptoms": {"身冷": -18},
        "pathogenesis": "《金匮》下血先便后血为远血（黄土汤），先血后便为近血（赤豆当归散）；亦主湿热蕴结膀胱阴部尿血淋痛、狐惑脓血。",
        "acupoints": [
            {"id": "acupoint:ren03:中极", "name": "中极", "role": "主穴", "reason": "膀胱募穴，清利下焦膀胱湿热淋血"},
            {"id": "acupoint:sp10:血海", "name": "血海", "role": "配穴", "reason": "清血分湿热以止尿血近血"},
        ],
    },
    {
        "atom_id": "atom:baihe-dihuang",
        "formula_id": "jinkui:百合地黄汤",
        "name": "百合地黄汤",
        "six_meridian": "肺肾阴虚百脉一宗内热证",
        "polarity": "yin_def_heat",
        "symptom_weights": {
            "心烦失眠": 22,
            "骨蒸盗汗": 20,
            "口苦": 14,
            "小便深黄": 14,
            "舌红少苔": 20,
            "失血": 12,
        },
        "pair_bonus": [("骨蒸盗汗", "舌红少苔", 14)],
        "boost_pulses": {"微细": 12, "数": 12},
        "conflict_pulses": {"洪大": -16, "紧": -16},
        "conflict_symptoms": {"身冷": -18, "下利清谷": -22, "便溏": -18},
        "pathogenesis": "《金匮》热病后或久思阴伤导致百脉一宗、悉致其病（意欲食复不能食、默默欲卧不能卧、如有神灵、口苦小便赤、脉微数），用百合滋肺清心安神，生地汁凉血清热。",
        "acupoints": [
            {"id": "acupoint:ht07:神门", "name": "神门", "role": "主穴", "reason": "安神定志、清心阴虚烦"},
            {"id": "acupoint:ki03:太溪", "name": "太溪", "role": "配穴", "reason": "滋肺肾阴液以除骨蒸盗汗"},
        ],
    },
    {
        "atom_id": "atom:ganmai-dazao",
        "formula_id": "jinkui:甘麦大枣汤",
        "name": "甘麦大枣汤",
        "six_meridian": "妇人脏躁心肝血虚证",
        "polarity": "balanced",
        "symptom_weights": {
            "心烦失眠": 24,
            "痛经": 14,
            "经期热入血室": 14,
            "舌红少苔": 10,
        },
        "pair_bonus": [("心烦失眠", "痛经", 10)],
        "boost_pulses": {"涩": 8, "微细": 10, "弦": 8},
        "conflict_pulses": {},
        "conflict_symptoms": {"腹满拒按": -18},
        "pathogenesis": "《金匮》妇人脏躁、喜悲伤欲哭、象如神灵所作、数欠伸，甘麦大枣甘润缓急、养心脾阴液。",
        "acupoints": [
            {"id": "acupoint:ht07:神门", "name": "神门", "role": "主穴", "reason": "宁心安神定脏躁悲哭"},
            {"id": "acupoint:sp06:三阴交", "name": "三阴交", "role": "配穴", "reason": "养血柔肝调妇人冲任"},
        ],
    },
    {
        "atom_id": "atom:tingli-dazao",
        "formula_id": "jinkui:葶苈大枣泻肺汤",
        "name": "葶苈大枣泻肺汤",
        "six_meridian": "痰饮水气壅肺喘不得卧证",
        "polarity": "heat_excess",
        "symptom_weights": {
            "咳喘痰多": 26,
            "水肿": 20,
            "胸痹": 14,
        },
        "pair_bonus": [("咳喘痰多", "水肿", 14)],
        "boost_pulses": {"滑": 12, "数": 10, "浮": 8},
        "conflict_pulses": {"微细": -16},
        "conflict_symptoms": {"虚喘短气": -18},
        "pathogenesis": "《金匮》肺痈喘不得卧、支饮不得息，属痰水实邪壅塞肺窍、肺气闭阻不降，葶苈子苦寒辛散急泻肺水，配大枣安脾防伤正。",
        "acupoints": [
            {"id": "acupoint:lu01:中府", "name": "中府", "role": "主穴", "reason": "肺募泻肺中实邪水饮"},
            {"id": "acupoint:bl13:肺俞", "name": "肺俞", "role": "配穴", "reason": "肃降肺气开壅塞喘逆"},
        ],
    },
    {
        "atom_id": "atom:dajianzhong",
        "formula_id": "jinkui:大建中汤",
        "name": "大建中汤",
        "six_meridian": "中焦阳虚寒凝剧痛呕不能食证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "腹痛": 12,
            "腹痛喜按": 26,
            "身冷": 16,
            "呕吐": 24,
            "舌淡胖滑": 16,
        },
        "pair_bonus": [("呕吐", "腹痛喜按", 16)],
        "boost_pulses": {"沉": 10, "迟": 14, "微细": 10},
        "conflict_pulses": {"洪大": -24, "数": -18, "滑": -12},
        "conflict_symptoms": {
            "腹满拒按": -26,
            "大便干": -18,
            "热厥": -28,
            "失血": -18,
            "骨蒸盗汗": -24,
        },
        "pathogenesis": "《金匮》心胸中大寒痛、呕不能饮食、腹中寒上冲皮起出见有头足上下痛而不可触近（喜温而大虚寒），以干姜蜀椒大辛温建中阳、人参饴糖急补中气。",
        "acupoints": [
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "主穴（重灸）", "reason": "温运脾胃沉寒剧痛"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "配穴（灸）", "reason": "扶太阴脾阳定中州寒逆"},
        ],
    },
    {
        "atom_id": "atom:wutou-chishizhi",
        "formula_id": "jinkui:乌头赤石脂丸",
        "name": "乌头赤石脂丸",
        "six_meridian": "极寒胸痹心痛彻背证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "心痛彻背": 30,
            "胸痹": 22,
            "身冷": 18,
            "脚冷": 16,
        },
        "pair_bonus": [("心痛彻背", "身冷", 16)],
        "boost_pulses": {"沉": 12, "紧": 14, "迟": 12, "微细": 10},
        "conflict_pulses": {"洪大": -22, "数": -18},
        "conflict_symptoms": {"热厥": -28},
        "pathogenesis": "《金匮》心痛彻背、背痛彻心，寒邪深痼阳微已极、较栝蒌薤白白酒证更剧，用乌头附子椒姜温破沉寒、赤石脂固脱。",
        "acupoints": [
            {"id": "acupoint:ren14:巨阙", "name": "巨阙", "role": "主穴", "reason": "心募，急救寒凝真心痛"},
            {"id": "acupoint:bl17:膈俞", "name": "膈俞", "role": "配穴（温灸）", "reason": "通胸背上下阻滞寒凝"},
        ],
    },
    {
        "atom_id": "atom:gualou-xiebai-banxia",
        "formula_id": "jinkui:栝蒌薤白半夏汤",
        "name": "栝蒌薤白半夏汤",
        "six_meridian": "胸痹痰浊痹阻不得卧证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "心痛彻背": 24,
            "胸痹": 24,
            "咳喘痰多": 18,
            "心烦失眠": 10,
        },
        "pair_bonus": [("胸痹", "咳喘痰多", 12)],
        "boost_pulses": {"沉": 10, "弦": 12, "紧": 10},
        "conflict_pulses": {"洪大": -18},
        "conflict_symptoms": {},
        "pathogenesis": "《金匮》胸痹不得卧、心痛彻背者，痰饮比白酒汤更盛阻痹胸阳，加半夏逐痰饮降逆。",
        "acupoints": [
            {"id": "acupoint:ren17:膻中", "name": "膻中", "role": "主穴", "reason": "宣散胸中痰浊闭阻"},
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "配穴", "reason": "宽胸利膈、安卧定痛"},
        ],
    },
    {
        "atom_id": "atom:zhishi-xiebai-guizhi",
        "formula_id": "jinkui:枳实薤白桂枝汤",
        "name": "枳实薤白桂枝汤",
        "six_meridian": "胸痹气结痞满逆抢心证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "胸痹": 24,
            "气上冲胸": 24,
            "心下痞": 18,
            "口苦": 10,
        },
        "pair_bonus": [("胸痹", "气上冲胸", 14)],
        "boost_pulses": {"沉": 10, "弦": 14, "紧": 8},
        "conflict_pulses": {"洪大": -18},
        "conflict_symptoms": {},
        "pathogenesis": "《金匮》胸痹心中痞气、气结在胸、胸满、胁下逆抢心，用枳实厚朴破气散满、桂枝通阳降冲、栝蒌薤白涤痰通痹。",
        "acupoints": [
            {"id": "acupoint:ren17:膻中", "name": "膻中", "role": "主穴", "reason": "破胸中气结痞满"},
            {"id": "acupoint:sp04:公孙", "name": "公孙", "role": "配穴", "reason": "配内关平调胁下冲逆"},
        ],
    },
    {
        "atom_id": "atom:dahuang-fuzi",
        "formula_id": "jinkui:大黄附子汤",
        "name": "大黄附子汤",
        "six_meridian": "寒实冷积胁下偏痛证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "腹痛": 14,
            "大便干": 14,
            "身冷": 14,
            "口苦": 16,
        },
        "pair_bonus": [("大便干", "口苦", 16)],
        "boost_pulses": {"紧": 18, "弦": 16, "沉": 6},
        "conflict_pulses": {"洪大": -20, "微细": -28, "涩": -16},
        "conflict_symptoms": {"热厥": -20},
        "pathogenesis": "《金匮》胁下偏痛、发热（微热或寒束微热）、其脉紧弦、此寒也，以温药下之，用附子细辛散寒破冷积、借大黄推荡下行（治冷闭绝妙）。",
        "acupoints": [
            {"id": "acupoint:sj06:支沟", "name": "支沟", "role": "主穴", "reason": "理三焦胁下气机通大便"},
            {"id": "acupoint:st25:天枢", "name": "天枢", "role": "配穴", "reason": "推荡肠间寒实冷积"},
        ],
    },
    {
        "atom_id": "atom:xiaoshi-fanshi",
        "formula_id": "jinkui:硝石矾石散",
        "name": "硝石矾石散",
        "six_meridian": "女劳疸黑疸阴湿瘀热证",
        "polarity": "heat_excess",
        "symptom_weights": {
            "黄疸": 26,
            "手掌烦热": 22,
            "水肿": 12,
            "小便自利": 10,
            "小便深黄": 10,
        },
        "pair_bonus": [("黄疸", "手掌烦热", 16)],
        "boost_pulses": {"沉": 8, "弦": 10, "涩": 10},
        "conflict_pulses": {"洪大": -10},
        "conflict_symptoms": {},
        "pathogenesis": "《金匮》黄家日晡所发热而反恶寒者此为女劳得之，膀胱急少腹满、身尽黄、额上黑、足下热、大便必黑时溏，用硝石消坚化瘀、矾石胜湿。",
        "acupoints": [
            {"id": "acupoint:du09:至阳", "name": "至阳", "role": "主穴", "reason": "退黄要穴、宣调三焦湿瘀"},
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "配穴", "reason": "疏利肝胆瘀黄"},
        ],
    },
    {
        "atom_id": "atom:guizhi-gancao-longgu-muli",
        "formula_id": "shanghan:桂枝甘草龙骨牡蛎汤",
        "name": "桂枝甘草龙骨牡蛎汤",
        "six_meridian": "心阳虚损火浮烦躁惊狂证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "心悸": 26,
            "心烦失眠": 26,
            "有汗": 12,
            "身冷": 8,
        },
        "pair_bonus": [("心悸", "心烦失眠", 16)],
        "boost_pulses": {"浮": 10, "沉": 8, "微细": 8},
        "conflict_pulses": {"洪大": -18},
        "conflict_symptoms": {"腹满拒按": -20, "大便干": -16},
        "pathogenesis": "《伤寒》火逆下之，因烧针烦躁者，桂枝甘草辛甘化阳固心中之阳，龙骨牡蛎重镇潜敛浮越虚阳定烦躁。",
        "acupoints": [
            {"id": "acupoint:ht07:神门", "name": "神门", "role": "主穴", "reason": "安神定惊敛浮火"},
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "配穴", "reason": "宁心悸安神定烦"},
        ],
    },
    {
        "atom_id": "atom:ganjiang-fuzi",
        "formula_id": "shanghan:干姜附子汤",
        "name": "干姜附子汤",
        "six_meridian": "下复发汗昼日烦躁夜安静亡阳证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "心烦失眠": 22,
            "身冷": 18,
            "脚冷": 18,
            "口不渴": 14,
            "口中和": 12,
        },
        "pair_bonus": [("心烦失眠", "脚冷", 16)],
        "boost_pulses": {"沉": 12, "微细": 14},
        "conflict_pulses": {"洪大": -22, "滑": -16},
        "conflict_symptoms": {"舌黄厚燥": -20, "大渴": -22},
        "pathogenesis": "《伤寒》下之后复发汗，昼日烦躁不得眠，夜而安静，不呕不渴无表证，脉沉微身无大热者，干姜生附顿服急回肾阳而抑阴躁。",
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（重灸）", "reason": "救急肾阳虚衰昼日阴躁"},
            {"id": "acupoint:ki03:太溪", "name": "太溪", "role": "配穴", "reason": "振少阴真阳退阴盛躁扰"},
        ],
    },
    {
        "atom_id": "atom:guizhi-jiagui",
        "formula_id": "shanghan:桂枝加桂汤",
        "name": "桂枝加桂汤",
        "six_meridian": "烧针汗后奔豚气从少腹上冲心证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "气上冲胸": 30,
            "心悸": 20,
            "有汗": 10,
            "身冷": 8,
        },
        "pair_bonus": [("气上冲胸", "心悸", 16)],
        "boost_pulses": {"沉": 8, "弦": 10},
        "conflict_pulses": {"洪大": -16},
        "conflict_symptoms": {"大便干": -16, "舌黄厚燥": -16},
        "pathogenesis": "《伤寒》烧针令其汗，针处被寒核起而赤，必发奔豚，气从少腹上冲心者，重用桂枝通心阳以平降下焦寒气上逆。",
        "acupoints": [
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "主穴", "reason": "宽胸平逆定奔豚冲心"},
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "配穴（温灸）", "reason": "温化下焦奔豚之本"},
        ],
    },
    {
        "atom_id": "atom:gancao-ganjiang",
        "formula_id": "jinkui:甘草干姜汤",
        "name": "甘草干姜汤",
        "six_meridian": "虚寒肺痿多涎不咳小便数证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "口不渴": 18,
            "小便自利": 22,
            "眩晕": 12,
            "身冷": 16,
            "虚喘短气": 16,
        },
        "pair_bonus": [("小便自利", "身冷", 14)],
        "boost_pulses": {"沉": 10, "微细": 12, "迟": 10},
        "conflict_pulses": {"洪大": -20, "数": -16},
        "conflict_symptoms": {"口渴": -18, "大渴": -22, "高热": -18},
        "pathogenesis": "《伤寒》29条误汗脚挛急先复阳及《金匮》肺痿吐涎沫而不咳、其人不渴必遗尿小便数、以上虚不能制下故也，甘草干姜辛甘温肺复阳。",
        "acupoints": [
            {"id": "acupoint:bl13:肺俞", "name": "肺俞", "role": "主穴（灸）", "reason": "温补肺气以摄上焦涎沫"},
            {"id": "acupoint:lu01:中府", "name": "中府", "role": "配穴", "reason": "培土生金固肺卫之虚"},
        ],
    },
    {
        "atom_id": "atom:baihe-zhimu",
        "formula_id": "jinkui:百合知母汤",
        "name": "百合知母汤",
        "six_meridian": "百合病已发汗后阴虚内燥证",
        "polarity": "yin_def_heat",
        "symptom_weights": {
            "心烦失眠": 22,
            "骨蒸盗汗": 18,
            "口苦": 14,
            "口渴": 14,
            "舌红少苔": 18,
        },
        "pair_bonus": [("心烦失眠", "舌红少苔", 14)],
        "boost_pulses": {"微细": 12, "数": 12},
        "conflict_pulses": {"紧": -16},
        "conflict_symptoms": {"下利清谷": -20, "身冷": -16},
        "pathogenesis": "《金匮》百合病发汗后者（误汗更伤心肺之阴而燥渴烦热），用百合知母汤滋阴润燥清虚热。",
        "acupoints": [
            {"id": "acupoint:ki03:太溪", "name": "太溪", "role": "主穴", "reason": "滋水清心肺误汗后虚燥"},
            {"id": "acupoint:ht07:神门", "name": "神门", "role": "配穴", "reason": "宁心除烦安卧"},
        ],
    },
    {
        "atom_id": "atom:fangji-fuling",
        "formula_id": "jinkui:防己茯苓汤",
        "name": "防己茯苓汤",
        "six_meridian": "皮水四肢肿聂聂动证",
        "polarity": "balanced",
        "symptom_weights": {
            "水肿": 28,
            "小便不利": 22,
            "虚喘短气": 12,
        },
        "pair_bonus": [("水肿", "小便不利", 14)],
        "boost_pulses": {"浮": 10, "沉": 8},
        "conflict_pulses": {},
        "conflict_symptoms": {"下利清谷": -14},
        "pathogenesis": "《金匮》皮水为病，四肢肿，水气在皮肤中，四肢聂聂动者，防己茯苓汤通阳益卫利皮肤之水（不汗不恶风异于越婢）。",
        "acupoints": [
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "主穴", "reason": "培土制水消四肢皮肿"},
            {"id": "acupoint:sp06:三阴交", "name": "三阴交", "role": "配穴", "reason": "健脾利水通三阴水道"},
        ],
    },
    {
        "atom_id": "atom:linggan-wuwei-jiangxin",
        "formula_id": "jinkui:苓甘五味姜辛汤",
        "name": "苓甘五味姜辛汤",
        "six_meridian": "无表寒而痰饮咳喘胸满证",
        "polarity": "yang_def_cold",
        "symptom_weights": {
            "咳喘痰多": 24,
            "胸痹": 14,
            "口不渴": 14,
            "虚喘短气": 14,
            "身冷": 10,
        },
        "pair_bonus": [("咳喘痰多", "口不渴", 14)],
        "boost_pulses": {"沉": 12, "弦": 10},
        "conflict_pulses": {"洪大": -20},
        "conflict_symptoms": {"口渴": -16, "高热": -18, "大渴": -20},
        "pathogenesis": "《金匮》冲气即低而反更咳胸满者，去桂加茯苓干姜细辛五味子，不外散而专温化肺胃寒饮止咳。",
        "acupoints": [
            {"id": "acupoint:lu01:中府", "name": "中府", "role": "主穴", "reason": "宣肺散寒饮止久咳胸满"},
            {"id": "acupoint:bl13:肺俞", "name": "肺俞", "role": "配穴", "reason": "温肺俞通阳化饮"},
        ],
    },
    *EXPANDED_PATTERN_ATOMS,
]


# ---------------------------------------------------------------------------
# 4. Multi-School Clinical Differential Notes (5-Layer Grounded)
# ---------------------------------------------------------------------------
EXTRA_DIFFERENTIAL_NOTES: list[dict[str, Any]] = [
    {
        "trigger_all": ("失血", "骨蒸盗汗"),
        "alt_trigger_all": ("失血", "手掌烦热"),
        "title": "【关键鉴别】古虚劳（建中）vs 今阴虚吐血咳嗽骨蒸（徐灵胎/血证论禁温补红线）",
        "explanation": "《伤寒》小建中汤所治「虚劳里急、悸衄腹痛」属脾肾阳虚气弱不摄；若现见「吐血/咯血、咳嗽、骨蒸盗汗、手掌烦热、舌红少苔、脉数或微细无力」，乃肺肾阴虚火旺逼血上行，与古虚劳迥异！徐灵胎《慎疾刍言》痛斥后世见虚劳便投人参建中、温燥发汗乃速死之道；《伤寒》亦明训衄家亡血家严禁麻黄发汗。当取泻心、黄连阿胶、百合地黄或炙甘草清火养阴宁血之法。",
    },
    {
        "trigger_all": ("经期热入血室", "发热"),
        "alt_trigger_all": ("经期热入血室", "往来寒热"),
        "title": "【妇科关键】女子经期外感：唯用小柴胡汤配期门穴，严禁汗下",
        "explanation": "《伤寒论》143–145条及汉唐临证铁律：女子月经适来、适断或经期忽感外邪（发热恶寒、头痛胸胁闷、甚则寒热如疟、暮则谵语），因冲任血室空虚，严禁使用麻黄汤等峻汗剂或承气汤寒下，以免邪气乘虚直陷血室！唯用小柴胡汤和解枢机、保津护血，针灸必配合肝募「期门穴」清泻血室实热。",
    },
    {
        "trigger_all": ("热厥", "口渴"),
        "alt_trigger_all": ("热厥", "腹满拒按"),
        "title": "【关键鉴别】厥深热深（热厥）vs 阴寒厥逆（寒厥）",
        "explanation": "《伤寒》335/350条及丹波《辑义》、徐灵胎《兰台轨范》（另大冢《解说》厥阴篇亦载「脉滑而厥，白虎汤主之」）皆重申：四肢厥冷决非尽属寒证！若见「四肢厥逆」却同时见「脉滑、数、沉实有力、口渴喜冷饮、小便深黄、腹胀痛拒按、舌黄燥」，乃里热深伏致阳气内郁不达四末之「热厥」（厥深者热亦深），当用白虎汤清热或大承气汤急下；若误见手足凉便投四逆汤、附子，必助火伤阴致危。",
    },
    {
        "trigger_all": ("戴阳格阳", "下利清谷"),
        "alt_trigger_all": ("戴阳格阳", "身冷"),
        "title": "【关键鉴别】真寒假热（戴阳格阳）vs 阳明实热",
        "explanation": "《伤寒》317条、丹波《辑义》、陈士铎《石室秘录》警示：下利清谷、四肢厥逆、脉微欲绝而面色泛红如妆（「戴阳」）、甚至身反不恶寒、咽痛烦躁者，乃内真寒极盛格拒微阳于外之假热危证！鉴别铁据在于「脉微细欲绝、小便清白或舌白厚滑润」：切忌误作阳明热投白虎承气，须用通脉四逆汤或白通汤破阴回阳（反佐冷服或加人尿猪胆汁防格拒）。",
    },
    {
        "trigger_all": ("下利清谷", "身冷"),
        "alt_trigger_all": ("下利清谷", "无汗"),
        "title": "【伤寒次序铁律】表里同病兼下利清谷：先温里、后解表",
        "explanation": "《伤寒》91条及丹波元简、徐灵胎明确指出：太阳与少阴太阴表里同病，若兼「下利清谷不止」与「身痛发热恶寒」，切忌直接发汗（发汗必致亡阳暴脱）！必须先以四逆汤或通脉四逆汤温复里阳；俟下利止、手足转温而表证身痛仍存者，方可小用桂枝汤和解。",
    },
    {
        "trigger_all": ("自利清水热", "咽干"),
        "alt_trigger_all": ("自利清水热", "腹满拒按"),
        "title": "【生死急证】少阴急下存阴（热结旁流）vs 虚寒下利清谷",
        "explanation": "《伤寒》320–322条及《证因方论》提示：少阴病得之二三日即见「口燥咽干、自利清水色纯青、心下必痛、腹胀满痛拒按」，切莫被「清水下利」迷惑而误投理中、四逆或桃花汤！此为阳明燥屎壅塞大肠、反逼清液从旁漏出（「热结旁流」下劫肾水），刻不容缓当用大承气汤急下以救少阴垂涸之阴。",
    },
    {
        "trigger_all": ("心下硬痛", "舌白厚湿"),
        "alt_trigger_all": ("心下硬痛", "饮食如故"),
        "title": "【死候警报】结胸实证 vs 脏结禁下危候",
        "explanation": "《伤寒》129/130/167条、丹波元简《辑义》与徐灵胎《伤寒论类方》重点辨析：同见心下硬痛，「结胸」必伴口渴、不欲食、苔黄燥、脉沉紧或浮滑有力，属水热实邪互结胸脘，宜大陷胸或小陷胸汤攻破；若反见「饮食如故、时时下利、舌上白胎滑腻、不渴、寸脉浮而关脉小细沉紧」者，名曰「脏结」（脾肾真阳败竭而阴寒固结脏膜），属难治危重之候，绝禁妄下，误下立危。",
    },
    {
        "trigger_all": ("咽喉肿痛", "身冷"),
        "alt_trigger_all": ("咽喉肿痛", "下利清谷"),
        "title": "【少阴咽痛四法】阴虚、客寒、痰疮、阴蛾切忌一律苦寒清热",
        "explanation": "《伤寒》310–313条及丹波《辑义》、《石室秘录》指出：咽痛若见脉微细、身冷或下利，切不可一概投板蓝根牛黄等寒凉封喉！少阴虚火上浮用猪肤汤；客寒痰阻（不肿不赤而痛）用半夏散及汤；微热用甘草汤，痰瘀脓痛用桔梗汤；咽疮失音用苦酒汤；若咽痛闭塞兼苔白滑冷如寒水冰凝，为极罕「阴蛾寒痹」，须温通破寒，寒药必毙。",
    },
    {
        "trigger_all": ("皮肤干燥", "便溏"),
        "alt_trigger_all": ("皮肤干燥", "口渴"),
        "title": "【汉唐秘旨】皮肤外干必有内湿 / 外湿必有内燥",
        "explanation": "汉唐临床重申：见全身皮肤干燥龟裂瘙痒，若同时伴大便溏软、腰以下冷或口渴饮水反不利，非单一胃热伤津（切忌叠用两味白虎系苦寒剂雪上加霜伤中阳）！乃里寒水停或湿郁中下，致脾肾阳气不能升清布津润于皮毛；当从太阴脾肾水湿或风湿郁表论治，恢复脾阳运水蒸津则皮燥自润。",
    },
    {
        "trigger_all": ("淋痛尿血", "小便深黄"),
        "alt_trigger_all": ("淋痛尿血", "发热"),
        "title": "【下焦淋证】尿血刺痛、石淋辨治（忌误套痢疾方或妄投大热）",
        "explanation": "《伤寒》《金匮》及汉唐三结石诊疗体系：见小便刺痛尿血、尿赤石淋，系下焦膀胱湿热伤阴或砂石络阻，当用猪苓汤育阴利水、赤豆当归散/滑石白鱼蒲灰清利尿血通淋（不可误套葛根芩连/白头翁肠痢方）；更禁在淋家（《伤寒》84条：淋家不可发汗，发汗则便血）妄用麻黄或纯燥热附子助火迫血。",
    },
    {
        "trigger_all": ("心脏术后禁忌", "身冷"),
        "alt_trigger_all": ("心脏术后禁忌", "无汗"),
        "title": "【现代临证红线】心脏外科术后（搭桥/支架/换瓣）严禁重用麻黄发汗",
        "explanation": "汉唐心脏病临证总则反复警诫：凡曾行开胸搭桥、瓣膜置换或放支架致心肺经气受创者，哪怕见恶寒无汗喘咳，临床亦严禁径投麻黄汤、大青龙汤等猛发汗宣散心阳之峻剂，恐强发汗导致心阳外越暴脱！宜改以和缓桂枝调和营卫或按实证择温和护心之法。",
    },
    {
        "trigger_all": ("发热", "舌红少苔"),
        "alt_trigger_all": ("咳喘痰多", "身冷"),
        "title": "【石室·慎疾铁律】邪留禁补（闭门留寇）与喘证虚实之分",
        "explanation": "《石室秘录》与《慎疾刍言》深戒：凡表寒（无汗恶寒）或痰热瘀水积实未清之时，早用五味子、熟地、阿胶、人参纯补收敛，必致「补住其邪、闭门留寇」！治喘亦先别风寒闭肺实喘（小青龙/射干麻黄）与肾不纳气虚喘短气（隔一补脾肺、纳肾气，忌过度发散伤肺）。",
    },
]


# ---------------------------------------------------------------------------
# 5. Context-Aware Suppression, Boosting & 5-Layer Classical Redline Engine
# ---------------------------------------------------------------------------
MAHUANG_ATOM_IDS: frozenset[str] = frozenset(
    {
        "atom:mahuang-tang",
        "atom:daqinglong",
        "atom:gegengtang",
        "atom:xiaoqinglong",
        "atom:maxingshigan",
        "atom:mahuang-fuzi-xixin",
        "atom:yuebi",
        "atom:shegan-mahuang",
        "atom:guizhi-mahuang-geban",
        "atom:guizhi-er-mahuang-yi",
        "atom:guizhi-er-yuebi-yi",
        "atom:gegen-jia-banxia",
        "atom:mahuang-lianqiao-chixiaodou",
        "atom:mahuang-fuzi-gancao",
        "atom:mahuang-shengma",
        "atom:mahuang-jiazhu",
        "atom:mahuang-xingren-yiyi-gancao",
        "atom:muli-tang",
        "atom:houpo-mahuang",
        "atom:xiaoqinglong-shigao",
        "atom:yuebi-jia-banxia",
        "atom:gancao-mahuang",
        "atom:guigan-jiangzao-maxin-fuzi",
        "atom:banxia-mahuang-wan",
        "atom:wenge-tang-jk",
    }
)


def _suppress_atoms(
    scored_atoms: list[dict[str, Any]],
    atom_ids: set[str],
    reason: str,
    *,
    floor_score: int = -10,
) -> None:
    """Mark matching scored_atoms as suppressed with transparent classical conflict reasons."""
    for entry in scored_atoms:
        if entry["atom_id"] in atom_ids:
            entry["suppressed"] = True
            entry["score"] = min(entry.get("score", 0), floor_score)
            reasons = entry.setdefault("conflict_reasons", [])
            if reason not in reasons:
                reasons.append(reason)


def _suppress_mahuang_family(scored_atoms: list[dict[str, Any]], reason: str) -> None:
    """Suppress all Mahuang-containing formulas safely across scored_atoms."""
    for entry in scored_atoms:
        if entry["atom_id"] in MAHUANG_ATOM_IDS or "麻黄" in (entry.get("herbs") or []):
            entry["suppressed"] = True
            entry["score"] = min(entry.get("score", 0), -10)
            reasons = entry.setdefault("conflict_reasons", [])
            if reason not in reasons:
                reasons.append(reason)


def _boost_atoms(
    scored_atoms: list[dict[str, Any]],
    boost_map: dict[str, int],
    *,
    matched_cue: str = "",
) -> None:
    """Safely add contextual priority points to unsuppressed classical atoms."""
    for entry in scored_atoms:
        aid = entry["atom_id"]
        if aid in boost_map and not entry.get("suppressed"):
            entry["score"] = entry.get("score", 0) + boost_map[aid]
            if matched_cue and matched_cue not in entry.get("matched_symptoms", []):
                entry.setdefault("matched_symptoms", []).append(matched_cue)


REDLINE_ANCHOR_SPECS: dict[str, list[tuple[str, int, str, str]]] = {
    "redline:yin-xulao-tuxue": [
        ("xu-lingtai-collection-pdf", 263, "虚劳", "《慎疾刍言》古今虚劳分界"),
        ("tang-rongchuan-xuezhenglun-pdf", 13, "衄家", "《血证论》亡血禁汗"),
    ],
    "redline:jingqi-chaihu": [
        ("ni-shanghan-pdf", 105, "期门", "《人纪伤寒》热入血室/期门"),
        ("ni-hantang-formulas-pdf", 53, "小柴胡", "《汉唐》经期外感小柴胡"),
    ],
    "redline:rejue-vs-hanjue": [
        ("shanghan-juyi-book-txt", 101, "脉滑而厥", "《伤寒论辑义》350条热厥"),
        ("xu-lingtai-collection-pdf", 261, "厥深", "《兰台轨范》厥深热深"),
        ("otsuka-shanghan-docx", 8, "脉滑而厥", "《大冢解说》厥阴脉滑而厥"),
    ],
    "redline:daiyang-geyang": [
        ("shanghan-juyi-book-txt", 95, "通脉四逆汤", "《伤寒论辑义》317条戴阳"),
        ("xu-lingtai-collection-pdf", 206, "通脉四逆汤", "《伤寒类方》通脉四逆汤"),
    ],
    "redline:xianli-houbiao": [
        ("xu-lingtai-collection-pdf", 205, "救里", "《伤寒类方》先救里后救表"),
        ("shanghan-juyi-book-txt", 33, "救里", "《伤寒论辑义》91条救里"),
    ],
    "redline:shaoyin-jixia": [
        ("shanghan-juyi-book-txt", 96, "自利清水", "《伤寒论辑义》321条急下存阴"),
    ],
    "redline:zangjie-jinxia": [
        ("shanghan-juyi-book-txt", 47, "脏结", "《伤寒论辑义》脏结禁下"),
        ("xu-lingtai-collection-pdf", 215, "脏结", "《伤寒类方》结胸与脏结"),
    ],
    "redline:shaoyin-yantong": [
        ("chen-shiduo-shishimilu-txt", 129, "阴蛾", "《石室秘录》阴蛾寒闭"),
        ("shanghan-juyi-book-txt", 92, "猪肤汤", "《伤寒论辑义》少阴咽痛"),
    ],
    "redline:heart-surgery-no-mahuang": [
        ("ni-hantang-formulas-pdf", 199, "绕道", "《汉唐》心脏手术后禁麻黄"),
        ("ni-hantang-articles-cases-pdf", 43, "心脏", "《汉唐医案》心脏术后禁麻黄"),
    ],
    "redline:relin-niaoxue": [
        ("shanghan-juyi-book-txt", 32, "淋家", "《伤寒论辑义》淋家禁汗"),
        ("ni-hantang-formulas-pdf", 184, "HT-65", "《汉唐》HT-65下焦淋石"),
    ],
    "redline:skin-dry-inner-damp": [
        ("ni-hantang-formulas-pdf", 68, "HT-16", "《汉唐》HT-16皮肤干痒癣"),
        ("ni-hantang-articles-cases-pdf", 86, "皮肤干燥", "《汉唐医案》皮肤外干内湿"),
    ],
    "redline:xuchuan-bomen": [
        ("chen-shiduo-shishimilu-txt", 129, "抬肩", "《石室秘录》实喘抬肩 vs 虚喘"),
        ("xu-lingtai-collection-pdf", 376, "五味子", "《慎疾刍言》五味邪留禁补"),
    ],
    "redline:wuhan-shigao-jixu": [
        ("chen-shiduo-shishimilu-txt", 82, "无汗而渴", "《石室秘录》无汗大渴忌石膏"),
        ("huangdi-waijing-pdf", 83, "从逆", "《黄帝外经》从逆窥源辨"),
    ],
    "redline:beiehan-kouzhonghe": [
        ("xu-lingtai-collection-pdf", 209, "口中和", "《伤寒类方》口中和背恶寒"),
    ],
    "redline:hanhua-huangdan": [
        ("wang-rulin-zhengyinfanglun-doc", 20, "硝石矾石散", "《证因方论》女劳黑瘅"),
        ("xu-lingtai-collection-pdf", 211, "茵陈蒿汤", "《伤寒类方》茵陈蒿汤"),
    ],
    "redline:yuxue-farre-yuanjin": [
        ("ni-jinkui-pdf", 333, "先便后血", "《金匮》远血黄土/近血赤豆"),
        ("tang-rongchuan-xuezhenglun-pdf", 54, "远血", "《血证论》先便后血远血"),
        ("huangdi-waijing-pdf", 56, "补气", "《黄帝外经》大失血急固气"),
    ],
    "redline:pregnancy-contraindication": [
        ("ni-jinkui-pdf", 389, "当归芍药散", "《人纪金匮》妊娠腹痛水肿当归芍药散"),
        ("ni-jinkui-pdf", 390, "当归贝母苦参丸", "《人纪金匮》妊娠小便难当归贝母苦参丸"),
        ("ni-jinkui-pdf", 393, "干姜人参半夏丸", "《人纪金匮》妊娠恶阻干姜人参半夏丸"),
    ],
    "redline:hanshan-futong": [
        ("ni-jinkui-pdf", 179, "寒疝", "《人纪金匮》腹满寒疝脉证"),
        ("xu-lingtai-collection-pdf", 300, "乌头桂枝汤", "《兰台轨范》寒疝大乌头/乌头桂枝"),
    ],
}


@lru_cache(maxsize=1)
def _book_catalog_meta() -> dict[str, dict[str, Any]]:
    cat_path = DATA_DIR / "library" / "catalog.json"
    if not cat_path.exists():
        return {}
    raw = json.loads(cat_path.read_text(encoding="utf-8"))
    return {b["book_id"]: b for b in raw.get("books", [])}


@lru_cache(maxsize=32)
def _load_lib_page_index(book_id: str) -> dict[int, dict[str, Any]]:
    jsonl_path = LIB_SOURCES_DIR / f"{book_id}.jsonl"
    if not jsonl_path.exists():
        return {}
    rows = {}
    for ln in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        row = json.loads(ln)
        rows[int(row["page_no"])] = row
    return rows


@lru_cache(maxsize=64)
def resolve_redline_anchors(redline_id: str) -> list[dict[str, Any]]:
    """Resolve and hash-verify verbatim classical prose anchors for a clinical redline."""
    specs = REDLINE_ANCHOR_SPECS.get(redline_id, ())
    if not specs:
        return []
    meta = _book_catalog_meta()
    anchors: list[dict[str, Any]] = []
    for book_id, page_no, q, label in specs:
        row = _load_lib_page_index(book_id).get(int(page_no))
        if not row:
            continue
        body = row.get("body_text") or ""
        if not body:
            continue
        pos = _locate_in_body(body, q.lower())
        if pos < 0:
            pos = 0
        start = max(0, pos - 28)
        end = min(len(body), pos + 88)
        snippet = re.sub(r"\s+", " ", body[start:end]).strip()
        snippet = re.sub(r"(?<=[\u4e00-\u9fff，。；：、！？])\s+(?=[\u4e00-\u9fff])", "", snippet)
        bm = meta.get(book_id, {})
        anchors.append(
            {
                "book_id": book_id,
                "book_title": bm.get("short_title", book_id),
                "shelf": bm.get("shelf", "classical_companions"),
                "page_no": int(page_no),
                "unit_label": row.get("unit_label", f"第 {page_no} 页"),
                "section_title": row.get("section_title", ""),
                "q": q,
                "label": label,
                "snippet": snippet,
                "text_sha256": row.get("text_sha256", ""),
            }
        )
    return anchors


def evaluate_classical_context(
    scored_atoms: list[dict[str, Any]],
    all_atoms: list[dict[str, Any]],
    symptoms: list[str],
    pulses: list[str],
    tongues: list[str],
    raw_q: str,
    fmap: dict[str, dict[str, Any]] | None = None,
    herb_fn: Any = None,
) -> dict[str, Any]:
    """Apply multi-school contextual redlines, rescue missing critical atoms, and return grounded alerts.

    Returns dict with keys:
    - "redlines": list of 5-layer attributed high-risk warning dicts
    - "extra_safety_lines": list of concise plaintext alerts for decoction_and_safety
    - "extra_acupoints": contextual must-add acupoints (e.g. 期门 for 经期外感)
    """
    redlines: list[dict[str, Any]] = []
    extra_safety: list[str] = []
    extra_acupoints: list[dict[str, str]] = []
    scored_by_id = {a["atom_id"]: a for a in scored_atoms}

    def _ensure_atom_present(atom_id: str, min_score: int, cue_label: str) -> None:
        if atom_id in scored_by_id:
            entry = scored_by_id[atom_id]
            entry["suppressed"] = False
            entry["score"] = max(entry.get("score", 0), min_score)
            if cue_label and cue_label not in entry.get("matched_symptoms", []):
                entry.setdefault("matched_symptoms", []).append(cue_label)
            return
        src = next((a for a in all_atoms if a["atom_id"] == atom_id), None)
        if src:
            fobj = (fmap or {}).get(src["formula_id"], {})
            new_entry = {
                **src,
                "score": min_score,
                "suppressed": False,
                "matched_symptoms": [cue_label] if cue_label else [],
                "matched_pulses": [f"+脉{p}" for p in pulses if p in src.get("boost_pulses", {})],
                "conflict_reasons": [],
                "formula_summary": fobj.get("indication", ""),
                "decoction": fobj.get("decoction_method", ""),
                "herbs": herb_fn(fobj) if herb_fn else [],
            }
            scored_atoms.append(new_entry)
            scored_by_id[atom_id] = new_entry

    sym_set = set(symptoms)
    pulse_set = set(pulses)
    tongue_set = set(tongues)

    # --- Redline 1: 吐血/亡血家禁汗 + 阴虚骨蒸咯血禁温补小建中/人参 ---
    has_bleeding = "失血" in sym_set
    has_upper_yin_heat = bool({"骨蒸盗汗", "手掌烦热", "舌红少苔"} & (sym_set | tongue_set))
    has_yin_heat_bleeding = has_bleeding and (
        has_upper_yin_heat
        or (
            "数" in pulse_set
            and not ({"淋痛尿血", "先血后便", "先便后血"} & sym_set)
            and not ({"身冷", "脚冷", "下利清谷"} & sym_set)
        )
        or ("微细" in pulse_set and "咳喘痰多" in sym_set and "骨蒸盗汗" in sym_set)
    )
    if has_bleeding:
        sweat_reason = "《伤寒》83/85条、《血证论》：衄家/亡血家不可发汗（麻黄桂枝发汗必动血亡阳）"
        _suppress_mahuang_family(scored_atoms, sweat_reason)
    if has_yin_heat_bleeding:
        yin_reason = "徐灵胎《慎疾刍言》：阴虚吐血咳嗽骨蒸脉数非古虚劳，严禁小建中汤/人参/麻桂温补发汗，误用必毙"
        _suppress_atoms(
            scored_atoms,
            {"atom:xiaojianzhong", "atom:guizhi-jiafuzi", "atom:guizhi", "atom:sini", "atom:lizhong", "atom:dajianzhong"},
            yin_reason,
        )
        _ensure_atom_present("atom:jinkui-xiexin", 48, "失血")
        _ensure_atom_present("atom:baihe-dihuang", 46, "骨蒸盗汗")
        _boost_atoms(
            scored_atoms,
            {"atom:jinkui-xiexin": 12, "atom:huanglian-ejiao": 18, "atom:baihe-dihuang": 12, "atom:zhigancao": 12, "atom:maimendong": 12},
            matched_cue="失血",
        )
        redlines.append(
            {
                "id": "redline:yin-xulao-tuxue",
                "title": "【血证禁汗禁温补红线】古虚劳（建中）vs 今阴虚吐血骨蒸",
                "severity": "critical",
                "classic_basis": "《伤寒论》85条：亡血家，不可发汗；《金匮要略》：吐血衄血宜泻心汤折其火邪。",
                "ni_and_hantang_note": "汉唐临证与针灸体系指出肺肾阴虚咯血重在凉降肺胃逆火、忌燥烈发表。",
                "schools_crossref": "徐灵胎《慎疾刍言》专论「今之阴虚吐血咳嗽骨蒸脉数，绝非古虚劳，误用小建中人参温补必毙」；唐容川《血证论》严戒血家禁麻桂汗剂。",
                "action_rule": "已自动拦截麻黄系发汗方及小建中/建中温补剂；备选清火养阴凉血轴（仅供临床理论对照学习）。",
            }
        )
        extra_safety.append("【重要临床红线】吐血/亡血兼骨蒸盗汗脉数，严禁麻黄发汗及建中参附温补（防血随热涌）！")

    # --- Redline 2: 女子经期外感 -> 唯用小柴胡 + 期门，禁汗下 ---
    if "经期热入血室" in sym_set and ({"发热", "身冷", "头痛", "无汗", "有汗", "往来寒热"} & sym_set):
        period_reason = "《伤寒》143–145条、《金匮》《汉唐》：经期适来适断外感严禁发汗（麻黄/桂枝）及苦寒攻下（承气），防热入血室"
        _suppress_atoms(
            scored_atoms,
            {"atom:mahuang-tang", "atom:daqinglong", "atom:guizhi", "atom:gegengtang", "atom:dachengqi", "atom:tiaowei-chengqi"},
            period_reason,
        )
        _ensure_atom_present("atom:xiaochaihu", 58, "经期热入血室")
        extra_acupoints.append(
            {
                "id": "acupoint:lv14:期门",
                "name": "期门",
                "role": "经期必配（泻实热）",
                "reason": "《伤寒》143/144条：热入血室、当刺期门、随其实而泻之（与小柴胡汤为标准合璧）",
                "from_axis": "经期外感/热入血室",
            }
        )
        redlines.append(
            {
                "id": "redline:jingqi-chaihu",
                "title": "【经期外感禁汗下】妇人经水适来适断唯宜小柴胡汤配期门",
                "severity": "high_risk",
                "classic_basis": "《伤寒论》143–145条、《金匮要略·妇人杂病》：妇人中风，经水适来/适断，热入血室，小柴胡汤主之，当刺期门。",
                "ni_and_hantang_note": "倪师《人纪》及汉唐临证反复叮嘱：女性经期无论表寒太阳何证，一概不用麻黄桂枝，必直用小柴胡汤和解。",
                "schools_crossref": "丹波《辑义》、大冢《解说》均明言经期忌汗下以免引邪入胞宫血海。",
                "action_rule": "已自动拦截麻黄/桂枝发汗及承气攻下剂，置顶「小柴胡汤」并配「期门穴」。",
            }
        )
        extra_safety.append("【经期用药铁律】月经期外感严禁直接发汗或攻下，唯宜和解少阳枢机（小柴胡汤）配刺期门穴。")

    # --- Redline 3: 热厥（厥深热深）vs 寒厥 ---
    if "热厥" in sym_set:
        rj_reason = "《伤寒》350条、丹波《辑义》：脉滑数或腹满尿黄口渴见四肢厥冷属「热厥」（阳气内郁），禁用四逆/真武大热"
        _suppress_atoms(
            scored_atoms,
            {"atom:zhenwu", "atom:sini", "atom:tongmai-sini", "atom:lizhong", "atom:danggui-sini", "atom:fuzi-tang", "atom:guizhi-jiafuzi", "atom:dajianzhong"},
            rj_reason,
        )
        if "下利清谷" not in sym_set:
            _suppress_atoms(scored_atoms, {"atom:baitouweng", "atom:gegen-qinlian"}, "无下利脓血热泻之纯热厥证，不以痢疾方主轴混用")
        if {"口渴", "喜冷饮", "高热"} & sym_set or "滑" in pulse_set or "数" in pulse_set:
            _ensure_atom_present("atom:baihu", 52, "热厥")
        if {"腹满拒按", "大便干", "腹痛"} & sym_set:
            _ensure_atom_present("atom:dachengqi", 54, "热厥")
        redlines.append(
            {
                "id": "redline:rejue-vs-hanjue",
                "title": "【热厥禁温红线】厥深者热亦深（热厥 vs 寒厥）",
                "severity": "critical",
                "classic_basis": "《伤寒论》335/350条：伤寒脉滑而厥者，里有热，白虎汤主之；厥深者热亦深，厥微者热亦微。",
                "ni_and_hantang_note": "汉唐辨厥：勿见手足厥冷便投四逆！必参脉滑数有力、口渴喜冷饮、尿黄腹满拒按。",
                "schools_crossref": "丹波元简《伤寒论辑义》、徐灵胎《兰台轨范》（另大冢《解说》厥阴篇亦载「脉滑而厥，白虎汤主之」）详辨热郁于内则手足愈厥，当清下（白虎/承气）勿误温。",
                "action_rule": "已拦截四逆/真武等温阳剂，解锁并提升白虎汤（里热散厥）或大承气汤（实闭热厥）。",
            }
        )
        extra_safety.append("【重要临床鉴别】四肢厥冷兼滑数脉/口渴/小便深黄/腹痛拒按乃「热厥」，切勿误投四逆附子！")

    # --- Redline 4: 真寒假热 · 戴阳格阳 ---
    has_cold_core = bool({"下利清谷", "脚冷", "小便清白", "舌白厚湿", "舌淡胖滑"} & (sym_set | tongue_set)) or bool({"微细", "迟"} & pulse_set)
    if "戴阳格阳" in sym_set and has_cold_core and not ({"腹满拒按", "舌黄厚燥"} & (sym_set | tongue_set)):
        dy_reason = "《伤寒》317条、丹波《辑义》：少阴阴盛格阳（戴阳面赤却下利清谷脉微细）属真寒假热，严禁白虎/承气/泻心苦寒"
        _suppress_atoms(
            scored_atoms,
            {"atom:baihu", "atom:baihu-jiarenshen", "atom:dachengqi", "atom:tiaowei-chengqi", "atom:dahuang-huanglian-xiexin", "atom:jinkui-xiexin", "atom:huanglian-ejiao"},
            dy_reason,
        )
        _ensure_atom_present("atom:tongmai-sini", 68, "戴阳格阳")
        _boost_atoms(scored_atoms, {"atom:baitong": 22, "atom:sini": 16}, matched_cue="戴阳格阳")
        redlines.append(
            {
                "id": "redline:daiyang-geyang",
                "title": "【真寒假热救急】少阴戴阳格阳证（忌投苦寒）",
                "severity": "critical",
                "classic_basis": "《伤寒论》317条：少阴病，下利清谷，里寒外热，手足厥逆，脉微欲绝，身反不恶寒，其人面色赤……通脉四逆汤主之。",
                "ni_and_hantang_note": "倪师急救脉诀：但见脉微细沉绝、小便清白，纵面红燥热如戴阳妆色，亦是真阳外脱危候。",
                "schools_crossref": "丹波《辑义》引注格阳机理，陈士铎《石室秘录》亦主假热需反佐冷服辛热药回阳（或加人尿猪胆汁防格拒）。",
                "action_rule": "已屏蔽苦寒凉下剂，优先呈现「通脉四逆汤 / 白通汤」回阳救逆脉案逻辑。",
            }
        )
        extra_safety.append("【危重假热警示】下利清谷+手足厥+脉微而面赤反不恶寒属「真寒假热·戴阳格阳」，误用苦寒立危！")

    # --- Redline 5: 表里同病兼下利清谷 -> 先救里、后攻表 ---
    if "下利清谷" in sym_set and ({"身冷", "脚冷"} & sym_set or bool({"微细", "沉"} & pulse_set)) and "自利清水热" not in sym_set:
        if {"发热", "头痛", "无汗", "有汗", "项背强"} & sym_set:
            ri_reason = "《伤寒》91条、丹波《辑义》、徐灵胎：医法大禁——下利清谷兼身疼表寒，必须「先救其里（四逆/通脉四逆），后攻其表」，严禁先用麻黄/桂枝发汗"
            _suppress_mahuang_family(scored_atoms, ri_reason)
            _suppress_atoms(scored_atoms, {"atom:guizhi"}, ri_reason)
            _ensure_atom_present("atom:sini", 66, "下利清谷")
            _boost_atoms(scored_atoms, {"atom:tongmai-sini": 16}, matched_cue="下利清谷")
            redlines.append(
                {
                    "id": "redline:xianli-houbiao",
                    "title": "【伤寒次序铁律】表里同病兼下利清谷：先温里、后攻表",
                    "severity": "critical",
                    "classic_basis": "《伤寒论》91/92条：伤寒医下之，续得下利清谷不止，身疼痛者，急当救里；后身疼痛，清便自调者，急当救表。救里宜四逆汤，救表宜桂枝汤。",
                    "ni_and_hantang_note": "汉唐临床强调中焦太阴少阴败竭时若强汗解表，即刻亡阳厥脱。",
                    "schools_crossref": "丹波《辑义》、大冢《解说》、徐灵胎《伤寒论类方》均列此条为汗下先后死活纲领。",
                    "action_rule": "已拦截麻黄/桂枝表药，置顶「四逆汤 / 通脉四逆汤」先救里阳。",
                }
            )
            extra_safety.append("【救治次序红线】下利清谷+身冷脉微纵兼发热表证，必须「先温里（四逆）、待下利止再轻和表」。")

    # --- Redline 6: 少阴急下存阴（热结旁流）---
    if "自利清水热" in sym_set or ("微细" in pulse_set and "咽干" in sym_set and "腹满拒按" in sym_set):
        jixia_reason = "《伤寒》320–322条、《证因方论》：口燥咽干+自利清水色纯青+腹胀满拒按属「热结旁流/少阴急下存阴」，非虚寒下利，禁用理中桃花等温涩止利"
        _suppress_atoms(scored_atoms, {"atom:lizhong", "atom:taohua", "atom:sini", "atom:tongmai-sini"}, jixia_reason)
        _ensure_atom_present("atom:dachengqi", 64, "自利清水热")
        redlines.append(
            {
                "id": "redline:shaoyin-jixia",
                "title": "【少阴急下存阴】热结旁流（自利清水+口燥咽干+腹痛拒按）",
                "severity": "critical",
                "classic_basis": "《伤寒论》320/321条：少阴病，自利清水，色纯青，心下必痛，口干燥者，可下之，宜大承气汤。",
                "ni_and_hantang_note": "倪师课堂重点：纯利臭清水、肠鸣腹胀痛拒按乃是阳明大实燥屎挡道，水从旁绕出，非脾寒水泻。",
                "schools_crossref": "《证因方论》、丹波《辑义》并列少阴三急下与阳明急下同机，慢下或误温则真阴干涸。",
                "action_rule": "已拦截理中/桃花/四逆止利药，置顶「大承气汤」急下存阴逻辑。",
            }
        )
        extra_safety.append("【少阴急下危证】自利清水伴口燥咽干腹痛拒按属「热结旁流」，切忌误作脾寒水泻而温涩！")

    # --- Redline 7: 结胸 vs 脏结死候禁下 ---
    is_zangjie = "心下硬痛" in sym_set and (
        "饮食如故" in sym_set
        or "舌白厚湿" in tongue_set
        or ("下利清谷" in sym_set and "口不渴" in sym_set)
    )
    if is_zangjie:
        zj_reason = "《伤寒》129/130/167条、丹波《辑义》、徐灵胎《类方》：心下硬痛却「饮食如故、时时下利、舌上白胎滑、不渴」属脏结死候，严禁大陷胸/承气猛下"
        _suppress_atoms(scored_atoms, {"atom:daxianxiong", "atom:xiaoxianxiong", "atom:dachengqi", "atom:shizao-tang"}, zj_reason)
        _boost_atoms(scored_atoms, {"atom:sini": 16, "atom:zhenwu": 14, "atom:lizhong": 14}, matched_cue="舌白厚湿")
        redlines.append(
            {
                "id": "redline:zangjie-jinxia",
                "title": "【生死大关 · 禁下警告】脏结阴寒危候 vs 结胸实证",
                "severity": "emergency",
                "classic_basis": "《伤寒论》129/130/167条：饮食如故，时时下利，寸脉浮，关脉小细沉紧，名曰脏结；舌上白胎滑者，难治。",
                "ni_and_hantang_note": "汉唐胃气绝/阳衰鉴别：胸脘痛而舌白厚滑湿、能食或下利者，决不可用甘遂大黄硝黄劫攻。",
                "schools_crossref": "丹波元简《伤寒论辑义》、徐灵胎《伤寒论类方》严判结胸实热（可下）与脏结真阳匮乏（误下即亡）。",
                "action_rule": "已严格拦截大陷胸汤/小陷胸汤/大承气汤，警示临床极高危重难治状态。",
            }
        )
        extra_safety.append("【极危禁下警告】心下硬痛伴「饮食如故 / 舌白厚滑 / 不渴」疑属《伤寒》脏结危候，绝禁攻下！")

    # --- Redline 8: 少阴咽痛四法 + 阴蛾 ---
    if "咽喉肿痛" in sym_set and ({"身冷", "下利清谷"} & sym_set or "微细" in pulse_set or "舌白厚湿" in tongue_set):
        yt_reason = "《伤寒》310–313条、《石室秘录》：少阴微细脉或身冷下利伴咽痛切忌承气/白虎大寒封喉（防阴蛾恶化）"
        _suppress_atoms(scored_atoms, {"atom:dachengqi", "atom:baihu", "atom:baihu-jiarenshen"}, yt_reason)
        _ensure_atom_present("atom:zhufu", 56, "咽喉肿痛")
        _ensure_atom_present("atom:banxia-san", 58, "咽喉肿痛")
        _ensure_atom_present("atom:gancao-tang", 42, "咽喉肿痛")
        _ensure_atom_present("atom:jiegeng-tang", 44, "咽喉肿痛")
        _ensure_atom_present("atom:kujiu-tang", 42, "咽喉肿痛")
        redlines.append(
            {
                "id": "redline:shaoyin-yantong",
                "title": "【少阴咽痛细辨】猪肤/半夏散/甘草/桔梗/苦酒与阴蛾",
                "severity": "high_risk",
                "classic_basis": "《伤寒论》310–313条分立猪肤汤（下利心烦虚火）、半夏散（客寒）、甘草/桔梗汤（微热痰脓）、苦酒汤（咽疮失音）。",
                "ni_and_hantang_note": "汉唐提示咽喉病不可盲目一味清热解毒；须分舌苔白滑寒阻 vs 红赤痰热。",
                "schools_crossref": "陈士铎《石室秘录》专论「阴蛾」：咽闭却口淡苔白滑寒极，寒凉一入口则咽锁窒息，需辛温破寒。",
                "action_rule": "已呈列少阴咽痛诸经方以便依寒热痰疮对证鉴别，并拦截纯苦寒攻下剂。",
            }
        )

    # --- Redline 9: 西医心脏术后严禁麻黄 ---
    if "心脏术后禁忌" in sym_set:
        hs_reason = "汉唐心外科临证总则：搭桥/换瓣/支架术后严禁麻黄系发汗峻剂（麻黄汤/葛根汤/大青龙/小青龙等），防汗出心阳暴脱"
        _suppress_mahuang_family(scored_atoms, hs_reason)
        redlines.append(
            {
                "id": "redline:heart-surgery-no-mahuang",
                "title": "【心脏外科术后铁律】严禁使用麻黄峻汗发越心阳",
                "severity": "emergency",
                "classic_basis": "《伤寒论》心阳悸动与汗为心液总纲：亡阳心悸禁用猛汗剂。",
                "ni_and_hantang_note": "汉唐心脏病案核心忌讳：心脏经西医开胸、搭桥、换瓣、支架后，纵见无汗表寒喘逆，亦绝禁单开麻黄重发汗。",
                "schools_crossref": "徐灵胎重申「汗剂损心气，心病虚极汗出则亡」。",
                "action_rule": "已强制拦截所有麻黄发汗类方剂条目，请由专科医师面对面评估桂枝调和或温阳稳心方案。",
            }
        )
        extra_safety.append("【极高危术后禁忌】心脏外科手术后绝对禁忌发汗峻剂麻黄类方！")

    # --- Redline 10: 下焦热淋尿血（勿误套痢疾方或妄温） ---
    if "淋痛尿血" in sym_set and "下利清谷" not in sym_set:
        lin_reason = "《伤寒》《金匮》：小便刺痛尿血属下焦膀胱热淋/石淋，宜猪苓/赤豆当归通淋，勿误套葛根芩连/白头翁肠痢方或纯温热剂"
        _suppress_atoms(scored_atoms, {"atom:gegen-qinlian", "atom:baitouweng", "atom:taohua"}, lin_reason)
        _ensure_atom_present("atom:zhuling", 56, "淋痛尿血")
        _ensure_atom_present("atom:chidou-danggui", 54, "淋痛尿血")
        redlines.append(
            {
                "id": "redline:relin-niaoxue",
                "title": "【下焦淋证尿血辨】猪苓/赤豆当归通淋（淋家忌汗勿温燥）",
                "severity": "high_risk",
                "classic_basis": "《伤寒论》84条：淋家，不可发汗，发汗必便血；《伤寒》《金匮》水热尿血重用猪苓汤。",
                "ni_and_hantang_note": "汉唐结石诊疗：配合膀胱/肾石压痛点定位，石淋尿血严防助热劫阴药。",
                "schools_crossref": "丹波《辑义》考证淋家汗后血虚络伤变证；《石室》强调淋痛湿热多忌呆滞温补。",
                "action_rule": "已清理肠道痢疾方误匹配，优先呈现猪苓汤/赤豆当归散/五苓方向。",
            }
        )

    # --- Redline 11: 皮肤外干内湿 vs 叠用双白虎 ---
    if "皮肤干燥" in sym_set and ({"便溏", "身冷", "小便不利"} & sym_set or "缓" in pulse_set):
        skin_reason = "汉唐「外干必有内湿/内寒水不布津」：大便溏软或脉不洪实反见皮肤干燥口渴，不可径用纯大寒白虎伤脾阳"
        if "高热" not in sym_set and "洪大" not in pulse_set:
            _suppress_atoms(scored_atoms, {"atom:baihu", "atom:baihu-jiarenshen"}, skin_reason)
        _boost_atoms(scored_atoms, {"atom:wuling": 12, "atom:zhenwu": 10}, matched_cue="皮肤干燥")
        redlines.append(
            {
                "id": "redline:skin-dry-inner-damp",
                "title": "【汉唐肤病关键】外干必内湿（皮肤干燥兼便溏禁妄凉）",
                "severity": "moderate",
                "classic_basis": "《金匮》风湿水气津不上承及太阴脾不散精归肺皮毛论。",
                "ni_and_hantang_note": "汉唐皮肤医案核心辨证：皮肤燥痒伴口渴而便溏/不实热者，乃脾肾阳虚水寒不化津，非胃实热，妄清反令中寒湿增而皮益燥。",
                "schools_crossref": "《黄帝外经》与《血证论》均重脾运水谷精微达于皮毛之理。",
                "action_rule": "未见洪大壮热时已拦截纯苦寒白虎双兄叠用，引导审视健脾温化布津轴。",
            }
        )

    # --- Redline 12: 邪留禁补 & 实喘抬肩 vs 虚喘短气不抬肩 ---
    has_real_asthma_cues = ("水鸡声" in sym_set or any(w in raw_q for w in ("痰鸣", "抬肩", "水鸡声"))) and "不抬肩" not in raw_q
    is_shi_chuan = "咳喘痰多" in sym_set and (has_real_asthma_cues or ("喘" in raw_q and "虚喘" not in raw_q and "不抬肩" not in raw_q)) and "心痛彻背" not in sym_set
    if is_shi_chuan:
        _ensure_atom_present("atom:shegan-mahuang", 74, "咳喘痰多")
        _ensure_atom_present("atom:xiaoqinglong", 72, "咳喘痰多")
        if "胸痛" not in raw_q:
            for entry in scored_atoms:
                if entry["atom_id"] == "atom:wutou-chishizhi":
                    entry["score"] -= 26
    if "虚喘短气" in sym_set and not ({"发热", "无汗", "头痛"} & sym_set) and not has_real_asthma_cues:
        _suppress_atoms(scored_atoms, {"atom:mahuang-tang", "atom:daqinglong"}, "纯少气虚喘不抬肩且无表实闭阻者，严防麻黄散肺耗气")
        _boost_atoms(scored_atoms, {"atom:gancao-ganjiang": 14, "atom:linggan-wuwei-jiangxin": 12, "atom:zhigancao": 10}, matched_cue="虚喘短气")
    if "虚喘短气" in sym_set or has_real_asthma_cues or ("咳喘痰多" in sym_set and ({"发热", "无汗"} & sym_set or "痰饮" in raw_q)):
        redlines.append(
            {
                "id": "redline:xuchuan-bomen",
                "title": "【喘证虚实与邪留禁补】实喘抬肩痰鸣 vs 虚喘短气不抬肩",
                "severity": "high_risk",
                "classic_basis": "《伤寒》《金匮》咳喘上气辨表寒水饮（小青龙/射干麻黄）vs 虚寒多涎（甘草干姜）与麦门冬/炙甘草阴虚肺痿。",
                "ni_and_hantang_note": "汉唐重申外邪未解时早投收敛补药必留邪于肺；五味子止外寒水饮咳必须合干姜细辛散寒降逆。",
                "schools_crossref": "陈士铎《石室秘录》立「实喘必抬肩、虚喘张口短气而不抬肩」铁尺；徐灵胎《慎疾刍言》戒外邪未尽误投五味人参熟地阿胶「闭门留寇」。",
                "action_rule": "已依抬肩痰鸣与不抬肩虚喘分流寒饮散降 vs 温肺补虚轴，外邪未解严防早用纯收敛滋腻。",
            }
        )
        extra_safety.append("【邪留禁补提醒】表邪痰饮未解时忌早投五味子、阿胶、熟地等酸涩滋腻药，防「闭门留寇」（《石室秘录》《慎疾刍言》）。")

    # --- Redline 13: 大渴无汗禁石膏遏热 ---
    if "无汗" in sym_set and "有汗" not in sym_set and ({"大渴", "口渴"} & sym_set) and ({"发热", "高热", "身冷"} & sym_set or "石膏" in raw_q):
        sg_reason = "《石室秘录》《伤寒》：阳明「有汗如雨」始可用白虎石膏清热，若表闭无汗大渴早投纯寒石膏，必遏抑邪热内陷！"
        _suppress_atoms(scored_atoms, {"atom:baihu", "atom:baihu-jiarenshen", "atom:zhuye-shigao"}, sg_reason)
        if {"身冷", "心烦失眠"} & sym_set:
            _ensure_atom_present("atom:daqinglong", 58, "无汗")
        redlines.append(
            {
                "id": "redline:wuhan-shigao-jixu",
                "title": "【无汗大渴禁单石膏】表闭勿用白虎汤遏邪内陷",
                "severity": "critical",
                "classic_basis": "《伤寒论》176/219条及大青龙证：白虎汤主「大汗出、大烦渴」，若脉紧无汗恶寒烦躁须麻黄先开太阳表闭。",
                "ni_and_hantang_note": "人纪伤寒严守白虎四禁与大青龙汤分界：未见真汗出如雨前，单投生石膏知母反将寒湿热邪闭留深陷。",
                "schools_crossref": "陈士铎《石室秘录》明言「阳明热渴必汗出如雨乃可投石膏，无汗而渴用石膏则遏邪不散」；《黄帝外经·从逆窥源篇》论外寒内热反治枢机。",
                "action_rule": "已拦截纯寒白虎系（白虎/白虎加人参/竹叶石膏），引导先辨大青龙散表兼清里或解表机转。",
            }
        )
        extra_safety.append("【无汗大渴红线】无汗表闭见大渴勿径投白虎汤生石膏遏邪内陷！")

    # --- Redline 14: 背恶寒 · 口中和（附子汤）vs 口燥渴（白虎加人参）---
    if "背恶寒" in sym_set:
        if "口中和" in sym_set or ("口不渴" in sym_set and not ({"口渴", "大渴"} & sym_set)):
            bh_reason = "《伤寒》304条、徐灵胎：少阴背恶寒而「口中和（不燥不渴）」属少阴阳虚阴寒凝滞，宜附子汤，禁用白虎寒凉"
            _suppress_atoms(scored_atoms, {"atom:baihu", "atom:baihu-jiarenshen"}, bh_reason)
            _ensure_atom_present("atom:fuzi-tang", 76, "背恶寒")
            _boost_atoms(scored_atoms, {"atom:fuzi-tang": 12}, matched_cue="口中和")
        elif {"口渴", "大渴", "有汗"} & sym_set:
            bh_reason = "《伤寒》168条：背微恶寒而「口燥渴」属表里津气俱热伤（汗出肌疏兼气分大热），宜白虎加人参汤，禁妄温附子四逆"
            _suppress_atoms(scored_atoms, {"atom:fuzi-tang", "atom:sini", "atom:zhenwu"}, bh_reason)
            _ensure_atom_present("atom:baihu-jiarenshen", 62, "背恶寒")
        redlines.append(
            {
                "id": "redline:beiehan-kouzhonghe",
                "title": "【背恶寒寒热分水岭】口中和（少阴附子汤）vs 口燥渴（白虎加人参）",
                "severity": "high_risk",
                "classic_basis": "《伤寒论》304条少阴背恶寒口中和（附子汤）vs 168条背微恶寒口燥渴（白虎加人参汤）。",
                "ni_and_hantang_note": "人纪强调「口中和（口不燥苦不渴、味淡或喜温饮）」乃一字铁证，切分少阴阳虚与阳明里热伤津。",
                "schools_crossref": "徐灵胎《伤寒论类方》直将背恶寒二条对举辨析：一字之差而附子生温与石膏大寒天壤悬隔。",
                "action_rule": "已依「口中和/口不渴」与「口燥渴」完成附子汤温经 vs 白虎加人参清气分流。",
            }
        )

    # --- Redline 15: 阳黄湿热 vs 寒湿阴黄及女劳黑瘅 ---
    if "黄疸" in sym_set and ({"身冷", "脚冷", "下利清谷", "便溏", "手掌烦热"} & sym_set or {"微细", "迟"} & pulse_set or "舌淡胖滑" in tongue_set or any(k in raw_q for k in ("阴黄", "女劳", "黑瘅", "额黑"))):
        if "手掌烦热" in sym_set or any(k in raw_q for k in ("女劳", "黑瘅", "额黑")):
            _ensure_atom_present("atom:xiaoshi-fanshi", 60, "黄疸")
        if ({"身冷", "脚冷", "下利清谷", "便溏"} & sym_set or {"微细", "迟"} & pulse_set or "阴黄" in raw_q) and "舌黄厚燥" not in tongue_set:
            yh_reason = "寒湿阴黄脉迟微或身冷便溏属太阴脾湿寒瘀，忌纯投大承气或单苦寒茵陈蒿猛下伤中阳"
            _suppress_atoms(scored_atoms, {"atom:dachengqi", "atom:yinchenhao"}, yh_reason)
            _ensure_atom_present("atom:yinchen-wuling", 56, "黄疸")
            _boost_atoms(scored_atoms, {"atom:sini": 14, "atom:lizhong": 14}, matched_cue="黄疸")
        redlines.append(
            {
                "id": "redline:hanhua-huangdan",
                "title": "【黄疸阴阳辨】阳黄湿热（茵陈蒿）vs 阴黄寒湿与女劳黑瘅",
                "severity": "high_risk",
                "classic_basis": "《金匮要略·黄疸病脉证并治》分湿热发黄（茵陈蒿/大黄硝石）与女劳黑瘅日晡发热反恶寒（硝石矾石散）及寒湿太阴发黄。",
                "ni_and_hantang_note": "人纪金匮重点：阳黄鲜明如橘子色而渴尿黄用茵陈蒿/五苓；阴黄暗晦身冷便溏脉沉迟须在温里四逆/理中中合茵陈化湿。",
                "schools_crossref": "汪汝麟《证因方论集要》详论硝石矾石散消女劳瘀浊湿黄；徐灵胎《伤寒类方》厘清茵陈蒿加减进退。",
                "action_rule": "已根据寒热苔脉鉴别阴黄温化/女劳黑瘅硝石矾石与阳黄苦寒泻下轴。",
            }
        )

    # --- Redline 16: 下血远血/近血辨与九窍大脱先急补气 ---
    has_blood_collapse_cues = (
        any(k in raw_q for k in ("九窍", "大失血", "血脱", "气随血脱", "黄土"))
        or ("失血" in sym_set and "微细" in pulse_set and "骨蒸盗汗" not in sym_set and "淋痛尿血" not in sym_set)
    )
    if "先便后血" in sym_set or "先血后便" in sym_set or has_blood_collapse_cues:
        if "先便后血" in sym_set:
            _suppress_atoms(scored_atoms, {"atom:dachengqi", "atom:tiaowei-chengqi"}, "下血先便后血属脾阳不统远血（黄土汤证），严禁误用承气猛攻")
            _ensure_atom_present("atom:xiexin-huangtu", 64, "先便后血")
        if "先血后便" in sym_set:
            _ensure_atom_present("atom:chidou-danggui", 62, "先血后便")
        if has_blood_collapse_cues:
            _ensure_atom_present("atom:xiexin-huangtu", 56, "失血")
            _ensure_atom_present("atom:baiye", 52, "失血")
        redlines.append(
            {
                "id": "redline:yuxue-farre-yuanjin",
                "title": "【血证先后与气血缓急】远血黄土 · 近血赤豆 · 血脱急固气",
                "severity": "critical",
                "classic_basis": "《金匮要略》：下血先便后血此远血也（黄土汤），先血后便此近血也（赤小豆当归散）；吐血不止温阳用柏叶汤。",
                "ni_and_hantang_note": "人纪金匮反复纠偏先后顺序：大便先下而后滴紫暗黑血为脾胃中焦远血（黄土汤），先出鲜血而后排便为大肠痔疮湿热近血（赤豆当归散）。",
                "schools_crossref": "唐容川《血证论》治血四法分远血近血与降火止血；陈士铎《黄帝外经》警诫大失血「有形之血不能速生，无形之气所当急固」。",
                "action_rule": "已严格区分先便后血（远血·黄土）vs 先血后便（近血·赤豆当归），并在大脱失血危候提示优先固气急诊。",
            }
        )
        if has_blood_collapse_cues:
            extra_safety.append("【大失血固脱红线】九窍或大量急性失血属休克急症，须立即现代急诊止血输液；文献治法尤重先补无形之气防气随血脱。")

    # --- Redline 17: 妇人妊娠禁忌与恶阻/胎前安胎辨证红线 ---
    has_pregnancy_ctx = (
        "妊娠禁忌" in sym_set
        or "妊娠恶阻" in sym_set
        or any(k in raw_q for k in ("怀孕", "妊娠", "孕妇", "胎动不安", "恶阻", "孕吐"))
    )
    if has_pregnancy_ctx:
        preg_reason = "《神农本草经》《金匮要略》妇人妊娠严禁峻下逐水、破血虫积及大辛大毒乌头附子妄攻胎元，防动胎滑胎"
        _suppress_atoms(
            scored_atoms,
            {
                "atom:taohe-chengqi",
                "atom:didang",
                "atom:didang-wan",
                "atom:dachengqi",
                "atom:xiaochengqi",
                "atom:tiaowei-chengqi",
                "atom:daxianxiong",
                "atom:daxianxiong-wan",
                "atom:shizao-tang",
                "atom:dahuang-mudan",
                "atom:yiyifuzi-baijiang",
                "atom:dahuang-zhechong",
                "atom:biejia-jianwan",
                "atom:dawutou-jian",
                "atom:wutou-guizhi",
                "atom:wutou",
                "atom:chi-wan",
                "atom:xiayuxue-tang",
                "atom:tuguagen-san",
                "atom:dahuang-gansui",
                "atom:guadi-san",
                "atom:gansui-banxia",
                "atom:jijiao-lihuang-wan",
                "atom:muli-zexie",
                "atom:dahuang-gancao",
                "atom:houpo-sanwu",
                "atom:houpo-dahuang",
                "atom:dahuang-xiaoshi",
                "atom:zhizi-dahuang",
                "atom:guizhi-jia-dahuang",
                "atom:houpo-qiwu",
                "atom:dahuang-fuzi",
                "atom:dahuang-huanglian-xiexin",
            },
            preg_reason,
        )
        if "呕吐" in sym_set or "妊娠恶阻" in sym_set:
            _ensure_atom_present("atom:ganjiang-renshen-banxia", 62, "妊娠恶阻")
        if "水肿" in sym_set:
            _ensure_atom_present("atom:kuizi-fuling", 56, "水肿")
        if "小便不利" in sym_set or "淋痛尿血" in sym_set:
            _ensure_atom_present("atom:danggui-beimu-kushen", 58, "小便不利")
        if "腹痛" in sym_set:
            _ensure_atom_present("atom:danggui-shaoyao", 54, "腹痛")
        redlines.append(
            {
                "id": "redline:pregnancy-contraindication",
                "title": "【妇人妊娠用药红线】禁峻下破瘀生乌附 · 恶阻小便水肿安全专方",
                "severity": "critical",
                "classic_basis": "《金匮要略·妇人妊娠病脉证并治》专立干姜人参半夏丸止妊娠呕吐不止、当归芍药散治妊娠腹痛、葵子茯苓散消妊娠水肿、当归贝母苦参丸利妊娠小便难，严别常服安胎与破血攻下禁忌。",
                "ni_and_hantang_note": "人纪金匮重点：孕妇病非癥瘕「有故无殒」切忌大黄芒硝芫花甘遂巴豆桃仁水蛭蟅虫及大剂量生附乌头，针灸亦避深刺合谷、三阴交与下腹部穴位。",
                "schools_crossref": "徐灵胎、陈士铎俱戒孕期妄用破气滑胎之品；《金匮》当归散养血清热、白术散温脾安胎各有寒热专司。",
                "action_rule": "已自动屏蔽峻下逐水、破血虫积与乌头刚燥之剂，优先保留干姜人参半夏丸/当归芍药散/当归贝母苦参丸/葵子茯苓散。",
            }
        )
        extra_safety.append("【妊娠用药红线】孕期属极高危用药与针灸敏感期（避深刺合谷、三阴交及腹骶穴），一切方药须由产科与经方医师线下辨明「有故无殒」后慎用。")

    # --- Redline 18: 寒疝绕脐急痛 vs 阳明腑实及急腹症鉴别 ---
    if "寒疝腹痛" in sym_set or any(k in raw_q for k in ("寒疝", "绕脐痛", "乌头煎")):
        if not ("腹满拒按" in sym_set and "大渴" in sym_set and "高热" in sym_set):
            hs_reason = "《金匮》寒疝脉沉紧、绕脐剧痛白汗出厥冷属阴寒内结，忌误作阳明热结用大承气/大黄牡丹皮大苦寒直泻"
            _suppress_atoms(scored_atoms, {"atom:dachengqi", "atom:dahuang-mudan", "atom:baihu"}, hs_reason)
            if not has_pregnancy_ctx:
                if "产后" in sym_set or "腹痛喜按" in sym_set:
                    _ensure_atom_present("atom:danggui-shengjiang-yangrou", 62, "寒疝腹痛")
                else:
                    _ensure_atom_present("atom:dawutou-jian", 60, "寒疝腹痛")
        redlines.append(
            {
                "id": "redline:hanshan-futong",
                "title": "【寒疝痛证鉴别】阴寒绕脐厥冷（乌头煎/当归生姜羊肉）vs 嵌顿急腹症预警",
                "severity": "high_risk",
                "classic_basis": "《金匮要略·腹满寒疝宿食病》区分寒实绕脐厥冷白汗（大乌头煎）、血虚寒滞胁痛（当归生姜羊肉汤）及兼表寒肢痛（乌头桂枝汤）。",
                "ni_and_hantang_note": "人纪临床严明：乌头必以白蜜久煎去其毒沫、令水气尽而后试服五七合；若伴嵌顿肠梗阻绞窄坏死征象，须即时外科急诊手术。",
                "schools_crossref": "徐灵胎《兰台轨范》详载寒疝诸乌头方煎服缓急之度，不可与阳明热实燥屎混同。",
                "action_rule": "已根据有热无热、虚寒实寒切分大乌头煎/当归生姜羊肉汤，屏蔽误用苦寒攻下剂，并提示生乌头减毒规范与外科急腹症红线。",
            }
        )
        extra_safety.append("【乌头毒性与嵌顿急腹症警示】大乌头煎等含生/制乌头毒剧饮片，必须依法先以白蜜熬减毒，且若剧痛伴腹膜炎板状腹或嵌顿疝呕吐闭塞，应立即外科急诊。")

    for rl in redlines:
        rl["source_anchors"] = resolve_redline_anchors(rl["id"])

    return {
        "redlines": redlines,
        "extra_safety_lines": extra_safety,
        "extra_acupoints": extra_acupoints,
    }
