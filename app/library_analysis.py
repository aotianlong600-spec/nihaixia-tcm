"""Library-grounded formula-pattern retrieval.

The ranking is an explicit evidence count over local sign-term evidence and
classical modification rules. It is not a probability, diagnosis or prescription.
"""
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import math
import re

from . import engine, formula_engine, library_evidence, library_modifications, library_signs

FORMAT = "nihaixia-library-analysis"
NOTICE = "库内方证检索：按体征词在原文证据和加减规则中的命中计数排序，不是概率、诊断或处方；须回看原文和临床情境。"
SCORE_EXPLANATION = "已确认体征与独立检索词按逆频率召回，已确认反证扣分；原文加减仅为线索，不执行。分数不是概率，检索词不确立患者事实。"
EXTRA_ALIASES = {"手脚冰凉": "手脚冰冷", "脉微细": "微"}
RULE_EQUIVALENTS = {
    "口渴": ("渴",),
    "手脚冰凉": ("手足冷", "四肢冷", "厥冷", "手脚冷"),
    "手脚冰冷": ("手足冷", "四肢冷", "厥冷", "手脚冷"),
    "怕冷": ("恶寒", "畏寒"),
    "全身怕冷": ("恶寒", "畏寒"),
}


def _variants(item: dict, minimum: int = 1) -> list[str]:
    values = [item.get("term"), *(item.get("aliases") or [])]
    result = []
    for value in values:
        if isinstance(value, str) and len(value) >= minimum and value not in result:
            result.append(value)
    return result


@lru_cache(maxsize=1)
def _sign_index() -> dict:
    terms = library_signs.all_terms()
    exact = {}
    variant_to_term = {}
    for item in terms:
        exact[item["term"]] = item["term"]
        for alias in item.get("aliases") or []:
            if isinstance(alias, str) and alias:
                exact.setdefault(alias, item["term"])
        for variant in _variants(item, 2):
            variant_to_term.setdefault(variant, item["term"])
    for alias, canonical in EXTRA_ALIASES.items():
        variant_to_term.setdefault(alias, canonical)
    variants = sorted(variant_to_term, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(value) for value in variants))
    return {"terms": terms, "exact": exact, "variant_to_term": variant_to_term, "pattern": pattern}


@lru_cache(maxsize=1)
def _term_labels() -> dict[str, str]:
    return {item["term"]: item.get("label") or item["term"] for item in library_signs.all_terms()}


@lru_cache(maxsize=1)
def _term_variants() -> dict[str, list[str]]:
    result = {}
    for item in library_signs.all_terms():
        result[item["term"]] = _variants(item, 1)
    return result


def _find_terms(text: str) -> set[str]:
    index = _sign_index()
    found = set()
    for match in index["pattern"].finditer(text):
        term = index["variant_to_term"].get(match.group())
        if term:
            found.add(term)
    return found


def extract_terms(text: str) -> list[str]:
    if not isinstance(text, str) or len(text) > 4000:
        raise ValueError("文本过长")
    return sorted(_find_terms(text))


def _resolve(values) -> tuple[set[str], list[str]]:
    index = _sign_index()
    found = set()
    unmatched = []
    for value in values:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value:
            continue
        if value in EXTRA_ALIASES:
            found.add(EXTRA_ALIASES[value])
            continue
        exact = index["exact"].get(value)
        if exact:
            found.add(exact)
            continue
        mentions = _find_terms(value)
        if mentions:
            found.update(mentions)
        else:
            unmatched.append(value)
    return found, unmatched


def _collect(symptoms, absent, text, facts) -> dict:
    indexed, ignored = engine._facts(facts)
    normalized = defaultdict(list)
    unmatched = []
    for key, records in indexed.items():
        resolved, raw = _resolve([key])
        unmatched.extend(raw)
        for term in resolved or raw:
            normalized[term].extend({**record, "key": term} for record in records)
    states = {state: set() for state in ("present", "absent", "unknown", "conflicts")}
    for term in normalized:
        trace = engine._evaluate({"fact": term}, normalized)
        state = "conflicts" if trace["conflicts"] else "unknown" if trace["value"] is None else "present" if trace["value"] else "absent"
        states[state].add(term)
    hints, raw_hints = _resolve(symptoms)
    absent_hints, raw_absent = _resolve(absent)
    hints.update(_find_terms(text))
    blocked = states["conflicts"] | states["unknown"] | states["absent"]
    hints -= blocked | states["present"]
    raw_hints = sorted(set(raw_hints) - blocked - states["present"])
    unverified = set(symptoms) | set(absent)
    unverified.update(record["key"] for record in ignored)
    return {**states, "retrieval_terms": hints, "raw_retrieval": raw_hints,
            "unmatched": sorted(set(unmatched + raw_hints + raw_absent)),
            "unverified_terms": sorted(unverified), "background_facts": ignored,
            "unverified_absent_terms": sorted(absent_hints | set(raw_absent))}


@lru_cache(maxsize=1)
def _formula_texts() -> dict[str, str]:
    return {
        item["formula_id"]: " ".join([item["formula_name"],
                                       *[evidence.get("quote", "") for evidence in item.get("evidence") or []]])
        for item in library_evidence.all_formulas()
    }


@lru_cache(maxsize=1)
def _formula_terms() -> dict[str, set[str]]:
    return {formula_id: _find_terms(text) for formula_id, text in _formula_texts().items()}


@lru_cache(maxsize=1)
def _term_df() -> dict[str, int]:
    result = defaultdict(int)
    for found in _formula_terms().values():
        for term in found:
            result[term] += 1
    return dict(result)


@lru_cache(maxsize=1)
def _term_weights() -> dict[str, float]:
    total = len(_formula_terms())
    return {term: round(1 + math.log((total + 1) / (count + 1)), 2)
            for term, count in _term_df().items()}


@lru_cache(maxsize=1)
def _modification_index() -> dict[str, list[dict]]:
    result = defaultdict(list)
    for rule in library_modifications.all_rules():
        text = " ".join([rule.get("condition", ""), rule.get("raw", "")])
        result[rule["formula_id"]].append({"rule": rule, "terms": _find_terms(text)})
    return result


def _matched_terms(terms: set[str], text: str) -> list[str]:
    variants = _term_variants()
    result = []
    for term in terms:
        if any(value in text for value in variants.get(term, [term])):
            result.append(term)
    return sorted(result)


def clear_cache():
    for cached in (_sign_index, _term_labels, _term_variants, _formula_texts, _formula_terms,
                   _term_df, _term_weights, _modification_index):
        cached.cache_clear()


def analyze(symptoms=None, absent=None, text: str = "", facts=None, limit: int = 10) -> dict:
    symptoms = symptoms or []
    absent = absent or []
    facts = facts or []
    if not isinstance(symptoms, (list, tuple)) or len(symptoms) > 100:
        raise ValueError("症状列表无效")
    if not isinstance(absent, (list, tuple)) or len(absent) > 100:
        raise ValueError("反证列表无效")
    if any(not isinstance(term, str) or not term.strip() or len(term) > 200 for term in [*symptoms, *absent]):
        raise ValueError("体征检索词须为不超过200字符的非空文字")
    if not isinstance(facts, list) or len(facts) > 100:
        raise ValueError("体征事实列表无效")
    if not isinstance(text, str) or len(text) > 4000:
        raise ValueError("文本过长")
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("limit 须在 1 到 30 之间")
    collected = _collect(symptoms, absent, text, facts)
    known = set(_term_labels())
    present = collected["present"] & known
    absent_set = collected["absent"] & known
    present_raw = collected["present"] - known
    absent_raw = collected["absent"] - known
    retrieval = collected["retrieval_terms"]
    raw_retrieval = collected["raw_retrieval"]
    labels = _term_labels()
    result = {key: sorted(collected[key]) for key in ("conflicts", "unknown", "unverified_terms", "retrieval_terms", "raw_retrieval", "unmatched", "unverified_absent_terms")}
    result.update({"present": sorted(present), "absent": sorted(absent_set),
                   "raw_present": sorted(present_raw), "raw_absent": sorted(absent_raw),
                   "present_labels": {term: labels.get(term, term) for term in sorted(present)},
                   "absent_labels": {term: labels.get(term, term) for term in sorted(absent_set)},
                   "retrieval_labels": {term: labels.get(term, term) for term in sorted(retrieval)},
                   "background_facts": collected["background_facts"], "items": [],
                   "score_explanation": SCORE_EXPLANATION, "review_status": "library_source", "notice": NOTICE,
                   "source_kind": "ni_library_retrieval", "modification_execution": "decision_graph_only"})
    if not present and not present_raw and not retrieval and not raw_retrieval:
        return result

    formula_terms = _formula_terms()
    formula_texts = _formula_texts()
    modification_index = _modification_index()
    weights = _term_weights()
    candidates = []
    for formula in library_evidence.all_formulas():
        formula_id = formula["formula_id"]
        formula_text = formula_texts.get(formula_id, "")
        found = formula_terms.get(formula_id, set())
        matched = present & found
        matched_raw = {term for term in present_raw if term in formula_text}
        retrieval_hits = retrieval & found
        raw_retrieval_hits = {term for term in raw_retrieval if term in formula_text}
        contradicted = absent_set & found
        contradicted_raw = {term for term in absent_raw if term in formula_text}
        matched_mods = []
        for entry in modification_index.get(formula_id, []):
            rule_text = entry["rule"].get("condition", "")
            rule_matched = _matched_terms(present, rule_text)
            for raw in present_raw:
                if (raw in rule_text or any(value in rule_text for value in RULE_EQUIVALENTS.get(raw, ()))) \
                        and raw not in rule_matched:
                    rule_matched.append(raw)
            if rule_matched:
                item = deepcopy(entry["rule"])
                item["matched_terms"] = sorted(rule_matched)
                item["application_status"] = "unapplied"
                item["application_reason"] = "原文条件的部分词命中仅为检索线索；未核对整组条件，不自动执行加减"
                matched_mods.append(item)
        if not matched and not matched_raw and not matched_mods and not retrieval_hits and not raw_retrieval_hits:
            continue
        score_retrieval = round(sum(weights.get(term, 1.0) for term in retrieval_hits) + len(raw_retrieval_hits), 2)
        score_evidence = round(sum(weights.get(term, 1.0) for term in matched) + len(matched_raw)
                               - 2 * len(contradicted) - 2 * len(contradicted_raw), 2)
        score_modifications = 3 * min(len(matched_mods), 5)
        score = round(score_evidence + score_modifications + score_retrieval, 2)
        if score <= 0:
            continue
        candidates.append({
            "formula_id": formula_id,
            "formula_name": formula["formula_name"],
            "score": score,
            "score_breakdown": {"evidence": score_evidence, "modifications": score_modifications,
                                "retrieval": score_retrieval,
                                "contradictions": -2 * len(contradicted) - 2 * len(contradicted_raw),
                                "raw_evidence": len(matched_raw)},
            "matched_terms": sorted(matched),
            "matched_raw_terms": sorted(matched_raw),
            "retrieval_terms": sorted(retrieval_hits), "raw_retrieval": sorted(raw_retrieval_hits),
            "retrieval_only": not bool(matched or matched_raw or matched_mods),
            "matched_labels": {term: _term_labels().get(term, term) for term in sorted(matched)},
            "missing_terms": sorted(found - present - absent_set - collected["conflicts"])[:12],
            "contradicted_terms": sorted(contradicted) + sorted(contradicted_raw),
            "modification_hits": matched_mods,
            "_found": found,
        })
    candidates.sort(key=lambda item: (-item["score"],
                                      -(len(item["matched_terms"]) + len(item["matched_raw_terms"])),
                                      item["formula_name"]))
    items = []
    for candidate in candidates[:limit]:
        formula_id = candidate["formula_id"]
        detail = library_evidence.get_formula(formula_id) or {}
        evidence = []
        for item in detail.get("evidence") or []:
            quote = item.get("quote", "")
            hits = _matched_terms(present | retrieval, quote)
            raw_hits = [term for term in present_raw | set(raw_retrieval) if term in quote]
            if not hits and not raw_hits:
                continue
            evidence.append({**deepcopy(item), "matched_terms": hits, "matched_raw_terms": raw_hits})
            if len(evidence) >= 5:
                break
        metadata = formula_engine.get_formula(formula_id) or {}
        items.append({
            "formula_id": formula_id,
            "formula_name": candidate["formula_name"],
            "syndrome": metadata.get("syndrome", ""),
            "six_meridian": metadata.get("six_meridian", ""),
            "components": deepcopy(metadata.get("components", [])),
            "score": candidate["score"],
            "score_breakdown": candidate["score_breakdown"],
            "retrieval_only": candidate["retrieval_only"],
            "retrieval_terms": candidate["retrieval_terms"], "raw_retrieval": candidate["raw_retrieval"],
            "source_kind": "ni_library_retrieval",
            "matched_terms": candidate["matched_terms"],
            "matched_raw_terms": candidate["matched_raw_terms"],
            "matched_labels": candidate["matched_labels"],
            "missing_terms": candidate["missing_terms"],
            "contradicted_terms": candidate["contradicted_terms"],
            "evidence": evidence,
            "composition_versions": deepcopy(detail.get("compositions") or []),
            "modifications": deepcopy(candidate["modification_hits"]),
        })
    result["items"] = items
    return result


def summary() -> dict:
    return {
        "review_status": "library_source",
        "notice": NOTICE,
        "formulas_with_evidence": len(library_evidence.all_formulas()),
        "sign_terms": len(library_signs.all_terms()),
        "modification_rules": len(library_modifications.all_rules()),
        "score_explanation": SCORE_EXPLANATION,
    }


def mount_library_analysis_routes(app, protected):
    from fastapi import Query
    from pydantic import BaseModel, Field

    class AnalysisInput(BaseModel):
        symptoms: list[str] = Field(default_factory=list, max_length=100)
        absent: list[str] = Field(default_factory=list, max_length=100)
        text: str = Field(default="", max_length=4000)
        facts: list[dict] = Field(default_factory=list, max_length=100)
        limit: int = Field(default=10, ge=1, le=30)

    @app.get("/api/library/analysis/summary", dependencies=protected)
    def library_analysis_summary():
        return summary()

    @app.post("/api/library/analysis", dependencies=protected)
    def library_analysis(payload: AnalysisInput):
        return analyze(payload.symptoms, payload.absent, payload.text, payload.facts, payload.limit)
