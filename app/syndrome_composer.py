"""Deterministic clinical syndrome decomposition, pulse-weighted Jingfang compound composition,
and meridian-acupoint reasoning engine (Stage 5 Clinical Differentiation + AI Hook).
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from ai.grounded_study import _detect_safety_boundary
from app import acupuncture_diagnose, formula_diagnose, hantang_catalog
from app.syndrome_rules import (
    EXTRA_DIFFERENTIAL_NOTES,
    EXTRA_INQUIRY_PILLS,
    EXTRA_PATTERN_ATOMS,
    EXTRA_PRESET_CASES,
    EXTRA_SYMPTOM_CANONICAL_RULES,
    LEGACY_ATOM_POLARITIES,
    are_formulas_redundant_siblings,
    canonical_formula_name,
    detect_compound_herb_conflicts,
    evaluate_classical_context,
    score_atom_tongue,
)
from retrieval.index import norm_simp, search_library_pages, tokenize_query
from retrieval.tcm_synonyms import strip_clinical_negations


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data"


PULSE_OPTIONS: list[dict[str, Any]] = [
    {"id": "沉", "label": "脉沉", "axis": "interior", "note": "病位在里（太阴、少阴、厥阴或里水瘀结）"},
    {"id": "微细", "label": "脉微细", "axis": "yin_def_yang_weak", "note": "少阴气血阴阳俱虚、阳气衰微之核心脉象"},
    {"id": "迟", "label": "脉迟", "axis": "cold", "note": "里寒阳虚、营卫气血运行迟滞（亦须分阳明实热腑阻偶见沉迟）"},
    {"id": "弦", "label": "脉弦", "axis": "shaoyang_water", "note": "主少阳枢机不利、肝胆郁滞、或饮停心下胸胁"},
    {"id": "紧", "label": "脉紧", "axis": "cold_excess", "note": "主表寒束表、寒饮痛剧或寒凝经脉"},
    {"id": "浮", "label": "脉浮", "axis": "exterior", "note": "病邪在表（太阳中风浮缓 / 伤寒浮紧 / 或虚阳外越浮大无根）"},
    {"id": "缓", "label": "脉缓", "axis": "wind_def", "note": "太阳中风营卫失调（发热汗出恶风）"},
    {"id": "滑", "label": "脉滑", "axis": "phlegm_heat", "note": "痰饮停蓄、胃肠宿食或阳明里热充盛"},
    {"id": "数", "label": "脉数", "axis": "heat", "note": "热邪偏旺、阴虚内热或热毒逼血"},
    {"id": "洪大", "label": "脉洪大", "axis": "yangming_heat", "note": "阳明经分热盛（大热大汗大烦渴）"},
    {"id": "涩", "label": "脉细涩", "axis": "blood_stasis_def", "note": "血虚津少、冲任寒凝或下焦瘀血阻滞"},
    {"id": "结代", "label": "脉结代", "axis": "heart_def", "note": "心动悸（脉律不齐），需先辨心阳心血不足或高危心律急症"},
]

TONGUE_OPTIONS: list[dict[str, Any]] = [
    {"id": "舌白厚湿", "label": "苔白厚湿腻", "axis": "interior_cold", "note": "里寒阴实或寒湿内停（即便是重证久病见苔白厚湿仍主里寒，忌妄投大寒）"},
    {"id": "舌淡胖滑", "label": "舌淡胖齿痕", "axis": "yang_water_def", "note": "脾肾阳虚、水饮停蓄（真武汤 / 理中丸 / 苓桂术甘汤方向）"},
    {"id": "舌黄厚燥", "label": "苔黄厚实燥", "axis": "yangming_heat", "note": "阳明胃肠燥热或脏腑实热蕴结（须合小便深黄、大便闭及腹诊拒按辨）"},
    {"id": "舌红少苔", "label": "舌红绛少苔", "axis": "yin_fluid_def", "note": "胃津枯涸或少阴阴虚火旺（黄连阿胶汤 / 麦门冬汤 / 炙甘草汤方向，忌峻攻）"},
    {"id": "舌紫暗瘀", "label": "舌紫暗瘀斑", "axis": "blood_stasis", "note": "下焦蓄血或胞宫瘀积（桂枝茯苓丸 / 桃核承气 / 抵当汤方向）"},
    {"id": "舌转薄白", "label": "光苔生薄白", "axis": "stomach_recovery", "note": "镜面舌逐渐生出淡白薄苔乃胃气回复佳兆；反之越治越光绛则津伤告急"},
]

INQUIRY_PILLS: list[dict[str, str]] = [
    {"group": "寒热手足", "label": "双足冰冷", "token": "脚冷"},
    {"group": "寒热手足", "label": "手掌烦热", "token": "手掌烦热"},
    {"group": "寒热手足", "label": "大热大渴喜冷", "token": "高热 大汗 口渴 喜冷饮"},
    {"group": "寒热手足", "label": "头凉足温(佳兆)", "token": "手足转温"},
    {"group": "二便口渴", "label": "小便清白", "token": "小便清白"},
    {"group": "二便口渴", "label": "小便深黄", "token": "小便深黄"},
    {"group": "二便口渴", "label": "便闭不屁", "token": "大便闭 不放屁"},
    {"group": "二便口渴", "label": "水泻(防热结旁流)", "token": "水泻 腹痛拒按"},
    {"group": "二便口渴", "label": "先便后血(远血)", "token": "先便后血 便血"},
    {"group": "二便口渴", "label": "先血后便(近血)", "token": "先血后便 便血"},
    {"group": "眠胃时辰", "label": "1-3点肝经醒", "token": "1-3点醒 失眠"},
    {"group": "眠胃时辰", "label": "3-5点肺经醒", "token": "3-5点醒 咳嗽"},
    {"group": "眠胃时辰", "label": "半夜腹饥(胃回)", "token": "半夜腹饥"},
    {"group": "腹诊压痛", "label": "腹满痛拒按", "token": "腹满拒按 腹痛"},
    {"group": "腹诊压痛", "label": "腹痛喜温按", "token": "腹痛喜按 腹痛"},
    {"group": "腹诊压痛", "label": "少腹急结如狂", "token": "少腹急结 如狂"},
    {"group": "腹诊压痛", "label": "心下硬痛(结胸)", "token": "心下硬痛"},
    {"group": "腹诊压痛", "label": "右下腹阑尾压痛", "token": "右下腹痛"},
]

QUICK_SYMPTOM_PILLS: list[dict[str, str]] = [
    {"label": "身冷", "token": "身冷"},
    {"label": "脚冷", "token": "脚冷"},
    {"label": "眩晕", "token": "眩晕"},
    {"label": "但头汗出", "token": "但头汗出"},
    {"label": "小便不利", "token": "小便不利"},
    {"label": "往来寒热", "token": "往来寒热"},
    {"label": "腹痛", "token": "腹痛"},
    {"label": "痛经", "token": "痛经"},
    {"label": "习惯性便秘", "token": "习惯性便秘"},
    {"label": "大便干", "token": "大便干"},
    {"label": "胸痹短气", "token": "胸痹 短气"},
    {"label": "心下痞呕", "token": "心下痞 呕吐"},
    {"label": "自汗恶风", "token": "发热 汗出 恶风"},
    {"label": "无汗恶寒", "token": "无汗 恶寒"},
    {"label": "口苦咽干", "token": "口苦 咽干"},
    {"label": "下利清谷", "token": "下利清谷"},
    {"label": "失眠心烦", "token": "失眠 心烦"},
    {"label": "咳嗽白痰", "token": "咳嗽 白痰"},
    {"label": "夜尿频多", "token": "夜尿多"},
    {"label": "关节痛", "token": "关节痛"},
]

PRESET_CASES: list[dict[str, Any]] = [
    {
        "id": "case:zhenwu-danggui",
        "title": "示范A：身冷脚冷眩晕 + 腹痛痛经大便干（合方示范）",
        "symptoms": "身冷，脚冷，眩晕，习惯性便秘，腹痛，大便干，痛经",
        "pulse": "沉 微细 涩",
        "note": "对比示范组1：少阴阳虚水寒（真武汤轴）兼肝脾血虚湿滞胞宫冲任（当归芍药散轴），脉沉微细则拒寒凉泻下而辨津血冷秘。",
    },
    {
        "id": "case:zhenwu-chaihu-guizhi-ganjiang",
        "title": "示范B：改见但头汗出+小便不利+往来寒热（动态变方示范）",
        "symptoms": "身冷，脚冷，眩晕，但头汗出，小便不利，往来寒热",
        "pulse": "沉 弦 微细",
        "note": "对比示范组2：保留少阴水寒轴，改兼《伤寒》147条但头汗出、小便不利、往来寒热少阳太阴枢机证，自动转合【真武汤 合 柴胡桂枝干姜汤】。",
    },
    {
        "id": "case:xiongbi-xintong",
        "title": "示范C：胸痹心痛彻背短气 + 心悸不得卧",
        "symptoms": "胸痛，短气，心痛彻背，不得卧，心悸",
        "pulse": "沉 迟 弦",
        "note": "阳微阴弦胸痹痰瘀痹阻，合方与内关/膻中/巨阙配穴并出。",
    },
    {
        "id": "case:taiyang-yangming-shaoyang",
        "title": "示范D：发热无汗项背强 + 口苦心烦呕吐",
        "symptoms": "发热，无汗，恶寒，项背强，口苦，心烦，呕吐",
        "pulse": "浮 紧 弦",
        "note": "太阳伤寒兼少阳（太少合病 / 葛根与柴胡桂枝系统鉴别）。",
    },
    {
        "id": "case:buxu-first",
        "title": "示范E：补虚前置铁律（腹中急痛喜按 / 心动悸脉结代）",
        "symptoms": "心悸，腹痛喜按，手掌烦热，失眠，舌红少苔",
        "pulse": "结代 微细",
        "note": "仲景“先补虚”示范：表阳虚腹急痛先以小建中汤，脉结代心动悸先以炙甘草汤复脉建中，忌直接峻攻。",
    },
    {
        "id": "case:jinxiong-xuxue",
        "title": "示范F：太阳蓄血如狂 vs 阳明腑实辨证",
        "symptoms": "少腹急结，腹痛，如狂，小便自利，舌紫暗瘀",
        "pulse": "沉 涩",
        "note": "蓄血见“小便自利、少腹急结如狂”（桃核承气/抵当汤），藉小便清利与小便不利、腹软硬直接切分蓄水与阳明。",
    },
]

# Synonym normalizer -> canonical symptom tags
SYMPTOM_CANONICAL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("身冷", ("身冷", "怕冷", "畏寒", "恶寒", "背恶寒", "身体冷", "全身发冷", "打寒颤")),
    ("脚冷", ("脚冷", "手脚冰冷", "手脚冰凉", "四肢厥冷", "厥逆", "足冷", "膝盖冷", "手足寒", "脚凉", "双足冰冷")),
    ("眩晕", ("眩晕", "头晕", "头眩", "站立不稳", "欲仆地", "眼花", "美尼尔", "起立眩")),
    ("但头汗出", ("但头汗出", "头汗", "只有头出汗", "头汗出")),
    ("小便不利", ("小便不利", "尿少", "小便少", "小便不畅", "尿不出来", "小便难", "浮肿", "水肿", "蓄水")),
    ("小便自利", ("小便自利", "小便清长", "小便利", "小便通畅")),
    ("小便清白", ("小便清白", "尿清白", "小便白")),
    ("小便深黄", ("小便深黄", "小便赤黄", "尿黄", "尿赤", "小便黄赤")),
    ("往来寒热", ("往来寒热", "寒热往来", "忽冷忽热", "时冷时热", "一阵冷一阵热")),
    ("痛经", ("痛经", "经痛", "行经腹痛", "月经痛", "经水不调", "经闭", "血块")),
    ("腹痛喜按", ("腹痛喜按", "喜温喜按", "喜按", "按之舒适", "腹满时减")),
    ("腹满拒按", ("腹满拒按", "腹痛拒按", "痛而拒按", "腹部硬满", "肚子按着更痛", "硬满拒按", "大便闭", "不放屁")),
    ("少腹急结", ("少腹急结", "少腹硬满", "少腹满如敦", "小腹急结")),
    ("右下腹痛", ("右下腹痛", "少腹肿痞", "阑尾点", "盲肠痛", "盲肠炎", "肠痈")),
    ("腹痛", ("腹痛", "肚子痛", "小腹痛", "少腹痛", "腹中㽲痛", "绕脐痛", "少腹急结", "肚子疼")),
    ("习惯性便秘", ("习惯性便秘", "长期便秘", "便秘", "排便困难", "几天不大便")),
    ("大便干", ("大便干", "大便硬", "大便干结", "大便难", "燥屎", "羊屎", "不大便", "拉不出来", "不放屁")),
    ("下利清谷", ("下利清谷", "腹泻", "泄泻", "拉肚子", "稀水便", "五更泻", "水泻", "拉稀", "拉水", "完谷不化")),
    ("高热", ("高热", "壮热", "高烧", "大热", "蒸发发热")),
    ("发热", ("发热", "发烧", "身热", "壮热", "潮热", "高热")),
    ("有汗", ("有汗", "自汗", "汗出", "恶风", "盗汗", "大汗", "漏不止")),
    ("无汗", ("无汗", "不出汗", "没怎么出汗", "没出汗", "表实")),
    ("项背强", ("项背强", "项强", "脖子僵", "颈项强", "脖子紧")),
    ("口苦", ("口苦", "胸胁苦满", "胁痛", "两胁胀", "胁胀")),
    ("咽干", ("咽干", "口燥咽干", "咽痛", "唇口干燥")),
    ("喜冷饮", ("喜冷饮", "喜冰水", "喜饮冷水", "饮冷")),
    ("口渴", ("口渴", "大渴", "烦渴", "欲饮水", "渴而不呕", "消渴", "引饮")),
    ("呕吐", ("呕吐", "干呕", "恶心", "喜呕", "反胃", "吐涎沫", "朝食暮吐")),
    ("呃逆胃虚", ("呃逆", "哕", "打嗝不止", "噫气")),
    ("心悸", ("心悸", "心动悸", "心跳快", "心跳不齐", "脐下悸", "心慌", "惊悸")),
    ("气上冲胸", ("气上冲", "气上冲胸", "奔豚", "脐下悸")),
    ("心痛彻背", ("心痛彻背", "背痛彻心", "胸背彻痛", "不得卧")),
    ("胸痹", ("胸痹", "胸痛", "胸闷", "心痛彻背", "背痛彻心", "短气", "胸中气塞")),
    ("心下硬痛", ("心下硬痛", "按之石硬", "结胸", "正在心下", "按之则痛")),
    ("心下痞", ("心下痞", "胃胀", "心下闷", "痞满", "胃痛", "心下痞满")),
    ("如狂发狂", ("如狂", "发狂", "狂躁", "登高而歌", "弃衣而走", "狂言")),
    ("心烦失眠", ("心烦", "失眠", "不得卧", "睡不着", "懊憹", "多梦", "不得眠", "1-3点醒", "3-5点醒")),
    ("1-3点醒", ("1-3点醒", "半夜1-3点", "凌晨一两点醒", "丑时醒")),
    ("3-5点醒", ("3-5点醒", "半夜3-5点", "凌晨三五点醒", "寅时醒")),
    ("手掌烦热", ("手掌烦热", "手心烦热", "手心热", "五心烦热", "手足心热")),
    ("水鸡声", ("水鸡声", "哮鸣", "喉中痰鸣", "哮吼")),
    ("咳喘痰多", ("咳嗽", "咳喘", "哮喘", "白痰", "黄痰", "痰多", "不得平卧", "水鸡声", "咳唾脓血", "气喘")),
    ("头痛", ("头痛", "偏头痛", "巅顶痛", "前额痛", "头疼", "眉棱骨痛")),
    ("先便后血", ("先便后血", "远血", "黑便")),
    ("先血后便", ("先血后便", "近血", "鲜血")),
    ("失血", ("吐血", "鼻衄", "便血", "先便后血", "先血后便", "崩漏", "下血", "咳血")),
    ("脚肿如脱", ("脚肿如脱", "关节变形", "不可屈伸", "历节剧痛")),
    ("关节痹痛", ("风湿", "历节", "关节痛", "膝痛", "腿肿", "脚肿如脱", "骨节痛", "四肢沉重")),
    ("夜尿多", ("夜尿多", "夜尿频数", "夜尿", "小便频数", "小便反多")),
    ("口不渴", ("口不渴", "不欲饮", "不渴")),
    ("耳鸣", ("耳鸣", "耳聋", "暴聋")),
    ("黄疸", ("黄疸", "发黄", "身目黄", "胆结石", "胆囊痛", "胆石点")),
    ("鼻症", ("鼻炎", "过敏性鼻炎", "鼻息肉", "鼻塞", "流涕", "鼻窦炎", "打喷嚏")),
    ("面瘫", ("面瘫", "面部中风", "口眼歪斜", "嘴角歪")),
    ("水肿", ("水肿", "浮肿", "腹水", "肺积水", "胸腔积液", "皮水", "风水", "全身肿")),
    ("咽喉肿痛", ("喉咙痛", "咽痛", "扁桃腺", "咽喉痛", "梅核气", "咽喉不利")),
    ("带下崩漏", ("白带", "赤白带", "赤带", "崩漏", "经血不止", "漏下")),
    ("第五椎压痛", ("第五椎", "T5压痛", "五椎压痛")),
    ("半夜腹饥", ("半夜腹饥", "半夜醒来饿", "夜半饥饿")),
    ("手足转温", ("手足转温", "手足温", "双足转温", "脚底温")),
    ("舌白厚湿", ("舌白厚湿", "苔白厚", "苔白腻", "白厚苔")),
    ("舌淡胖滑", ("舌淡胖", "齿痕舌", "舌滑润")),
    ("舌黄厚燥", ("舌黄厚", "苔黄厚", "黄燥苔", "苔黄腻")),
    ("舌红少苔", ("舌红少苔", "红绛无苔", "镜面舌", "光苔无津")),
    ("舌紫暗瘀", ("舌紫暗", "舌下瘀", "瘀斑舌")),
    ("舌转薄白", ("舌转薄白", "生薄白苔", "胃气回")),
]

CLINICAL_ENTRY_CARDS: list[dict[str, Any]] = [
    {
        "id": "entry:exterior-cold",
        "title": "外感发热 / 太阳表证",
        "subtitle": "伤寒太阳 · 桂枝/麻黄/葛根汤轴",
        "tokens": ["恶寒", "发热", "无汗", "有汗", "项背强"],
        "default_query": "发热 无汗 恶寒 项背强",
        "formulas_hint": "桂枝汤 / 麻黄汤 / 葛根汤",
    },
    {
        "id": "entry:shaoyang",
        "title": "少阳寒热 / 胸胁口苦",
        "subtitle": "少阳枢机 · 小柴胡/柴桂干姜轴",
        "tokens": ["往来寒热", "口苦", "咽干", "但头汗出", "小便不利"],
        "default_query": "往来寒热 口苦 咽干",
        "formulas_hint": "小柴胡汤 / 柴胡桂枝干姜汤",
    },
    {
        "id": "entry:headache",
        "title": "头痛 / 偏头痛 / 眩晕",
        "subtitle": "《针灸》头部治症 · 厥阴/少阳",
        "tokens": ["头痛", "偏头痛", "前额痛", "眩晕", "呕吐"],
        "default_query": "头痛 眩晕 呕吐",
        "formulas_hint": "吴茱萸汤 / 苓桂术甘汤 / 五苓散",
    },
    {
        "id": "entry:chest-heart",
        "title": "胸痹心痛 / 心悸心律",
        "subtitle": "《金匮》胸痹 · 《针灸》心脏治症",
        "tokens": ["胸痹", "胸痛", "心痛彻背", "短气", "心悸"],
        "default_query": "胸痛 短气 心痛彻背 心悸",
        "formulas_hint": "栝蒌薤白半夏汤 / 炙甘草汤",
    },
    {
        "id": "entry:lung-cough",
        "title": "咳嗽哮喘 / 痰饮积水",
        "subtitle": "肺症虚实 · 《针灸》肺积水",
        "tokens": ["咳嗽", "白痰", "黄痰", "咳喘痰多", "水肿"],
        "default_query": "咳嗽 白痰 咳喘痰多",
        "formulas_hint": "小青龙汤 / 麻杏石甘汤 / 十枣汤",
    },
    {
        "id": "entry:stomach",
        "title": "胃痛痞满 / 呕吐反胃",
        "subtitle": "脾肿大与胃病 · 朝食暮吐",
        "tokens": ["心下痞", "胃痛", "呕吐", "反胃", "口不渴"],
        "default_query": "心下痞 呕吐 胃痛",
        "formulas_hint": "半夏泻心汤 / 理中丸 / 旋覆代赭汤",
    },
    {
        "id": "entry:abdomen",
        "title": "腹痛肠痈 / 奔豚气冲",
        "subtitle": "《针灸》盲肠奔豚 · 太阴寒滞",
        "tokens": ["腹痛", "少腹痛", "右下腹痛", "身冷"],
        "default_query": "腹痛 少腹痛",
        "formulas_hint": "小建中汤 / 大黄牡丹汤 / 桂枝加桂汤",
    },
    {
        "id": "entry:constipation",
        "title": "便秘便干 / 寒实与阳明",
        "subtitle": "《针灸》大肠虚实 · 冷秘 vs 燥屎",
        "tokens": ["习惯性便秘", "大便干", "身冷", "脚冷"],
        "default_query": "习惯性便秘 大便干",
        "formulas_hint": "大承气汤 / 麻子仁丸 / 真武汤",
    },
    {
        "id": "entry:diarrhea",
        "title": "下利泄泻 / 霍乱吐利",
        "subtitle": "少阴太阴虚寒 · 协热下利",
        "tokens": ["下利清谷", "腹泻", "口不渴", "身冷"],
        "default_query": "下利清谷 腹泻",
        "formulas_hint": "四逆汤 / 理中丸 / 葛根芩连汤",
    },
    {
        "id": "entry:shaoyin-urinary",
        "title": "身冷脚冷 / 夜尿水不利",
        "subtitle": "少阴肾阳气化 · 五苓与真武",
        "tokens": ["身冷", "脚冷", "眩晕", "小便不利", "夜尿多"],
        "default_query": "身冷 脚冷 眩晕 小便不利",
        "formulas_hint": "真武汤 / 肾气丸 / 五苓散",
    },
    {
        "id": "entry:insomnia",
        "title": "心烦失眠 / 癫狂神志",
        "subtitle": "十三鬼穴 · 心肾不交",
        "tokens": ["失眠", "心烦", "不得卧", "心悸"],
        "default_query": "失眠 心烦 不得卧",
        "formulas_hint": "酸枣仁汤 / 黄连阿胶汤 / 栀子豉汤",
    },
    {
        "id": "entry:gynecology",
        "title": "痛经崩漏 / 赤白带下",
        "subtitle": "《针灸》妇科经带 · 金匮妇人",
        "tokens": ["痛经", "腹痛", "脚冷", "赤白带", "崩漏"],
        "default_query": "痛经 腹痛 脚冷",
        "formulas_hint": "当归芍药散 / 温经汤 / 桂枝茯苓丸",
    },
    {
        "id": "entry:bleeding",
        "title": "吐血衄血 / 痔疮便血",
        "subtitle": "《针灸》血症肠风 · 先血先便",
        "tokens": ["吐血", "鼻衄", "便血", "痔疮", "失血"],
        "default_query": "便血 吐血 鼻衄",
        "formulas_hint": "黄土汤 / 柏叶汤 / 泻心汤",
    },
    {
        "id": "entry:metabolic-liver",
        "title": "消渴引饮 / 黄疸胆结石",
        "subtitle": "《针灸》消渴与肝胆治症",
        "tokens": ["消渴", "口渴", "黄疸", "胆结石", "口苦"],
        "default_query": "消渴 口渴 黄疸",
        "formulas_hint": "白虎加人参汤 / 肾气丸 / 茵陈蒿汤",
    },
    {
        "id": "entry:ent",
        "title": "耳鸣鼻炎 / 喉症面瘫",
        "subtitle": "《针灸》五官头面专病",
        "tokens": ["耳鸣", "过敏性鼻炎", "鼻塞", "咽喉痛", "面瘫"],
        "default_query": "耳鸣 过敏性鼻炎 鼻塞",
        "formulas_hint": "麻黄附子细辛汤 / 葛根汤 / 半夏散",
    },
    {
        "id": "entry:arthritis",
        "title": "风湿历节 / 关节痹痛",
        "subtitle": "桂枝附子 / 历节痛风",
        "tokens": ["关节痛", "风湿", "腿肿", "身冷"],
        "default_query": "关节痛 风湿",
        "formulas_hint": "桂枝芍药知母汤 / 乌头汤 / 麻杏苡甘汤",
    },
]

# Classic Pattern Atoms (with strict verifiable formula IDs and classic clinical logic)
PATTERN_ATOMS: list[dict[str, Any]] = [
    {
        "atom_id": "atom:zhenwu",
        "formula_id": "shanghan:真武汤",
        "name": "真武汤",
        "six_meridian": "少阴病 · 阳虚水泛轴",
        "pathogenesis": "少阴肾阳衰微，不能温煦四肢百骸（身冷脚冷），水邪停蓄上泛（头眩、心下悸、小便不利或腹痛自利）。",
        "symptom_weights": {"身冷": 16, "脚冷": 18, "眩晕": 16, "小便不利": 12, "腹痛": 8, "心悸": 10, "下利清谷": 12},
        "boost_pulses": {"沉": 10, "微细": 14, "迟": 8},
        "conflict_pulses": {"洪大": -22, "数": -12},
        "conflict_symptoms": {"发热": -6},
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（宜灸）", "reason": "培元固本、温壮少阴下焦元阳，治身冷脚冷水寒上泛"},
            {"id": "acupoint:ki03:太溪", "name": "太溪", "role": "主穴（补法/灸）", "reason": "足少阴肾经原穴，交通水火、温肾利水定眩"},
            {"id": "acupoint:sp09:阴陵泉", "name": "阴陵泉", "role": "配穴", "reason": "健脾渗湿利小便，佐真武分消停蓄之水邪"},
            {"id": "acupoint:ki07:复溜", "name": "复溜", "role": "配穴", "reason": "补肾阳、通利下焦水道、调节汗水代谢"},
        ],
    },
    {
        "atom_id": "atom:danggui-shaoyao",
        "formula_id": "jinkui:当归芍药散",
        "name": "当归芍药散",
        "six_meridian": "太阴厥阴妇科 · 血虚肝郁夹湿胞宫痛经轴",
        "pathogenesis": "《金匮·妇人》主方：脾土虚寒水湿内停，兼肝血不足冲任涩滞，见妇人腹中㽲痛、痛经、眩晕手足不温，兼津血不濡肠窍而现虚性大便干。",
        "symptom_weights": {"痛经": 26, "腹痛": 14, "眩晕": 10, "脚冷": 8, "大便干": 10, "习惯性便秘": 8, "身冷": 6, "小便不利": 6},
        "boost_pulses": {"沉": 6, "微细": 10, "涩": 14, "弦": 8},
        "conflict_pulses": {"洪大": -18},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:sp06:三阴交", "name": "三阴交", "role": "主穴", "reason": "肝脾肾三阴交会，调冲任止痛经兼健脾除湿、养血润肠"},
            {"id": "acupoint:sp10:血海", "name": "血海", "role": "配穴", "reason": "理血活血，统调经水与胞宫血室瘀滞腹痛"},
            {"id": "acupoint:sp08:地机", "name": "地机", "role": "配穴", "reason": "足太阴脾经郄穴，急性与周期性痛经要穴"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "配穴", "reason": "健运中土气血生化之源，配合三阴交化湿定眩"},
        ],
    },
    {
        "atom_id": "atom:chaihu-guizhi-ganjiang",
        "formula_id": "shanghan:柴胡桂枝干姜汤",
        "name": "柴胡桂枝干姜汤",
        "six_meridian": "少阳枢机兼太阴津郁 · 《伤寒》147条专轴",
        "pathogenesis": "《伤寒》明文：“胸胁满微结，小便不利，渴而不呕，但头汗出，往来寒热，心烦者，此为未解也，柴胡桂枝干姜汤主之。”枢机郁热不得下达而单上蒸作头汗，同时中焦脾虚阴寒不运（干姜配栝蒌根、牡蛎）。",
        "symptom_weights": {"但头汗出": 28, "往来寒热": 24, "小便不利": 16, "口苦": 10, "口渴": 8, "身冷": 6, "心烦失眠": 6},
        "pair_bonus": [("但头汗出", "往来寒热", 18), ("但头汗出", "小便不利", 14), ("往来寒热", "小便不利", 10)],
        "boost_pulses": {"弦": 14, "沉": 8, "微细": 8},
        "conflict_pulses": {"洪大": -12},
        "conflict_symptoms": {"无汗": -8},
        "acupoints": [
            {"id": "acupoint:lv14:期门", "name": "期门", "role": "主穴", "reason": "肝募兼入少阳厥阴交关，解胸胁满微结与寒热往来"},
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "主穴", "reason": "胆经合穴，疏泄少阳胆腑枢机不利"},
            {"id": "acupoint:sj05:外关", "name": "外关", "role": "配穴", "reason": "手少阳三焦经络穴，宣通三焦水道、解往来寒热但头汗"},
            {"id": "acupoint:sp09:阴陵泉", "name": "阴陵泉", "role": "配穴", "reason": "复三焦脾运化水湿，助小便不利通调"},
        ],
    },
    {
        "atom_id": "atom:wenjing",
        "formula_id": "jinkui:温经汤",
        "name": "温经汤",
        "six_meridian": "妇人虚寒瘀滞 · 下寒兼上虚热",
        "pathogenesis": "冲任虚寒（身冷脚冷、痛经瘀块）兼瘀久微化虚热（手心烦热、口唇干）。",
        "symptom_weights": {"痛经": 20, "脚冷": 10, "身冷": 8, "腹痛": 8, "咽干": 8},
        "boost_pulses": {"涩": 10, "沉": 6, "迟": 6},
        "conflict_pulses": {"洪大": -16},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（宜灸）", "reason": "温煦冲任下元"},
            {"id": "acupoint:sp06:三阴交", "name": "三阴交", "role": "主穴", "reason": "理肝脾肾经血"},
        ],
    },
    {
        "atom_id": "atom:maziren",
        "formula_id": "shanghan:麻子仁丸",
        "name": "麻子仁丸",
        "six_meridian": "阳明脾约 · 津亏大便硬便秘",
        "pathogenesis": "胃热津耗、脾不为胃行津液，致习惯性大便硬如羊屎；若全身兼明显身冷脚冷脉沉微，须防苦寒泻下伤阳！",
        "symptom_weights": {"习惯性便秘": 16, "大便干": 16},
        "pair_bonus": [("习惯性便秘", "大便干", 10)],
        "boost_pulses": {"数": 8, "滑": 6},
        "conflict_pulses": {"微细": -12, "迟": -10},
        "conflict_symptoms": {"身冷": -10, "脚冷": -10, "下利清谷": -20},
        "acupoints": [
            {"id": "acupoint:st25:天枢", "name": "天枢", "role": "主穴", "reason": "大肠募穴，调理大肠传导之腑气"},
            {"id": "acupoint:sj06:支沟", "name": "支沟", "role": "配穴", "reason": "三焦经经穴，古传专治习惯性便秘与大便干难"},
            {"id": "acupoint:ki06:照海", "name": "照海", "role": "配穴", "reason": "配支沟“支沟照海通大便”（尤其虚燥津亏便干）"},
        ],
    },
    {
        "atom_id": "atom:xiaochaihu",
        "formula_id": "shanghan:小柴胡汤",
        "name": "小柴胡汤",
        "six_meridian": "少阳经病 · 半表半里枢机主方",
        "pathogenesis": "正邪分争少阳胆与三焦，但见往来寒热、胸胁苦满、口苦咽干目眩、心烦喜呕一证便是。",
        "symptom_weights": {"往来寒热": 18, "胁痛": 14, "口苦": 16, "呕吐": 12, "咽干": 10, "心烦失眠": 8, "头痛": 6},
        "pair_bonus": [("往来寒热", "口苦", 10), ("往来寒热", "呕吐", 10), ("口苦", "咽干", 8)],
        "boost_pulses": {"弦": 14},
        "conflict_pulses": {},
        "conflict_symptoms": {"但头汗出": -4},
        "acupoints": [
            {"id": "acupoint:sj05:外关", "name": "外关", "role": "主穴", "reason": "和解少阳三焦气机"},
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "主穴", "reason": "清泄胆热、利胸胁苦满"},
            {"id": "acupoint:lv14:期门", "name": "期门", "role": "配穴", "reason": "兼热入血室或胸胁胀满加刺期门"},
        ],
    },
    {
        "atom_id": "atom:guizhi",
        "formula_id": "shanghan:桂枝汤",
        "name": "桂枝汤",
        "six_meridian": "太阳表虚中风 · 调和营卫",
        "pathogenesis": "卫阳外浮、营阴外泄，见发热、汗出、恶风、脉浮缓。",
        "symptom_weights": {"发热": 12, "有汗": 20, "头痛": 6},
        "pair_bonus": [("发热", "有汗", 14)],
        "boost_pulses": {"浮": 12, "缓": 14},
        "conflict_pulses": {"紧": -10, "洪大": -10},
        "conflict_symptoms": {"无汗": -18, "但头汗出": -10},
        "acupoints": [
            {"id": "acupoint:gb20:风池", "name": "风池", "role": "主穴", "reason": "祛太阳风邪、止头项疼痛"},
            {"id": "acupoint:lu07:列缺", "name": "列缺", "role": "配穴", "reason": "宣肺解肌、疏泄后项头部风邪"},
            {"id": "acupoint:li04:合谷", "name": "合谷", "role": "配穴", "reason": "调和营卫气血，固表解肌"},
        ],
    },
    {
        "atom_id": "atom:gegengtang",
        "formula_id": "shanghan:葛根汤",
        "name": "葛根汤",
        "six_meridian": "太阳表实兼项背强 · 无汗恶寒",
        "pathogenesis": "太阳寒实束表无汗而津液不能上输阳明太阳经脉，故项背强几几。",
        "symptom_weights": {"项背强": 24, "无汗": 16, "身冷": 8, "发热": 8},
        "pair_bonus": [("项背强", "无汗", 14)],
        "boost_pulses": {"浮": 10, "紧": 14},
        "conflict_pulses": {"缓": -10},
        "conflict_symptoms": {"有汗": -16},
        "acupoints": [
            {"id": "acupoint:du14:大椎", "name": "大椎", "role": "主穴", "reason": "手足三阳与督脉交会，退表热解项强"},
            {"id": "acupoint:gb20:风池", "name": "风池", "role": "主穴", "reason": "松解项背肌肉痉挛"},
            {"id": "acupoint:si03:后溪", "name": "后溪", "role": "配穴", "reason": "通督脉，专治颈项强痛不能回顾"},
        ],
    },
    {
        "atom_id": "atom:wuling",
        "formula_id": "shanghan:五苓散",
        "name": "五苓散",
        "six_meridian": "太阳蓄水 · 膀胱气化不利",
        "pathogenesis": "膀胱气化不行致小便不利，津不上承则口渴欲饮水或水入即吐。",
        "symptom_weights": {"小便不利": 18, "口渴": 14, "眩晕": 8, "心悸": 6},
        "pair_bonus": [("小便不利", "口渴", 16)],
        "boost_pulses": {"浮": 6},
        "conflict_pulses": {},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:ren09:水分", "name": "水分", "role": "主穴（宜灸）", "reason": "分利水谷、治一切水肿水逆小便不利"},
            {"id": "acupoint:sp09:阴陵泉", "name": "阴陵泉", "role": "主穴", "reason": "健脾化气利小便"},
        ],
    },
    {
        "atom_id": "atom:xiongbi",
        "formula_id": "jinkui:栝蒌薤白白酒汤",
        "name": "栝蒌薤白白酒汤",
        "six_meridian": "金匮胸痹心痛 · 阳微阴弦",
        "pathogenesis": "胸阳不振而痰浊阴邪上乘胸膈，见胸痛彻背、短气喘息。",
        "symptom_weights": {"胸痹": 28, "咳喘痰多": 8, "心悸": 8},
        "boost_pulses": {"沉": 8, "迟": 8, "弦": 6},
        "conflict_pulses": {"洪大": -12},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "主穴", "reason": "宣通心脉、宽胸定痛（配公孙主胸腹诸疾）"},
            {"id": "acupoint:ren17:膻中", "name": "膻中", "role": "主穴", "reason": "气会膻中，宽胸散结、通心阳短气"},
            {"id": "acupoint:ren14:巨阙", "name": "巨阙", "role": "主穴", "reason": "心之募穴，治心痛彻背胸痹急证"},
        ],
    },
    {
        "atom_id": "atom:sini",
        "formula_id": "shanghan:四逆汤",
        "name": "四逆汤",
        "six_meridian": "少阴回阳救逆 · 亡阳厥逆",
        "pathogenesis": "少阴肾阳衰极、下利清谷、四肢厥冷、脉微欲绝。",
        "symptom_weights": {"下利清谷": 20, "脚冷": 16, "身冷": 14},
        "pair_bonus": [("下利清谷", "脚冷", 14)],
        "boost_pulses": {"微细": 16, "迟": 10},
        "conflict_pulses": {"洪大": -25, "数": -15},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "急救灸穴", "reason": "隔盐隔姜重灸关元回阳固脱"},
            {"id": "acupoint:ren06:气海", "name": "气海", "role": "配穴（宜灸）", "reason": "益原气、温脾肾"},
        ],
    },
    {
        "atom_id": "atom:lizhong",
        "formula_id": "shanghan:理中丸",
        "name": "理中丸",
        "six_meridian": "太阴中焦虚寒 · 寒多吐利腹痛",
        "pathogenesis": "脾胃虚寒不运，腹痛喜温、食不下、呕吐泄泻、口不渴。",
        "symptom_weights": {"腹痛": 10, "下利清谷": 14, "呕吐": 10, "身冷": 8},
        "boost_pulses": {"沉": 8, "迟": 8, "缓": 6},
        "conflict_pulses": {"洪大": -20, "数": -10},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "主穴", "reason": "胃募腑会，温运中焦脾胃"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "主穴", "reason": "升清降浊、固护胃气"},
            {"id": "acupoint:bl20:脾俞", "name": "脾俞", "role": "配穴", "reason": "温补脾阳"},
        ],
    },
    {
        "atom_id": "atom:xiaoqinglong",
        "formula_id": "shanghan:小青龙汤",
        "name": "小青龙汤",
        "six_meridian": "外寒内饮射肺 · 喘咳白沫痰",
        "pathogenesis": "太阳伤寒不解而心下有水气上冲犯肺，咳嗽喘急白沫痰。",
        "symptom_weights": {"咳喘痰多": 22, "无汗": 10, "身冷": 8},
        "boost_pulses": {"浮": 8, "紧": 10, "弦": 8},
        "conflict_pulses": {},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:lu05:尺泽", "name": "尺泽", "role": "主穴", "reason": "肺经合穴泻肺实平喘降逆"},
            {"id": "acupoint:bl13:肺俞", "name": "肺俞", "role": "主穴", "reason": "宣通肺气、化背寒伏饮"},
            {"id": "acupoint:st40:丰隆", "name": "丰隆", "role": "配穴", "reason": "化痰要穴，蠲化心下胸膈顽痰"},
        ],
    },
    {
        "atom_id": "atom:dachengqi",
        "formula_id": "shanghan:大承气汤",
        "name": "大承气汤",
        "six_meridian": "阳明腑实燥热 · 痞满燥实",
        "pathogenesis": "阳明胃家实热与燥屎搏结（日晡潮热、腹满硬痛、大便硬结、脉沉实洪滑）。切忌用于身冷脉微细虚寒便干！",
        "symptom_weights": {"大便干": 14, "习惯性便秘": 10, "腹痛": 8, "发热": 10},
        "boost_pulses": {"滑": 14, "数": 12, "洪大": 12},
        "conflict_pulses": {"微细": -28, "迟": -18},
        "conflict_symptoms": {"身冷": -22, "脚冷": -22, "下利清谷": -30},
        "acupoints": [
            {"id": "acupoint:st25:天枢", "name": "天枢", "role": "主穴", "reason": "泻阳明大肠实滞"},
            {"id": "acupoint:li04:合谷", "name": "合谷", "role": "主穴", "reason": "阳明原穴清泻腑热"},
        ],
    },
    {
        "atom_id": "atom:suanzaoren",
        "formula_id": "jinkui:酸枣仁汤",
        "name": "酸枣仁汤",
        "six_meridian": "肝血虚热 · 虚烦失眠不得眠",
        "pathogenesis": "肝阴血虚内生虚烦，夜不能寐、心悸多梦。",
        "symptom_weights": {"心烦失眠": 22, "眩晕": 6, "心悸": 8},
        "boost_pulses": {"弦": 8, "数": 6, "涩": 6},
        "conflict_pulses": {},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:ht07:神门", "name": "神门", "role": "主穴", "reason": "心经原穴，宁心安神定失眠"},
            {"id": "acupoint:sp06:三阴交", "name": "三阴交", "role": "配穴", "reason": "养血滋阴以敛肝魂"},
        ],
    },
    {
        "atom_id": "atom:wuzhuyu",
        "formula_id": "shanghan:吴茱萸汤",
        "name": "吴茱萸汤",
        "six_meridian": "厥阴寒痰浊阴上逆 · 巅顶痛吐涎沫",
        "pathogenesis": "胃寒肝虚浊阴上冲巅顶，头痛、干呕、吐涎沫。",
        "symptom_weights": {"头痛": 18, "呕吐": 14, "脚冷": 8, "身冷": 6},
        "pair_bonus": [("头痛", "呕吐", 16)],
        "boost_pulses": {"沉": 8, "迟": 10},
        "conflict_pulses": {"洪大": -16},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:du20:百会", "name": "百会", "role": "主穴", "reason": "巅顶厥阴督脉汇处"},
            {"id": "acupoint:lv03:太冲", "name": "太冲", "role": "主穴", "reason": "疏降肝胃上冲逆气"},
        ],
    },
    {
        "atom_id": "atom:xiexin-huangtu",
        "formula_id": "jinkui:黄土汤",
        "name": "黄土汤",
        "six_meridian": "脾阳虚寒不摄 · 下血远血",
        "pathogenesis": "脾阳虚弱不能统摄血脉，先便后血、四肢不温。",
        "symptom_weights": {"先便后血": 26, "失血": 24, "身冷": 8, "脚冷": 8},
        "boost_pulses": {"沉": 8, "微细": 10},
        "conflict_pulses": {"洪大": -14},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:sp10:血海", "name": "血海", "role": "主穴", "reason": "养血止血要穴"},
            {"id": "acupoint:bl20:脾俞", "name": "脾俞", "role": "配穴（宜灸）", "reason": "温脾以统血"},
        ],
    },
    {
        "atom_id": "atom:linggui-zhugan",
        "formula_id": "jinkui:苓桂术甘汤",
        "name": "苓桂术甘汤",
        "six_meridian": "太阴痰饮气冲 · 脾虚水饮上凌心肺",
        "pathogenesis": "《伤寒》《金匮》名方：中阳不足而痰饮停聚中焦，上冲作心下逆满、起则头眩、心悸胸胁支满。",
        "symptom_weights": {"眩晕": 14, "心悸": 16, "胸痹": 10, "咳喘痰多": 8, "小便不利": 6},
        "pair_bonus": [("眩晕", "心悸", 14)],
        "boost_pulses": {"沉": 6, "弦": 8, "紧": 8},
        "conflict_pulses": {"洪大": -14},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "主穴", "reason": "健运中土化饮降浊"},
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "主穴", "reason": "定心悸、宽胸理气降冲逆"},
            {"id": "acupoint:st40:丰隆", "name": "丰隆", "role": "配穴", "reason": "化中焦痰饮水浊"},
            {"id": "acupoint:sp09:阴陵泉", "name": "阴陵泉", "role": "配穴", "reason": "渗湿利水通调水道"},
        ],
    },
    {
        "atom_id": "atom:banxia-xiexin",
        "formula_id": "shanghan:半夏泻心汤",
        "name": "半夏泻心汤",
        "six_meridian": "寒热错杂痞证 · 升降失司心下痞呕利",
        "pathogenesis": "中焦脾胃升降失调、寒热互结心下，见心下痞满而不痛、呕吐干呕、肠鸣下利。",
        "symptom_weights": {"心下痞": 26, "呕吐": 14, "下利清谷": 10, "口苦": 6},
        "pair_bonus": [("心下痞", "呕吐", 14)],
        "boost_pulses": {"弦": 6, "滑": 8},
        "conflict_pulses": {},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "主穴", "reason": "消痞散结、和胃降逆"},
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "主穴", "reason": "止呕宽胃痞（配公孙主胃心胸）"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "配穴", "reason": "调中州升降、止肠鸣下利"},
            {"id": "acupoint:sp04:公孙", "name": "公孙", "role": "配穴", "reason": "八脉交会通冲脉，配内关治心下痞呕吐"},
        ],
    },
    {
        "atom_id": "atom:sini-san",
        "formula_id": "shanghan:四逆散",
        "name": "四逆散",
        "six_meridian": "少阴阳郁气滞 · 肝脾失调四肢不温",
        "pathogenesis": "阳气内郁不达四末（手足不温而脉弦非微细），常兼胸胁苦满、腹痛、或泄利下重。",
        "symptom_weights": {"口苦": 14, "腹痛": 14, "脚冷": 10, "痛经": 8, "心下痞": 8, "心烦失眠": 6},
        "pair_bonus": [("口苦", "腹痛", 12)],
        "boost_pulses": {"弦": 14},
        "conflict_pulses": {"微细": -14, "迟": -8},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:lv03:太冲", "name": "太冲", "role": "主穴", "reason": "疏肝解郁、达阳气于四末"},
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "主穴", "reason": "利少阳肝胆气机、舒筋止胁痛腹痛"},
            {"id": "acupoint:lv14:期门", "name": "期门", "role": "配穴", "reason": "解胸胁苦满肝郁气滞"},
            {"id": "acupoint:sp06:三阴交", "name": "三阴交", "role": "配穴", "reason": "柔肝缓急调脾止腹痛"},
        ],
    },
    {
        "atom_id": "atom:shenqi-wan",
        "formula_id": "jinkui:肾气丸",
        "name": "肾气丸",
        "six_meridian": "下焦肾气虚弱 · 腰痛脚弱小便不利或反多",
        "pathogenesis": "《金匮》肾气不足核心方：腰冷脚弱、少腹拘急、小便不利或夜尿反多、耳鸣消渴。",
        "symptom_weights": {"夜尿多": 24, "小便不利": 16, "耳鸣": 14, "脚冷": 10, "身冷": 10, "口渴": 8},
        "pair_bonus": [("夜尿多", "身冷", 12)],
        "boost_pulses": {"沉": 10, "微细": 10, "迟": 6},
        "conflict_pulses": {"洪大": -18},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:bl23:肾俞", "name": "肾俞", "role": "主穴", "reason": "补益肾气、强腰膝定耳鸣"},
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（宜灸）", "reason": "培补下焦真元、统摄夜尿小便开阖"},
            {"id": "acupoint:ki03:太溪", "name": "太溪", "role": "主穴", "reason": "肾经原穴滋水涵阳"},
            {"id": "acupoint:du04:命门", "name": "命门", "role": "配穴（宜灸）", "reason": "温煦下元肾阳命火"},
        ],
    },
    {
        "atom_id": "atom:guizhi-fuling",
        "formula_id": "jinkui:桂枝茯苓丸",
        "name": "桂枝茯苓丸",
        "six_meridian": "妇人癥瘕瘀血 · 胞宫血瘀腹痛痛经",
        "pathogenesis": "瘀血阻滞胞宫少腹（痛经血块、少腹硬痛、经行不畅、或下血不止）。",
        "symptom_weights": {"痛经": 18, "腹痛": 14, "失血": 8, "小便不利": 6},
        "boost_pulses": {"涩": 12, "弦": 6, "滑": 6},
        "conflict_pulses": {"微细": -10},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:sp06:三阴交", "name": "三阴交", "role": "主穴", "reason": "调理冲任胞宫血室瘀滞"},
            {"id": "acupoint:sp10:血海", "name": "血海", "role": "主穴", "reason": "活血化瘀止少腹胞宫痛经"},
            {"id": "acupoint:st29:归来", "name": "归来", "role": "配穴", "reason": "下腹归来直入胞宫散结止痛"},
            {"id": "acupoint:bl32:次髎", "name": "次髎", "role": "配穴", "reason": "八髎调经活血止胞宫瘀痛要穴"},
        ],
    },
    {
        "atom_id": "atom:danggui-sini",
        "formula_id": "shanghan:当归四逆汤",
        "name": "当归四逆汤",
        "six_meridian": "厥阴血虚寒凝 · 手足厥寒关节冷痛",
        "pathogenesis": "《伤寒》厥阴篇：营血不足复感寒邪客于经脉（手足厥寒、脉细欲绝、寒凝痛经或关节冷痛）。",
        "symptom_weights": {"脚冷": 16, "关节痹痛": 16, "痛经": 10, "腹痛": 6, "身冷": 6},
        "pair_bonus": [("脚冷", "关节痹痛", 14)],
        "boost_pulses": {"微细": 12, "涩": 8},
        "conflict_pulses": {"洪大": -20, "数": -12},
        "conflict_symptoms": {"发热": -6},
        "acupoints": [
            {"id": "acupoint:sp06:三阴交", "name": "三阴交", "role": "主穴", "reason": "养阴血、温经散厥阴寒凝"},
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（宜灸）", "reason": "温经通阳散下焦冲任寒滞"},
            {"id": "acupoint:lv03:太冲", "name": "太冲", "role": "配穴", "reason": "厥阴肝经原穴，养肝血通经脉止厥冷"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "配穴", "reason": "益气养血温运四肢经脉"},
        ],
    },
    {
        "atom_id": "atom:mahuang-tang",
        "formula_id": "shanghan:麻黄汤",
        "name": "麻黄汤",
        "polarity": "warm_exterior",
        "six_meridian": "太阳伤寒表实 · 无汗身痛喘咳",
        "pathogenesis": "寒邪束表卫闭，见恶寒、发热、无汗、身体痛关节痹痛、肺气上逆而喘、脉浮紧。",
        "symptom_weights": {"无汗": 22, "身冷": 14, "发热": 14, "咳喘痰多": 10, "关节痹痛": 8, "头痛": 8},
        "pair_bonus": [("无汗", "身冷", 14), ("无汗", "发热", 12)],
        "boost_pulses": {"浮": 12, "紧": 14},
        "conflict_pulses": {"微细": -18, "缓": -12},
        "conflict_symptoms": {"有汗": -24, "咽干": -8, "失血": -16},
        "acupoints": [
            {"id": "acupoint:lu07:列缺", "name": "列缺", "role": "主穴", "reason": "肺经络穴，宣肺散表寒解头项痛"},
            {"id": "acupoint:li04:合谷", "name": "合谷", "role": "主穴", "reason": "手阳明原穴，通闭塞解无汗恶寒"},
            {"id": "acupoint:gb20:风池", "name": "风池", "role": "配穴", "reason": "祛风散寒解太阳头身疼痛"},
        ],
    },
    {
        "atom_id": "atom:daqinglong",
        "formula_id": "shanghan:大青龙汤",
        "name": "大青龙汤",
        "polarity": "warm_exterior",
        "six_meridian": "太阳表寒兼阳明里热 · 无汗烦躁脉浮紧",
        "pathogenesis": "《伤寒》表寒闭郁、内生热躁：发热恶寒、身痛无汗而见心烦失眠或大渴烦躁，脉浮紧。",
        "symptom_weights": {"无汗": 18, "发热": 16, "身冷": 12, "心烦失眠": 16, "口渴": 10, "水肿": 10},
        "pair_bonus": [("无汗", "心烦失眠", 16), ("发热", "心烦失眠", 10)],
        "boost_pulses": {"浮": 10, "紧": 12, "数": 8},
        "conflict_pulses": {"微细": -22, "迟": -14},
        "conflict_symptoms": {"有汗": -24, "脚冷": -16},
        "acupoints": [
            {"id": "acupoint:du14:大椎", "name": "大椎", "role": "主穴", "reason": "退表里大热宣散督脉阳郁"},
            {"id": "acupoint:li11:曲池", "name": "曲池", "role": "主穴", "reason": "清阳明烦热止躁"},
            {"id": "acupoint:lu05:尺泽", "name": "尺泽", "role": "配穴", "reason": "清肺热定喘烦"},
        ],
    },
    {
        "atom_id": "atom:baihu",
        "formula_id": "shanghan:白虎汤",
        "name": "白虎汤",
        "polarity": "heat_excess",
        "six_meridian": "阳明气分大热 · 四大证（大热大汗大渴脉洪大）",
        "pathogenesis": "阳明胃肺气分纯热亢盛而腑尚无燥屎阻结：高热、大汗、口大渴喜冷饮、舌黄苔干而脉洪大。",
        "symptom_weights": {"高热": 24, "发热": 14, "口渴": 20, "喜冷饮": 22, "有汗": 14, "舌黄厚燥": 10},
        "pair_bonus": [("高热", "喜冷饮", 16), ("口渴", "喜冷饮", 14)],
        "boost_pulses": {"洪大": 20, "滑": 8, "数": 10},
        "conflict_pulses": {"微细": -26, "迟": -20, "沉": -10},
        "conflict_symptoms": {"身冷": -18, "脚冷": -20, "口不渴": -18, "舌白厚湿": -14},
        "acupoints": [
            {"id": "acupoint:li11:曲池", "name": "曲池", "role": "主穴", "reason": "阳明合穴清气分壮热"},
            {"id": "acupoint:st44:内庭", "name": "内庭", "role": "主穴", "reason": "胃经荥穴泻胃火烦渴"},
            {"id": "acupoint:du14:大椎", "name": "大椎", "role": "配穴", "reason": "泻全身阳明实热"},
        ],
    },
    {
        "atom_id": "atom:baihu-jiarenshen",
        "formula_id": "shanghan:白虎加人参汤",
        "name": "白虎加人参汤",
        "polarity": "heat_excess",
        "six_meridian": "阳明气津两伤 · 消渴大渴饮水数升",
        "pathogenesis": "白虎汤证兼津气大伤、背微恶寒、大烦渴不解（经方治热证上消核心方，忌作寒虚论）。",
        "symptom_weights": {"口渴": 24, "喜冷饮": 18, "高热": 16, "有汗": 10, "身冷": 6},
        "pair_bonus": [("口渴", "喜冷饮", 14), ("口渴", "高热", 12)],
        "boost_pulses": {"洪大": 18, "数": 10},
        "conflict_pulses": {"微细": -18, "迟": -16},
        "conflict_symptoms": {"脚冷": -16, "口不渴": -18},
        "acupoints": [
            {"id": "acupoint:st44:内庭", "name": "内庭", "role": "主穴", "reason": "清胃热生津止渴"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "主穴", "reason": "益胃气护津液消渴"},
            {"id": "acupoint:lu05:尺泽", "name": "尺泽", "role": "配穴", "reason": "清金水之源止上消引饮"},
        ],
    },
    {
        "atom_id": "atom:dachaihu",
        "formula_id": "shanghan:大柴胡汤",
        "name": "大柴胡汤",
        "polarity": "heat_excess",
        "six_meridian": "少阳兼阳明腑实 · 表里两解呕痛便秘",
        "pathogenesis": "少阳枢机不利兼阳明燥实内结：往来寒热、胸胁苦满口苦、呕不止、心下急或腹满拒按便秘，脉弦数有力。",
        "symptom_weights": {"往来寒热": 16, "口苦": 16, "呕吐": 14, "腹满拒按": 20, "大便干": 14, "黄疸": 10, "心烦失眠": 8},
        "pair_bonus": [("口苦", "腹满拒按", 16), ("往来寒热", "呕吐", 12)],
        "boost_pulses": {"弦": 14, "数": 10, "滑": 8},
        "conflict_pulses": {"微细": -22, "迟": -14},
        "conflict_symptoms": {"脚冷": -14, "腹痛喜按": -16, "下利清谷": -14},
        "acupoints": [
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "主穴", "reason": "清疏少阳胆腑滞热与胁痛"},
            {"id": "acupoint:sj06:支沟", "name": "支沟", "role": "主穴", "reason": "通调三焦大肠气机泻实秘"},
            {"id": "acupoint:st25:天枢", "name": "天枢", "role": "配穴", "reason": "通下阳明宿食燥屎"},
        ],
    },
    {
        "atom_id": "atom:chaihu-guizhi",
        "formula_id": "shanghan:柴胡桂枝汤",
        "name": "柴胡桂枝汤",
        "polarity": "half_interior",
        "six_meridian": "太阳少阳并病 · 发热微恶寒肢节痛兼心腹卒痛",
        "pathogenesis": "小柴胡汤与桂枝汤合半方：太少合病见发热微恶寒、支节烦疼、微呕、心下支结或腹卒痛。",
        "symptom_weights": {"往来寒热": 14, "发热": 10, "身冷": 8, "口苦": 12, "呕吐": 10, "关节痹痛": 10, "有汗": 8},
        "pair_bonus": [("往来寒热", "关节痹痛", 12), ("口苦", "有汗", 10)],
        "boost_pulses": {"弦": 12, "浮": 8},
        "conflict_pulses": {"洪大": -12},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:sj05:外关", "name": "外关", "role": "主穴", "reason": "合解太阳少阳表里邪气"},
            {"id": "acupoint:gb20:风池", "name": "风池", "role": "配穴", "reason": "散头项肩背痹痛"},
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "配穴", "reason": "利胆舒筋解胁结"},
        ],
    },
    {
        "atom_id": "atom:xiaojianzhong",
        "formula_id": "shanghan:小建中汤",
        "name": "小建中汤",
        "polarity": "balanced",
        "six_meridian": "太阴虚劳 · “先补虚”中焦脾胃急痛悸衄",
        "pathogenesis": "仲景虚劳“先补虚”第一方：重用白芍配饴糖桂枝，治腹中急痛喜温喜按、心中悸烦、手足烦热或表虚气怯。",
        "symptom_weights": {"腹痛喜按": 26, "心悸": 16, "手掌烦热": 14, "腹痛": 10, "心烦失眠": 10, "失血": 8},
        "pair_bonus": [("腹痛喜按", "心悸", 18), ("腹痛喜按", "手掌烦热", 14)],
        "boost_pulses": {"弦": 6, "涩": 8, "微细": 8, "缓": 8},
        "conflict_pulses": {"洪大": -16},
        "conflict_symptoms": {"腹满拒按": -22, "呕吐": -10},
        "acupoints": [
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "主穴（宜灸）", "reason": "建中焦胃气养营血"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "主穴", "reason": "健脾强胃止虚劳腹痛"},
            {"id": "acupoint:bl20:脾俞", "name": "脾俞", "role": "配穴", "reason": "培补中土生血统血"},
        ],
    },
    {
        "atom_id": "atom:zhigancao",
        "formula_id": "shanghan:炙甘草汤",
        "name": "炙甘草汤",
        "polarity": "balanced",
        "six_meridian": "“先补虚”复脉主方 · 心动悸脉结代阴血两虚",
        "pathogenesis": "经方补心复脉之冠（又名复脉汤）：气血津液大亏致心动悸、脉结代，兼见失眠舌红少苔干咳（需排查急症）。",
        "symptom_weights": {"心悸": 24, "心烦失眠": 14, "舌红少苔": 14, "手掌烦热": 10, "咳喘痰多": 8, "大便干": 6},
        "pair_bonus": [("心悸", "舌红少苔", 14)],
        "boost_pulses": {"结代": 32, "微细": 10, "涩": 8},
        "conflict_pulses": {"洪大": -12},
        "conflict_symptoms": {"腹满拒按": -16},
        "acupoints": [
            {"id": "acupoint:ren14:巨阙", "name": "巨阙", "role": "主穴", "reason": "心募强心安神定悸"},
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "主穴", "reason": "宁心复脉调心律"},
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "配穴", "reason": "培补元阴元阳充血脉"},
        ],
    },
    {
        "atom_id": "atom:guizhi-jiafuzi",
        "formula_id": "shanghan:桂枝加附子汤",
        "name": "桂枝加附子汤",
        "polarity": "yang_def_cold",
        "six_meridian": "太阳表阳虚漏 · 发汗过多遂漏不止",
        "pathogenesis": "太阳发汗太过亡阳，致汗漏不止、恶风、小便难、四肢微急难以屈伸（必用炮附子固表）。",
        "symptom_weights": {"有汗": 22, "身冷": 14, "小便不利": 14, "关节痹痛": 10, "脚冷": 10},
        "pair_bonus": [("有汗", "身冷", 12), ("有汗", "小便不利", 12)],
        "boost_pulses": {"浮": 8, "微细": 14, "迟": 10},
        "conflict_pulses": {"洪大": -22},
        "conflict_symptoms": {"无汗": -20, "高热": -14},
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（宜灸）", "reason": "固护卫阳止大汗漏脱"},
            {"id": "acupoint:ki07:复溜", "name": "复溜", "role": "配穴", "reason": "配关元固表敛汗温阳"},
            {"id": "acupoint:li04:合谷", "name": "合谷", "role": "配穴", "reason": "与复溜配合调控开阖止漏汗"},
        ],
    },
    {
        "atom_id": "atom:daxianxiong",
        "formula_id": "shanghan:大陷胸汤",
        "name": "大陷胸汤",
        "polarity": "heat_excess",
        "six_meridian": "太阳结胸热实 · 水热互结心下硬满拒按如石硬",
        "pathogenesis": "《伤寒》误下邪热与水饮结于胸膈心下：从心下至少腹硬满而痛不可近、日晡潮热或短气烦躁、脉沉紧。",
        "symptom_weights": {"心下硬痛": 30, "腹满拒按": 18, "大便干": 10, "心烦失眠": 10, "口渴": 8},
        "pair_bonus": [("心下硬痛", "腹满拒按", 18)],
        "boost_pulses": {"沉": 12, "紧": 10, "滑": 10},
        "conflict_pulses": {"微细": -22},
        "conflict_symptoms": {"腹痛喜按": -24, "下利清谷": -20, "舌白厚湿": -14},
        "acupoints": [
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "主穴", "reason": "泻心下硬满结聚"},
            {"id": "acupoint:ren17:膻中", "name": "膻中", "role": "配穴", "reason": "宽胸膈逐上中焦水热互结"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "配穴", "reason": "导水热下行出腑"},
        ],
    },
    {
        "atom_id": "atom:xiaoxianxiong",
        "formula_id": "shanghan:小陷胸汤",
        "name": "小陷胸汤",
        "polarity": "heat_excess",
        "six_meridian": "小结胸病 · 痰热互结正在心下按之则痛",
        "pathogenesis": "痰热结于正在心下（未至全腹石硬），按之方痛、呕吐吞酸或胃灼假心痛、舌黄苔腻、脉浮滑。",
        "symptom_weights": {"心下硬痛": 20, "心下痞": 14, "胸痹": 10, "呕吐": 10, "舌黄厚燥": 10},
        "pair_bonus": [("心下硬痛", "呕吐", 12)],
        "boost_pulses": {"浮": 8, "滑": 16, "数": 8},
        "conflict_pulses": {"微细": -18, "迟": -12},
        "conflict_symptoms": {"腹痛喜按": -16, "脚冷": -12},
        "acupoints": [
            {"id": "acupoint:ren12:中脘", "name": "中脘", "role": "主穴", "reason": "清化心下痰热止胃脘灼痛"},
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "主穴", "reason": "清宽胸脘逆气吐酸"},
            {"id": "acupoint:st40:丰隆", "name": "丰隆", "role": "配穴", "reason": "化胸脘顽痰热结"},
        ],
    },
    {
        "atom_id": "atom:taohe-chengqi",
        "formula_id": "shanghan:桃核承气汤",
        "name": "桃核承气汤",
        "polarity": "blood_stasis",
        "six_meridian": "太阳蓄血轻缓初结 · 少腹急结其人如狂小便自利",
        "pathogenesis": "太阳表热随经入里与血搏结下焦：少腹急结疼痛、其人如狂、小便自利，破瘀泄热先用桂枝甘草以防过寒。",
        "symptom_weights": {"少腹急结": 26, "如狂发狂": 18, "小便自利": 18, "腹痛": 10, "舌紫暗瘀": 12, "大便干": 6},
        "pair_bonus": [("少腹急结", "小便自利", 18), ("少腹急结", "如狂发狂", 14)],
        "boost_pulses": {"沉": 10, "涩": 12, "数": 8},
        "conflict_pulses": {"微细": -14},
        "conflict_symptoms": {"小便不利": -14, "下利清谷": -14},
        "acupoints": [
            {"id": "acupoint:sp10:血海", "name": "血海", "role": "主穴", "reason": "破少腹下焦蓄血急结"},
            {"id": "acupoint:sp06:三阴交", "name": "三阴交", "role": "主穴", "reason": "通下焦血室泄热化瘀"},
            {"id": "acupoint:bl40:委中", "name": "委中", "role": "配穴（放血）", "reason": "血郄泄下焦瘀热急结"},
        ],
    },
    {
        "atom_id": "atom:didang",
        "formula_id": "shanghan:抵当汤",
        "name": "抵当汤",
        "polarity": "blood_stasis",
        "six_meridian": "下焦深重蓄血 · 少腹硬满发狂屎黑小便利",
        "pathogenesis": "《伤寒》《金匮》破久瘀虫积第一方：少腹硬满、发狂喜忘、屎虽硬大便反易其色必黑、小便自利。",
        "symptom_weights": {"少腹急结": 24, "如狂发狂": 22, "小便自利": 16, "舌紫暗瘀": 16, "痛经": 10},
        "pair_bonus": [("如狂发狂", "小便自利", 18), ("少腹急结", "舌紫暗瘀", 16)],
        "boost_pulses": {"沉": 12, "涩": 14, "紧": 8},
        "conflict_pulses": {"微细": -18},
        "conflict_symptoms": {"小便不利": -16, "腹痛喜按": -18},
        "acupoints": [
            {"id": "acupoint:sp10:血海", "name": "血海", "role": "主穴", "reason": "荡涤胞宫膀胱深层久瘀"},
            {"id": "acupoint:lv03:太冲", "name": "太冲", "role": "配穴", "reason": "破肝经血室郁结"},
            {"id": "acupoint:ki02:然谷", "name": "然谷", "role": "配穴（点刺放血）", "reason": "《内经》跌堕蓄血小腹胀取然骨青筋放血"},
        ],
    },
    {
        "atom_id": "atom:zhuling",
        "formula_id": "shanghan:猪苓汤",
        "name": "猪苓汤",
        "polarity": "yin_def_heat",
        "six_meridian": "阳明少阴水热互结 · 育阴利水治咳呕渴心烦不得眠",
        "pathogenesis": "热与水结且伤及少阴阴津（脉浮发热、渴欲饮水、小便不利、心烦不得眠，或下利咳呕）。",
        "symptom_weights": {"小便不利": 18, "口渴": 16, "心烦失眠": 16, "小便深黄": 14, "发热": 10, "舌红少苔": 10},
        "pair_bonus": [("小便不利", "心烦失眠", 14), ("小便不利", "口渴", 10)],
        "boost_pulses": {"数": 10, "浮": 8, "微细": 8},
        "conflict_pulses": {"迟": -14},
        "conflict_symptoms": {"口不渴": -16, "小便清白": -14, "舌白厚湿": -12},
        "acupoints": [
            {"id": "acupoint:sp09:阴陵泉", "name": "阴陵泉", "role": "主穴", "reason": "分利湿热通调小便不利"},
            {"id": "acupoint:ren03:中极", "name": "中极", "role": "主穴", "reason": "膀胱募清利下焦水热蓄痛"},
            {"id": "acupoint:ki03:太溪", "name": "太溪", "role": "配穴", "reason": "护少阴肾水防利尿更伤阴"},
        ],
    },
    {
        "atom_id": "atom:yinchenhao",
        "formula_id": "shanghan:茵陈蒿汤",
        "name": "茵陈蒿汤",
        "polarity": "heat_excess",
        "six_meridian": "阳明湿热实黄 · 身黄如橘子色但头汗腹满小便不利",
        "pathogenesis": "湿热瘀郁太阴脾土与阳明胃腑致身目鲜黄、但头汗出（剂颈而还）、腹满、大便秘、小便深黄不利。",
        "symptom_weights": {"黄疸": 28, "小便深黄": 16, "小便不利": 14, "腹满拒按": 12, "大便干": 10, "但头汗出": 10},
        "pair_bonus": [("黄疸", "小便深黄", 16), ("黄疸", "大便干", 12)],
        "boost_pulses": {"滑": 10, "数": 10, "弦": 8},
        "conflict_pulses": {"微细": -18, "迟": -12},
        "conflict_symptoms": {"脚冷": -14, "小便清白": -14},
        "acupoints": [
            {"id": "acupoint:du09:至阳", "name": "至阳", "role": "主穴", "reason": "古传退黄疸要穴兼利肝胆膜原"},
            {"id": "acupoint:bl19:胆俞", "name": "胆俞", "role": "主穴", "reason": "清泄胆腑湿热发黄"},
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "配穴", "reason": "疏胆排石泄湿热"},
        ],
    },
    {
        "atom_id": "atom:yinchen-wuling",
        "formula_id": "jinkui:茵陈五苓散",
        "name": "茵陈五苓散",
        "polarity": "balanced",
        "six_meridian": "黄瘅湿重于热 · 黄疸伴小便不利微饮胆结石",
        "pathogenesis": "《金匮·黄瘅》：湿重于热，身目黄疸而大便不闭或偏濡、小便不利、口渴微烦（倪师常配四金用治胆石轻黄）。",
        "symptom_weights": {"黄疸": 26, "小便不利": 14, "口渴": 8, "口苦": 8, "水肿": 6},
        "pair_bonus": [("黄疸", "小便不利", 14)],
        "boost_pulses": {"弦": 10, "浮": 6},
        "conflict_pulses": {"微细": -10},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "主穴", "reason": "舒利肝胆止胁痛胆石"},
            {"id": "acupoint:sp09:阴陵泉", "name": "阴陵泉", "role": "配穴", "reason": "利脾湿从膀胱消黄"},
            {"id": "acupoint:bl19:胆俞", "name": "胆俞", "role": "配穴", "reason": "通调胆气化湿热"},
        ],
    },
    {
        "atom_id": "atom:huanglian-ejiao",
        "formula_id": "shanghan:黄连阿胶汤",
        "name": "黄连阿胶汤",
        "polarity": "yin_def_heat",
        "six_meridian": "少阴热化水火不交 · 心中烦不得卧（泄南补北）",
        "pathogenesis": "少阴肾水真阴大亏、心火亢盛于上：夜彻不寐、心中躁烦、舌红少苔无津、脉细数（忌苦温燥烈劫阴）。",
        "symptom_weights": {"心烦失眠": 26, "舌红少苔": 20, "手掌烦热": 12, "咽干": 10, "口渴": 8},
        "pair_bonus": [("心烦失眠", "舌红少苔", 18), ("心烦失眠", "手掌烦热", 12)],
        "boost_pulses": {"数": 14, "微细": 10},
        "conflict_pulses": {"迟": -18},
        "conflict_symptoms": {"舌白厚湿": -20, "脚冷": -12, "下利清谷": -14},
        "acupoints": [
            {"id": "acupoint:ki06:照海", "name": "照海", "role": "主穴", "reason": "滋少阴肾水交通心肾（配阴跷夜灸/针定夜眠）"},
            {"id": "acupoint:ht07:神门", "name": "神门", "role": "主穴", "reason": "清心火安神定不寐"},
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "配穴", "reason": "引心火下行济肾水"},
        ],
    },
    {
        "atom_id": "atom:baitong",
        "formula_id": "shanghan:白通汤",
        "name": "白通汤",
        "polarity": "yang_def_cold",
        "six_meridian": "少阴阴盛戴阳格拒 · 下利清谷手足厥冷面微赤",
        "pathogenesis": "下焦阴寒极盛逼浮阳上冲于面：下利、手足厥冷、脉微（危急加猪胆汁人尿防热因热用格拒）。",
        "symptom_weights": {"下利清谷": 24, "脚冷": 20, "身冷": 16, "舌白厚湿": 10},
        "pair_bonus": [("下利清谷", "脚冷", 16)],
        "boost_pulses": {"微细": 20, "沉": 12, "迟": 10},
        "conflict_pulses": {"洪大": -28, "数": -20},
        "conflict_symptoms": {"大便干": -20, "舌黄厚燥": -20},
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "急救主穴（宜重灸）", "reason": "回少阴垂绝之元阳"},
            {"id": "acupoint:ren08:神阙", "name": "神阙", "role": "急救主穴（隔盐姜灸）", "reason": "温固中下焦脱阳下利"},
        ],
    },
    {
        "atom_id": "atom:gegen-qinlian",
        "formula_id": "shanghan:葛根黄芩黄连汤",
        "name": "葛根黄芩黄连汤",
        "polarity": "heat_excess",
        "six_meridian": "太阳表邪未罢误下 · 协热下利喘而汗出",
        "pathogenesis": "表热内陷阳明大肠致热泻臭秽、肛门灼热、有汗而喘、脉促（绝非少阴虚寒下利）。",
        "symptom_weights": {"下利清谷": 16, "发热": 14, "有汗": 12, "小便深黄": 14, "舌黄厚燥": 12, "口渴": 8},
        "pair_bonus": [("下利清谷", "发热", 14), ("下利清谷", "小便深黄", 16)],
        "boost_pulses": {"数": 14, "滑": 10},
        "conflict_pulses": {"微细": -22, "迟": -20},
        "conflict_symptoms": {"脚冷": -18, "身冷": -16, "舌白厚湿": -16},
        "acupoints": [
            {"id": "acupoint:st25:天枢", "name": "天枢", "role": "主穴", "reason": "清泄大肠湿热协利"},
            {"id": "acupoint:st37:上巨虚", "name": "上巨虚", "role": "配穴", "reason": "大肠下合穴止热利止泻"},
            {"id": "acupoint:li11:曲池", "name": "曲池", "role": "配穴", "reason": "清阳明里热兼表汗"},
        ],
    },
    {
        "atom_id": "atom:baitouweng",
        "formula_id": "shanghan:白头翁汤",
        "name": "白头翁汤",
        "polarity": "heat_excess",
        "six_meridian": "厥阴肝经湿热毒利 · 下重脓血口渴饮水",
        "pathogenesis": "湿热疫毒深迫厥阴下焦血分：腹痛里急后重、下利脓血或赤白相杂、渴欲饮水。",
        "symptom_weights": {"下利清谷": 16, "失血": 16, "口渴": 12, "腹痛": 10, "小便深黄": 12, "舌黄厚燥": 10},
        "pair_bonus": [("下利清谷", "失血", 18)],
        "boost_pulses": {"数": 14, "弦": 10},
        "conflict_pulses": {"微细": -20, "迟": -18},
        "conflict_symptoms": {"脚冷": -16, "舌白厚湿": -14},
        "acupoints": [
            {"id": "acupoint:st25:天枢", "name": "天枢", "role": "主穴", "reason": "解下重泻肠热毒"},
            {"id": "acupoint:lv02:行间", "name": "行间", "role": "配穴", "reason": "清厥阴肝经血分郁热"},
        ],
    },
    {
        "atom_id": "atom:taohua",
        "formula_id": "shanghan:桃花汤",
        "name": "桃花汤",
        "polarity": "yang_def_cold",
        "six_meridian": "少阴虚寒滑脱 · 下利便脓血（暗晦清冷）小便不利",
        "pathogenesis": "少阴脾肾下焦虚寒失固致便脓血日久不愈、腹痛、小便不利、手足逆冷。",
        "symptom_weights": {"下利清谷": 18, "失血": 16, "小便不利": 10, "腹痛": 8, "脚冷": 10},
        "pair_bonus": [("下利清谷", "脚冷", 12), ("失血", "脚冷", 10)],
        "boost_pulses": {"微细": 16, "沉": 12, "迟": 10},
        "conflict_pulses": {"洪大": -20, "数": -14},
        "conflict_symptoms": {"舌黄厚燥": -16, "高热": -16},
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（宜灸）", "reason": "温涩固脱止下利脓血"},
            {"id": "acupoint:du01:长强", "name": "长强", "role": "配穴", "reason": "固肛门脱陷与下利便血"},
        ],
    },
    {
        "atom_id": "atom:maxingshigan",
        "formula_id": "shanghan:麻黄杏仁甘草石膏汤",
        "name": "麻黄杏仁甘草石膏汤",
        "polarity": "heat_excess",
        "six_meridian": "邪热壅肺 · 汗出而喘黄痰咳喘",
        "pathogenesis": "太阳寒邪化热入肺（汗出而喘、鼻翼煽动、口渴痰黄粘、或无大热），重用生石膏清肺透热定喘。",
        "symptom_weights": {"咳喘痰多": 24, "有汗": 14, "口渴": 12, "发热": 10, "舌黄厚燥": 10},
        "pair_bonus": [("咳喘痰多", "有汗", 14), ("咳喘痰多", "口渴", 10)],
        "boost_pulses": {"数": 12, "滑": 10, "浮": 8},
        "conflict_pulses": {"微细": -18, "迟": -16},
        "conflict_symptoms": {"脚冷": -16, "舌白厚湿": -12},
        "acupoints": [
            {"id": "acupoint:lu05:尺泽", "name": "尺泽", "role": "主穴", "reason": "肺经合穴实泻肺热平喘"},
            {"id": "acupoint:lu10:鱼际", "name": "鱼际", "role": "主穴", "reason": "荥穴清肺热定喘"},
            {"id": "acupoint:bl13:肺俞", "name": "肺俞", "role": "配穴", "reason": "清宣肺气止咳喘"},
        ],
    },
    {
        "atom_id": "atom:mahuang-fuzi-xixin",
        "formula_id": "shanghan:麻黄附子细辛汤",
        "name": "麻黄附子细辛汤",
        "polarity": "yang_def_cold",
        "six_meridian": "太少两感 · 少阴发热身冷恶寒暴聋鼻冷塞",
        "pathogenesis": "《伤寒》少阴反发热脉沉，配生附助肾阳、麻黄发太阳表、细辛入少阴通九窍（亦治暴聋/阴寒鼻塞头痛）。",
        "symptom_weights": {"身冷": 16, "无汗": 12, "耳鸣": 14, "发热": 10, "脚冷": 10},
        "pair_bonus": [("身冷", "发热", 12), ("耳鸣", "身冷", 14), ("鼻症", "身冷", 14)],
        "boost_pulses": {"沉": 18, "紧": 8, "微细": 8},
        "conflict_pulses": {"洪大": -22},
        "conflict_symptoms": {"有汗": -14, "大渴喜冷": -18},
        "acupoints": [
            {"id": "acupoint:ki03:太溪", "name": "太溪", "role": "主穴", "reason": "助少阴肾阳通耳窍寒闭"},
            {"id": "acupoint:lu07:列缺", "name": "列缺", "role": "配穴", "reason": "宣通肺卫开鼻窍散风寒"},
            {"id": "acupoint:du04:命门", "name": "命门", "role": "配穴（宜灸）", "reason": "助阳托邪外达太阳"},
        ],
    },
    {
        "atom_id": "atom:lingguiganzhao",
        "formula_id": "shanghan:茯苓桂枝甘草大枣汤",
        "name": "茯苓桂枝甘草大枣汤",
        "polarity": "yang_def_cold",
        "six_meridian": "水寒奔豚 · 脐下悸欲作奔豚气上冲胸",
        "pathogenesis": "发汗后心阳不足、下焦肾水欲乘虚冲逆：脐下悸动欲作奔豚、气上冲胸，用甘澜水轻清化饮降冲。",
        "symptom_weights": {"气上冲胸": 28, "心悸": 18, "小便不利": 10, "身冷": 8},
        "pair_bonus": [("气上冲胸", "心悸", 16)],
        "boost_pulses": {"沉": 10, "弦": 10},
        "conflict_pulses": {"洪大": -14},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（宜灸）", "reason": "镇纳脐下冲逆肾水奔豚"},
            {"id": "acupoint:sp04:公孙", "name": "公孙", "role": "主穴", "reason": "配内关降冲脉奔豚上冲"},
            {"id": "acupoint:pc06:内关", "name": "内关", "role": "配穴", "reason": "平冲降逆止心悸胸冲"},
        ],
    },
    {
        "atom_id": "atom:dahuang-mudan",
        "formula_id": "jinkui:大黄牡丹汤",
        "name": "大黄牡丹汤",
        "polarity": "heat_excess",
        "six_meridian": "急性肠痈未成脓 · 右下腹少腹肿痞按之痛",
        "pathogenesis": "《金匮》肠痈急性期脓尚未成（腹皮急按如肿、时发热自汗出恶寒、右足屈不伸），峻攻瘀热，禁加枳朴甘草。",
        "symptom_weights": {"右下腹痛": 30, "腹满拒按": 16, "大便干": 10, "小便深黄": 10, "发热": 8},
        "pair_bonus": [("右下腹痛", "腹满拒按", 16)],
        "boost_pulses": {"紧": 8, "数": 10, "滑": 8},
        "conflict_pulses": {"微细": -18},
        "conflict_symptoms": {"腹痛喜按": -20, "脚冷": -12},
        "acupoints": [
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "主穴（定位阑尾穴）", "reason": "取足三里下一寸左右压痛阑尾奇穴，急救急性肠痈"},
            {"id": "acupoint:st25:天枢", "name": "天枢", "role": "配穴", "reason": "泻肠道瘀滞实热"},
        ],
    },
    {
        "atom_id": "atom:yiyifuzi-baijiang",
        "formula_id": "jinkui:薏苡附子败酱散",
        "name": "薏苡附子败酱散",
        "polarity": "balanced",
        "six_meridian": "慢性肠痈脓已成 · 身甲错腹皮急按之濡脉数",
        "pathogenesis": "《金匮》慢性/已化脓肠痈（或妇人腹膜炎后遗脓浊），切忌猛用大黄硝黄，以薏苡排脓、附子行阳散结，小便下即愈。",
        "symptom_weights": {"右下腹痛": 24, "腹痛喜按": 12, "小便不利": 10, "身冷": 8},
        "pair_bonus": [("右下腹痛", "腹痛喜按", 14)],
        "boost_pulses": {"数": 8, "沉": 8, "微细": 8},
        "conflict_pulses": {"洪大": -12},
        "conflict_symptoms": {"腹满拒按": -10},
        "acupoints": [
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "主穴", "reason": "扶正托脓消慢性肠痈（配合奇穴肘尖灸）"},
            {"id": "acupoint:sp09:阴陵泉", "name": "阴陵泉", "role": "配穴", "reason": "导湿浊脓毒从小便下行"},
        ],
    },
    {
        "atom_id": "atom:fangji-huangqi",
        "formula_id": "jinkui:防己黄耆汤",
        "name": "防己黄耆汤",
        "polarity": "balanced",
        "six_meridian": "表虚风水风湿 · 脉浮身重汗出恶风腰以上肿",
        "pathogenesis": "《金匮》卫表气虚挟水湿（风湿身重恶风汗出，或下肢腰下水肿），黄芪固三焦油网卫气配防己白术除湿利水。",
        "symptom_weights": {"水肿": 20, "有汗": 16, "关节痹痛": 16, "小便不利": 12},
        "pair_bonus": [("水肿", "有汗", 14), ("关节痹痛", "有汗", 14)],
        "boost_pulses": {"浮": 12, "缓": 8},
        "conflict_pulses": {"紧": -10},
        "conflict_symptoms": {"无汗": -14},
        "acupoints": [
            {"id": "acupoint:sp09:阴陵泉", "name": "阴陵泉", "role": "主穴", "reason": "健脾化三焦肌肉水湿"},
            {"id": "acupoint:ren09:水分", "name": "水分", "role": "主穴", "reason": "分清泌浊利全身水肿"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "配穴", "reason": "实脾固卫杜绝风水"},
        ],
    },
    {
        "atom_id": "atom:yuebi",
        "formula_id": "jinkui:越婢汤",
        "name": "越婢汤",
        "polarity": "heat_excess",
        "six_meridian": "实热风水全身肿 · 一身悉肿恶风脉浮不渴续自汗",
        "pathogenesis": "《金匮·水气》“腰以上肿，当发汗乃愈”代表方：重用麻黄石膏发越肺表水气兼清郁热。",
        "symptom_weights": {"水肿": 24, "发热": 10, "口不渴": 10, "无汗": 8, "咳喘痰多": 8},
        "pair_bonus": [("水肿", "无汗", 12)],
        "boost_pulses": {"浮": 14, "滑": 8, "数": 8},
        "conflict_pulses": {"微细": -18},
        "conflict_symptoms": {"脚冷": -16},
        "acupoints": [
            {"id": "acupoint:lu07:列缺", "name": "列缺", "role": "主穴", "reason": "开鬼门（宣肺发汗退头面腰上水肿）"},
            {"id": "acupoint:ren09:水分", "name": "水分", "role": "配穴", "reason": "通水道分消水气"},
        ],
    },
    {
        "atom_id": "atom:shegan-mahuang",
        "formula_id": "jinkui:射干麻黄汤",
        "name": "射干麻黄汤",
        "polarity": "yang_def_cold",
        "six_meridian": "寒饮伏肺哮喘 · 咳而上气喉中水鸡声",
        "pathogenesis": "《金匮·肺痿咳嗽上气》：深伏冷痰上涌阻塞气道，喉中如水鸡哮鸣、咳唾白泡沫痰。",
        "symptom_weights": {"水鸡声": 28, "咳喘痰多": 22, "身冷": 8, "舌白厚湿": 8},
        "pair_bonus": [("水鸡声", "咳喘痰多", 16)],
        "boost_pulses": {"沉": 8, "紧": 10, "弦": 10},
        "conflict_pulses": {"洪大": -16},
        "conflict_symptoms": {"舌黄厚燥": -12, "大渴喜冷": -12},
        "acupoints": [
            {"id": "acupoint:ren22:天突", "name": "天突", "role": "主穴", "reason": "宣通喉中哮鸣冷痰堵闭"},
            {"id": "acupoint:lu07:列缺", "name": "列缺", "role": "主穴", "reason": "宣肺定喘化冷饮"},
            {"id": "acupoint:st40:丰隆", "name": "丰隆", "role": "配穴", "reason": "涤荡顽固痰浊"},
        ],
    },
    {
        "atom_id": "atom:maimendong",
        "formula_id": "jinkui:麦门冬汤",
        "name": "麦门冬汤",
        "polarity": "yin_def_heat",
        "six_meridian": "胃肺阴津不足火逆上气 · 大逆上气咽喉不利",
        "pathogenesis": "《金匮》7倍麦冬配半夏，清养胃肺虚热、止逆下气治咽喉不利与阴虚干咳喘逆。",
        "symptom_weights": {"咳喘痰多": 16, "咽干": 18, "咽喉肿痛": 16, "舌红少苔": 18, "口渴": 10},
        "pair_bonus": [("咳喘痰多", "咽干", 14), ("咳喘痰多", "舌红少苔", 14)],
        "boost_pulses": {"数": 10, "微细": 8},
        "conflict_pulses": {"迟": -12},
        "conflict_symptoms": {"舌白厚湿": -16},
        "acupoints": [
            {"id": "acupoint:lu07:列缺", "name": "列缺", "role": "主穴", "reason": "配照海专治肺肾阴虚咽喉不利"},
            {"id": "acupoint:ki06:照海", "name": "照海", "role": "主穴", "reason": "生金水润咽降上逆火气"},
        ],
    },
    {
        "atom_id": "atom:guizhi-shaoyao-zhimu",
        "formula_id": "jinkui:桂枝芍药知母汤",
        "name": "桂枝芍药知母汤",
        "polarity": "balanced",
        "six_meridian": "寒热错杂历节痹证 · 肢节肿痛脚肿如脱头眩短气",
        "pathogenesis": "《金匮·中风历节》上下寒热并行主方：下焦肿痹如脱（麻附桂），上兼知母清燥热、白术防风除湿肿。",
        "symptom_weights": {"关节痹痛": 24, "脚肿如脱": 26, "眩晕": 10, "咳喘痰多": 8, "水肿": 10},
        "pair_bonus": [("关节痹痛", "脚肿如脱", 18)],
        "boost_pulses": {"沉": 8, "弦": 8, "数": 8},
        "conflict_pulses": {},
        "conflict_symptoms": {},
        "acupoints": [
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "主穴（筋会）", "reason": "筋会治诸历节关节挛急肿痛"},
            {"id": "acupoint:bl11:大杼", "name": "大杼", "role": "主穴（骨会）", "reason": "骨会强骨止关节变形疼痛"},
            {"id": "acupoint:sp09:阴陵泉", "name": "阴陵泉", "role": "配穴", "reason": "阳陵透阴陵消膝足如脱肿痹"},
        ],
    },
    {
        "atom_id": "atom:wutou",
        "formula_id": "jinkui:乌头汤",
        "name": "乌头汤",
        "polarity": "yang_def_cold",
        "six_meridian": "纯寒痼冷历节 · 疼痛不可屈伸脉沉紧",
        "pathogenesis": "纯寒湿深入骨节筋脉（白蜜煎乌头去毒留效），专攻剧烈冷痛、关节不可屈伸。",
        "symptom_weights": {"关节痹痛": 24, "脚肿如脱": 18, "身冷": 14, "脚冷": 12},
        "pair_bonus": [("关节痹痛", "身冷", 14)],
        "boost_pulses": {"沉": 12, "紧": 14},
        "conflict_pulses": {"洪大": -20, "数": -12},
        "conflict_symptoms": {"高热": -18, "舌黄厚燥": -16},
        "acupoints": [
            {"id": "acupoint:gb34:阳陵泉", "name": "阳陵泉", "role": "主穴", "reason": "舒筋止不可屈伸剧痛"},
            {"id": "acupoint:st36:足三里", "name": "足三里", "role": "配穴（宜温灸）", "reason": "温经通阳壮下肢行痹"},
        ],
    },
    {
        "atom_id": "atom:baiye",
        "formula_id": "jinkui:柏叶汤",
        "name": "柏叶汤",
        "polarity": "yang_def_cold",
        "six_meridian": "虚寒吐血不主热 · 吐血不止心下悸脉微",
        "pathogenesis": "《金匮·惊悸吐衄》明确区分“热伤络泻心汤 vs 虚寒不摄柏叶汤”：干姜艾叶温摄肺胃冲任之血。",
        "symptom_weights": {"失血": 22, "身冷": 12, "脚冷": 10, "心悸": 10},
        "pair_bonus": [("失血", "身冷", 14)],
        "boost_pulses": {"微细": 14, "沉": 10, "迟": 10},
        "conflict_pulses": {"洪大": -20, "数": -14},
        "conflict_symptoms": {"舌黄厚燥": -16, "高热": -18},
        "acupoints": [
            {"id": "acupoint:ren04:关元", "name": "关元", "role": "主穴（宜温灸）", "reason": "温固下焦摄冲任止虚寒吐血"},
            {"id": "acupoint:sp01:隐白", "name": "隐白", "role": "配穴（艾灸）", "reason": "脾主统血急止诸虚寒失血"},
        ],
    },
    {
        "atom_id": "atom:jiaoai",
        "formula_id": "jinkui:胶艾汤",
        "name": "胶艾汤",
        "polarity": "balanced",
        "six_meridian": "妇人冲任虚损下血 · 崩漏不止妊娠下血腹痛",
        "pathogenesis": "《金匮·妊娠》重用生地配川芎当归阿胶艾叶：治冲任不固经水漏下不止、妊娠胎动下血腹痛。",
        "symptom_weights": {"带下崩漏": 24, "失血": 18, "腹痛": 8, "痛经": 8},
        "pair_bonus": [("带下崩漏", "失血", 18)],
        "boost_pulses": {"微细": 10, "涩": 10},
        "conflict_pulses": {"洪大": -14},
        "conflict_symptoms": {"习惯性便秘": -8},
        "acupoints": [
            {"id": "acupoint:sp01:隐白", "name": "隐白", "role": "主穴（灸/针）", "reason": "统脾摄血立止漏下崩中（注：妊娠忌三阴交合谷）"},
            {"id": "acupoint:sp10:血海", "name": "血海", "role": "配穴", "reason": "非孕期调冲任养血止崩"},
        ],
    },
]


# Curated Clinical Symptom -> Formula/Acupoint Differential Notes
CLINICAL_DIFFERENTIAL_NOTES: list[dict[str, Any]] = [
    {
        "trigger_all": ("习惯性便秘", "身冷"),
        "alt_trigger_all": ("大便干", "脚冷"),
        "title": "【关键鉴别】寒虚（阳虚/血虚）大便干 vs 阳明实热燥屎",
        "explanation": "见「习惯性便秘 / 大便干」却同时伴见「身冷、脚冷、脉沉微细」时，切忌见到便干就误投大承气汤等纯苦寒攻下剂！张仲景与汉唐思路指出：大肠传导全赖脾肾阳气蒸腾与津血濡润。阳虚水停则用真武汤温肾气化；血虚水湿挟胞宫痛经则配当归芍药散养血柔肝兼调肠道津微。判断燥屎还是寒秘：一看小便（深黄 vs 清白），二看是否放屁（不放屁、按腹拒按方为承气实证）。",
    },
    {
        "trigger_all": ("但头汗出", "往来寒热"),
        "alt_trigger_all": ("但头汗出", "小便不利"),
        "title": "【核心枢纽】《伤寒》147条「但头汗出 + 小便不利 + 往来寒热」合方推演",
        "explanation": "但头汗出（余处无汗）配小便不利、往来寒热，乃少阳三焦枢机瘀郁（热郁上熏于头）同时下焦/中焦阳虚寒滞（水湿不行），正合《伤寒论》第147条「柴胡桂枝干姜汤」专证；若同时兼身冷、脚冷、眩晕少阴肾阳水寒之底色，即自然构成「真武汤 合 柴胡桂枝干姜汤」双轴并发格局。",
    },
    {
        "trigger_all": ("痛经", "腹痛"),
        "alt_trigger_all": ("痛经", "脚冷"),
        "title": "【妇人调经取穴理法】冲任虚寒血滞 vs 肝脾血虚湿郁 vs 奶水经血逆流",
        "explanation": "痛经兼身冷脚冷、眩晕腹痛，经方层以真武汤温少阴肾水、当归芍药散（或温经汤手掌烦热唇干）调肝脾血室；针灸层以「关元、三阴交、血海、地机」为核心。倪师特别警示：49岁后仍按月准时来经警讯子宫肌瘤；断奶与日常须保大便通畅兼强心，免奶水余浊淤滞胞宫乳房。",
    },
    {
        "trigger_all": ("有汗", "身冷"),
        "alt_trigger_all": ("无汗", "身冷"),
        "title": "【太阳表证门户】表虚桂枝汤 vs 表实麻黄汤 vs 汗漏桂枝加附子汤",
        "explanation": "外感恶寒发热先分有汗无汗：有汗恶风脉浮缓属表虚营卫不和（桂枝汤）；无汗身痛喘咳脉浮紧属表实卫闭（麻黄汤）；若兼项背强几几，有汗用桂枝加葛根汤，无汗用葛根汤；若过汗致漏不止、恶风小便难四肢微急，急改炮附子固表（桂枝加附子汤）；淋家、疮家、衄家、亡血家虽脉浮紧亦严禁麻黄发汗。",
    },
    {
        "trigger_all": ("小便自利", "少腹急结"),
        "alt_trigger_all": ("小便不利", "口渴"),
        "title": "【蓄水 vs 蓄血铁律】五苓散（小便不利口渴）vs 桃核承气/抵当汤（小便自利如狂）",
        "explanation": "同在太阳下焦膀胱少腹：若口渴欲饮、水入即吐、小便不利、脉浮，属膀胱气化停水（五苓散）；若少腹急结硬满、其人如狂发狂、反见小便自利或大便黑易解，乃瘀血留滞血室下焦（轻用桃核承气汤，重久发狂用抵当汤），绝不可只以利尿伤津治蓄血。",
    },
    {
        "trigger_all": ("心下硬痛",),
        "alt_trigger_all": ("心下痞",),
        "title": "【结胸 vs 痞证分界】大陷胸汤（石硬剧痛）vs 小陷胸汤（按之痛）vs 泻心汤辈（按之濡满）",
        "explanation": "同居心下胃脘：从心下至少腹硬满拒按如石硬（大陷胸汤，脉沉紧）；正在心下、按之方痛、呕酸脉浮滑（小陷胸汤，常用于胆石/胃酸灼食道假心痛）；若但满而不痛、按之濡软（诸泻心汤：半夏泻心寒热错杂呕利肠鸣、大黄黄连泻心纯热、附子泻心心痞兼恶寒汗出）。藏结则似结胸而饮食如故、舌白苔滑、绝无热象，误下则死。",
    },
    {
        "trigger_all": ("心悸",),
        "alt_trigger_all": ("腹痛喜按",),
        "title": "【仲景先补虚铁律】表虚先建中（小建中汤）· 脉结代先复脉（炙甘草汤）",
        "explanation": "人纪临证第一大禁忌“先补虚”：凡见病人心悸脉结代、或表虚里急腹痛喜温按、手足烦热梦失精，纵有他经兼症，未可先攻伐或发汗，当先用「小建中汤」实脾营卫或「炙甘草汤」补益心气心血，待脉气连续胃口恢复后方图他治。",
    },
    {
        "trigger_all": ("高热", "喜冷饮"),
        "alt_trigger_all": ("腹满拒按", "大便干"),
        "title": "【阳明双分流】白虎气分清热 vs 三承气腑实攻下（先辨屁与小便）",
        "explanation": "同见阳明壮热大渴：脉洪大、大汗喜冰水、腹未满拒按、尚能通便 → 纯属气分热（白虎汤/白虎加人参汤）；必须同时具「腹满痛拒按、多日大便闭且不放屁、小便深黄、舌苔黄厚干」始属腑实燥屎（调胃、小承气、大承气依痞满燥实四证权衡；若见双足冰冷、小便清白或舌白厚湿，虽数日不大便亦严禁妄下承气）。",
    },
    {
        "trigger_all": ("下利清谷", "脚冷"),
        "alt_trigger_all": ("下利清谷", "小便深黄"),
        "title": "【寒热下利五辨】真寒四逆白通 vs 热利葛根芩连/白头翁 vs 热结旁流小承气",
        "explanation": "腹泻稀水绝不可一概止泻或一律用温药！清谷完谷、不渴、双足冰冷、小便清白、脉微细 → 太少虚寒（理中/四逆/白通/桃花汤）；肛门灼热、便臭粘滞、小便深黄 → 协热或热毒（葛根芩连/白头翁汤）；若排纯清水臭秽却同时见腹部硬满拒按、小便深黄，乃胃有燥屎梗阻之「热结旁流」，宜小承气汤急通其实。",
    },
    {
        "trigger_all": ("黄疸",),
        "alt_trigger_all": ("小便深黄", "腹满拒按"),
        "title": "【金匮黄瘅五辨】茵陈蒿实热 vs 茵陈五苓湿重 vs 栀子大黄/硝石矾石/桂枝加黄芪",
        "explanation": "身目发黄先辨湿热比例与表里：大便闭腹满、身黄鲜亮如橘、小便深黄不利 → 茵陈蒿汤；湿重于热、伴胆石肋胀小便难 → 茵陈五苓散；心中懊憹酒疸 → 栀子大黄汤；额上黑手足心热薄暮发之女劳疸 → 硝石矾石散；兼表虚恶风汗出 → 桂枝加黄芪汤（配穴首选至阳、胆俞、阳陵泉）。",
    },
    {
        "trigger_all": ("胸痹",),
        "alt_trigger_all": ("心痛彻背",),
        "title": "【胸痹心痛五梯次】栝蒌薤白谱系 vs 乌头赤石脂丸 vs 假心痛（胃酸灼食道）",
        "explanation": "经方论心胸痛讲究“阳微阴弦”痰瘀轻重：喘息咳唾胸背痛 → 栝蒌薤白白酒汤；彻背痛甚不能平卧 → 加半夏汤；气塞短气 → 橘枳姜汤；心痛彻背、背痛彻心、四肢厥逆寒凝闭脱 → 乌头赤石脂丸。倪师临床加分：持续刺痛+耳心点压痛属冠脉瘀血（配红花、重用白芍配炮附）；若胸闷兼频频吐酸水灼热，实为胃酸反流之假心脏病（旋覆代赭合小陷胸）；第五椎压痛主瓣膜心律问题；急危见无名指关冲触“碎玻璃渣感”兼剧痛须即刻就医并参关元少府急法。",
    },
    {
        "trigger_all": ("咳喘痰多",),
        "alt_trigger_all": ("水鸡声",),
        "title": "【肺系咳喘寒热七路】小青龙 / 射干麻黄 / 麻杏石甘 / 麦门冬 / 葶苈苇茎",
        "explanation": "外感咳喘必看寒热舌苔与痰色：恶寒无汗白泡沫清痰 → 小青龙汤；喉中水鸡声哮喘 → 射干麻黄汤；汗出喘急、口渴苔黄痰粘 → 麻杏甘石汤；干咳咽干、大逆上气舌红少苔 → 麦门冬汤；实满喘不能卧欲成肺痈 → 葶苈大枣泻肺汤合千金苇茎汤；若重症日久见白泡沫痰且苔反白厚湿兼腹泻一日多次，谨依苔辨里寒阴实。",
    },
    {
        "trigger_all": ("右下腹痛",),
        "title": "【肠痈（盲肠炎）两期生死分界】未成脓（大黄牡丹）vs 已成脓（薏苡附子败酱）",
        "explanation": "右下腹阑尾点压痛必须先用掌探温度与腹皮软硬辨是否穿孔：未成脓（痛剧拒按、皮急如肿）→ 大黄牡丹汤（严禁加甘草、枳实、厚朴）配针奇穴阑尾穴，小便淡黄停药；若已成脓或体虚（按之濡、身甲错）→ 薏苡附子败酱散扶正排脓，不可久煎；若忽止剧痛而腹发烫一动即疼属破溃腹膜炎危候（古用肘尖重灸并急送医院）。",
    },
    {
        "trigger_all": ("关节痹痛",),
        "alt_trigger_all": ("脚肿如脱",),
        "title": "【风湿历节三梯次】表湿（桂枝附子/防己黄芪）vs 寒热错杂（桂枝芍药知母）vs 纯寒痛（乌头汤）",
        "explanation": "肢节痹痛分寒热虚实：表虚汗多身重水湿 → 防己黄芪汤；风湿相搏身体疼烦不能转侧、大便坚小便利 → 桂枝附子/白术附子/甘草附子汤；肢节肿大、脚肿如脱、温温欲吐上热下寒 → 桂枝芍药知母汤；纯寒深痼关节剧痛不可屈伸脉沉紧 → 白蜜煎乌头汤。",
    },
    {
        "trigger_all": ("失血",),
        "title": "【金匮血证寒热先便分水岭】远血（黄土汤）· 近血（赤豆当归）· 热泻心 vs 寒柏叶",
        "explanation": "大便先便后血且色黯疲乏（胃十二指肠等脾不统远血）→ 黄土汤（灶心黄土配熟地附子阿胶黄芩）；先血后便色鲜热痛（大肠直肠痔疮近血）→ 赤小豆当归散（或配槐花）；上部吐衄分二极：热迫阳亢面赤心烦舌黄 → 三黄泻心汤；虚寒不摄脉微手足冷 → 柏叶汤。牢记《内经》「血无止法」，勿纯用寒凉涩止留瘀。",
    },
    {
        "trigger_all": ("心烦失眠", "舌红少苔"),
        "alt_trigger_all": ("1-3点醒", "心烦失眠"),
        "title": "【失眠不寐三鉴与夜半醒时辰】黄连阿胶（阴虚心肾）vs 酸枣仁（肝血）vs 半夏秫米/经络醒点",
        "explanation": "彻夜难眠必分虚实寒热与醒时规律：舌红少苔、手心烦热、夜烦躁不得卧 → 少阴阴虚水火不交（黄连阿胶汤配鸡子黄）；虚劳夜梦纷纭心悸酸乏 → 酸枣仁汤养肝血；半夜1-3点固定醒属肝胆枢机或阴实警讯；3-5点固定醒属肺气郁阻。日常常按双耳与照海（夜痫失眠核心穴）、神门助阳入阴。",
    },
]

# Apply modular clinical differentiation enhancements and explicit legacy polarities
for _atom in PATTERN_ATOMS:
    if not _atom.get("polarity") and _atom["atom_id"] in LEGACY_ATOM_POLARITIES:
        _atom["polarity"] = LEGACY_ATOM_POLARITIES[_atom["atom_id"]]

INQUIRY_PILLS.extend(EXTRA_INQUIRY_PILLS)
PRESET_CASES.extend(EXTRA_PRESET_CASES)
SYMPTOM_CANONICAL_RULES.extend(EXTRA_SYMPTOM_CANONICAL_RULES)
PATTERN_ATOMS.extend(EXTRA_PATTERN_ATOMS)
CLINICAL_DIFFERENTIAL_NOTES.extend(EXTRA_DIFFERENTIAL_NOTES)


@lru_cache(maxsize=1)
def _formulas_by_id() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for fn in ("formulas.json", "jinkui_formulas.json"):
        for f in json.loads((DATA_DIR / fn).read_text(encoding="utf-8")):
            out[f["id"]] = f
    return out


@lru_cache(maxsize=1)
def _curated_batches_map() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    cb_dir = DATA_DIR / "curated_batches"
    if cb_dir.exists():
        for p in sorted(cb_dir.glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                out.update(data)
    return out


@lru_cache(maxsize=1)
def _modifications_index() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    path = DATA_DIR / "formula_modifications.json"
    items = json.loads(path.read_text(encoding="utf-8")).get("items", []) if path.exists() else []
    by_fid: dict[str, list[dict[str, Any]]] = {}
    for m in items:
        bfid = m.get("base_formula_id")
        if bfid:
            by_fid.setdefault(bfid, []).append(m)
    return items, by_fid


@lru_cache(maxsize=1)
def _fa_links_by_formula() -> dict[str, list[dict[str, Any]]]:
    path = DATA_DIR / "formula_acupuncture_links.json"
    items = json.loads(path.read_text(encoding="utf-8")).get("items", []) if path.exists() else []
    by_fid: dict[str, list[dict[str, Any]]] = {}
    for lk in items:
        fid = lk.get("formula_id")
        if fid:
            by_fid.setdefault(fid, []).append(lk)
    return by_fid


@lru_cache(maxsize=1)
def _acupoints_by_id() -> dict[str, dict[str, Any]]:
    path = DATA_DIR / "acupuncture" / "acupoints.json"
    items = json.loads(path.read_text(encoding="utf-8")).get("items", []) if path.exists() else []
    return {pt["id"]: pt for pt in items}


def _extract_query_terms(q: str, canonical_symptoms: list[str]) -> list[str]:
    """Combine normalized symptom tokens, space/comma clauses, and authentic TCM synonyms without noisy bigrams."""
    nq = norm_simp(q)
    nq_syn = nq.replace("但头汗出", " ").replace("头汗出", " ").replace("往来寒热", " ")
    raw = [t.strip() for t in re.split(r"[\s,，、；;：:。！？!?\-\/]+", nq) if len(t.strip()) >= 2]
    terms: list[str] = list(dict.fromkeys(canonical_symptoms + raw))
    seen = set(terms)
    for grp in formula_diagnose.SYNONYM_GROUPS:
        norm_grp = [norm_simp(g) for g in grp]
        if any(g in nq_syn or any(g == t for t in terms) for g in norm_grp):
            for g in norm_grp:
                if g and g not in seen:
                    seen.add(g)
                    terms.append(g)
    # Remove overly broad 1-char or non-clinical tokens if any crept in
    return [t for t in terms if len(t) >= 2][:28]


def _is_clean_symptom_cue(cue: str, formula_name: str = "") -> bool:
    """Reject classical clause fragments, formula titles, and overly long phrases from clickable cue pills."""
    c = re.sub(r"[（）()\s]", "", cue or "").strip()
    if not (2 <= len(c) <= 6):
        return False
    if formula_name and (c in formula_name or norm_simp(formula_name) in norm_simp(c)):
        return False
    bad_markers = ("，", "。", "、", "：", "；", "而", "之", "者", "得之", "假令", "此远", "二三日", "以上", "不瘥", "服后", "汤", "散", "丸", "方")
    return not any(m in c for m in bad_markers)


def _search_all_jingfang_clues(
    cleaned_q: str,
    canonical_symptoms: list[str],
    top_atom_fids: list[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Score ALL 299 formulas using curated symptoms, Ni why rationale, overview, and 108 modifications."""
    fmap = _formulas_by_id()
    cbmap = _curated_batches_map()
    _, mods_by_fid = _modifications_index()
    fa_by_fid = _fa_links_by_formula()
    pt_map = _acupoints_by_id()
    terms = _extract_query_terms(cleaned_q, canonical_symptoms)
    nq = norm_simp(cleaned_q)

    scored: list[tuple[int, dict[str, Any]]] = []
    for fid, fobj in fmap.items():
        fname = fobj.get("name", "")
        cb = cbmap.get(fid, {})
        cb_syms = cb.get("symptoms") if isinstance(cb.get("symptoms"), list) else []
        why_txt = norm_simp(cb.get("why") or "")
        ind_txt = norm_simp(fobj.get("indication") or "")
        ov_paras = ""
        if isinstance(cb.get("overview"), dict):
            ov_paras = " ".join(cb["overview"].get("paragraphs", []))
        ov_txt = norm_simp(ov_paras)
        six_m = fobj.get("six_meridian") or fobj.get("chapter") or cb.get("six_channel") or ""

        sc = 0
        matched_terms: list[str] = []
        supporting_symptoms: list[str] = []
        unselected_cues: list[str] = []

        fname_n = norm_simp(fname)
        if fname_n and fname_n in nq:
            sc += 55
            matched_terms.append(fname)

        for sym_entry in cb_syms:
            if not isinstance(sym_entry, dict):
                continue
            sname = (sym_entry.get("name") or "").strip()
            sname_n = norm_simp(sname)
            sexp_n = norm_simp(sym_entry.get("explanation") or "")
            hit_sym = False
            for t in terms:
                if len(t) < 2:
                    continue
                if t in sname_n or sname_n in t:
                    sc += 22
                    hit_sym = True
                    if t not in matched_terms:
                        matched_terms.append(t)
                elif t in sexp_n:
                    sc += 8
                    hit_sym = True
                    if t not in matched_terms:
                        matched_terms.append(t)
            if hit_sym and sname and sname not in supporting_symptoms:
                supporting_symptoms.append(sname)
            elif sname and sname not in unselected_cues and _is_clean_symptom_cue(sname, fname):
                unselected_cues.append(sname)

        for t in terms:
            if len(t) < 2:
                continue
            in_ind = t in ind_txt
            in_why = t in why_txt
            in_ov = t in ov_txt
            if in_ind:
                sc += 14
            if in_why:
                sc += 10
            if in_ov and not in_why:
                sc += 5
            if (in_ind or in_why or in_ov) and t not in matched_terms:
                matched_terms.append(t)

        # Match 108 modifications connected to this base formula
        f_mods = mods_by_fid.get(fid, [])
        relevant_mods: list[dict[str, Any]] = []
        for m in f_mods:
            cond_n = norm_simp(m.get("condition", ""))
            rat_n = norm_simp(m.get("rationale", ""))
            mod_hit = any(t in cond_n or t in rat_n for t in terms if len(t) >= 2)
            if mod_hit:
                sc += 10
            if mod_hit or fid in top_atom_fids:
                relevant_mods.append(
                    {
                        "id": m["id"],
                        "condition": m.get("condition", ""),
                        "changes_summary": (m.get("changes") or {}).get("summary", ""),
                        "target_formula_id": m.get("target_formula_id", ""),
                        "target_formula_name": m.get("target_formula_name", ""),
                        "rationale": m.get("rationale", ""),
                        "boundary": m.get("boundary", ""),
                        "matched": mod_hit,
                    }
                )
        relevant_mods.sort(key=lambda x: (not x["matched"], x["id"]))

        if fid in top_atom_fids:
            idx_boost = 150 - top_atom_fids.index(fid) * 20
            sc += idx_boost

        if sc < 10:
            continue

        links = []
        for lk in fa_by_fid.get(fid, [])[:4]:
            tid = lk.get("target_id", "")
            pt_obj = pt_map.get(tid, {})
            links.append(
                {
                    "id": tid,
                    "name": lk.get("target_name") or pt_obj.get("canonical_name", tid),
                    "relation_kind": lk.get("relation_kind", ""),
                    "quote": lk.get("quote", ""),
                    "note": lk.get("note", ""),
                }
            )

        herbs = _herb_names_of(fobj)
        scored.append(
            (
                sc,
                {
                    "formula_id": fid,
                    "name": fname,
                    "book": fobj.get("book", ""),
                    "six_meridian": six_m,
                    "score": sc,
                    "in_compound": fid in top_atom_fids,
                    "matched_terms": matched_terms[:6],
                    "supporting_symptoms": supporting_symptoms[:6],
                    "unselected_cues": unselected_cues[:4],
                    "why_summary": (cb.get("why") or fobj.get("indication") or "")[:180],
                    "ingredients_summary": "、".join(herbs[:8]),
                    "decoction": (cb.get("usage_plain") or fobj.get("decoction_method") or fobj.get("decoction") or "")[:140],
                    "modifications": relevant_mods[:3],
                    "linked_acupoints": links,
                },
            )
        )

    scored.sort(key=lambda x: (-x[0], not x[1]["in_compound"], x[1]["formula_id"]))
    deduped: list[dict[str, Any]] = []
    by_canon_idx: dict[str, int] = {}
    for _, item in scored:
        canon_name = canonical_formula_name(item["name"])
        if canon_name in by_canon_idx:
            prev = deduped[by_canon_idx[canon_name]]
            other_book = item.get("book") or ""
            if other_book and other_book != prev.get("book"):
                also = prev.setdefault("also_in_books", [])
                if other_book not in also:
                    also.append(other_book)
            continue
        by_canon_idx[canon_name] = len(deduped)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def _build_followup_questions(
    symptoms: list[str],
    pulses: list[str],
    top_clues: list[dict[str, Any]],
    cond_patterns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Suggest high-discrimination clinical follow-up symptoms & pulses (学习问诊 · 鉴别追问)."""
    probes: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    sym_set = set(symptoms)
    pulse_set = set(pulses)

    def add_probe(label: str, token: str = "", pulse_id: str = "", why: str = "", kind: str = "symptom") -> None:
        tok_parts = {p for p in token.split() if p}
        if not label or label in sym_set or token in sym_set or (tok_parts and tok_parts.issubset(sym_set)) or (pulse_id and pulse_id in pulse_set):
            return
        if label in seen_labels:
            return
        seen_labels.add(label)
        probes.append({"label": label, "token": token, "pulse_id": pulse_id, "why": why, "kind": kind})

    # Structured differential probes based on present symptoms
    if sym_set & {"发热", "恶寒", "身冷"}:
        if "无汗" not in sym_set:
            add_probe("是否无汗", token="无汗", why="太阳伤寒表实（麻黄/葛根）vs 中风自汗（桂枝）")
        if "有汗" not in sym_set and "但头汗出" not in sym_set:
            add_probe("是否但头汗出", token="但头汗出", why="少阳三焦水热互结（柴胡桂枝干姜汤专症）")
        if "往来寒热" not in sym_set:
            add_probe("是否往来寒热", token="往来寒热", why="区分邪仍在太阳 vs 己入少阳半表半里")

    if sym_set & {"身冷", "脚冷", "习惯性便秘", "大便干", "腹痛", "痛经"}:
        add_probe("是否脉沉", pulse_id="沉", why="判断病在表或在里阴虚寒水停", kind="pulse")
        add_probe("是否脉微细", pulse_id="微细", why="少阴虚寒核心脉象，忌苦寒泻下", kind="pulse")
        add_probe("是否小便不利", token="小便不利", why="辨水气停蓄（真武 / 五苓 / 柴胡桂枝干姜）")
        add_probe("是否但头汗出", token="但头汗出", why="若寒热兼但头汗出则转合柴胡桂枝干姜汤")
        add_probe("是否脉洪大", pulse_id="洪大", why="若便干兼洪大数实则属阳明热实而非寒秘", kind="pulse")

    if sym_set & {"头痛", "偏头痛", "前额痛", "眩晕"}:
        add_probe("是否项背强痛", token="项背强", why="辨太阳/督脉葛根汤及后溪申脉证")
        add_probe("是否干呕吐涎", token="呕吐", why="辨厥阴吴茱萸汤巅顶痛 vs 少阳呕")
        add_probe("是否口渴小便少", token="口渴 小便不利", why="辨蓄水证头晕口渴（五苓散）")

    if sym_set & {"胸痹", "胸痛", "心悸", "咳喘痰多", "心下痞"}:
        add_probe("是否心痛彻背", token="心痛彻背", why="辨胸阳痹阻痰饮偏重（栝蒌薤白半夏/乌头赤石脂）")
        add_probe("是否口苦咽干", token="口苦 咽干", why="辨少阳柴胡或半夏泻心寒热错杂")
        add_probe("是否脉弦", pulse_id="弦", why="阳微阴弦或少阳水饮之核心脉象", kind="pulse")

    if "鼻症" in sym_set:
        add_probe("是否恶寒无汗", token="恶寒 无汗", why="鼻症兼恶寒无汗常由肺表受寒闭郁（可参葛根汤/麻黄/小青龙）")
        add_probe("是否稀清涕喷嚏", token="咳喘痰多", why="肺寒水饮停蓄致鼻流清涕、喷嚏不止（小青龙汤证）")
        add_probe("是否口渴黄涕", token="口渴", why="辨肺寒水饮 vs 鼻窦郁热")

    # Add top unselected symptom cues from top 299-formula matches & acupuncture patterns
    for clue in top_clues[:3]:
        for cue in clue.get("unselected_cues", [])[:2]:
            clean_cue = re.sub(r"[（）()\s]", "", cue).strip()
            if _is_clean_symptom_cue(clean_cue, clue.get("name", "")):
                add_probe(f"兼见{clean_cue}?", token=clean_cue, why=f"核对「{clue['name']}」核心主症")
    for cp in cond_patterns[:2]:
        for s in cp.get("symptoms", [])[:3]:
            cs = re.sub(r"[（）()\s]", "", s).strip()
            if _is_clean_symptom_cue(cs):
                add_probe(f"兼见{cs}?", token=cs, why=f"核对《针灸》「{cp['pattern_name'][:14]}」分型")

    return probes[:10]


def _extract_symptoms(q: str, pulses: list[str] | None = None) -> list[str]:
    nq = norm_simp(q)
    pulse_set = set(pulses or ())
    # Prevent negated, nocturnal, or localized phrases from triggering opposite positive axes
    nq_no_head_sweat = (
        nq.replace("但头汗出", " ")
        .replace("只有头出汗", " ")
        .replace("头汗出", " ")
        .replace("骨蒸盗汗", " ")
        .replace("潮热盗汗", " ")
        .replace("盗汗", " ")
        .replace("手足心汗", " ")
        .replace("无汗", " ")
        .replace("不出汗", " ")
        .replace("没怎么出汗", " ")
        .replace("没出汗", " ")
    )
    nq_no_thirst = nq.replace("口不渴", " ").replace("不欲饮", " ").replace("不渴", " ").replace("渴不敢饮", " ")
    nq_no_urine_block = nq.replace("小便自利", " ").replace("小便清长", " ").replace("小便利", " ").replace("小便清白", " ")
    nq_no_dry_stool = nq.replace("大便不干", " ").replace("大便顺畅", " ")
    nq_no_clear_water = nq.replace("自利清水", " ").replace("纯利清水", " ").replace("热结旁流", " ")
    nq_no_xu_chuan = nq.replace("虚喘", " ").replace("不抬肩", " ").replace("无抬肩", " ")
    if ("虚喘" in nq or "不抬肩" in nq) and not any(k in nq for k in ("痰鸣", "水鸡声", "黄痰")):
        nq_no_xu_chuan = nq_no_xu_chuan.replace("喘", " ")
    nq_no_mouth_mid = nq.replace("口中和", " ")

    # Disambiguate 四肢厥冷 / 厥逆 into 热厥 (heat excess trapping yang) vs 脚冷 (yang-def cold)
    has_cold_collapse = (
        any(k in nq for k in ("下利清谷", "自利清谷", "小便清白", "戴阳", "格阳", "身反不恶寒", "脉微", "微细", "舌白厚", "舌淡胖"))
        or "微细" in pulse_set
        or "迟" in pulse_set
    )
    has_heat_jue_signal = (
        bool({"滑", "数", "洪大"} & pulse_set)
        or any(k in nq for k in ("热厥", "热深厥深", "脉滑", "脉数", "洪大", "高热", "喜冷饮", "小便深黄", "尿黄", "腹满拒按", "腹胀痛拒按", "黄厚"))
    )
    is_heat_jue = ("四肢厥冷" in nq or "厥逆" in nq) and has_heat_jue_signal and not has_cold_collapse
    nq_cold_feet = nq.replace("四肢厥冷", " ").replace("厥逆", " ") if is_heat_jue else nq

    scoped_haystacks = {
        "有汗": nq_no_head_sweat,
        "口渴": nq_no_thirst,
        "大渴": nq_no_thirst,
        "口苦": nq_no_mouth_mid,
        "小便不利": nq_no_urine_block,
        "大便干": nq_no_dry_stool,
        "下利清谷": nq_no_clear_water,
        "脚冷": nq_cold_feet,
        "咳喘痰多": nq_no_xu_chuan,
    }
    found: list[str] = []
    seen_canon: set[str] = set()
    for canon, aliases in SYMPTOM_CANONICAL_RULES:
        haystack = scoped_haystacks.get(canon, nq)
        if any(a in haystack for a in aliases) and canon not in seen_canon:
            found.append(canon)
            seen_canon.add(canon)
    if is_heat_jue and "热厥" not in seen_canon:
        found.append("热厥")
        seen_canon.add("热厥")
    if "口中和" in seen_canon and "口不渴" not in seen_canon:
        found.append("口不渴")
        seen_canon.add("口不渴")
    return found


def _extract_tongues(q: str) -> list[str]:
    found_syms = set(_extract_symptoms(q))
    return [t["id"] for t in TONGUE_OPTIONS if t["id"] in found_syms]


def _are_polarities_compatible(p1: str, p2: str) -> bool:
    """Prevent thermally antagonistic formulas (e.g. pure heat-purging vs yang-collapse) from auto-combining."""
    s1 = p1 or "balanced"
    s2 = p2 or "balanced"
    pair = {s1, s2}
    if pair == {"heat_excess", "yang_def_cold"}:
        return False
    if pair == {"warm_exterior", "yin_def_heat"}:
        return False
    return True


def _build_plain_triage_summary(
    symptoms: list[str],
    pulses: list[str],
    tongues: list[str],
    active: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a plain-language crossroads guide inspired by beginner-oriented Ni Haixia triage."""
    sym_set = set(symptoms)
    crossroads: list[dict[str, str]] = []
    if sym_set & {"发热", "身冷", "有汗", "无汗"}:
        crossroads.append({
            "question": "外感先分「有汗/无汗」与「但头汗出」",
            "why": "有汗恶风偏太阳中风（桂枝汤），无汗身痛喘偏太阳伤寒（麻黄汤），若仅头出汗配往来寒热与小便不利则转少阳枢机（柴胡桂枝干姜汤）。",
        })
    if sym_set & {"习惯性便秘", "大便干", "下利清谷", "腹痛", "腹满拒按", "腹痛喜按"}:
        crossroads.append({
            "question": "肠胃二便先辨「小便深黄/清白」与「喜按/拒按」",
            "why": "便秘若见双足冰冷、小便清白或喜温按属阳虚寒秘/血虚秘，禁投承气；下利见腹部硬满拒按、小便深黄亦须警惕「热结旁流」。",
        })
    if sym_set & {"脚冷", "心悸", "胸痹", "心痛彻背", "失血"}:
        crossroads.append({
            "question": "里证先查「双足温凉、舌象与是否须先补虚」",
            "why": "心悸脉结代或虚劳腹急痛喜按须「先补虚」（炙甘草/小建中）；胸痛剧烈或大口呕血属急症红线，须先就医而后再参经典学习。",
        })
    if not crossroads and active:
        crossroads.append({
            "question": "核对「舌象 + 小便色 + 双足温凉 + 脉象」",
            "why": "经方用药先求寒热表里大方向不错：手足转温、大便通、半夜胃回饥饿即正向；若见相反寒热则立即停止原向推演。",
        })

    headline_parts = []
    if active:
        headline_parts.append(f"当前优先偏向【{active[0]['name']}】方向（{active[0]['six_meridian']}）")
    if excluded:
        headline_parts.append(f"已依据寒热脉症自动排误排除「{'、'.join(e['name'] for e in excluded[:2])}」")
    return {
        "headline": "；".join(headline_parts) if headline_parts else "已进入四诊分型研习视角，请结合下方临床追问继续缩小辨证分水岭。",
        "crossroads": crossroads[:3],
        "tongue_notes": [f"{t['label']}：{t['note']}" for t in TONGUE_OPTIONS if t["id"] in tongues],
    }


def _build_decoction_and_recovery_guide(
    active: list[dict[str, Any]],
    symptoms: list[str],
    pulses: list[str],
    acup_pts: list[dict[str, str]],
) -> list[str]:
    """Surface Ni Haixia processing, decoction, forbidden, and six-health recovery notes."""
    notes: list[str] = []
    all_herbs = {h for a in active[:3] for h in a.get("herbs", [])}
    names = {a["name"] for a in active[:3]}

    if "附子" in all_herbs:
        notes.append("【生附子 vs 炮附子炮制】破阴回阳救少阴厥逆（四逆/真武/白通）须用生附子（棉布包、9碗水慢熬成3碗足2小时去乌头碱毒）；固表止漏汗（桂枝加附子汤）或温脾肾多用炮附子。")
    if "乌头" in all_herbs:
        notes.append("【乌头白蜜同煎与反药】大乌头煎/乌头汤必先用白蜜熬制减毒且中病即止（不可一日再服）；乌头附子传统反半夏、瓜蒌、贝母、白蔹、白及。")
    if "麻黄" in all_herbs and "麻黄汤" in names | ({"大青龙汤", "射干麻黄汤", "越婢汤", "麻黄杏仁甘草石膏汤"} & names):
        notes.append("【麻黄先煮去沫】含麻黄发汗散邪诸方传统要求先煎麻黄减二升去上沫免令人烦；表虚多汗、咽燥、失血、淋家严禁误发汗。")
    if "大黄" in all_herbs or "芒硝" in all_herbs:
        notes.append("【泻下剂煎序与中病即止】含大黄芒硝之承气/大陷胸/大黄牡丹汤须审大便闭且不放屁、小便深黄方可用；芒硝后冲、大黄微煎以保留峻下之力，得快利即停。")
    if "黄土汤" in names or "灶心土" in all_herbs:
        notes.append("【灶心黄土与当归保油】黄土汤治先便后血远血，传统必取烧柴老土灶底焦黄土；方中当归宜低温保存油脂方能兼顾润便。")
    if acup_pts:
        notes.append("【针灸操作与禁忌红线】热症宜针泄或点刺放血、寒症宜艾温灸；第14椎以上背俞一律斜刺防伤脏；孕期禁合谷三阴交（转胎位只灸至阴）；胃出血禁足三里；针后72小时戒酒、辣椒、麻油。")
    notes.append("【人纪临床停药与向愈六大金标准】①双足手掌持续温热而头面清凉；②一觉天明（1-3点肝/3-5点肺经不再固定惊醒）；③重病突觉半夜饥饿欲食（胃气回）；④苔由光绛渐生淡白薄苔；⑤运动微汗；⑥大便每日通畅、小便淡黄有力。")
    return notes


_NON_PULSE_COMPOUNDS_RE = re.compile(
    r"(?:浮肿|虚浮|浮阳|浮火|轻浮|沉重|昏沉|沉闷|沉滞|下沉|数日|数天|数月|数年|数次|数回|数十|"
    r"微寒|微热|微汗|微微|轻微|细辛|细小|细碎|缓慢|缓解|舒缓|紧张|紧缩|拘紧|滑胎|滑泻|滑利|滑腻|"
    r"迟滞|延迟|迟缓|大小|大便|大渴|大热|大汗|口涩|小便涩|涩滞)"
)
_Q_PULSE_CLAUSE_RE = re.compile(
    r"(?:寸|关|尺|两寸|两尺)?脉(?:象|来|见|转|亦|兼|仍|似)?[：:是为]*小?"
    r"(?:洪大|结代|微细|浮|沉|迟|数|滑|涩|弦|紧|缓|微|细|濡|弱|短|促)"
    r"(?:[、\s和兼与亦偏略稍而]{0,2}(?:洪大|结代|微细|浮|沉|迟|数|滑|涩|弦|紧|缓|微|细|濡|弱|短|促)){0,4}"
    r"|(?:洪大|结代|微细|浮|沉|迟|数|滑|涩|弦|紧|缓){1,3}脉"
)


def _extract_pulses(pulse_str: str, q: str) -> list[str]:
    pulse_norm = norm_simp(pulse_str or "")
    q_clean = _NON_PULSE_COMPOUNDS_RE.sub(" ", norm_simp(q or ""))
    q_pulse_clauses = " ".join(_Q_PULSE_CLAUSE_RE.findall(q_clean))
    combined = f"{pulse_norm} {q_pulse_clauses}".strip()
    selected: list[str] = []
    for p in PULSE_OPTIONS:
        pid = p["id"]
        if pid in combined or (pid == "微细" and ("微" in combined or "细" in combined)):
            selected.append(pid)
    return list(dict.fromkeys(selected))


def _herb_names_of(formula: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for ing in formula.get("ingredients", []):
        if isinstance(ing, dict):
            nm = ing.get("herb") or ing.get("name") or ""
        else:
            nm = str(ing)
        nm = re.sub(r"（.*?）", "", nm).strip()
        if nm:
            names.append(nm)
    return names


def _build_regimen_entry(
    f1: dict[str, Any],
    f2: dict[str, Any] | None,
    symptoms: list[str],
    *,
    regimen_kind: str = "primary",
    herb_conflict: dict[str, Any] | None = None,
    single_note: str = "",
) -> dict[str, Any]:
    """Construct a single-formula or compatible two-formula regimen entry cleanly."""
    if f2 is None:
        return {
            "regimen_kind": regimen_kind,
            "is_compound": False,
            "title": (f"备选参考单方：{f1['name']}" if regimen_kind == "alternative" else f"单方专治统摄：{f1['name']}"),
            "formula_ids": [f1["formula_id"]],
            "formula_names": [f1["name"]],
            "axis_roles": [f"【专方主轴】{f1['name']}（{f1['six_meridian']}）：统括「{'、'.join(f1['matched_symptoms'])}」"],
            "covered_symptoms": list(f1["matched_symptoms"]),
            "uncovered_symptoms": [s for s in symptoms if s not in set(f1["matched_symptoms"])],
            "overlap_herbs": [],
            "herb_conflict_alerts": [],
            "overlap_note": single_note or "目前症状已由单首核心经方完全覆盖（或兼顾避免同类/十八反十九畏互斥），优先考虑专方纯正取效，无须机械合方。",
        }

    covered = set(f1["matched_symptoms"]) | set(f2["matched_symptoms"])
    overlap_herbs = sorted(set(f1.get("herbs", [])) & set(f2.get("herbs", [])))
    hc_alerts = (herb_conflict or {}).get("alerts", [])
    note_parts: list[str] = []
    if hc_alerts:
        note_parts.append("【配伍警戒】" + "；".join(hc_alerts) + "。")
    if overlap_herbs:
        note_parts.append(
            f"两方共有重叠药味：{'、'.join(overlap_herbs)}（传统合方需依轻重统调克数并分明姜/干姜及制附先后煎法，不可机械叠加双倍剂量）。"
        )
    elif not hc_alerts:
        note_parts.append("两方药味分工各专，可据证候主次斟酌主从合参。")

    prefix = "备选对照合方" if regimen_kind == "alternative" else "主推合方"
    return {
        "regimen_kind": regimen_kind,
        "is_compound": True,
        "title": f"{prefix}：{f1['name']} 合 {f2['name']}",
        "formula_ids": [f1["formula_id"], f2["formula_id"]],
        "formula_names": [f1["name"], f2["name"]],
        "axis_roles": [
            f"【主轴一】{f1['name']}（{f1['six_meridian']}）：主司「{'、'.join(f1['matched_symptoms'])}」",
            f"【主轴二】{f2['name']}（{f2['six_meridian']}）：兼顾「{'、'.join(f2['matched_symptoms'])}」",
        ],
        "covered_symptoms": [s for s in symptoms if s in covered],
        "uncovered_symptoms": [s for s in symptoms if s not in covered],
        "overlap_herbs": overlap_herbs,
        "herb_conflict_alerts": hc_alerts,
        "overlap_note": " ".join(note_parts),
    }


def compose_differentiation(q: str = "", pulse: str = "") -> dict[str, Any]:
    """Perform clinical symptom + pulse breakdown -> dynamic single/compound Jingfang + Acupoints."""
    cleaned_q = (q or "").strip()
    cleaned_pulse = (pulse or "").strip()
    positive_q, negated_terms = strip_clinical_negations(cleaned_q)
    safety = _detect_safety_boundary(f"{cleaned_q} {cleaned_pulse}")
    pulses = _extract_pulses(cleaned_pulse, positive_q)
    symptoms = _extract_symptoms(positive_q, pulses=pulses)
    tongues = _extract_tongues(positive_q)
    fmap = _formulas_by_id()

    if not cleaned_q and not cleaned_pulse:
        return {
            "query": "",
            "pulse": "",
            "safety_boundary": safety,
            "pulse_options": PULSE_OPTIONS,
            "tongue_options": TONGUE_OPTIONS,
            "inquiry_pills": INQUIRY_PILLS,
            "quick_symptom_pills": QUICK_SYMPTOM_PILLS,
            "clinical_entry_cards": CLINICAL_ENTRY_CARDS,
            "preset_cases": PRESET_CASES,
            "recognized_symptoms": [],
            "recognized_negations": [],
            "recognized_pulses": [],
            "recognized_tongues": [],
            "followup_questions": [],
            "compound_regimens": [],
            "candidate_formulas": [],
            "matched_jingfang_clues": [],
            "matched_condition_patterns": [],
            "acupoint_protocol": {"primary": [], "adjuncts": [], "technique_note": ""},
            "differential_notes": [],
            "classical_redlines": [],
            "excluded_pitfalls": [],
            "hantang_context": hantang_catalog.match_clinical_context(),
            "triage_summary": {},
            "decoction_and_safety": [],
            "library_evidence": [],
            "ai_ready_case_packet": {},
        }

    # Score every pattern atom dynamically
    scored_atoms: list[dict[str, Any]] = []
    for atom in PATTERN_ATOMS:
        score = 0
        matched_syms: list[str] = []
        matched_pulses: list[str] = []
        conflict_reasons: list[str] = []

        for sym, w in atom.get("symptom_weights", {}).items():
            if sym in symptoms:
                score += w
                matched_syms.append(sym)
        for s1, s2, bonus in atom.get("pair_bonus", []):
            if s1 in symptoms and s2 in symptoms:
                score += bonus
        for p, w in atom.get("boost_pulses", {}).items():
            if p in pulses:
                score += w
                matched_pulses.append(f"+脉{p}")
        t_delta, matched_tongues, t_conflict = score_atom_tongue(atom, tongues)
        score += t_delta
        if t_conflict:
            conflict_reasons.append(t_conflict)
        for sym, pen in atom.get("conflict_symptoms", {}).items():
            if sym in symptoms:
                score += pen
                conflict_reasons.append(f"症状「{sym}」偏离本方寒热表里边界（{pen}）")
        for p, pen in atom.get("conflict_pulses", {}).items():
            if p in pulses:
                score += pen
                conflict_reasons.append(f"脉象「{p}」与本方病机相反（{pen}）")

        if score <= 8 or not matched_syms:
            if conflict_reasons and matched_syms:
                # Keep suppressed candidates transparently for "excluded pitfalls" UI!
                scored_atoms.append(
                    {
                        **atom,
                        "score": score,
                        "suppressed": True,
                        "matched_symptoms": matched_syms,
                        "matched_pulses": matched_pulses,
                        "matched_tongues": matched_tongues,
                        "conflict_reasons": conflict_reasons,
                    }
                )
            continue

        fobj = fmap.get(atom["formula_id"], {})
        scored_atoms.append(
            {
                **atom,
                "score": score,
                "suppressed": False,
                "matched_symptoms": matched_syms,
                "matched_pulses": matched_pulses,
                "matched_tongues": matched_tongues,
                "conflict_reasons": conflict_reasons,
                "formula_summary": fobj.get("indication", ""),
                "decoction": fobj.get("decoction_method", ""),
                "herbs": _herb_names_of(fobj),
            }
        )

    ctx = evaluate_classical_context(
        scored_atoms,
        PATTERN_ATOMS,
        symptoms,
        pulses,
        tongues,
        positive_q,
        fmap=fmap,
        herb_fn=_herb_names_of,
    )

    active = [a for a in scored_atoms if not a["suppressed"]]
    active.sort(key=lambda x: (-x["score"], -len(x["matched_symptoms"]), x["atom_id"]))
    suppressed = [a for a in scored_atoms if a["suppressed"]]

    # Build Dynamic Single/Compound Regimen(s): check polarity, sibling overlap, symptom necessity & 十八反/十九畏
    compound_regimens: list[dict[str, Any]] = []
    compound_conflict_alerts: list[str] = []
    if active:
        f1 = active[0]
        def _assess_partner(
            base: dict[str, Any],
            cand: dict[str, Any],
            missing_syms: set[str],
            weak_syms: set[str],
        ) -> tuple[bool, tuple[int, int], dict[str, Any], list[str]]:
            if cand["formula_id"] == base["formula_id"]:
                return False, (0, 0), {}, []
            if not _are_polarities_compatible(base.get("polarity", "balanced"), cand.get("polarity", "balanced")):
                return False, (0, 0), {}, []
            if are_formulas_redundant_siblings(base["formula_id"], cand["formula_id"]):
                return False, (0, 0), {}, []
            h1_set, h2_set = set(base.get("herbs", [])), set(cand.get("herbs", []))
            if (
                h1_set
                and h2_set
                and base.get("polarity") == cand.get("polarity")
                and len(h1_set & h2_set) >= 4
                and len(h1_set & h2_set) / max(1, len(h1_set | h2_set)) >= 0.5
            ):
                return False, (0, 0), {}, []
            hc = detect_compound_herb_conflicts(base.get("herbs", []), cand.get("herbs", []), base["name"], cand["name"])
            if hc["blocking"]:
                alerts = [
                    f"【十八反/十九畏合方拦截】{msg}，系统已阻止两方自动合方。"
                    for msg in hc.get("blocking_alerts", hc["alerts"])
                ]
                return False, (0, 0), hc, alerts
            b_weights = base.get("symptom_weights", {})
            c_syms = set(cand["matched_symptoms"])
            c_weights = cand.get("symptom_weights", {})
            hard_uncov = len(c_syms & missing_syms)
            weak_dom = sum(
                1 for s in (c_syms & weak_syms) if c_weights.get(s, 0) - b_weights.get(s, 0) >= 6 and c_weights.get(s, 0) >= 12
            )
            return True, (hard_uncov, weak_dom), hc, []

        # Check whether f1 already strongly handles every symptom or whether a complementary partner covers missing/weak axes
        f1_weights = f1.get("symptom_weights", {})
        uncovered = {s for s in symptoms if s not in set(f1["matched_symptoms"])}
        weakly_covered = {s for s in f1["matched_symptoms"] if f1_weights.get(s, 0) < 10}
        meaningful_partners: list[tuple[tuple[int, int], dict[str, Any], dict[str, Any]]] = []
        for cand in active[1:10]:
            ok, gain, hc, blocked_msgs = _assess_partner(f1, cand, uncovered, weakly_covered)
            for alert_line in blocked_msgs:
                if alert_line not in compound_conflict_alerts:
                    compound_conflict_alerts.append(alert_line)
            if not ok:
                continue
            if gain[0] >= 1 or (gain[1] >= 2 and cand["score"] >= int(f1["score"] * 0.6)):
                meaningful_partners.append((gain, cand, hc))

        # Only propose a two-formula compound primary hero when uncovered or clearly subordinate symptoms need a distinct axis
        if meaningful_partners:
            meaningful_partners.sort(
                key=lambda row: (-(row[0][0] * 25 + row[0][1] * 14 + row[1]["score"]), row[1]["atom_id"])
            )
            _, f2, f2_hc = meaningful_partners[0]
            compound_regimens.append(
                _build_regimen_entry(f1, f2, symptoms, regimen_kind="primary", herb_conflict=f2_hc)
            )
        else:
            if not uncovered:
                note = f"核心方「{f1['name']}」已完整覆盖当前全部核心症候（{'、'.join(f1['matched_symptoms'])}），依「有是证用是方」原则单用本方即可，避免冗余合方。"
            elif compound_conflict_alerts:
                note = "；".join(compound_conflict_alerts)
            else:
                note = "目前症状集中于单一主经病机（或备选方存在寒热/同类互斥），优先考虑专方纯正取效。"
            compound_regimens.append(
                _build_regimen_entry(f1, None, symptoms, regimen_kind="primary", single_note=note)
            )

        # Optional secondary comparative regimen (distinct non-sibling meridian/axis, strictly conflict-checked)
        primary_fids = set(compound_regimens[0]["formula_ids"])
        for alt in active[1:6]:
            if alt["formula_id"] in primary_fids or are_formulas_redundant_siblings(f1["formula_id"], alt["formula_id"]):
                continue
            if alt["score"] < max(42, int(f1["score"] * 0.68)):
                continue
            alt_uncov = set(symptoms) - set(alt["matched_symptoms"])
            if alt_uncov:
                alt_partners = []
                for cand in active:
                    if cand["formula_id"] in primary_fids:
                        continue
                    ok, gain, alt_hc, _ = _assess_partner(alt, cand, alt_uncov, set())
                    if ok and gain[0] >= 1:
                        alt_partners.append((gain[0], cand["score"], cand, alt_hc))
                if alt_partners:
                    alt_partners.sort(key=lambda row: (-row[0], -row[1], row[2]["atom_id"]))
                    _, _, p2, p2_hc = alt_partners[0]
                    compound_regimens.append(
                        _build_regimen_entry(alt, p2, symptoms, regimen_kind="alternative", herb_conflict=p2_hc)
                    )
                    break
            compound_regimens.append(
                _build_regimen_entry(
                    alt,
                    None,
                    symptoms,
                    regimen_kind="alternative",
                    single_note=f"若临床侧重「{alt['six_meridian']}」证候或兼顾「{'、'.join(alt['matched_symptoms'])}」，可作鉴方对照参考。",
                )
            )
            break

    # Build Dynamic Acupoint Protocol from top active atoms + uncovered symptoms
    primary_pts: list[dict[str, str]] = []
    adjunct_pts: list[dict[str, str]] = []
    seen_pts: set[str] = set()
    for idx, atom in enumerate(active[:3]):
        for pt in atom.get("acupoints", []):
            if pt["id"] in seen_pts:
                continue
            seen_pts.add(pt["id"])
            entry = {**pt, "from_axis": atom["name"]}
            if idx < 2 and pt["role"].startswith(("主", "急")):
                primary_pts.append(entry)
            else:
                adjunct_pts.append(entry)

    # Full-corpus Jingfang clues (299 formulas + 258 curated symptoms + 108 modifications)
    clue_q = positive_q or " ".join(symptoms)
    top_atom_fids = [a["formula_id"] for a in active[:4]]
    jingfang_clues = _search_all_jingfang_clues(clue_q, symptoms, top_atom_fids, limit=8)

    # Full-corpus Acupuncture Condition Sub-patterns (34倪师《针灸》临床治症)
    acup_diag = acupuncture_diagnose.diagnose_symptoms(clue_q, limit_patterns=6, limit_points=8)
    cond_patterns_raw = acup_diag.get("matched_patterns", [])
    matched_condition_patterns: list[dict[str, Any]] = []
    for cp in cond_patterns_raw[:6]:
        matched_condition_patterns.append(
            {
                "condition_id": cp.get("condition_id", ""),
                "condition_name": cp.get("condition_name", ""),
                "pattern_name": cp.get("pattern_name", ""),
                "symptoms": cp.get("symptoms", []),
                "syndrome_differentiation": cp.get("syndrome_differentiation", ""),
                "why_selected": cp.get("why_selected", ""),
                "differentiation_notes": cp.get("differentiation_notes", ""),
                "score": cp.get("score", 0),
                "points": [
                    {"id": p.get("id", ""), "name": p.get("canonical_name", ""), "meridian_name": p.get("meridian_name", "")}
                    for p in cp.get("resolved_points", [])[:6]
                ],
            }
        )

    # Fallback hero recommendation if no compound atom matched directly (e.g. disease search like 胆结石/鼻炎/消渴)
    if not compound_regimens and jingfang_clues:
        jc1 = jingfang_clues[0]
        jc2 = jingfang_clues[1] if len(jingfang_clues) > 1 else None
        compound_regimens.append(
            {
                "title": f"全库经方线索：{jc1['name']}" + (f" / 互参 {jc2['name']}" if jc2 else ""),
                "formula_ids": [x["formula_id"] for x in ([jc1, jc2] if jc2 else [jc1])],
                "formula_names": [x["name"] for x in ([jc1, jc2] if jc2 else [jc1])],
                "axis_roles": [
                    f"【经方首选线索】{jc1['name']}（{jc1['book']} · {jc1['six_meridian']}）：{jc1['why_summary'] or '命中主症 ' + '、'.join(jc1['matched_terms'])}"
                ] + (
                    [f"【对照互参方】{jc2['name']}（{jc2['book']} · {jc2['six_meridian']}）：{jc2['why_summary'] or '命中 ' + '、'.join(jc2['matched_terms'])}"]
                    if jc2
                    else []
                ),
                "covered_symptoms": jc1["matched_terms"],
                "uncovered_symptoms": [],
                "overlap_herbs": [],
                "overlap_note": "由全库 299 首经方与 258 套课程症候资料自动关联命中；请点击右侧「支持/待核症状」与加减条文进一步收敛。",
            }
        )
    elif not compound_regimens and not jingfang_clues and matched_condition_patterns:
        cp0 = matched_condition_patterns[0]
        pts0 = [p["name"] for p in cp0.get("points", [])[:6]]
        compound_regimens.append(
            {
                "title": f"《针灸》专症主治：{cp0['condition_name']}",
                "formula_ids": [],
                "formula_names": [],
                "axis_roles": [
                    f"【《针灸》分型主症】{cp0['pattern_name']}：{cp0.get('syndrome_differentiation') or ''}",
                    f"【选穴思路】{cp0.get('why_selected') or '按局部/邻近/远端经络配穴：' + '、'.join(pts0)}",
                ],
                "covered_symptoms": [s for s in cp0.get("symptoms", [])[:4]],
                "uncovered_symptoms": [],
                "overlap_herbs": [],
                "overlap_note": "当前输入侧重局部或专科病症，《针灸》原书已有明确专症分型与选穴；如欲同步匹配经方内服，请点击下方「临床症状追问」补充全身寒热、出汗、二便或脉象线索。",
            }
        )

    # Merge formula_acupuncture_links & matched_condition_patterns acupoints when needed so every disease gets points!
    fa_by_fid = _fa_links_by_formula()
    pt_by_id = _acupoints_by_id()
    for fid in ([a["formula_id"] for a in active[:2]] or [c["formula_id"] for c in jingfang_clues[:2]]):
        fname_lbl = fmap.get(fid, {}).get("name", fid)
        for lk in fa_by_fid.get(fid, [])[:3]:
            tid = lk.get("target_id", "")
            if not tid or tid in seen_pts:
                continue
            seen_pts.add(tid)
            target_pt = pt_by_id.get(tid, {})
            entry = {
                "id": tid,
                "name": lk.get("target_name") or target_pt.get("canonical_name", tid),
                "role": lk.get("relation_kind") or "针药并行",
                "reason": lk.get("note") or lk.get("quote", ""),
                "from_axis": f"《伤寒/金匮》{fname_lbl}原文针药直连",
            }
            if len(primary_pts) < 3:
                primary_pts.append(entry)
            else:
                adjunct_pts.append(entry)

    for cp in matched_condition_patterns[:2]:
        for p in cp.get("points", [])[:4]:
            pid = p.get("id", "")
            if not pid or pid in seen_pts:
                continue
            seen_pts.add(pid)
            entry = {
                "id": pid,
                "name": p["name"],
                "role": "针灸治症取穴" if len(primary_pts) < 4 else "分型随症配穴",
                "reason": (cp.get("why_selected") or cp.get("syndrome_differentiation") or "")[:96],
                "from_axis": f"《针灸》{cp['condition_name']}",
            }
            if len(primary_pts) < 3:
                primary_pts.append(entry)
            else:
                adjunct_pts.append(entry)

    for cp_pt in ctx.get("extra_acupoints", []):
        pid = cp_pt.get("id", "")
        if not pid:
            continue
        primary_pts = [p for p in primary_pts if p.get("id") != pid]
        adjunct_pts = [p for p in adjunct_pts if p.get("id") != pid]
        seen_pts.add(pid)
        primary_pts.insert(0, cp_pt)

    if len(primary_pts) < 3:
        for mp in acup_diag.get("matched_points", [])[:4]:
            pid = mp.get("id", "")
            if not pid or pid in seen_pts:
                continue
            seen_pts.add(pid)
            primary_pts.append(
                {
                    "id": pid,
                    "name": mp.get("canonical_name", pid),
                    "role": "《针灸》主治专穴",
                    "reason": "；".join(mp.get("indications", [])[:2]) or mp.get("technique_notes", "")[:80],
                    "from_axis": f"《针灸》{mp.get('meridian_name', '十四经')}主治匹配",
                }
            )
            if len(primary_pts) >= 4:
                break

    # Extra targeted symptom-to-acupoint rules (preserved cleanly)
    if ("习惯性便秘" in symptoms or "大便干" in symptoms) and "acupoint:st25:天枢" not in seen_pts:
        adjunct_pts.append({"id": "acupoint:st25:天枢", "name": "天枢", "role": "便干随症配穴", "reason": "大肠募穴，调肠通腑（兼寒可用温灸/配照海润燥）", "from_axis": "大便干/便秘轴"})
        seen_pts.add("acupoint:st25:天枢")
    if ("习惯性便秘" in symptoms or "大便干" in symptoms) and "acupoint:sj06:支沟" not in seen_pts:
        adjunct_pts.append({"id": "acupoint:sj06:支沟", "name": "支沟", "role": "便干随症配穴", "reason": "支沟配照海为通调大便经典对穴", "from_axis": "大便干/便秘轴"})
        seen_pts.add("acupoint:sj06:支沟")
    if ("身冷" in symptoms or "脚冷" in symptoms) and "acupoint:du04:命门" not in seen_pts:
        adjunct_pts.append({"id": "acupoint:du04:命门", "name": "命门", "role": "虚寒温灸配穴", "reason": "温命门肾火，引火归元散寒", "from_axis": "身冷/脚冷轴"})
        seen_pts.add("acupoint:du04:命门")

    moxa_advice = []
    if any(s in symptoms for s in ("身冷", "脚冷", "下利清谷", "痛经")):
        moxa_advice.append("【刺灸寒热区分】含身冷脚冷/下利/虚寒痛经，下焦关元、命门、太溪宜重用隔姜灸或温针以助阳气化水；若兼但头汗出或少阳口苦，阳陵泉、外关、期门宜针刺平泻而不重灸。")
    if acup_diag.get("safety_alerts"):
        moxa_advice.append("【针灸安全提醒】" + "；".join(acup_diag["safety_alerts"][:2]))
    if pulses:
        pulse_notes = [f"{p['label']}：{p['note']}" for p in PULSE_OPTIONS if p["id"] in pulses]
        moxa_advice.append("【脉象参与辨证权重】" + "；".join(pulse_notes))

    # Dynamic differential follow-up questions (学习问诊)
    followup_questions = _build_followup_questions(symptoms, pulses, jingfang_clues, matched_condition_patterns)

    # Match differential notes & excluded pitfalls
    diffs = []
    for d in CLINICAL_DIFFERENTIAL_NOTES:
        t1 = d.get("trigger_all", ())
        t2 = d.get("alt_trigger_all", ())
        if (t1 and all(x in symptoms for x in t1)) or (t2 and all(x in symptoms for x in t2)):
            diffs.append({"title": d["title"], "explanation": d["explanation"]})

    excluded = []
    for sp in suppressed:
        reasons = list(dict.fromkeys(sp["conflict_reasons"]))
        excluded.append(
            {
                "name": sp["name"],
                "formula_id": sp["formula_id"],
                "why_excluded": "；".join(reasons),
            }
        )

    hantang_ctx = hantang_catalog.match_clinical_context(
        q=positive_q,
        symptoms=symptoms,
        pulses=pulses,
        suppressed_names=[e["name"] for e in excluded],
        limit=4,
    )

    triage_summary = _build_plain_triage_summary(symptoms, pulses, tongues, active, excluded)
    regimen_fids = set(compound_regimens[0]["formula_ids"]) if compound_regimens and compound_regimens[0].get("formula_ids") else set()
    guide_atoms = [a for a in active if a["formula_id"] in regimen_fids] if regimen_fids else active[:2]
    decoction_and_safety = _build_decoction_and_recovery_guide(guide_atoms or active[:2], symptoms, pulses, primary_pts + adjunct_pts)
    for line in reversed([*compound_conflict_alerts, *ctx.get("extra_safety_lines", [])]):
        if line not in decoction_and_safety:
            decoction_and_safety.insert(0, line)

    lib_query = " ".join((symptoms[:4] or _extract_query_terms(positive_q, [])[:3])) or positive_q or cleaned_q
    lib_res = search_library_pages(lib_query, limit=6)
    lib_refs = [
        {
            "book_id": r["book_id"],
            "book_title": r["book_title"],
            "page_no": r["page_no"],
            "unit_label": r["unit_label"],
            "snippet": r["snippet"],
            "text_sha256": r["text_sha256"],
        }
        for r in lib_res.get("items", [])
    ]

    # Pre-formatted packet ready for Stage 6 LLM clinical co-pilot integration
    ai_packet = {
        "schema": "tcm_brain.ai_clinical_case_packet.v1",
        "ready_for_llm": True,
        "safety_gate": safety,
        "recognized_symptoms": symptoms,
        "negated_terms": negated_terms,
        "recognized_pulses": pulses,
        "recognized_tongues": tongues,
        "decomposed_axes": [
            {
                "formula": a["name"],
                "axis": a["six_meridian"],
                "matched": a["matched_symptoms"],
                "matched_tongues": a.get("matched_tongues", []),
                "score": a["score"],
            }
            for a in active[:4]
        ],
        "matched_jingfang_ids": [c["formula_id"] for c in jingfang_clues[:6]],
        "matched_condition_ids": [cp["condition_id"] for cp in matched_condition_patterns[:4]],
        "proposed_compound": compound_regimens[0]["formula_names"] if compound_regimens else [],
        "proposed_acupoints": [p["name"] for p in (primary_pts + adjunct_pts)[:8]],
        "excluded_pitfalls": excluded,
        "classical_redlines": ctx.get("redlines", []),
        "hantang_hints": {
            "matched_ht_numbers": [h["ht_number"] for h in hantang_ctx.get("hantang_formulas", [])],
            "western_triggers": [w["title"] for w in hantang_ctx.get("western_history_guidance", [])],
            "du_spine_warnings": [d["warning_target"] for d in hantang_ctx.get("du_spine_guides", [])],
        },
        "grounded_citations": [{"book": c["book_title"], "unit": c["unit_label"], "sha256": c["text_sha256"], "snippet": c["snippet"]} for c in lib_refs[:4]],
        "system_constraint": "Future AI plugin MUST cite only grounded_citations SHA hashes, respect safety_gate non-prescribing rules, and never drop contradictory pulse constraints.",
    }

    return {
        "query": cleaned_q,
        "pulse": cleaned_pulse,
        "safety_boundary": safety,
        "pulse_options": PULSE_OPTIONS,
        "tongue_options": TONGUE_OPTIONS,
        "inquiry_pills": INQUIRY_PILLS,
        "quick_symptom_pills": QUICK_SYMPTOM_PILLS,
        "clinical_entry_cards": CLINICAL_ENTRY_CARDS,
        "preset_cases": PRESET_CASES,
        "recognized_symptoms": symptoms,
        "recognized_negations": negated_terms,
        "recognized_pulses": pulses,
        "recognized_tongues": tongues,
        "followup_questions": followup_questions,
        "compound_regimens": compound_regimens,
        "candidate_formulas": active[:6],
        "matched_jingfang_clues": jingfang_clues,
        "matched_condition_patterns": matched_condition_patterns,
        "acupoint_protocol": {
            "primary": primary_pts[:6],
            "adjuncts": adjunct_pts[:6],
            "technique_note": " ".join(moxa_advice),
        },
        "differential_notes": diffs,
        "classical_redlines": ctx.get("redlines", []),
        "excluded_pitfalls": excluded,
        "hantang_context": hantang_ctx,
        "triage_summary": triage_summary,
        "decoction_and_safety": decoction_and_safety,
        "library_evidence": lib_refs,
        "ai_ready_case_packet": ai_packet,
    }
