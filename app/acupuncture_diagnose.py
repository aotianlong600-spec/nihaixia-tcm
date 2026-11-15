"""Deterministic textbook-grounded symptom differentiation & acupoint reasoning engine."""
from __future__ import annotations

import json
import re
from typing import Any

from app.acupuncture_catalog import (
    _entities_by_id,
    _entity_summary,
    _load_json,
    _pages_by_num,
)
from retrieval.tcm_synonyms import strip_clinical_negations


SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("头痛", "头疼", "偏头痛", "偏头疼", "太阳穴痛", "前额痛", "眉棱骨痛", "后头痛", "巅顶痛", "脑瘤", "脑萎缩", "脑震荡"),
    ("头晕", "眩晕", "晕眩", "美尼尔"),
    ("鼻炎", "鼻塞", "鼻息肉", "流鼻水", "流清涕", "鼻流清涕", "流鼻涕", "清涕", "浊涕", "黄涕", "鼻涕", "鼻渊", "脑漏", "鼻窦炎"),
    ("流鼻血", "鼻衄", "鼻出血"),
    ("耳鸣", "耳聋", "耳脓", "耳流脓", "耳朵化脓", "中耳炎", "重听"),
    ("眼痛", "目赤", "视力", "近视", "老花", "青光眼", "白内障", "迎风流泪", "针眼"),
    ("牙痛", "牙齿痛", "齿痛", "牙龈", "牙关痛"),
    ("面瘫", "面部中风", "口眼歪斜", "面肌"),
    ("咽喉痛", "喉咙痛", "扁桃腺", "扁桃体", "失声", "失音", "舌强", "舌肿"),
    ("咳嗽", "久咳", "干咳", "痰多", "黄痰", "痰黄", "白痰", "哮喘", "气喘", "喘", "肺痨", "肺积水", "肺癌"),
    ("胸痛", "胸闷", "心痛", "心绞痛", "心脏肥大", "心悸", "心律不整", "动脉阻塞", "心肌梗塞", "血瘀胸中"),
    ("乳癌", "乳房硬块", "乳房胀痛", "乳痈", "无乳", "少乳", "奶水", "奶水不出"),
    ("胃痛", "胃疼", "胃脘痛", "心下痛", "胃胀", "胃酸", "反胃", "呕吐", "朝食暮吐", "打嗝", "呃逆", "喝水吐", "饮水即吐"),
    ("腹痛", "肚子痛", "绕脐痛", "肚脐痛", "腹胀", "水胀", "鼓胀", "腹膜炎", "奔豚", "痞块", "痞根"),
    ("便秘", "大便干", "大便干结", "大便不通", "大便不顺", "燥热", "燥矢"),
    ("羊屎", "羊大便", "颗粒便", "大便粒如羊屎"),
    ("下利", "腹泻", "泄泻", "泄利", "拉肚子", "血痢", "便血", "下血", "大便带血", "肠风下血", "痔疮", "脱肛", "肠漏", "大肠癌"),
    ("胆结石", "胆囊", "黄疸", "肝病", "肝硬化", "肝癌", "肝腹水", "脾肿大", "胁痛", "右肋痛", "肝结石", "易怒"),
    ("消渴", "糖尿病", "口渴", "三消"),
    ("盲肠炎", "阑尾炎", "右下腹痛"),
    ("腰痛", "闪腰", "背痛", "肩背痛", "脊椎痛", "脊柱痛", "尾椎痛", "坐骨神经痛", "椎间盘凸出"),
    ("水肿", "浮肿", "脚肿", "积水", "小便不利", "尿血", "肾结石", "尿道炎", "尿痛"),
    ("痛经", "经痛", "月经", "经期", "闭经", "血块"),
    ("赤白带", "赤带", "白带", "带下"),
    ("崩漏", "下血不止", "产后大出血", "血崩"),
    ("子宫瘤", "卵巢瘤", "子宫肌瘤", "助孕", "不孕", "绝孕"),
    ("胎盘不落", "胎盘下不来", "胎盘出不来", "胞衣不下", "难产", "催生"),
    ("怀孕", "孕妇", "孕期", "安胎", "胎位不正", "堕胎"),
    ("失眠", "睡不着", "早醒", "多梦"),
    ("癫痫", "癫症", "狂症", "发狂", "中邪", "昏迷", "晕针", "晕倒", "中风", "半身不遂", "瘫痪", "帕金森"),
    ("肩膀痛", "肩痛", "五十肩", "手臂痛", "手腕痛", "扭毛巾"),
    ("膝盖冷", "膝盖冰冷", "脚冷膝冷", "脚膝冷", "脚膝冰冷"),
    ("膝痛", "膝盖痛", "膝关节痛"),
    ("关节炎", "风湿", "痛风", "历节"),
    ("脚抽筋", "转筋", "足跟痛", "脚后跟痛", "脚麻", "手麻"),
    ("疝气", "阴部痛", "睾丸痛", "缩睾", "睾丸上缩", "子宫下垂"),
    ("湿疹", "皮肤病", "牛皮癣", "皮肤癣", "红斑性狼疮", "红斑狼疮", "脂肪瘤", "黑痣", "鸡眼"),
)

MERIDIAN_TIME_RULES = [
    {
        "tokens": ("寅时", "凌晨三点", "凌晨四点", "半夜三点", "3点", "4点", "凌晨3", "凌晨4"),
        "window": "03:00–05:00（寅时）",
        "meridian_id": "meridian:lu",
        "meridian_name": "手太阴肺经",
        "rule": "凌晨三点至五点（寅时）气血流注手太阴肺经（俞穴太渊、荣穴鱼际常用）。",
    },
    {
        "tokens": ("卯时", "早上五点", "早上六点", "清晨五点", "清晨六点", "5点", "6点"),
        "window": "05:00–07:00（卯时）",
        "meridian_id": "meridian:li",
        "meridian_name": "手阳明大肠经",
        "rule": "清晨五点至七点（卯时）气血流注手阳明大肠经（原穴合谷、俞穴三间）。",
    },
    {
        "tokens": ("辰时", "早上七点", "早上八点", "上午七点", "上午八点", "7点", "8点"),
        "window": "07:00–09:00（辰时）",
        "meridian_id": "meridian:st",
        "meridian_name": "足阳明胃经",
        "rule": "上午七点至九点（辰时）气血流注足阳明胃经（俞穴陷谷、合穴足三里）。",
    },
    {
        "tokens": ("巳时", "上午九点", "上午十点", "9点", "10点"),
        "window": "09:00–11:00（巳时）",
        "meridian_id": "meridian:sp",
        "meridian_name": "足太阴脾经",
        "rule": "上午九点至十一点（巳时）气血流注足太阴脾经（俞原太白、络穴公孙）。",
    },
    {
        "tokens": ("午时", "中午十一点", "中午十二点", "11点", "12点"),
        "window": "11:00–13:00（午时）",
        "meridian_id": "meridian:ht",
        "meridian_name": "手少阴心经",
        "rule": "中午十一点至下午一点（午时）气血流注手少阴心经（俞原/子穴神门）。",
    },
    {
        "tokens": ("未时", "下午一点", "下午两点", "13点", "14点"),
        "window": "13:00–15:00（未时）",
        "meridian_id": "meridian:si",
        "meridian_name": "手太阳小肠经",
        "rule": "下午一点至三点（未时）气血流注手太阳小肠经（俞/母穴后溪）。",
    },
    {
        "tokens": ("申时", "下午三点", "下午四点", "15点", "16点"),
        "window": "15:00–17:00（申时）",
        "meridian_id": "meridian:bl",
        "meridian_name": "足太阳膀胱经",
        "rule": "下午三点至五点（申时）气血流注足太阳膀胱经（俞/子穴束骨）。",
    },
    {
        "tokens": ("酉时", "傍晚五点", "傍晚六点", "下午五点", "17点", "18点"),
        "window": "17:00–19:00（酉时）",
        "meridian_id": "meridian:ki",
        "meridian_name": "足少阴肾经",
        "rule": "傍晚五点至七点（酉时）气血流注足少阴肾经（俞原太溪）。",
    },
    {
        "tokens": ("戌时", "晚上七点", "晚上八点", "19点", "20点"),
        "window": "19:00–21:00（戌时）",
        "meridian_id": "meridian:pc",
        "meridian_name": "手厥阴心包经",
        "rule": "晚上七点至九点（戌时）气血流注手厥阴心包经（俞原/子穴大陵、络穴内关）。",
    },
    {
        "tokens": ("亥时", "晚上九点", "晚上十点", "21点", "22点"),
        "window": "21:00–23:00（亥时）",
        "meridian_id": "meridian:sj",
        "meridian_name": "手少阳三焦经",
        "rule": "晚上九点至十一点（亥时）气血流注手少阳三焦经（俞/母穴中渚、络穴外关）。",
    },
    {
        "tokens": ("子时", "半夜十一点", "半夜十二点", "23点", "0点"),
        "window": "23:00–01:00（子时）",
        "meridian_id": "meridian:gb",
        "meridian_name": "足少阳胆经",
        "rule": "子时（23:00–01:00）气血流注足少阳胆经（俞穴足临泣）。",
    },
    {
        "tokens": ("丑时", "凌晨一点", "凌晨两点", "半夜一点", "半夜两点", "1点", "2点"),
        "window": "01:00–03:00（丑时）",
        "meridian_id": "meridian:lv",
        "meridian_name": "足厥阴肝经",
        "rule": "凌晨一点至三点（丑时）醒来多主肝经受病（俞原太冲）。",
    },
]

CHANNEL_GUIDES = [
    {
        "triggers": ("头痛", "头疼", "前额", "眉棱骨", "偏头", "后头", "巅顶", "太阳穴"),
        "title": "头痛分经辨证纲要（依教材所授循行与压痛判别）",
        "branches": [
            {"label": "前额痛 / 眉棱骨痛", "meridian": "阳明经（足阳明胃/手阳明大肠）", "query_chip": "前额痛", "note": "眉棱骨痛可见对侧奇穴眉棱点；两眉间印堂痛多涉胃腑可考中脘。"},
            {"label": "两侧偏头痛 / 耳周", "meridian": "少阳经（足少阳胆/手少阳三焦）", "query_chip": "偏头痛", "note": "常取对侧率谷、太阳、合谷、中渚等，区分虚实补泻。"},
            {"label": "后脑痛 / 后项僵硬", "meridian": "太阳经（足太阳膀胱）或督脉", "query_chip": "后头痛", "note": "常用天柱、束骨、后溪、昆仑等分虚实调治。"},
            {"label": "巅顶痛 / 百会区", "meridian": "足厥阴肝经 / 督脉", "query_chip": "巅顶痛", "note": "百会放血或灸法配合涌泉、太冲等随证辨别。"},
            {"label": "持续剧痛 / 压痛 / 疑颅内肿块", "meridian": "高风险急重警示", "query_chip": "脑瘤", "note": "须先行专业影像/医疗排查；教材头部与脑瘤治症分型列有涌泉、绝骨等教学思路。"},
        ],
    },
    {
        "triggers": ("背痛", "腰痛", "脊椎痛", "闪腰"),
        "title": "背痛与腰痛三线分经辨证纲要（教材第127页等）",
        "branches": [
            {"label": "脊椎正中痛", "meridian": "督脉", "query_chip": "督脉", "note": "正中督脉痛，常考后溪（通督脉）或督脉压痛点对应治法。"},
            {"label": "脊柱旁开一寸半（膀胱经第一线）", "meridian": "足太阳膀胱经 / 肾虚辨别", "query_chip": "膀胱经", "note": "沿膀胱经寻压痛，区分实证泻委中/束骨与肾虚腰痛取肾俞、太溪等。"},
            {"label": "肩胛与腰背外侧二线 / 横向带状", "meridian": "膀胱经二线 / 带脉 / 三焦经", "query_chip": "带脉", "note": "教材专门提示背痛第一线与第二线及带脉区别取穴（如委中、外关、足临泣）。"},
        ],
    },
    {
        "triggers": ("肩痛", "肩膀痛", "五十肩", "手臂痛"),
        "title": "肩臂痛循经辨证纲要（忌见肩痛一概只扎曲池）",
        "branches": [
            {"label": "肩前缘近胸处痛", "meridian": "手太阴肺经", "query_chip": "肺经", "note": "如肺经虚实痛，分取尺泽（实泻）或太渊（虚补），兼核中府云门。"},
            {"label": "肩前外侧、臂上缘举臂痛", "meridian": "手阳明大肠经", "query_chip": "曲池", "note": "属大肠经循行痛者方取合谷、曲池、条口透承山或对侧对应取穴。"},
            {"label": "肩外侧正中痛（不能侧举）", "meridian": "手少阳三焦经", "query_chip": "天井", "note": "教材于三焦经明辨肩髎、天井（子）、中渚（母）按久病虚/新病实区分。"},
            {"label": "肩后缘、肩胛背侧、不能反手扭毛巾", "meridian": "手太阳小肠经", "query_chip": "养老", "note": "属小肠经者用养老透间使、后溪、小海等。"},
        ],
    },
    {
        "triggers": ("鼻塞", "鼻炎", "鼻息肉", "流鼻水", "流清涕", "浊涕", "流鼻血"),
        "title": "鼻病与肺系辨证追问要点（肺开窍在鼻）",
        "branches": [
            {"label": "清涕、遇冷风塞、过敏性鼻炎", "meridian": "虚寒 / 肺气宣降失司", "query_chip": "流清涕", "note": "重在宣肺通窍，常考迎香、通天、上星、合谷、中府、肺俞、太渊等。"},
            {"label": "鼻息肉（鼻孔内赘肉阻塞）", "meridian": "鼻息肉专题", "query_chip": "鼻息肉", "note": "教材专列迎香、内迎香、合谷等理气散结思路。"},
            {"label": "黄稠浊涕、鼻渊/脑漏/鼻窦炎", "meridian": "郁热上蒸", "query_chip": "鼻窦炎", "note": "区别一般清涕，常配神庭、上星、天柱、曲池、风池清宣上焦。"},
            {"label": "流鼻血（鼻衄）", "meridian": "热迫血行 / 外伤或急症", "query_chip": "流鼻血", "note": "教材载天府为鼻血大穴，兼须排查高血压与急重出血。"},
        ],
    },
    {
        "triggers": ("咳嗽", "久咳", "喘", "气喘", "哮喘"),
        "title": "咳喘虚实与时段辨证要点",
        "branches": [
            {"label": "新病、咳声重浊、实证气喘", "meridian": "肺经实证", "query_chip": "实症", "note": "依“实则泻其子”用尺泽，兼考俞募（肺俞/中府）及奇穴定喘。"},
            {"label": "久咳、声音低怯、寅时（3–5点）醒", "meridian": "肺经虚证 / 肾不纳气", "query_chip": "久咳", "note": "依“虚则补其母”用太渊，久病肾不纳气兼考太溪、复溜、关元。"},
        ],
    },
    {
        "triggers": ("胃痛", "胃寒", "胃热", "呕吐", "反胃", "朝食暮吐", "胃出血", "吐血"),
        "title": "胃痛、呕吐与胃出血辨证分型纲要（第184–185页）",
        "branches": [
            {"label": "胃寒胃痛（苔白厚、面苍白）", "meridian": "足阳明胃经 / 任脉（用灸为主）", "query_chip": "胃寒", "note": "隔姜灸胃募中脘配公孙、内关（胃心胸），佐足三里止呕。"},
            {"label": "胃热 / 湿热痛（苔黄湿、面红）", "meridian": "足阳明胃经（只针不灸）", "query_chip": "胃热", "note": "针刺中脘、胃俞、足三里及四花/梅花法，忌灸助热。"},
            {"label": "朝食暮吐（宿食滞留下口）", "meridian": "胃募中脘", "query_chip": "朝食暮吐", "note": "中脘下针或艾灸令胃蠕动恢复即畅。"},
            {"label": "胃出血 / 黑便远血 / 吐血（高危戒律）", "meridian": "冲脉 / 阴维 / 任脉（禁用足三里）", "query_chip": "胃出血", "note": "教材明戒足三里反促蠕动大出血！改取公孙、内关、中脘。"},
        ],
    },
    {
        "triggers": ("痛经", "月经", "赤白带", "赤带", "白带", "崩漏", "怀孕", "孕妇", "胎位", "助孕", "胎盘", "胞衣", "产后", "难产"),
        "title": "妇科经带与妊娠分证辨治及忌针纲要（第189–192页）",
        "branches": [
            {"label": "痛经发作当时（经期第一日剧痛）", "meridian": "足太阴脾经 / 任脉", "query_chip": "痛经", "note": "痛时直下三阴交（按寻痛点勿刺误）、血海，配灸三阴交、中极、关元。"},
            {"label": "月经延后（寒证）与不孕助孕", "meridian": "任脉 / 脾经 / 大肠经", "query_chip": "助孕", "note": "寒延及助孕宜常灸合谷、三阴交、中极、关元至复28日准期。"},
            {"label": "崩漏经血不止（淋漓不断）", "meridian": "足太阴脾经", "query_chip": "隐白", "note": "妇科止血大穴取隐白双侧下针留二十分钟。"},
            {"label": "赤带（湿热）vs 白带（寒湿）", "meridian": "带脉 / 脾经 / 膀胱经", "query_chip": "白带", "note": "皆取足临泣、三阴交、血海、隐白、归来、水道、曲骨、白环俞；赤带禁灸只针，白带加灸除寒湿。"},
            {"label": "妊娠安胎、忌针、胎位不正与产后", "meridian": "严格分经远取（严禁动腹）", "query_chip": "孕妇", "note": "禁动腹部及四花灸；胎位不正刺至阴；水肿针三皇配水泉太溪太冲；胎盘不下针昆仑太溪隐白。"},
        ],
    },
    {
        "triggers": ("耳鸣", "耳聋", "中耳炎", "耳流脓", "耳朵化脓"),
        "title": "耳病虚实与化脓三经辨治纲要（第173–174页）",
        "branches": [
            {"label": "久鸣、耳聋属肾虚", "meridian": "足少阴肾经 / 俞募", "query_chip": "耳鸣 久虚", "note": "补肾取肾俞、志室、京门、章门配复溜斜刺迎随补法，兼轮刺耳门、听宫、听会。"},
            {"label": "新发暴鸣、耳痛属实证", "meridian": "肾经 / 三焦经", "query_chip": "然谷", "note": "初发实证取然谷配外关、支沟（飞虎）疏导三焦与肾经实火。"},
            {"label": "耳朵流脓 / 耳洞发炎", "meridian": "手阳明大肠经 / 近取三针", "query_chip": "化脓", "note": "耳门听宫听会轮刺单刺配干燥散剂；上半身或耳洞炎取对侧曲池消炎。"},
        ],
    },
    {
        "triggers": ("眼痛", "目赤", "白内障", "近视", "青光眼", "迎风流泪"),
        "title": "眼目湿热赤肿与内障视力分型纲要（第171–172页）",
        "branches": [
            {"label": "目赤红肿热痛（湿热实证）", "meridian": "四穴三棱针点刺放血", "query_chip": "目赤", "note": "于攒竹、丝竹空、耳尖、太阳四穴三棱针点刺挤一二滴血（忌用梅花针）。"},
            {"label": "白内障、生翳膜、近视与迎风流泪", "meridian": "膀胱经 / 胆经 / 肝肾俞", "query_chip": "白内障", "note": "常用睛明、承泣、瞳子髎、风池配远取养老、光明、太冲、肾俞、肝俞辨虚实。"},
        ],
    },
    {
        "triggers": ("便秘", "大便干结", "羊屎", "下利", "痔疮", "肠漏", "盲肠炎", "奔豚"),
        "title": "便秘大小肠寒热鉴别与急腹肠漏纲要（第187–189页）",
        "branches": [
            {"label": "小肠堵便秘（频放屁、羊屎颗粒便）", "meridian": "任脉 / 心 / 脾 / 三焦阴跷", "query_chip": "羊屎", "note": "不用天枢！取关元、巨阙、章门增小肠热与脾湿，通用对穴支沟、照海。"},
            {"label": "大肠寒实（数日不便而不难过、尿白）", "meridian": "胃经 / 任脉 / 脾本穴", "query_chip": "大肠寒实", "note": "用灸远胜于针：灸天枢、关元、中脘、足三里及四花灸，兼针太白与支沟照海。"},
            {"label": "大肠热燥矢（腹痛难耐、尿浊黄、天枢压痛）", "meridian": "胃 / 任 / 三焦（严禁艾灸）", "query_chip": "燥矢", "note": "只针不灸：针天枢、关元、中极、巨阙配支沟照海。"},
            {"label": "盲肠炎与腹膜炎破裂救急（高危）", "meridian": "经外奇穴阑尾 / 肘尖", "query_chip": "盲肠炎", "note": "取足三里下一寸阑尾最痛点针刺止痛；若破成腹部旁寒中烫腹膜炎急隔姜灸肘尖至肠鸣排脓。"},
            {"label": "肠风下血与痔疮 / 术后肠漏", "meridian": "膀胱经 / 督脉 / 尾脊三痛点", "query_chip": "痔疮", "note": "承山、孔最、长强配天应放血；大量鲜血或瘘管由尾椎十四椎上按压寻三个痛点隔姜灸。"},
        ],
    },
    {
        "triggers": ("胸痛", "胸闷", "心痛", "心悸", "心脏肥大", "心肌梗塞", "动脉阻塞"),
        "title": "心痛胸闷瘀血与气堵鉴别纲要（第178–179、197页）",
        "branches": [
            {"label": "胸刺痛（瘀血阻络）", "meridian": "任脉 / 手少阴心经", "query_chip": "刺痛", "note": "取心募巨阙配心经少府、神门及劳宫、关元，配合天应压痛与背心俞。"},
            {"label": "胸闷痛（气机郁堵）", "meridian": "冲脉 / 阴维 / 任脉 / 督脉", "query_chip": "闷痛", "note": "先公孙、内关、天突导气，配巨阙、关元及背第十一椎，兼埋耳屏正中心脏点护心并验第5椎心俞。"},
        ],
    },
    {
        "triggers": ("肝病", "胆结石", "肝硬化", "肝腹水", "黄疸", "消渴", "糖尿病"),
        "title": "肝胆痞块时症及消渴生津纲要（第179–186页）",
        "branches": [
            {"label": "肝胆实痛 / 胆结石 / 凌晨1–3点或23–1点发作", "meridian": "肝经 / 胆经 / 奇穴", "query_chip": "胆结石", "note": "胁痛取对侧肝关，结石配胆石点、日月、期门、天枢、肝胆俞，子丑时症择阳陵泉或行间并强脾水。"},
            {"label": "肝硬化脾肿大与痞块积水（高危）", "meridian": "脾经 / 肾经 / 奇穴痞根消积", "query_chip": "痞块", "note": "灸痞根、消积、固中脘、三皇、章门，先行强水（京门、肾俞、复溜、关元中极）防传变。"},
            {"label": "消渴糖尿病（三消口渴）", "meridian": "任脉 / 肺经 / 膀胱经奇穴消渴", "query_chip": "消渴", "note": "针灸天突、关元、天枢生大肠水精上归中府云门肺俞，配阳池与背第8椎下奇穴消渴压痛点。"},
        ],
    },
]

SPECIAL_GROUP_ALERTS = [
    (("孕妇", "怀孕", "胎", "备孕", "绝孕", "堕胎"), "【妊娠与生育安全警示】妊娠期对合谷、三阴交、石门、关元、昆仑、至阴等穴具严格禁忌或特定胎位用途；教材所述绝孕/安胎/堕胎均属传统文献及专业教学记载，严禁个人尝试。"),
    (("小儿", "幼儿", "小孩", "儿童", "惊厥"), "【儿童安全警示】教材第二、四章明确提示幼儿一般单刺不留针（或用三关指针推拿），且需区分惊风/高热急症，必须由专业儿科/医疗人员评估。"),
    (("癌", "肿瘤", "脑瘤", "硬块", "肿块", "积水", "吐血", "下血", "血痢", "昏迷", "中风"), "【急重症与高风险医疗声明】涉及肿瘤、积水、出血、昏迷或脑血管急症者，须立即优先进入现代急诊与专科诊疗体系；本系统呈现之治症与选穴仅供《人纪针灸》文献研究参考。"),
]

COMMON_QUALIFIER_CHIPS = [
    ("寒证/怕冷/清涕", "怕冷"),
    ("热证/黄痰/红肿", "燥热"),
    ("虚证/久病/酸软", "虚症"),
    ("实证/新病/压痛拒按", "实症"),
    ("有压痛肿块/疑难重症", "压痛"),
    ("妊娠/备孕期", "怀孕"),
    ("小儿/幼儿", "小儿"),
]


def _tokenize_query(q: str) -> list[str]:
    raw = [t.strip() for t in re.split(r"[\s,，、/+;；|]+", q.strip()) if len(t.strip()) >= 1]
    seen: list[str] = []
    for t in raw:
        if t not in seen:
            seen.append(t)
    if q.strip() and q.strip() not in seen:
        seen.append(q.strip())
    return seen


def _expand_tokens(tokens: list[str]) -> tuple[list[str], dict[str, set[str]]]:
    expanded: list[str] = []
    token_groups: dict[str, set[str]] = {}
    for tok in tokens:
        low = tok.lower()
        group: set[str] = {low}
        for syn_tuple in SYNONYM_GROUPS:
            if any(low in s.lower() or s.lower() in low for s in syn_tuple if len(low) >= 2 or low == s.lower()):
                group.update(s.lower() for s in syn_tuple)
        token_groups[tok] = group
        for g in group:
            if g not in expanded:
                expanded.append(g)
    return expanded, token_groups


def _score_text(text: str, token_groups: dict[str, set[str]], weight: int = 1) -> tuple[int, list[str]]:
    if not text:
        return 0, []
    low = text.lower()
    score = 0
    hits: list[str] = []
    for orig_tok, syns in token_groups.items():
        if len(orig_tok) >= 2 and orig_tok.lower() in low:
            score += weight * 3
            if orig_tok not in hits:
                hits.append(orig_tok)
            continue
        for syn in syns:
            if len(syn) >= 2 and syn in low:
                score += weight * 2
                if orig_tok not in hits:
                    hits.append(orig_tok)
                break
            if len(orig_tok) == 1 and orig_tok in low:
                score += weight
                if orig_tok not in hits:
                    hits.append(orig_tok)
                break
    return score, hits


def _enrich_point_brief(pt: dict | None, entities: dict[str, dict], fallback_id: str) -> dict:
    if not pt:
        return {
            **_entity_summary(None, fallback_id),
            "meridian_name": "",
            "special_categories": [],
            "location_simplified": "",
            "location_source": "",
            "technique_notes": "",
            "cautions": "",
            "indications": [],
        }
    mid = pt.get("meridian_id", "")
    mer = entities.get(mid, {})
    return {
        **_entity_summary(pt, fallback_id),
        "meridian_name": mer.get("canonical_name", mid),
        "sequence": pt.get("sequence"),
        "pinyin": pt.get("pinyin", ""),
        "aliases": pt.get("aliases", []),
        "special_categories": pt.get("special_categories", []),
        "location_simplified": pt.get("location_simplified", ""),
        "location_source": pt.get("location_source", ""),
        "technique_notes": pt.get("technique_notes", ""),
        "cautions": pt.get("cautions", ""),
        "indications": pt.get("indications", [])[:8],
        "safety_warning": pt.get("safety_warning", ""),
    }


def diagnose_symptoms(
    q: str = "",
    risk_level: str = "",
    meridian_id: str = "",
    limit_patterns: int = 10,
    limit_points: int = 12,
) -> dict[str, Any]:
    cleaned = q.strip()
    entities = _entities_by_id()
    meridians = _load_json("meridians.json").get("items", [])
    acupoints = _load_json("acupoints.json").get("items", [])
    techniques = _load_json("techniques.json").get("items", [])
    conditions = _load_json("conditions.json").get("items", [])
    relations = _load_json("relations.json").get("items", [])
    indexes = _load_json("book_indexes.json")

    if not cleaned:
        approved_conds = [c for c in conditions if c.get("review_status") == "approved"]
        return {
            "query": "",
            "tokens": [],
            "quick_examples": [
                "偏头痛",
                "鼻塞 流清涕",
                "久咳 气喘 寅时醒",
                "胃痛 呕吐",
                "胆结石 右肋痛",
                "痛经 血块拒按",
                "腰痛 背痛",
                "失眠 耳鸣",
            ],
            "qualifier_chips": COMMON_QUALIFIER_CHIPS,
            "stats": {
                "meridians": len(meridians),
                "acupoints": len(acupoints),
                "techniques": len(techniques),
                "conditions": len(conditions),
                "approved_conditions": len(approved_conds),
                "total_patterns": sum(len(c.get("sub_patterns", [])) for c in conditions),
            },
            "matched_patterns": [],
            "matched_points": [],
            "matched_techniques": [],
            "matched_meridian_clocks": [],
            "channel_guides": [],
            "matched_indexes": [],
            "matched_pages": [],
            "follow_up_facets": [],
            "safety_alerts": [],
        }

    positive_q, _ = strip_clinical_negations(cleaned)
    tokens = _tokenize_query(positive_q)
    expanded, token_groups = _expand_tokens(tokens)

    # 1. Safety & population notices triggered by input
    safety_alerts: list[str] = []
    low_q = positive_q.lower()
    for triggers, msg in SPECIAL_GROUP_ALERTS:
        if any(t in low_q or any(t in ex for ex in expanded) for t in triggers):
            safety_alerts.append(msg)

    # 2. Check Meridian Ziwu Clock matches
    matched_clocks = []
    for entry in MERIDIAN_TIME_RULES:
        if any(tok in positive_q for tok in entry["tokens"]):
            mer = entities.get(entry["meridian_id"], {})
            fs = mer.get("five_shu_table", {})
            matched_clocks.append(
                {
                    "window": entry["window"],
                    "meridian_id": entry["meridian_id"],
                    "meridian_name": entry["meridian_name"],
                    "rule": entry["rule"],
                    "five_shu": {
                        k: _entity_summary(entities.get(pid), pid)
                        for k, pid in fs.items()
                        if isinstance(pid, str) and pid in entities
                    },
                }
            )

    # 3. Check Channel Differentiation Guides
    guides = []
    for guide in CHANNEL_GUIDES:
        if any(t in positive_q or any(t in ex for ex in expanded) for t in guide["triggers"]):
            guides.append(guide)

    # Pre-index techniques related to points or conditions via relations
    cond_to_techs: dict[str, list[dict]] = {}
    pt_to_techs: dict[str, list[dict]] = {}
    for rel in relations:
        rtype = rel.get("relation_type")
        if rtype == "technique_to_condition":
            t_ent = entities.get(rel["from_id"])
            if t_ent:
                cond_to_techs.setdefault(rel["to_id"], []).append(_entity_summary(t_ent, rel["from_id"]))
        elif rtype == "acupoint_to_technique":
            t_ent = entities.get(rel["to_id"])
            if t_ent:
                pt_to_techs.setdefault(rel["from_id"], []).append(_entity_summary(t_ent, rel["to_id"]))

    # 4. Score Condition Sub-Patterns (primary 辨证分型推理链)
    asked_pregnancy = any(w in positive_q for w in ("孕", "胎", "产", "生育", "绝孕", "避孕", "分娩"))
    scored_patterns: list[dict] = []
    for cond in conditions:
        if risk_level and cond.get("risk_level") != risk_level:
            continue
        cond_title = f"{cond.get('canonical_name', '')} {' '.join(cond.get('aliases', []))}"
        c_score, c_hits = _score_text(cond_title, token_groups, weight=3)
        summary_score, s_hits = _score_text(cond.get("summary", ""), token_groups, weight=1)

        for pat in cond.get("sub_patterns", []):
            if meridian_id and meridian_id not in pat.get("related_meridian_ids", []):
                continue
            sym_text = " ".join(pat.get("symptoms", []))
            pname_text = pat.get("pattern_name", "")
            diff_text = f"{pat.get('syndrome_differentiation', '')} {pat.get('differentiation_notes', '')}"
            why_text = pat.get("why_selected", "")

            sc1, h1 = _score_text(sym_text, token_groups, weight=5)
            sc2, h2 = _score_text(pname_text, token_groups, weight=4)
            sc3, h3 = _score_text(diff_text, token_groups, weight=3)
            sc4, h4 = _score_text(why_text, token_groups, weight=2)
            total_sc = sc1 + sc2 + sc3 + sc4 + c_score + summary_score
            if total_sc <= 0:
                continue

            # Reward verbatim literal token matches across pattern fields
            combined_pat_low = f"{cond_title} {pname_text} {sym_text} {diff_text}".lower()
            exact_hits = sum(1 for tok in tokens if len(tok) >= 2 and tok.lower() in combined_pat_low)
            total_sc += exact_hits * 22

            # Index-only "(略)" chapter summary should rank below full-text clinical patterns
            if cond["id"] == "cond:ch6:s297":
                total_sc = max(1, total_sc // 3)
            # Do not let pregnancy-only protocols outrank general protocols unless user asks about pregnancy
            if not asked_pregnancy and any(w in pname_text or w in cond_title for w in ("孕期", "怀孕", "胎位", "绝孕")):
                total_sc = max(1, total_sc - 18)

            hit_tokens = []
            for h in h1 + h2 + h3 + h4 + c_hits + s_hits:
                if h not in hit_tokens:
                    hit_tokens.append(h)

            resolved_meridians = [
                {
                    **_entity_summary(entities.get(mid), mid),
                    "five_shu_table": entities.get(mid, {}).get("five_shu_table", {}),
                    "flow_hour": entities.get(mid, {}).get("flow_hour", ""),
                }
                for mid in pat.get("related_meridian_ids", [])
            ]
            resolved_points = [
                _enrich_point_brief(entities.get(pid), entities, pid)
                for pid in pat.get("referenced_point_ids", [])
            ]
            tech_map: dict[str, dict] = {
                t["id"]: t for t in cond_to_techs.get(cond["id"], [])
            }
            for pid in pat.get("referenced_point_ids", []):
                for t in pt_to_techs.get(pid, []):
                    tech_map[t["id"]] = t

            scored_patterns.append(
                {
                    "score": total_sc + len(hit_tokens) * 6,
                    "matched_tokens": hit_tokens,
                    "condition_id": cond["id"],
                    "condition_name": cond["canonical_name"],
                    "condition_page_range": cond.get("page_range", []),
                    "risk_level": cond.get("risk_level", "standard"),
                    "safety_warning": cond.get("safety_warning", ""),
                    "pattern_name": pat.get("pattern_name", ""),
                    "symptoms": pat.get("symptoms", []),
                    "syndrome_differentiation": pat.get("syndrome_differentiation", ""),
                    "why_selected": pat.get("why_selected", ""),
                    "differentiation_notes": pat.get("differentiation_notes", ""),
                    "open_questions": pat.get("open_questions", []),
                    "resolved_meridians": resolved_meridians,
                    "resolved_points": resolved_points,
                    "related_techniques": list(tech_map.values()),
                    "source_spans": pat.get("source_spans", []),
                }
            )

    scored_patterns.sort(key=lambda x: (-x["score"], x["condition_id"], x["pattern_name"]))
    top_patterns = scored_patterns[:limit_patterns]

    # 5. Score Acupoints directly (indications + layers + combinations + special categories)
    scored_points: list[tuple[int, list[str], dict]] = []
    for pt in acupoints:
        if meridian_id and pt.get("meridian_id") != meridian_id:
            continue
        if risk_level and pt.get("risk_level") != risk_level:
            continue
        ind_text = " ".join(pt.get("indications", []))
        name_text = f"{pt.get('canonical_name', '')} {' '.join(pt.get('aliases', []))}"
        cat_text = " ".join(pt.get("special_categories", []))
        combo_text = " ".join(
            f"{c.get('point_id', '')} {c.get('purpose', '')}" for c in pt.get("combinations", [])
        )
        layers = pt.get("content_layers", {})
        layer_text = " ".join(
            " ".join(layers.get(k, [])) for k in ("ni_teaching", "source_quote", "organizer_summary")
        )
        sc1, h1 = _score_text(ind_text, token_groups, weight=5)
        sc2, h2 = _score_text(name_text, token_groups, weight=5)
        sc3, h3 = _score_text(combo_text, token_groups, weight=3)
        sc4, h4 = _score_text(f"{cat_text} {pt.get('summary', '')} {layer_text}", token_groups, weight=2)
        total_sc = sc1 + sc2 + sc3 + sc4
        if total_sc <= 0:
            continue
        combined_pt_low = f"{name_text} {ind_text} {pt.get('summary', '')} {layer_text}".lower()
        exact_pt_hits = sum(1 for tok in tokens if len(tok) >= 2 and tok.lower() in combined_pt_low)
        total_sc += exact_pt_hits * 16
        if pt.get("review_status") == "approved":
            total_sc += 4
        hits = []
        for h in h1 + h2 + h3 + h4:
            if h not in hits:
                hits.append(h)
        scored_points.append((total_sc + len(hits) * 4, hits, pt))

    scored_points.sort(key=lambda x: (-x[0], x[2].get("id", "")))
    top_points = [
        {
            **_enrich_point_brief(pt, entities, pt["id"]),
            "score": sc,
            "matched_tokens": hits,
            "summary": pt.get("summary", ""),
            "combinations": [
                {
                    **cb,
                    "peer": _entity_summary(entities.get(cb.get("point_id", "")), cb.get("point_id", "")),
                }
                for cb in pt.get("combinations", [])
            ],
            "source_spans": pt.get("source_spans", [])[:2],
        }
        for sc, hits, pt in scored_points[:limit_points]
    ]

    # 6. Score Techniques / Rules
    scored_techs: list[tuple[int, dict]] = []
    for tech in techniques:
        if risk_level and tech.get("risk_level") != risk_level:
            continue
        blob = " ".join(
            [
                tech.get("canonical_name", ""),
                tech.get("clinical_purpose", ""),
                tech.get("summary", ""),
                " ".join(tech.get("steps_or_rules", [])),
            ]
        )
        sc, _ = _score_text(blob, token_groups, weight=2)
        if sc > 0:
            scored_techs.append((sc, tech))
    scored_techs.sort(key=lambda x: (-x[0], x[1]["id"]))
    top_techs = [
        {
            **_entity_summary(t, t["id"]),
            "category": t.get("category", ""),
            "clinical_purpose": t.get("clinical_purpose", ""),
            "summary": t.get("summary", ""),
            "cautions": t.get("cautions", ""),
            "source_spans": t.get("source_spans", [])[:1],
        }
        for _, t in scored_techs[:6]
    ]

    # 7. Book Index Terms + Textbook Page Fallback
    matched_idx = []
    for item in indexes.get("condition_index", []):
        sc, _ = _score_text(item["name"], token_groups, weight=3)
        if sc > 0:
            matched_idx.append((sc, item))
    matched_idx.sort(key=lambda x: (-x[0], x[1]["name"]))

    pages_by_num = _pages_by_num()
    matched_pages = []
    for pno, row in sorted(pages_by_num.items()):
        if pno < 11 or pno > 200:
            continue
        body = row.get("body_text", "")
        sc, hits = _score_text(body, token_groups, weight=2)
        if sc <= 0:
            continue
        snippet = ""
        for ln in body.splitlines():
            if any(syn in ln.lower() for syn in expanded if len(syn) >= 2):
                snippet = ln.strip()
                break
        if not snippet:
            snippet = (body.splitlines() or [""])[0].strip()
        matched_pages.append(
            {
                "pdf_page": pno,
                "printed_page": row.get("printed_page"),
                "score": sc + len(hits) * 4,
                "matched_tokens": hits,
                "snippet": snippet[:180],
            }
        )
    matched_pages.sort(key=lambda x: (-x["score"], x["pdf_page"]))

    # 8. Dynamic follow-up differential facets (only relevant ones not yet in query)
    follow_ups = [
        {"label": lbl, "chip": chip}
        for lbl, chip in COMMON_QUALIFIER_CHIPS
        if chip not in cleaned
    ]

    return {
        "query": cleaned,
        "tokens": tokens,
        "expanded_terms": expanded[:24],
        "safety_alerts": safety_alerts,
        "matched_meridian_clocks": matched_clocks,
        "channel_guides": guides,
        "matched_patterns": top_patterns,
        "matched_points": top_points,
        "matched_techniques": top_techs,
        "matched_indexes": [it for _, it in matched_idx[:16]],
        "matched_pages": matched_pages[:10],
        "follow_up_facets": follow_ups,
    }
