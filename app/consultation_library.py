"""Bind library retrieval to frozen excerpts without inventing full source pages."""
from functools import lru_cache
import hashlib
import json
import re

from . import library_analysis, library_evidence, library_modifications, library_signs
from .domain import DomainError

FILES = ("formula_mentions.json", "formula_compositions.json", "modifications.json", "sign_terms.json")
_loaded_digest = None


def data_digest():
    digest = hashlib.sha256()
    for name in FILES:
        digest.update(name.encode())
        digest.update(hashlib.sha256((library_evidence.DATA_DIR / name).read_bytes()).digest())
    return digest.hexdigest()


def _refresh():
    global _loaded_digest
    current = data_digest()
    if current != _loaded_digest:
        for module in (library_analysis, library_evidence, library_modifications, library_signs):
            module.clear_cache()
        _source_index.cache_clear()
        _loaded_digest = current
    return current


def _quote(source):
    text = source.get("quote", source.get("block", ""))
    digest = hashlib.sha256(text.encode()).hexdigest()
    if not text or digest != source.get("quote_sha256", source.get("block_sha256")):
        raise ValueError("库内摘录文字与来源哈希不一致")
    return text, digest


def _identity(source):
    _, digest = _quote(source)
    return (source.get("source_id", source.get("document_id")), source["locator"],
            source["source_title"], digest)


def _evidence_id(identity):
    return "library:" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


@lru_cache(maxsize=1)
def _source_index(digest):
    sources = [source for formula in library_evidence.all_formulas() for source in formula["evidence"]]
    sources.extend(version for formula in library_evidence._compositions()["formulas"] for version in formula["versions"])
    sources.extend(rule["source"] for rule in library_modifications.all_rules())
    return {_identity(source): source for source in sources}


def _unit_no(conn, source):
    number = source.get("unit_no")
    if type(number) is int and number > 0:
        return number
    page = re.fullmatch(r"physical_page:([1-9][0-9]*)", source["locator"])
    if page:
        return int(page[1])
    source_id = source.get("source_id", source.get("document_id"))
    for number, locator in conn.execute("SELECT unit_no,locator FROM source_units WHERE source_id=?", (source_id,)):
        try:
            if json.loads(locator) == json.loads(source["locator"]):
                return number
        except (ValueError, TypeError):
            if locator == source["locator"]:
                return number
    return None


def build(conn, facts, text):
    digest = _refresh()
    analysis = library_analysis.analyze(facts=facts, text=text[:4000], limit=6)
    evidence = {}

    def bind(source):
        identity = _identity(source)
        quote, quote_hash = _quote(source)
        key = _evidence_id(identity)
        evidence[key] = {"id": key, "format": "library_excerpt", "source_id": identity[0],
                         "unit_no": _unit_no(conn, source), "source_title": identity[2],
                         "title": identity[2], "locator": source["locator"], "printed_page": source.get("printed_page"),
                         "text": quote, "quote_sha256": quote_hash, "content_sha256": quote_hash,
                         "source_layer": "unclassified_fragment", "corpus_role": "库内资料摘录",
                         "source_data": "library_evidence", "library_analysis_digest": digest,
                         "excerpt_only": True, "warning": "本项为原文摘录，非完整页；OCR和整理归属须回看来源，不自动确立患者事实"}
        source["evidence_ids"] = [key]
        return key

    for item in analysis["items"]:
        for version in item["composition_versions"]:
            identity = f"{version['source_id']}|{version['locator']}|{version['block_sha256']}"
            version["id"] = version.get("id") or hashlib.sha256(identity.encode()).hexdigest()[:16]
            version["raw_block"] = version["block"]
            version["source"] = {key: version.get(key) for key in ('source_id', 'unit_no', 'source_title', 'locator')}
            version["components"] = [{**component,
                "name": component.get("name") or component.get("herb_raw") or component.get("herb_text"),
                "source_dose": None if component.get("missing_dose") else component.get("dose_text") or component.get("dose_raw"),
                "source_unit": None} for component in version.get("components", [])]
        refs = [bind(source) for source in item["evidence"]]
        refs.extend(bind(version) for version in item["composition_versions"])
        refs.extend(bind(rule["source"]) for rule in item["modifications"])
        item["evidence_ids"] = list(dict.fromkeys(refs))
    analysis["data_digest"] = digest
    return analysis, list(evidence.values())


def warnings(conn, frozen):
    current = _refresh()
    if frozen.get("library_analysis_digest") != current:
        return ["库内摘录数据已更新，请基于当前资料重新分析"]
    sources = _source_index(current)
    warnings = []
    for item in frozen.get("evidence", []):
        if item.get("format") != "library_excerpt":
            continue
        identity = (item.get("source_id"), item.get("locator"), item.get("source_title"), item.get("quote_sha256"))
        source = sources.get(identity)
        text_hash = hashlib.sha256(item.get("text", "").encode()).hexdigest()
        if (source is None or item.get("id") != _evidence_id(identity)
                or text_hash != item.get("quote_sha256") or text_hash != item.get("content_sha256")
                or item.get("library_analysis_digest") != current or item.get("unit_no") != _unit_no(conn, source)):
            warnings.append("库内摘录身份或文字已变化：" + item.get("title", "未知摘录"))
    return list(dict.fromkeys(warnings))


def confirm_fact(conn, consultation_id, term, state, expected_revision):
    """Replace one user-confirmed current finding under the visible record revision."""
    from . import consultation_core as core, storage

    if not isinstance(term, str) or not term.strip() or len(term) > 200:
        raise DomainError(400, "核对体征须为不超过200字符的非空文字")
    if state not in ("present", "absent"):
        raise DomainError(400, "核对体征只能选择存在或不存在")
    if type(expected_revision) is not int or expected_revision < 1:
        raise DomainError(400, "核对体征须提供有效的记录版本")
    term = term.strip()
    _refresh()
    exact = library_analysis._sign_index()["exact"]

    def canonical(key):
        key = key.strip()
        return library_analysis.EXTRA_ALIASES.get(key, exact.get(key, key))

    key = canonical(term)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        record = core.get_record(conn, consultation_id, False)
        if record["revision"] != expected_revision:
            raise DomainError(409, "问诊信息已变化，请重新加载后核对")
        intake = record["intake"]
        core.facts_from_intake(intake)
        facts = [fact for fact in intake.get("facts", [])
                 if not (core._current_patient_fact(fact) and canonical(fact["key"]) == key)]
        if len(facts) >= 300:
            raise DomainError(400, "已达记录项数量上限，请先整理问诊单")
        facts.append({"key": key, "state": state, "verified": True, "scope": "current",
                      "subject": "patient", "source": "patient", "raw": "用户按钮核对：" + term})
        intake["facts"] = facts
        intake["symptoms"] = [symptom for symptom in intake.get("symptoms", []) if canonical(symptom) != key]
        core.facts_from_intake(intake)
        conn.execute("UPDATE consultations SET intake=?,revision=revision+1,updated_at=? WHERE id=?",
                     (storage.encode(intake), storage.now(), consultation_id))
    return core.get_record(conn, consultation_id)
