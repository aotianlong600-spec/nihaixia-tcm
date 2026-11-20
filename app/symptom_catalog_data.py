"""Original clinical symptom catalog, everyday symptom normalization aliases, and atom weight calibrations.

Strictly grounded in this repository's verified classical corpus:
- 《伤寒论》(112 formulas) / 《金匮要略》(187 formulas)
- 倪海厦《汉唐经方》(91 formulas) & 《人纪针灸》(34 conditions)
"""
from __future__ import annotations

from typing import Any


EVERYDAY_SYMPTOM_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("外感表证", ("感冒", "外感", "风寒感冒", "风热感冒", "伤风", "着凉", "受凉")),
    ("周身酸痛", ("全身痛", "浑身痛", "浑身酸痛", "周身疼痛", "身体疼痛", "身痛", "骨节烦疼")),
    ("黄涕鼻热", ("黄涕", "黄脓涕", "鼻流浊涕", "浊涕")),
    ("呼吸困难", ("呼吸困难", "喘不上气", "憋气", "胸闷气短", "呼吸急促", "气急")),
    ("痰多", ("多痰", "痰多", "咳痰", "白痰", "黄痰", "粘痰", "白泡沫痰")),
    ("声音沙哑", ("声音沙哑", "声音嘶哑", "声哑", "失音", "嘶哑", "咽哑", "嗓子哑")),
    ("肺炎肺热", ("肺炎", "肺热咳嗽", "咳黄脓痰", "肺痈")),
    ("口腔溃疡", ("口腔溃疡", "口疮", "口舌生疮", "舌疮", "狐惑")),
    ("口臭胃热", ("口臭", "口气重", "胃火", "牙龈肿痛")),
    ("反酸胃痛", ("胃酸过多", "胃酸", "反酸", "吐酸", "烧心", "胃灼热", "胃溃疡", "胃食管反流")),
    (
        "腹胀纳差",
        (
            "腹胀",
            "肚子胀",
            "胃胀气",
            "胀气",
            "消化不良",
            "肠胃虚弱",
            "脾胃虚弱",
            "食少",
            "纳差",
            "积食",
            "吃不下",
            "食欲不振",
            "小儿厌食",
            "厌食",
        ),
    ),
    ("痔疮便血", ("痔疮", "内痔", "外痔", "肛门肿痛", "肛裂", "脱肛")),
    (
        "胁痛肝郁",
        (
            "肝炎",
            "肝硬化",
            "脂肪肝",
            "肝区痛",
            "胁痛",
            "两胁胀痛",
            "易怒",
            "急躁易怒",
            "情绪烦躁",
            "肝火旺",
            "肝郁",
        ),
    ),
    ("消渴高糖", ("高血糖", "血糖高", "糖尿病", "消渴", "多饮多尿", "三多一少")),
    ("眩晕血压", ("高血压", "血压高", "头重脚轻", "面红头胀", "动脉硬化", "血脂高", "高血脂")),
    ("低血压贫血", ("低血压", "血压低", "贫血", "血虚", "面色苍白", "头晕眼花", "蹲起头晕", "体位性低血压")),
    ("心律不齐", ("心律不齐", "早搏", "房颤", "心跳不齐", "心慌气短", "心动过速", "心律失常")),
    (
        "前列腺尿频",
        (
            "前列腺增生",
            "前列腺肥大",
            "摄护腺肥大",
            "尿频",
            "尿急",
            "尿失禁",
            "漏尿",
            "排尿困难",
            "尿后余沥",
        ),
    ),
    ("阳痿早泄", ("阳痿", "勃起功能障碍", "早泄", "遗精", "滑精", "性功能减退", "肾虚")),
    ("月经不调", ("月经不调", "月经推迟", "月经提前", "经期紊乱", "月经过少", "月经过多", "闭经", "经闭", "不来月经")),
    ("症瘕肌瘤", ("子宫肌瘤", "卵巢囊肿", "乳腺增生", "乳房胀痛", "乳房结节", "盆腔积液", "症瘕")),
    ("更年期证", ("更年期", "更年期综合征", "潮热汗出", "烘热汗出", "绝经前后")),
    ("痤疮痘疹", ("青春痘", "痤疮", "粉刺", "长痘", "面部脓疱", "毛囊炎")),
    (
        "腰背痛",
        (
            "腰痛",
            "腰酸",
            "腰酸背痛",
            "腰肌劳损",
            "腰椎间盘突出",
            "坐骨神经痛",
        ),
    ),
    (
        "肩颈强痛",
        (
            "肩周炎",
            "肩膀痛",
            "五十肩",
            "落枕",
            "脖子痛",
            "颈椎病",
        ),
    ),
    ("脱发早白", ("脱发", "掉头发", "斑秃", "头发稀疏", "须发早白")),
]


# Additive/override symptom weights on existing PATTERN_ATOMS to ensure every common
# clinical symptom lands directly on authentic Jingfang primary formulas without disturbing
# multi-symptom differential & safety rules.
ATOM_WEIGHT_AUGMENTS: dict[str, dict[str, int]] = {
    # Exterior & Taiyang / Shaoyang / Yangming
    "atom:guizhi": {"外感表证": 22, "发热": 19, "头痛": 18, "周身酸痛": 14},
    "atom:mahuang-tang": {"外感表证": 19, "发热": 18, "头痛": 10, "周身酸痛": 20, "鼻症": 12},
    "atom:gegengtang": {"外感表证": 20, "发热": 18, "头痛": 19, "鼻症": 20, "肩颈强痛": 26, "周身酸痛": 16},
    "atom:guizhi-jia-gegen": {"肩颈强痛": 24, "外感表证": 14},
    "atom:xiaochaihu": {"发热": 20, "外感表证": 18, "胁痛肝郁": 22, "更年期证": 18, "症瘕肌瘤": 12},
    "atom:chaihu-guizhi": {"外感表证": 16, "周身酸痛": 16, "胁痛肝郁": 14},
    "atom:baihu": {"发热": 17, "消渴高糖": 16, "口臭胃热": 16},
    "atom:baihu-jiarenshen": {"消渴高糖": 24, "发热": 14},

    # Lung / ENT / Cough / Phlegm / Voice
    "atom:xiaoqinglong": {"咳喘痰多": 25, "鼻症": 24, "痰多": 22, "呼吸困难": 16},
    "atom:maxingshigan": {"咳喘痰多": 26, "肺炎肺热": 26, "呼吸困难": 22, "痰多": 20, "黄涕鼻热": 22, "鼻症": 14},
    "atom:tingli-dazao": {"咳喘痰多": 20, "呼吸困难": 18},
    "atom:yuebi-jia-banxia": {"肺炎肺热": 20, "呼吸困难": 18, "痰多": 16},
    "atom:linggan-wuwei-jiangxin": {"咳喘痰多": 22, "痰多": 22, "呼吸困难": 14},
    "atom:maimendong": {"咳喘痰多": 20, "声音沙哑": 18, "痰多": 10},
    "atom:kujiu-tang": {"声音沙哑": 26},
    "atom:banxia-san": {"声音沙哑": 20, "鼻症": 10},
    "atom:jiegeng-tang": {"声音沙哑": 16, "肺炎肺热": 16, "痰多": 12},
    "atom:mahuang-fuzi-xixin": {"鼻症": 18, "声音沙哑": 12},

    # Spleen / Stomach / Liver / Intestine / Metabolic
    "atom:lizhong": {"便溏": 24, "腹胀纳差": 20, "反酸胃痛": 12},
    "atom:wuling": {"便溏": 20, "眩晕血压": 14, "头痛": 10},
    "atom:gegen-qinlian": {"便溏": 18, "痤疮痘疹": 12},
    "atom:banxia-xiexin": {"反酸胃痛": 24, "腹胀纳差": 22, "便溏": 19, "口臭胃热": 14, "口腔溃疡": 14},
    "atom:gancao-xiexin": {"口腔溃疡": 26, "腹胀纳差": 14, "反酸胃痛": 14},
    "atom:shengjiang-xiexin": {"反酸胃痛": 20, "腹胀纳差": 18, "呃逆胃虚": 16, "便溏": 17},
    "atom:xuanfu-daizhe": {"反酸胃痛": 22, "腹胀纳差": 16, "痰多": 14},
    "atom:jupi-zhuru": {"呃逆胃虚": 24, "反酸胃痛": 14},
    "atom:xiaojianzhong": {"腹胀纳差": 24, "低血压贫血": 16, "心律不齐": 12},
    "atom:huangqi-jianzhong": {"腹胀纳差": 18, "低血压贫血": 20},
    "atom:wuzhuyu": {"反酸胃痛": 18, "头痛": 18},
    "atom:jinkui-xiexin": {"口臭胃热": 22, "口腔溃疡": 20, "痤疮痘疹": 20, "眩晕血压": 20},
    "atom:dahuang-huanglian-xiexin": {"口臭胃热": 20, "口腔溃疡": 18, "痤疮痘疹": 18, "眩晕血压": 18},
    "atom:chidou-danggui": {"痔疮便血": 26, "痤疮痘疹": 14},
    "atom:xiexin-huangtu": {"痔疮便血": 18, "低血压贫血": 16},
    "atom:sini-san": {"胁痛肝郁": 24, "腹胀纳差": 16, "阳痿早泄": 12},
    "atom:dachaihu": {"胁痛肝郁": 20, "眩晕血压": 18, "痤疮痘疹": 14, "口臭胃热": 14, "黄涕鼻热": 12},
    "atom:yinchenhao": {"胁痛肝郁": 18, "痤疮痘疹": 16},
    "atom:biejia-jianwan": {"胁痛肝郁": 22, "症瘕肌瘤": 18},

    # Heart / Blood Pressure / Arrhythmia / Mind
    "atom:zhigancao": {"心律不齐": 28, "低血压贫血": 20, "胸痹": 14, "呼吸困难": 12},
    "atom:gualou-xiebai-banxia": {"呼吸困难": 16, "心律不齐": 14, "痰多": 12},
    "atom:xiongbi": {"呼吸困难": 14, "心律不齐": 14},
    "atom:zhishi-xiebai-guizhi": {"呼吸困难": 12, "腹胀纳差": 12},
    "atom:linggui-zhugan": {"低血压贫血": 22, "眩晕血压": 18, "心律不齐": 16, "呼吸困难": 12, "痰多": 12},
    "atom:chaihu-longgu-muli": {"眩晕血压": 22, "心律不齐": 18, "胁痛肝郁": 16, "更年期证": 16},
    "atom:suanzaoren": {"心烦失眠": 28, "低血压贫血": 12},
    "atom:huanglian-ejiao": {"心烦失眠": 27, "口腔溃疡": 16, "更年期证": 14},

    # Kidney / Urinary / Andrology
    "atom:zhenwu": {"眩晕血压": 16, "低血压贫血": 14, "前列腺尿频": 16, "腰背痛": 18},
    "atom:shenqi-wan": {"消渴高糖": 22, "前列腺尿频": 24, "阳痿早泄": 24, "腰背痛": 24, "脱发早白": 22, "低血压贫血": 12, "眩晕血压": 16},
    "atom:zhuling": {"前列腺尿频": 18, "淋痛尿血": 26},
    "atom:gualou-qumai": {"前列腺尿频": 20, "消渴高糖": 16},
    "atom:guizhi-longgu-muli": {"阳痿早泄": 26, "脱发早白": 18, "心烦失眠": 16},
    "atom:tianxiong-san": {"阳痿早泄": 20, "前列腺尿频": 14},

    # Gynecology / Skin / Musculoskeletal
    "atom:wenjing": {"月经不调": 26, "更年期证": 20, "症瘕肌瘤": 16, "脱发早白": 12},
    "atom:guizhi-fuling": {"症瘕肌瘤": 28, "月经不调": 20, "痤疮痘疹": 20, "腰背痛": 12},
    "atom:danggui-shaoyao": {"月经不调": 22, "低血压贫血": 20, "症瘕肌瘤": 16, "腰背痛": 14},
    "atom:jiaoai": {"月经不调": 18, "低血压贫血": 18},
    "atom:ganmai-dazao": {"更年期证": 24, "胁痛肝郁": 14},
    "atom:guizhi-fuzi": {"腰背痛": 22, "肩颈强痛": 20, "周身酸痛": 18},
    "atom:shaoyao-gancao": {"腰背痛": 14, "脚挛急": 32},
    "atom:mahuang-lianqiao-chixiaodou": {"痤疮痘疹": 18},
    "atom:painong-san": {"痤疮痘疹": 22},
    "atom:taohe-chengqi": {"月经不调": 14, "痤疮痘疹": 16},
    "atom:danggui-sini": {"脱发早白": 12, "低血压贫血": 14, "腰背痛": 14},
}


# 64 common symptoms across 9 clinical categories for progressive symptom inquiry UX.
SYMPTOM_CATALOG: list[dict[str, Any]] = [
    # 1. 外感发热
    {"id": "sym:ganmao", "name": "感冒", "category": "外感发热", "aliases": "外感 风寒 风热 伤风", "hint": "桂枝汤 / 麻黄汤 / 葛根汤 / 小柴胡汤"},
    {"id": "sym:fashao", "name": "发烧", "category": "外感发热", "aliases": "发热 高烧 壮热", "hint": "小柴胡汤 / 桂枝汤 / 麻黄汤 / 白虎汤"},
    {"id": "sym:ehan", "name": "恶寒", "category": "外感发热", "aliases": "怕冷 畏寒 身冷", "hint": "麻黄汤 / 桂枝加附子 / 真武汤"},
    {"id": "sym:wanglai", "name": "往来寒热", "category": "外感发热", "aliases": "忽冷忽热 寒热往来 少阳", "hint": "小柴胡汤 / 柴胡桂枝干姜汤"},
    {"id": "sym:quanshentong", "name": "全身痛", "category": "外感发热", "aliases": "周身疼痛 浑身酸痛 身疼", "hint": "麻黄汤 / 葛根汤 / 桂枝附子汤"},
    {"id": "sym:touyun", "name": "头晕", "category": "外感发热", "aliases": "眩晕 目眩 天旋地转", "hint": "苓桂术甘汤 / 真武汤 / 五苓散"},
    {"id": "sym:toutong", "name": "头痛", "category": "外感发热", "aliases": "偏头痛 巅顶痛 前额痛", "hint": "葛根汤 / 吴茱萸汤 / 桂枝汤"},

    # 2. 肺系五官
    {"id": "sym:kesou", "name": "咳嗽", "category": "肺系五官", "aliases": "久咳 干咳 咳喘", "hint": "小青龙汤 / 麻杏石甘汤 / 麦门冬汤"},
    {"id": "sym:huxikunnan", "name": "呼吸困难", "category": "肺系五官", "aliases": "气喘 哮喘 喘不上气 憋气", "hint": "小青龙汤 / 麻杏石甘汤 / 越婢加半夏汤"},
    {"id": "sym:duotan", "name": "多痰", "category": "肺系五官", "aliases": "痰多 白痰 黄痰 咳痰", "hint": "小青龙汤 / 苓甘五味姜辛汤 / 麻杏石甘汤"},
    {"id": "sym:feiyan", "name": "肺炎", "category": "肺系五官", "aliases": "肺热咳嗽 肺痈 咳脓痰", "hint": "麻杏石甘汤 / 桔梗汤 / 越婢加半夏汤"},
    {"id": "sym:biyan", "name": "鼻炎", "category": "肺系五官", "aliases": "过敏性鼻炎 鼻渊 喷嚏", "hint": "小青龙汤 / 葛根汤 · 汉唐HT-39鼻渊丸"},
    {"id": "sym:bisai", "name": "鼻塞", "category": "肺系五官", "aliases": "流涕 不通气 鼻窦炎", "hint": "葛根汤 / 小青龙汤 / 麻黄附子细辛汤"},
    {"id": "sym:huangti", "name": "黄涕", "category": "肺系五官", "aliases": "黄脓涕 鼻窦炎浊涕", "hint": "麻杏石甘汤 / 大柴胡汤 · HT-81"},
    {"id": "sym:yanhoutong", "name": "咽喉痛", "category": "肺系五官", "aliases": "喉咙痛 扁桃体 梅核气", "hint": "半夏散及汤 / 桔梗汤 / 猪肤汤"},
    {"id": "sym:shengyasha", "name": "声音沙哑", "category": "肺系五官", "aliases": "嘶哑 失音 咽哑", "hint": "苦酒汤 / 麦门冬汤 / 半夏散及汤"},
    {"id": "sym:erming", "name": "耳鸣", "category": "肺系五官", "aliases": "耳聋 暴聋 蝉鸣", "hint": "肾气丸 / 麻黄附子细辛汤 · HT-34"},
    {"id": "sym:kouqiang", "name": "口腔溃疡", "category": "肺系五官", "aliases": "口疮 口舌生疮 狐惑", "hint": "甘草泻心汤 / 泻心汤 / 大黄黄连泻心汤"},
    {"id": "sym:kouchou", "name": "口臭", "category": "肺系五官", "aliases": "胃火 口气重 牙龈肿痛", "hint": "泻心汤 / 白虎汤 / 半夏泻心汤"},

    # 3. 脾胃消化
    {"id": "sym:weitong", "name": "胃痛", "category": "脾胃消化", "aliases": "胃脘痛 心下痞 胃溃疡", "hint": "半夏泻心汤 / 小建中汤 / 理中丸"},
    {"id": "sym:weisuan", "name": "胃酸过多", "category": "脾胃消化", "aliases": "反酸 吐酸 烧心 反流", "hint": "半夏泻心汤 / 旋覆代赭汤 · HT-78健胃散"},
    {"id": "sym:fuzhang", "name": "腹胀", "category": "脾胃消化", "aliases": "胃胀 胀气 肚子胀", "hint": "半夏泻心汤 / 小建中汤 / 厚朴生姜半夏"},
    {"id": "sym:xiaohua", "name": "消化不良", "category": "脾胃消化", "aliases": "肠胃虚弱 食少 积食 纳差", "hint": "小建中汤 / 理中丸 / 半夏泻心汤"},
    {"id": "sym:dage", "name": "打嗝", "category": "脾胃消化", "aliases": "呃逆 嗳气 噫气 哕", "hint": "旋覆代赭石汤 / 橘皮竹茹汤 / 生姜泻心汤"},
    {"id": "sym:outu", "name": "呕吐", "category": "脾胃消化", "aliases": "恶心 干呕 反胃", "hint": "半夏泻心汤 / 吴茱萸汤 / 旋覆代赭石汤"},
    {"id": "sym:fuxie", "name": "腹泻", "category": "脾胃消化", "aliases": "拉肚子 泄泻 便溏 五更泻", "hint": "理中丸 / 五苓散 / 葛根黄芩黄连汤"},
    {"id": "sym:bianmi", "name": "便秘", "category": "脾胃消化", "aliases": "大便干 排便困难 燥屎", "hint": "麻子仁丸 / 大承气汤 / 润肠寒热分流"},
    {"id": "sym:zhichuang", "name": "痔疮", "category": "脾胃消化", "aliases": "内痔 外痔 近血 便血", "hint": "赤豆当归散 / 黄土汤 · HT-9/HT-29"},
    {"id": "sym:futong", "name": "腹痛", "category": "脾胃消化", "aliases": "肚子痛 绕脐痛 右下腹痛", "hint": "小建中汤 / 大黄牡丹汤 / 当归芍药散"},

    # 4. 心胸血脉
    {"id": "sym:gaoxueya", "name": "高血压", "category": "心胸血脉", "aliases": "血压高 肝阳上亢 头胀", "hint": "柴胡加龙骨牡蛎汤 / 泻心汤 · HT-23"},
    {"id": "sym:dixueya", "name": "低血压", "category": "心胸血脉", "aliases": "头晕眼花 蹲起发黑 血虚", "hint": "苓桂术甘汤 / 炙甘草汤 / 黄耆建中汤"},
    {"id": "sym:guanxinbing", "name": "冠心病", "category": "心胸血脉", "aliases": "心绞痛 心肌缺血 胸闷痛", "hint": "栝蒌薤白半夏汤 / 栝蒌薤白白酒汤 · HT-77"},
    {"id": "sym:xinlvbuqi", "name": "心律不齐", "category": "心胸血脉", "aliases": "早搏 房颤 脉结代 心慌", "hint": "炙甘草汤 / 苓桂术甘汤 / 柴胡加龙骨牡蛎"},
    {"id": "sym:banmo", "name": "心脏瓣膜病", "category": "心胸血脉", "aliases": "心脏肥大 第五椎压痛 胸痹", "hint": "栝蒌薤白白酒汤 · HT-87心脏肥大"},
    {"id": "sym:xinji", "name": "心悸", "category": "心胸血脉", "aliases": "心慌 心动悸 惊悸", "hint": "炙甘草汤 / 苓桂术甘汤 / 桂枝甘草汤"},
    {"id": "sym:pinxue", "name": "贫血", "category": "心胸血脉", "aliases": "面色苍白 气血两虚 血虚", "hint": "炙甘草汤 / 黄耆建中汤 / 当归芍药散"},
    {"id": "sym:chuxue", "name": "出血", "category": "心胸血脉", "aliases": "吐血 鼻衄 流鼻血 便血", "hint": "泻心汤 / 黄土汤 / 柏叶汤"},
    {"id": "sym:gaoxuetang", "name": "高血糖", "category": "心胸血脉", "aliases": "糖尿病 消渴 多饮多尿", "hint": "白虎加人参汤 / 肾气丸 · HT-24降血糖"},

    # 5. 肝胆情志
    {"id": "sym:shimian", "name": "失眠", "category": "肝胆情志", "aliases": "心烦 彻夜难眠 多梦", "hint": "酸枣仁汤 / 黄连阿胶汤 · HT-41中安丸"},
    {"id": "sym:yinu", "name": "易怒", "category": "肝胆情志", "aliases": "急躁 烦躁 肝郁 胸胁苦满", "hint": "四逆散 / 小柴胡汤 / 大柴胡汤"},
    {"id": "sym:ganyan", "name": "肝炎", "category": "肝胆情志", "aliases": "肝区不适 口苦 胁痛 黄疸", "hint": "小柴胡汤 / 四逆散 / 茵陈蒿汤 · HT-68"},
    {"id": "sym:zhifanggan", "name": "脂肪肝", "category": "肝胆情志", "aliases": "高血脂 胁胀 脾湿肝郁", "hint": "四逆散 / 大柴胡汤 / 茵陈蒿汤"},
    {"id": "sym:ganyinghua", "name": "肝硬化", "category": "肝胆情志", "aliases": "癥瘕 腹水 第9椎 阴黄", "hint": "鳖甲煎丸 / 小柴胡汤 · HT-10/HT-68"},
    {"id": "sym:danjieshi", "name": "胆结石", "category": "肝胆情志", "aliases": "胆囊炎 右胁痛 黄疸", "hint": "大柴胡汤 / 茵陈五苓散 · HT-14胆石症"},

    # 6. 泌尿男科
    {"id": "sym:shenjieshi", "name": "肾结石", "category": "泌尿男科", "aliases": "尿道结石 输尿管结石 砂淋", "hint": "猪苓汤 / 赤豆当归散 · HT-26石淋"},
    {"id": "sym:pangguangjieshi", "name": "膀胱结石", "category": "泌尿男科", "aliases": "尿路结石 小便痛 血尿", "hint": "猪苓汤 / 五苓散 · HT-65"},
    {"id": "sym:xiaobiantong", "name": "小便痛", "category": "泌尿男科", "aliases": "尿痛 尿道炎 血尿 淋痛", "hint": "猪苓汤 / 赤豆当归散 · HT-13"},
    {"id": "sym:qianliexian", "name": "前列腺增生", "category": "泌尿男科", "aliases": "前列腺肥大 尿频 夜尿多 尿失禁", "hint": "肾气丸 / 栝蒌瞿麦丸 · HT-66"},
    {"id": "sym:niaopin", "name": "尿频", "category": "泌尿男科", "aliases": "夜尿多 尿失禁 尿急 漏尿", "hint": "肾气丸 / 桂枝龙骨牡蛎汤"},
    {"id": "sym:yangwei", "name": "阳痿", "category": "泌尿男科", "aliases": "早泄 遗精 滑精 肾阳不足", "hint": "桂枝龙骨牡蛎汤 / 肾气丸 · HT-37/HT-49"},
    {"id": "sym:shuizhong", "name": "水肿", "category": "泌尿男科", "aliases": "浮肿 小便不利 肾积水", "hint": "真武汤 / 五苓散 / 防己黄耆汤"},

    # 7. 妇科专病
    {"id": "sym:tongjing", "name": "痛经", "category": "妇科专病", "aliases": "行经腹痛 经水血块 宫寒", "hint": "当归芍药散 / 温经汤 / 桂枝茯苓丸"},
    {"id": "sym:yuejingbutiao", "name": "月经不调", "category": "妇科专病", "aliases": "经期紊乱 闭经 经少 经多", "hint": "温经汤 / 当归芍药散 / 桂枝茯苓丸"},
    {"id": "sym:zigongjiliu", "name": "子宫肌瘤", "category": "妇科专病", "aliases": "卵巢囊肿 胞宫癥瘕 少腹硬痛", "hint": "桂枝茯苓丸 / 温经汤 · HT-8子宫症痼"},
    {"id": "sym:ruxian", "name": "乳腺增生", "category": "妇科专病", "aliases": "乳房胀痛 经前乳胀 结节", "hint": "桂枝茯苓丸 / 小柴胡汤 · HT-5"},
    {"id": "sym:baidai", "name": "白带", "category": "妇科专病", "aliases": "带下 赤白带 下焦湿寒", "hint": "胶艾汤 / 当归芍药散 · HT-1白带丸"},
    {"id": "sym:gengnianqi", "name": "更年期", "category": "妇科专病", "aliases": "潮热盗汗 烘热 脏燥", "hint": "甘麦大枣汤 / 温经汤 / 小柴胡汤 · HT-64"},

    # 8. 筋骨皮肤
    {"id": "sym:yaotong", "name": "腰痛", "category": "筋骨皮肤", "aliases": "腰酸 腰椎间盘突出 坐骨神经痛", "hint": "肾气丸 / 桂枝附子汤 · HT-30"},
    {"id": "sym:jianzhouyan", "name": "肩周炎", "category": "筋骨皮肤", "aliases": "五十肩 落枕 脖子痛 项背强", "hint": "葛根汤 / 桂枝加葛根汤 / 桂枝附子汤"},
    {"id": "sym:jiaochoujin", "name": "脚抽筋", "category": "筋骨皮肤", "aliases": "小腿抽筋 脚挛急 夜间抽筋", "hint": "芍药甘草汤 / 芍药甘草附子汤"},
    {"id": "sym:guanjie", "name": "关节痛", "category": "筋骨皮肤", "aliases": "风湿 痛风 历节 脚肿如脱", "hint": "桂枝芍药知母汤 / 乌头汤 / 桂枝附子汤"},
    {"id": "sym:qingchundou", "name": "青春痘", "category": "筋骨皮肤", "aliases": "痤疮 粉刺 面部脓疱", "hint": "排脓散 / 桂枝茯苓丸 / 泻心汤 · HT-79"},
    {"id": "sym:shizhen", "name": "湿疹", "category": "筋骨皮肤", "aliases": "皮肤湿疹 流黄水 皮肤干燥 瘙痒", "hint": "五苓散 / 麻黄连轺赤小豆 · HT-16/HT-17"},
    {"id": "sym:tuofa", "name": "脱发", "category": "筋骨皮肤", "aliases": "掉头发 斑秃 须发早白", "hint": "肾气丸 / 桂枝龙骨牡蛎汤 · HT-34"},

    # 9. 儿科常见
    {"id": "sym:xiaoeryanshi", "name": "小儿厌食", "category": "儿科常见", "aliases": "小儿脾虚 挑食 积食 腹痛", "hint": "小建中汤 / 黄耆建中汤 / 理中丸"},
]
