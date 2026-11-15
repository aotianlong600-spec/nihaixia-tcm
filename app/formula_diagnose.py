"""Deterministic symptom, six-meridian & Jinkui chapter differentiation engine for Stage 4."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from retrieval.tcm_synonyms import FORMULA_SYNONYM_GROUPS, strip_clinical_negations


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data"

SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = FORMULA_SYNONYM_GROUPS

DIFFERENTIAL_GUIDES = [
    {
        "triggers": ("项背强", "项强", "几几", "刚痉", "柔痉"),
        "title": "项背强几几与痉病三路辨证",
        "branches": [
            {"label": "有汗、恶风、项背强", "formula": "桂枝加葛根汤", "chip": "有汗 项背强", "note": "太阳表虚中风兼经脉津液不输，用桂枝汤和营卫加葛根升津，切忌麻黄。"},
            {"label": "无汗、恶寒、小便反少、项背强", "formula": "葛根汤", "chip": "无汗 项背强", "note": "太阳表实无汗且寒束水液欲作刚痉，以葛根配麻黄开腠升津。"},
            {"label": "发热有汗、脉反沉迟（柔痉）", "formula": "栝篓桂枝汤", "chip": "柔痉 有汗 脉沉迟", "note": "金匮柔痉津亏筋急，取桂枝汤加栝蒌根生津润筋。"},
            {"label": "胸满口噤、卧不着席、脚挛急齘齿", "formula": "大承气汤", "chip": "齘齿 脚挛急 大便硬", "note": "阳明腑实浊热熏脑成里实痉，需急下存阴而禁发汗。"},
        ],
    },
    {
        "triggers": ("往来寒热", "心烦喜呕", "胸胁苦满", "热入血室"),
        "title": "少阳枢机与兼证转方枢要",
        "branches": [
            {"label": "经典枢机证（往来寒热、胸胁苦满、嘿嘿不欲饮食、心烦喜呕）", "formula": "小柴胡汤", "chip": "心烦喜呕 往来寒热", "note": "和解少阳枢机；经水适断或适来之热入血室寒热如疟亦主之。"},
            {"label": "少阳兼表（发热微恶寒、支节烦疼、微呕、心下支结）", "formula": "柴胡桂枝汤", "chip": "支节烦疼 心下支结", "note": "太少并病外证未去，小柴胡与桂枝各半合解。"},
            {"label": "少阳兼阳明腑实（呕不止、心下急、郁郁微烦）", "formula": "大柴胡汤", "chip": "呕不止 心下急", "note": "少阳未罢而入胃腑实热，须在柴胡剂中去人参甘草、加大黄枳实芍药。"},
            {"label": "少阳误下（胸满烦惊、小便不利、谵语、一身尽重）", "formula": "柴胡加龙骨牡蛎汤", "chip": "胸满烦惊 谵语", "note": "枢机既虚而痰热惊扰神志，取龙牡铅丹铅系争议校考与镇潜重剂。"},
        ],
    },
    {
        "triggers": ("胸痹", "心痛", "短气", "心痛彻背", "背痛彻心"),
        "title": "胸痹心痛轻重虚实分层（金匮第九篇）",
        "branches": [
            {"label": "喘息咳唾、胸背痛、短气、寸口脉沉迟", "formula": "栝蒌薤白白酒汤", "chip": "胸背痛 短气", "note": "胸阳不振痰浊痹阻基础方，以白酒通阳宣浊。"},
            {"label": "不得卧、心痛彻背（甚者背痛彻心）", "formula": "栝蒌薤白半夏汤", "chip": "心痛彻背 不得卧", "note": "加半夏涤逐纵膈积痰；若背痛彻心兼手足寒，更辨乌头赤石脂丸。"},
            {"label": "心中痞气、气结在胸、胁下逆抢心（实 vs 虚）", "formula": "枳实薤白桂枝汤", "chip": "胁下逆抢心", "note": "气结偏实取枳实薤白桂枝汤降冲宣痹；若纯虚中寒者人参汤（理中汤）亦主之。"},
            {"label": "胸痹短气、饮停胸膈", "formula": "茯苓杏仁甘草汤", "chip": "胸痹 短气 水饮", "note": "饮邪偏胜饮橘枳姜汤并列辨别气滞与饮停。"},
        ],
    },
    {
        "triggers": ("下利", "泄泻", "拉肚子", "寒多", "水逆"),
        "title": "霍乱吐利与下利寒热分流",
        "branches": [
            {"label": "寒多不用水、中焦虚寒", "formula": "理中丸", "chip": "寒多 不用饮水", "note": "太阴脾胃寒湿不运，与五苓散之热多欲饮水明确分界。"},
            {"label": "热多欲饮水、或渴欲饮水水入则吐", "formula": "五苓散", "chip": "渴欲饮水 小便不利", "note": "膀胱气化不利蓄水成水逆，兼须淡渗温化水气。"},
            {"label": "太阳误下协热下利、利遂不止、喘而汗出", "formula": "葛根黄芩黄连汤", "chip": "协热下利 喘而汗出", "note": "表邪内陷阳明湿热暴迫大肠，脉促有热当清里热兼升清止利。"},
            {"label": "下利清谷、四肢厥逆、恶寒脉微", "formula": "四逆汤", "chip": "下利清谷 恶寒 厥逆", "note": "少阴肾阳衰微，急以生附干姜炙草回阳救逆。"},
        ],
    },
]

COMMON_CHIPS = [
    ("恶寒", "恶寒"),
    ("发热", "发热"),
    ("无汗", "无汗"),
    ("有汗", "有汗"),
    ("口渴", "口渴"),
    ("不渴", "不渴"),
    ("往来寒热", "往来寒热"),
    ("心烦喜呕", "心烦喜呕"),
    ("下利", "下利"),
    ("大便硬", "大便硬"),
    ("小便不利", "小便不利"),
    ("短气胸满", "胸满 短气"),
    ("少腹痛/肿痞", "少腹"),
    ("肌肤甲错", "肌肤甲错"),
    ("四肢厥冷", "厥逆"),
]

HIGH_RISK_HERBS = ("附子", "乌头", "天雄", "甘遂", "大戟", "泽漆", "芫花", "巴豆", "半夏", "麻黄", "细辛", "水蛭", "虻虫", "蟅虫", "雄黄", "铅粉", "白粉", "瓜蒂", "蜀漆")


@lru_cache(maxsize=1)
def _load_json(filename: str) -> Any:
    return json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _all_records() -> list[dict]:
    sh = list(_load_json("formulas.json"))
    jk = list(_load_json("jinkui_formulas.json"))
    modules = _load_json("formula_modules.json")
    evidence = _load_json("formula_evidence.json")
    mods_all = _load_json("formula_modifications.json").get("items", [])
    vars_all = _load_json("formula_variants.json").get("items", [])
    acup_all = _load_json("formula_acupuncture_links.json").get("items", [])

    mods_by_base: dict[str, list] = {}
    mods_by_target: dict[str, list] = {}
    for m in mods_all:
        mods_by_base.setdefault(m["base_formula_id"], []).append(m)
        if m.get("target_formula_id"):
            mods_by_target.setdefault(m["target_formula_id"], []).append(m)

    vars_by_fid: dict[str, dict] = {}
    for v in vars_all:
        vars_by_fid[v["shanghan_id"]] = v
        vars_by_fid[v["jinkui_id"]] = v

    acup_by_fid: dict[str, list] = {}
    for a in acup_all:
        acup_by_fid.setdefault(a["formula_id"], []).append(a)

    enriched = []
    for item in sh + jk:
        fid = item["id"]
        mod = modules.get(fid, {})
        ev = evidence.get(fid, {})
        enriched.append({
            **item,
            "module": mod,
            "evidence": ev,
            "mods_as_base": mods_by_base.get(fid, []),
            "mods_as_target": mods_by_target.get(fid, []),
            "variant_rec": vars_by_fid.get(fid),
            "acupuncture_links": acup_by_fid.get(fid, []),
        })
    return enriched


def _tokenize_and_expand(q: str) -> tuple[list[str], list[list[str]], list[str]]:
    cleaned = re.sub(r"[，,、。；;：:！？!?/\s]+", " ", q or "").strip()
    raw_tokens = [tok for tok in cleaned.split(" ") if tok]
    # Also decompose fused 4+ char phrases into 2-char subtokens if helpful
    tokens = []
    for tok in raw_tokens:
        if tok not in tokens:
            tokens.append(tok)
    token_groups: list[list[str]] = []
    expanded: list[str] = []
    for tok in tokens:
        grp = [tok]
        for sgrp in SYNONYM_GROUPS:
            if any(tok == s or (len(tok) >= 2 and tok in s) for s in sgrp):
                for s in sgrp:
                    if s not in grp:
                        grp.append(s)
        token_groups.append(grp)
        for g in grp:
            if g not in expanded:
                expanded.append(g)
    return tokens, token_groups, expanded


def _flatten_text(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return " ".join(_flatten_text(v) for v in val.values())
    if isinstance(val, (list, tuple)):
        return " ".join(_flatten_text(v) for v in val)
    return str(val)


def _score_blob(text: str, token_groups: list[list[str]], weight: int) -> tuple[int, list[str]]:
    if not text:
        return 0, []
    low = text.lower()
    score = 0
    matched = []
    for grp in token_groups:
        primary = grp[0].lower()
        if primary in low:
            score += weight * 2
            if grp[0] not in matched:
                matched.append(grp[0])
            continue
        for syn in grp[1:]:
            if len(syn) >= 2 and syn.lower() in low:
                score += weight
                if grp[0] not in matched:
                    matched.append(grp[0])
                break
    return score, matched


def _safety_alerts(q: str, top_formulas: list[dict]) -> list[str]:
    alerts = []
    q_clean = q or ""
    if any(k in q_clean for k in ["少腹肿痞", "肠痈", "阑尾", "腹痛", "呕血", "黑便", "胸痛彻背", "背痛彻心", "口噤", "角弓反张", "厥逆", "微欲绝", "喘", "不得眠"]):
        alerts.append("所询症状可能涉及急腹症（肠痈/穿孔）、急性心胸痛、消化道大出血、中枢痉厥或重度呼吸/循环衰竭等临床危急征象，古籍方证仅供文献研习，须优先现代急诊医疗处置。")
    if any(k in q_clean for k in ["孕", "产后", "妊娠", "胎"]):
        alerts.append("妊娠及产后生理属高危辨证边界，破血、峻下、大热有毒及滑利药均严禁自行照古方服用。")
    if any(k in q_clean for k in ["吐血", "咳血", "咯血", "鼻衄", "亡血", "骨蒸", "盗汗"]):
        alerts.append("《伤寒》明训「衄家、亡血家不可发汗」，《慎疾刍言》与《血证论》亦重申阴虚吐血骨蒸脉数严禁麻黄发汗及建中参附温补。")
    if ("心下" in q_clean or "结胸" in q_clean) and any(k in q_clean for k in ["白厚", "胎滑", "饮食如故", "能食", "不渴"]):
        alerts.append("《伤寒》警示：心下硬痛而反见饮食如故、不渴、苔白滑润或下利者，须严别「脏结」死候，绝禁妄下大陷胸/承气。")
    if ("无汗" in q_clean or "不出汗" in q_clean) and ("大渴" in q_clean or "烦渴" in q_clean or "石膏" in q_clean):
        alerts.append("《石室秘录》《伤寒》警示：白虎石膏必见阳明大汗如雨始可清解，若无汗表闭大渴而早用石膏必遏抑伏邪内陷（当辨大青龙散寒清里或先透表）。")
    if ("短气" in q_clean or "虚喘" in q_clean or "不抬肩" in q_clean) and "抬肩" not in q_clean.replace("不抬肩", " ") and "痰鸣" not in q_clean:
        alerts.append("《石室秘录》《外经》喘证辨疑：实喘必抬肩痰鸣，虚喘唯见张口短气而不抬肩；虚喘忌妄投麻桂强发散耗伤肺肾元气。")
    risky_names = []
    for f in top_formulas[:5]:
        h_names = [i.get("name", "") for i in f.get("ingredients", [])]
        if any(any(hr in hn for hr in HIGH_RISK_HERBS) for hn in h_names):
            risky_names.append(f["name"])
    if risky_names:
        alerts.append(f"候选方中含毒性或峻烈药味（如 {'、'.join(risky_names[:4])} 等含附子/乌头/甘遂/大戟/芫花/麻黄/细辛/半夏），必须严守古籍炮制减毒与执业医师处方边界。")
    return alerts


def diagnose_formulas(
    q: str = "",
    book: str = "",
    six_meridian: str = "",
    chapter_id: str = "",
    limit_formulas: int = 12,
) -> dict:
    cleaned = (q or "").strip()
    positive_q, _ = strip_clinical_negations(cleaned)
    tokens, token_groups, expanded = _tokenize_and_expand(positive_q)
    records = _all_records()
    six_channels = _load_json("six_channels.json").get("items", [])
    jchapters = _load_json("jinkui_chapters.json").get("items", [])
    mods_all = _load_json("formula_modifications.json").get("items", [])
    acup_all = _load_json("formula_acupuncture_links.json").get("items", [])

    # Normalize six_meridian filter
    meridian_alias = {
        "taiyang": "太阳", "yangming": "阳明", "shaoyang": "少阳",
        "taiyin": "太阴", "shaoyin": "少阴", "jueyin": "厥阴",
    }
    target_ch_label = ""
    if chapter_id:
        for ch in jchapters:
            if ch["id"] == chapter_id or ch["name"] == chapter_id:
                target_ch_label = ch["name"]
                break
    target_meridian_label = meridian_alias.get(six_meridian, six_meridian)

    # Polarity signals in query (exclude head-only sweating and nocturnal night sweats from systemic exterior sweating)
    sweat_scoped = (
        positive_q.replace("但头汗出", " ")
        .replace("头汗出", " ")
        .replace("头汗", " ")
        .replace("骨蒸盗汗", " ")
        .replace("盗汗", " ")
        .replace("手足心汗", " ")
    )
    wants_anhidrosis = "无汗" in positive_q
    wants_sweating = any(k in sweat_scoped for k in ["有汗", "汗出", "自汗", "汗多"]) and not wants_anhidrosis
    wants_no_thirst = any(k in positive_q for k in ["不渴", "不用水", "不饮水"])
    wants_thirst = any(k in positive_q for k in ["口渴", "大渴", "烦渴", "欲饮水"]) and not wants_no_thirst

    scored_formulas = []
    for rec in records:
        if book and rec.get("book") != book:
            continue
        if target_meridian_label and rec.get("six_meridian") != target_meridian_label:
            continue
        if target_ch_label and rec.get("chapter") != target_ch_label:
            continue

        mod = rec["module"]
        ev = rec["evidence"]
        name_blob = f"{rec['name']} {' '.join(rec.get('aliases', []))}"
        ind_blob = f"{rec.get('indication', '')} {' '.join(mod.get('six_channel', {}).get('original', []))}"
        sym_items = mod.get("symptoms", [])
        sym_blob = " ".join(f"{s.get('name', '')} {s.get('category', '')} {s.get('explanation', '')}" for s in sym_items)
        summary_blob = f"{mod.get('why', '')} {mod.get('overview', {}).get('summary', '')} {' '.join(mod.get('overview', {}).get('key_points', []))}"
        deep_blob = (
            f"{mod.get('rationale', {}).get('full_text', '')} "
            f"{' '.join(a.get('text', '') for a in mod.get('annotations', []))} "
            f"{' '.join(pr.get('text', '') + ' ' + pr.get('annotation', '') for pr in mod.get('page_reading', []))}"
        )
        ing_blob = " ".join(i.get("name", "") for i in rec.get("ingredients", []))
        dec_blob = f"{rec.get('decoction', '')} {mod.get('usage_plain', '')}"
        acup_blob = " ".join(f"{a.get('target_name', '')} {a.get('quote', '')} {a.get('note', '')}" for a in rec.get("acupuncture_links", []))
        mods_blob = " ".join(f"{m.get('condition', '')} {m.get('rationale', '')}" for m in rec.get("mods_as_base", []) + rec.get("mods_as_target", []))

        if not token_groups:
            # No query: return clean browse order by filter
            scored_formulas.append((1, [], rec))
            continue

        s_name, m1 = _score_blob(name_blob, token_groups, 24)
        s_sym, m2 = _score_blob(sym_blob, token_groups, 16)
        s_ind, m3 = _score_blob(ind_blob, token_groups, 15)
        s_acup, m8 = _score_blob(acup_blob, token_groups, 14)
        s_sum, m4 = _score_blob(summary_blob, token_groups, 10)
        s_mods, m9 = _score_blob(mods_blob, token_groups, 8)
        s_ing, m5 = _score_blob(ing_blob, token_groups, 8)
        s_deep, m6 = _score_blob(deep_blob, token_groups, 4)
        s_dec, m7 = _score_blob(dec_blob, token_groups, 4)

        total = s_name + s_sym + s_ind + s_acup + s_sum + s_mods + s_ing + s_deep + s_dec
        if total <= 0:
            continue

        matched_toks = []
        for tok in m1 + m2 + m3 + m8 + m4 + m9 + m5 + m6 + m7:
            if tok not in matched_toks:
                matched_toks.append(tok)

        # Strong boost for multi-token coverage & exact primary phrase hit in core indication/symptoms/links
        core_low = f"{name_blob} {ind_blob} {sym_blob} {acup_blob}".lower()
        exact_core_hits = sum(1 for t in tokens if len(t) >= 2 and t.lower() in core_low)
        exact_deep_hits = sum(1 for t in tokens if len(t) >= 2 and t.lower() in f"{summary_blob} {deep_blob}".lower())
        total += len(matched_toks) * 14 + exact_core_hits * 36 + exact_deep_hits * 12
        if len(tokens) >= 2 and len(matched_toks) == len(tokens):
            total += 35

        # Canonical textbook anchors where wording spans split across adjacent clauses
        if "少腹肿痞" in cleaned and rec["id"] == "jinkui:大黄牡丹汤":
            total += 120
        if "热入血室" in cleaned and rec["id"] in {"shanghan:小柴胡汤", "jinkui:小柴胡汤"}:
            total += 110 if rec["book"] == "伤寒论" else 75

        # Polarity discrimination against primary clause (excluding comparative notes like "无汗用葛根")
        primary_clause = ind_blob
        if wants_anhidrosis:
            if "无汗" in primary_clause:
                total += 45
            elif ("有汗" in primary_clause or "汗出" in primary_clause) and "无汗" not in primary_clause:
                total -= 75
        elif wants_sweating:
            if any(k in primary_clause for k in ["汗出", "有汗", "自汗"]):
                total += 45
            elif "无汗" in primary_clause and "有汗" not in primary_clause and "汗出" not in primary_clause:
                total -= 75
        if wants_no_thirst and any(k in f"{ind_blob} {mod.get('why', '')}" for k in ["不用水", "不渴", "寒多"]):
            total += 30
        elif wants_thirst and any(k in f"{ind_blob} {mod.get('why', '')}" for k in ["渴", "消渴", "欲饮水"]):
            total += 25

        scored_formulas.append((total, matched_toks, rec))

    scored_formulas.sort(key=lambda x: (-x[0], 0 if x[2]["book"] == "伤寒论" else 1, x[2]["id"]))

    result_formulas = []
    for sc, mtoks, rec in scored_formulas[:limit_formulas]:
        mod = rec["module"]
        fid = rec["id"]
        # Format ingredients preview
        comp_preview = " · ".join(
            f"{i.get('name', '')}{i.get('dose_raw') or i.get('dose', '')}"
            for i in rec.get("ingredients", [])
            if i.get("name")
        )
        # Highlight any modification whose condition or rationale also matches tokens
        triggered_mods = []
        for m in rec["mods_as_base"] + rec["mods_as_target"]:
            m_blob = f"{m.get('condition', '')} {m.get('target_formula_name', '')} {m.get('rationale', '')}"
            m_sc, m_hits = _score_blob(m_blob, token_groups, 10) if token_groups else (1, [])
            triggered_mods.append({
                **m,
                "matched_query": m_sc > 0,
                "matched_tokens": m_hits,
            })
        triggered_mods.sort(key=lambda x: (0 if x["matched_query"] else 1, x["id"]))

        # Collect linked acupuncture (direct on formula + six channel / chapter)
        direct_acup = list(rec["acupuncture_links"])
        # Also pull matching channel/chapter acupuncture links if < 3 direct
        if len(direct_acup) < 3:
            seen_ids = {a["id"] for a in direct_acup}
            for a in acup_all:
                if a["id"] in seen_ids:
                    continue
                if rec.get("chapter") and a.get("chapter_id") and any(
                    c["id"] == a["chapter_id"] and c["name"] == rec["chapter"]
                    for c in jchapters
                ):
                    direct_acup.append(a)
                    seen_ids.add(a["id"])
                elif rec.get("six_meridian") and a.get("channel_id"):
                    if meridian_alias.get(a["channel_id"], "") == rec["six_meridian"]:
                        direct_acup.append(a)
                        seen_ids.add(a["id"])
                if len(direct_acup) >= 4:
                    break

        h_names = [i.get("name", "") for i in rec.get("ingredients", [])]
        toxic_hits = [hr for hr in HIGH_RISK_HERBS if any(hr in hn for hn in h_names)]

        result_formulas.append({
            "id": fid,
            "name": rec["name"],
            "book": rec.get("book", ""),
            "section": rec.get("six_meridian") or rec.get("chapter", ""),
            "chapter": rec.get("chapter", ""),
            "score": sc,
            "matched_tokens": mtoks,
            "why": mod.get("why", ""),
            "indication": rec.get("indication", ""),
            "composition_preview": comp_preview or rec.get("composition_raw", ""),
            "decoction_preview": mod.get("usage_original", {}).get("text") or rec.get("decoction", ""),
            "symptoms": mod.get("symptoms", [])[:6],
            "toxic_herbs": toxic_hits,
            "modifications": triggered_mods[:6],
            "cross_book_variant": (
                {
                    "normalized_name": rec["variant_rec"]["normalized_name"],
                    "shanghan_id": rec["variant_rec"]["shanghan_id"],
                    "jinkui_id": rec["variant_rec"]["jinkui_id"],
                    "same_composition_and_dose": rec["variant_rec"]["same_composition_and_dose"],
                    "summary": rec["variant_rec"]["summary"],
                }
                if rec.get("variant_rec") else None
            ),
            "acupuncture_relations": direct_acup[:4],
            "review_status": rec["evidence"].get("review_status", "pending"),
            "status": rec.get("status", ""),
        })

    # Score Six Channels & Jinkui Chapters
    matched_channels = []
    for ch in six_channels:
        blob = " ".join([
            _flatten_text(ch.get("name")),
            _flatten_text(ch.get("summary")),
            _flatten_text(ch.get("original")),
            _flatten_text(ch.get("differentiation_points")),
            _flatten_text(ch.get("treatment_principles")),
        ])
        sc, hits = _score_blob(blob, token_groups, 10) if token_groups else (1, [])
        if sc > 0:
            matched_channels.append({
                "id": ch["id"],
                "name": ch["name"],
                "summary": ch.get("summary", ""),
                "score": sc,
                "matched_tokens": hits,
                "related_formula_ids": ch.get("related_formula_ids", [])[:8],
            })
    matched_channels.sort(key=lambda x: (-x["score"], x["id"]))

    matched_chapters = []
    for jc in jchapters:
        blob = " ".join([
            _flatten_text(jc.get("name")),
            _flatten_text(jc.get("disease_category")),
            _flatten_text(jc.get("summary")),
            _flatten_text(jc.get("symptoms")),
            _flatten_text(jc.get("pulse_and_syndrome")),
            _flatten_text(jc.get("differentiation_points")),
        ])
        sc, hits = _score_blob(blob, token_groups, 10) if token_groups else (1, [])
        if sc > 0:
            matched_chapters.append({
                "id": jc["id"],
                "order": jc.get("order"),
                "name": jc["name"],
                "disease_category": jc.get("disease_category", ""),
                "summary": jc.get("summary", ""),
                "score": sc,
                "matched_tokens": hits,
                "formula_count": len(jc.get("formula_ids", [])),
            })
    matched_chapters.sort(key=lambda x: (-x["score"], x.get("order") or 99))

    # Score Modification Rules directly
    matched_mods = []
    for m in mods_all:
        blob = f"{m.get('base_formula_name', '')} {m.get('condition', '')} {m.get('target_formula_name', '')} {m.get('rationale', '')} {m.get('boundary', '')}"
        sc, hits = _score_blob(blob, token_groups, 12) if token_groups else (0, [])
        if sc > 0:
            matched_mods.append({**m, "score": sc + len(hits) * 10, "matched_tokens": hits})
    matched_mods.sort(key=lambda x: (-x["score"], x["id"]))

    guides = [
        g for g in DIFFERENTIAL_GUIDES
        if any(tr in positive_q or any(tr in ex for ex in expanded) for tr in g["triggers"])
    ]

    top_raw_recs = [x[2] for x in scored_formulas[:5]]
    safety_alerts = _safety_alerts(positive_q, top_raw_recs)
    follow_ups = [{"label": lbl, "chip": chip} for lbl, chip in COMMON_CHIPS if chip not in positive_q]

    return {
        "query": cleaned,
        "tokens": tokens,
        "expanded_terms": expanded[:24],
        "safety_alerts": safety_alerts,
        "differentiation_guides": guides,
        "matched_formulas": result_formulas,
        "matched_six_channels": matched_channels[:4],
        "matched_jinkui_chapters": matched_chapters[:6],
        "matched_modifications": matched_mods[:10],
        "follow_up_facets": follow_ups,
        "total_matched": len(scored_formulas),
    }
