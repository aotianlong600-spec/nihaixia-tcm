"""Backend read-only catalog & clinical matching for Hantang formulas & Ni Haixia case laws."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "brain_data" / "hantang" / "hantang_catalog.json"

_DU_TRIGGERS: dict[str, tuple[str, ...]] = {
    "du:t3-shenzhu": ("3椎", "三椎", "第三椎", "身柱", "肺积水", "肺癌", "胸水", "凌晨3点", "白泡沫痰"),
    "du:t5-shendao": ("5椎", "五椎", "第五椎", "神道", "红斑狼疮", "SLE", "红斑", "乳癌", "更年期", "失眠"),
    "du:t6-lingtai": ("6椎", "六椎", "第六椎", "灵台", "血癌", "白血病", "淋巴"),
    "du:t9-jinsuo": ("9椎", "九椎", "第九椎", "筋缩", "肝癌", "肝硬化", "阴黄", "凌晨1点"),
    "du:t13-xuanshu": ("13椎", "十三椎", "第十三椎", "悬枢", "淋巴癌", "三焦", "网膜", "4椎", "骨瘤"),
}

_PALP_TRIGGERS: dict[str, tuple[str, ...]] = {
    "palp:danshi": ("胆石", "胆结石", "胆囊", "章门", "阳陵泉", "右胁", "胁痛"),
    "palp:shenshi": ("肾石", "肾结石", "腰剧痛", "太溪", "血尿"),
    "palp:lanwei-sanyinjiao-tianshu": ("阑尾", "盲肠", "天枢", "三阴交", "肌瘤", "宿便", "少腹"),
    "palp:shougan-zuleng": ("摄护腺", "前列腺", "手干", "手裂", "下焦寒实", "足冷", "手脚冰冷"),
    "palp:eliang-zunuan": ("癫痫", "多动", "过动", "头冷足温", "心肾相交"),
    "palp:coronary4": ("冠心病", "心绞痛", "中风", "手指麻", "脚趾麻", "胸闷", "刺痛", "失眠", "大便交替"),
}

_REDLINE_TRIGGERS: dict[str, tuple[str, ...]] = {
    "ht-rl-1": ("白血病", "红斑狼疮", "SLE", "淋巴", "肝癌", "脑瘤", "肺癌", "乳汁", "通乳"),
    "ht-rl-2": ("经期", "月经", "经水", "热入血室", "往来寒热"),
    "ht-rl-3": ("绝经", "更年期", "雌激素", "荷尔蒙", "HRT", "穿刺", "切片", "骨松", "钙片"),
    "ht-rl-4": ("胃出血", "吐血", "胃痈", "胃癌", "切胃", "胃切除", "化疗"),
    "ht-rl-5": ("膀胱结石", "尿路结石", "血尿", "热淋", "小便刺痛"),
    "ht-rl-6": ("痛风", "心脏肥大", "瓣膜", "心颤", "赤丸"),
    "ht-rl-7": ("肝癌", "肝硬化", "肝病", "排毒", "阴黄", "黄疸"),
    "ht-rl-8": ("外用", "乳癌", "雄黄", "砒"),
    "ht-rl-9": ("鼻衄", "流鼻血", "便秘", "干地黄"),
    "ht-rl-10": ("消渴", "糖尿病", "胃酸", "反酸", "吐酸"),
}


_PATHO_GENERIC_TOKENS: frozenset[str] = frozenset({
    "感冒", "发烧", "发热", "发冷", "怕冷", "咳嗽", "拉肚子", "腹泻", "便溏",
    "头痛", "头晕", "呕吐", "疲劳", "熬夜", "吹冷气", "冷饮", "西药", "抗生素",
})

_HT_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "高血糖": ("糖尿病", "消渴"),
    "血糖高": ("糖尿病", "消渴"),
    "前列腺增生": ("前列腺肥大", "摄护腺肥大", "夜尿频"),
    "前列腺炎": ("前列腺肥大", "尿道炎"),
    "尿道结石": ("膀胱结石", "肾结石", "尿路结石", "砂淋"),
    "输尿管结石": ("肾结石", "膀胱结石", "砂淋"),
    "痔疮": ("内痔", "外痔", "近血", "便后滴血"),
    "鼻塞": ("鼻炎", "鼻渊", "流清涕"),
    "黄涕": ("鼻炎", "鼻渊"),
    "心脏瓣膜病": ("瓣膜不全", "心脏肥大"),
    "心律不齐": ("心颤", "心悸"),
    "动脉硬化": ("冠心病", "高血压", "高甘油三酯"),
    "高血脂": ("高甘油三酯",),
    "脂肪肝": ("高甘油三酯", "乙肝", "护肝"),
    "肝炎": ("乙肝", "护肝"),
    "肝硬化": ("肝硬化", "阴黄"),
    "胃胀": ("胃溃疡", "胃酸过多"),
    "反酸": ("胃酸过多", "胃溃疡"),
    "烧心": ("胃酸过多",),
    "消化不良": ("胃溃疡", "胃下垂"),
    "月经不调": ("痛经", "经少", "经前乳胀"),
    "闭经": ("经少", "痛经", "宫寒"),
    "乳腺增生": ("乳房硬块", "经前乳胀"),
    "粉刺": ("青春痘", "痤疮"),
    "痘痘": ("青春痘", "痤疮"),
    "口疮": ("口腔溃疡",),
    "掉头发": ("脱发",),
    "腰椎间盘突出": ("坐骨神经痛",),
    "腰痛": ("坐骨神经痛", "髋关节痛"),
    "多动症": ("小儿多动症",),
}


def _norm(value: str) -> str:
    return re.sub(r"[\s·・，,。；;：:（）()“”\"'、\-_]+", "", value or "").lower()


def _extract_ht_num(token: str) -> int | None:
    m = re.fullmatch(r"(?:hantang:)?ht[-_\s]?0*(\d{1,3})", (token or "").strip(), re.I)
    if m:
        return int(m.group(1))
    if re.fullmatch(r"0*\d{1,3}", (token or "").strip()):
        return int(token.strip())
    return None


@lru_cache(maxsize=1)
def _load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _redline_ht_nums(redline: dict[str, Any]) -> set[int]:
    return {int(n) for n in re.findall(r"\d+", redline.get("ref", ""))}


def overview() -> dict[str, Any]:
    """Return high-level Hantang catalog overview, diagnostics, western rules, redlines & cases."""
    cat = _load_catalog()
    safety_counts: dict[str, int] = {}
    for item in cat.get("formulas", []):
        lv = item.get("safety_level", "standard")
        safety_counts[lv] = safety_counts.get(lv, 0) + 1
    return {
        "version": cat.get("version"),
        "formula_count": cat.get("formula_count", len(cat.get("formulas", []))),
        "missing_numbers": cat.get("missing_numbers", []),
        "source_books": cat.get("source_books", []),
        "epistemic_notice": cat.get("epistemic_notice", ""),
        "categories": cat.get("categories", []),
        "safety_counts": safety_counts,
        "du_spine_diagnostics": cat.get("du_spine_diagnostics", []),
        "special_palpation_points": cat.get("special_palpation_points", []),
        "western_history_rules": cat.get("western_history_rules", []),
        "prognosis_and_recovery_criteria": cat.get("prognosis_and_recovery_criteria", {}),
        "clinical_redlines": cat.get("clinical_redlines", []),
        "cases_index": cat.get("cases_index", []),
    }


def _score_formula_search(item: dict[str, Any], q_raw: str, q_tokens: list[str], exact_num: int | None) -> int:
    if exact_num is not None:
        return 100 if item["num"] == exact_num else 0
    score = 0
    q_norm = _norm(q_raw)
    name_norm = _norm(item.get("name", ""))
    if q_norm and q_norm == name_norm:
        score += 40
    elif q_norm and q_norm in name_norm:
        score += 20

    tags = item.get("clinical_tags", [])
    classic_names = [c.get("name", "") for c in item.get("ziji_note", {}).get("linked_classical_formulas", [])]
    point_names = [p.get("name", "") for p in item.get("ziji_note", {}).get("linked_acupoints", [])]
    ni = item.get("ni_original", {})
    body_blob = " ".join(
        [
            item.get("full_title", ""),
            item.get("category", ""),
            ni.get("indications", ""),
            ni.get("pathogenesis", ""),
            ni.get("partial_herbs", ""),
            ni.get("contraindications", ""),
            item.get("ziji_note", {}).get("commentary", ""),
            " ".join(classic_names),
            " ".join(point_names),
        ]
    )
    body_norm = _norm(body_blob)

    # Whole-query substring boost for compound phrases like 胆切除 / 热药冷服
    if q_norm and q_norm in body_norm:
        score += 12

    for tok in q_tokens:
        if len(tok) < 2:
            continue
        tnorm = _norm(tok)
        if not tnorm:
            continue
        if any(tnorm in _norm(tg) or _norm(tg) in tnorm for tg in tags if len(_norm(tg)) >= 2):
            score += 8
        elif tnorm in name_norm:
            score += 10
        elif tnorm in body_norm:
            score += 4
    return score


def list_formulas(category: str = "", safety: str = "", q: str = "") -> dict[str, Any]:
    """Filter and search the 91 Hantang formulas by category, safety tier, or query."""
    cat = _load_catalog()
    formulas = cat.get("formulas", [])
    q_clean = (q or "").strip()
    exact_num = _extract_ht_num(q_clean) if q_clean else None
    q_tokens = [t for t in re.split(r"[\s,，;；/、+]+", q_clean) if t]

    filtered: list[tuple[int, dict[str, Any]]] = []
    for item in formulas:
        if category and category != "all":
            if category not in (item.get("category_id"), item.get("category_short"), item.get("category")):
                continue
        if safety and safety != "all" and item.get("safety_level") != safety:
            continue
        if q_clean:
            sc = _score_formula_search(item, q_clean, q_tokens, exact_num)
            if sc <= 0:
                continue
            filtered.append((sc, item))
        else:
            filtered.append((0, item))

    if q_clean:
        filtered.sort(key=lambda pair: (-pair[0], pair[1]["num"]))
    items = [pair[1] for pair in filtered]
    return {
        "total": len(items),
        "category": category,
        "safety": safety,
        "q": q_clean,
        "epistemic_notice": cat.get("epistemic_notice", ""),
        "items": items,
    }


def get_formula(formula_id: str) -> dict[str, Any] | None:
    """Resolve one Hantang formula by id, HT-number, number, or Chinese name."""
    cat = _load_catalog()
    formulas = cat.get("formulas", [])
    raw = (formula_id or "").strip()
    if not raw:
        return None
    target_num = _extract_ht_num(raw)
    raw_norm = _norm(raw)

    match: dict[str, Any] | None = None
    for item in formulas:
        if item["id"].lower() == raw.lower():
            match = item
            break
        if target_num is not None and item["num"] == target_num:
            match = item
            break
        base_name = item["name"].split("（")[0]
        if raw_norm and raw_norm in (_norm(item["name"]), _norm(base_name)):
            match = item
            break
    if not match:
        return None

    ht_code = match["ht_number"]
    ht_num = match["num"]
    related_redlines = [rl for rl in cat.get("clinical_redlines", []) if ht_num in _redline_ht_nums(rl)]
    related_western = [wr for wr in cat.get("western_history_rules", []) if ht_code in wr.get("linked_ht", [])]
    related_cases = [cs for cs in cat.get("cases_index", []) if ht_code in cs.get("formulas", [])]
    return {
        **match,
        "epistemic_notice": cat.get("epistemic_notice", ""),
        "related_redlines": related_redlines,
        "related_western_rules": related_western,
        "related_cases": related_cases,
    }


def _match_by_triggers(items: list[dict[str, Any]], trigger_map: dict[str, tuple[str, ...]], hay_norm: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for item in items:
        kws = trigger_map.get(item.get("id", ""), ())
        matched_kws = [kw for kw in kws if _norm(kw) and _norm(kw) in hay_norm]
        if matched_kws:
            hits.append({**item, "matched_triggers": matched_kws})
    return hits


def match_clinical_context(
    q: str = "",
    symptoms: list[str] | None = None,
    pulses: list[str] | None = None,
    suppressed_names: list[str] | None = None,
    limit: int = 4,
) -> dict[str, Any]:
    """Match Hantang formulas, Du spine diagnostics, Western intervention rules & prognosis cues."""
    cat = _load_catalog()
    raw_parts = [q or "", *(symptoms or []), *(pulses or [])]
    combined = " ".join(p for p in raw_parts if p).strip()
    if not combined:
        return {
            "hantang_formulas": [],
            "western_history_guidance": [],
            "du_spine_guides": [],
            "special_palpations": [],
            "ht_redlines": [],
            "prognosis_summary": {},
        }

    hay_norm = _norm(combined)

    # 1. Western history interventions
    western_hits: list[dict[str, Any]] = []
    boosted_ht_codes: set[str] = set()
    for wr in cat.get("western_history_rules", []):
        matched_tr = [tr for tr in wr.get("triggers", []) if _norm(tr) in hay_norm]
        if matched_tr:
            western_hits.append({**wr, "matched_triggers": matched_tr})
            boosted_ht_codes.update(wr.get("linked_ht", []))

    # 2. Du spine diagnostics & special palpation points
    du_hits = _match_by_triggers(cat.get("du_spine_diagnostics", []), _DU_TRIGGERS, hay_norm)
    palp_hits = _match_by_triggers(cat.get("special_palpation_points", []), _PALP_TRIGGERS, hay_norm)

    # 3. Score candidate HT formulas against symptoms, query tokens, explicit HT numbers & Western boosts
    explicit_nums = {int(n) for n in re.findall(r"ht[-_\s]?0*(\d{1,3})", combined, re.I)}
    tokens = [t for t in re.split(r"[\s,，;；/、+]+", combined) if t]
    for s in symptoms or []:
        if s and s not in tokens:
            tokens.append(s)
    alias_tokens: list[str] = []
    for tok in list(tokens):
        tn = _norm(tok)
        for k, vals in _HT_QUERY_ALIASES.items():
            kn = _norm(k)
            if kn and (kn == tn or kn in hay_norm):
                for v in vals:
                    if v not in alias_tokens and v not in tokens:
                        alias_tokens.append(v)
    search_tokens = tokens + alias_tokens

    scored_ht: list[tuple[int, dict[str, Any], list[str]]] = []
    for item in cat.get("formulas", []):
        sc = 0
        reasons: list[str] = []
        if item["num"] in explicit_nums:
            sc += 50
            reasons.append(f"点名 {item['ht_number']}")
        if item["ht_number"] in boosted_ht_codes:
            sc += 18
            reasons.append("西医介入史关联方")

        base_name = _norm(item["name"].split("（")[0])
        if len(base_name) >= 2 and base_name in hay_norm:
            sc += 18
            reasons.append(f"命中方名「{item['name']}」")

        matched_tags: list[str] = []
        for tg in item.get("clinical_tags", []):
            tn = _norm(tg)
            if len(tn) < 2:
                continue
            direct_hit = tn in hay_norm
            alias_hit = any(
                len(_norm(tok)) >= 2
                and (
                    tn == _norm(tok)
                    or (tok not in _PATHO_GENERIC_TOKENS and (_norm(tok) in tn or tn in _norm(tok)))
                )
                for tok in search_tokens
            )
            if direct_hit or alias_hit:
                matched_tags.append(tg)
        if matched_tags:
            sc += 6 * min(len(matched_tags), 4)
            reasons.append("标签命中：" + "、".join(matched_tags[:4]))

        ind_norm = _norm(item.get("ni_original", {}).get("indications", ""))
        patho_norm = _norm(item.get("ni_original", {}).get("pathogenesis", ""))
        hit_ind_tokens = [
            tok for tok in search_tokens
            if tok not in _PATHO_GENERIC_TOKENS and len(_norm(tok)) >= 2 and _norm(tok) in ind_norm
        ]
        if hit_ind_tokens:
            sc += 4 * min(len(hit_ind_tokens), 3)
            if not matched_tags:
                reasons.append("主治病机相合：" + "、".join(hit_ind_tokens[:3]))

        # Only allow non-generic pathogenesis matches when indications/tags/Western-history already support this formula
        if sc >= 4:
            hit_patho_tokens = [
                tok for tok in tokens
                if tok not in _PATHO_GENERIC_TOKENS and len(_norm(tok)) >= 2 and _norm(tok) in patho_norm and tok not in hit_ind_tokens
            ]
            if hit_patho_tokens:
                sc += 2 * min(len(hit_patho_tokens), 2)

        if sc > 0:
            scored_ht.append((sc, item, reasons))

    scored_ht.sort(key=lambda row: (-row[0], row[1]["num"]))
    matched_formulas = []
    matched_ht_nums: set[int] = set()
    for sc, item, reasons in scored_ht[: max(1, min(limit, 8))]:
        matched_ht_nums.add(item["num"])
        matched_formulas.append(
            {
                "id": item["id"],
                "num": item["num"],
                "ht_number": item["ht_number"],
                "name": item["name"],
                "full_title": item["full_title"],
                "category_short": item["category_short"],
                "safety_level": item["safety_level"],
                "indications": item["ni_original"]["indications"],
                "partial_herbs": item["ni_original"]["partial_herbs"],
                "is_partial_disclosure": item["ni_original"]["is_partial_disclosure"],
                "contraindications": item["ni_original"]["contraindications"],
                "ziji_commentary": item["ziji_note"]["commentary"],
                "linked_classical_formulas": item["ziji_note"]["linked_classical_formulas"],
                "linked_acupoints": item["ziji_note"]["linked_acupoints"],
                "source_anchor": item["source_anchor"],
                "match_score": sc,
                "match_reasons": reasons,
            }
        )

    # 4. Applicable Hantang clinical redlines (triggered by keywords or referenced HT number)
    redline_hits: list[dict[str, Any]] = []
    for rl in cat.get("clinical_redlines", []):
        kws = _REDLINE_TRIGGERS.get(rl.get("id", ""), ())
        kw_hit = any(_norm(kw) in hay_norm for kw in kws)
        ht_hit = bool(_redline_ht_nums(rl) & matched_ht_nums)
        # Also trigger heart/mahuang redline when suppressed_names contains mahuang
        if kw_hit or ht_hit:
            redline_hits.append(rl)

    # 5. Include prognosis recovery signs whenever any Hantang rule/formula matched
    prog = cat.get("prognosis_and_recovery_criteria", {})
    prognosis_summary: dict[str, Any] = {}
    if matched_formulas or western_hits or du_hits or palp_hits or redline_hits:
        prognosis_summary = {
            "ni_six_criteria": prog.get("ni_six_criteria", [])[:3],
            "seven_recovery_signs": prog.get("seven_recovery_signs", []),
            "danger_reversal_signs": prog.get("danger_reversal_signs", []),
            "anchor": prog.get("anchor", {}),
        }

    return {
        "epistemic_notice": cat.get("epistemic_notice", ""),
        "hantang_formulas": matched_formulas,
        "western_history_guidance": western_hits,
        "du_spine_guides": du_hits,
        "special_palpations": palp_hits,
        "ht_redlines": redline_hits[:4],
        "prognosis_summary": prognosis_summary,
    }
