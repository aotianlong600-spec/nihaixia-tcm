"""Adapt frozen, source-mapped graph results to the existing consultation protocol."""
from copy import deepcopy
import hashlib

from . import decision, library


def evidence_id(package_id, version, anchor_id):
    return f"decision:{package_id}@{version}:{anchor_id}"


def bind_question(question, graph):
    """Bind only the exact current graph question, never a model's claimed source identity."""
    question['source_kind'] = 'ai_inference'
    matches = [q for q in graph.get('questions', []) if q['key'] == question['key'] and q['question'] == question['question']]
    if len(matches) != 1 or not matches[0].get('source_bindings'):
        return
    source = matches[0]
    claims = {(c['package_id'], c['package_version'], c['id']): c for c in graph['claims']}
    anchors = {(a['package_id'], a['package_version'], a['id']): a for a in graph['anchors']}
    refs = list(question['evidence_ids'])
    layers = set()
    for binding in source['source_bindings']:
        ids = binding['claim_ids'] + [key for c in binding['condition_refs'] for key in c['claim_ids']]
        for key in dict.fromkeys(ids):
            claim = claims.get((binding['package_id'], binding['package_version'], key))
            if claim is None:
                raise ValueError('补问的原文断言缺失，未保存为有效答复')
            for key in claim['anchor_ids']:
                anchor = anchors.get((binding['package_id'], binding['package_version'], key))
                if anchor is None:
                    raise ValueError('补问的来源锚点缺失，未保存为有效答复')
                layers.add(anchor['layer'])
                refs.append(evidence_id(binding['package_id'], binding['package_version'], key))
    if question['reason'] != source['reason']:
        question['ai_reason'] = question['reason']
    original = {'classic_clause','ni_commentary','ni_case','compiler_annotation','reference_author'}
    kind = 'source_mapped_question' if layers and layers <= original else (
        'ai_inference' if layers == {'ai_inference'} else 'open_source_question' if layers == {'open_source_summary'} else 'mixed_source_question')
    question.update(reason=source['reason'], source_kind=kind, source_layers=sorted(layers),
                    source_bindings=deepcopy(source['source_bindings']), priority=deepcopy(source['priority']),
                    evidence_ids=list(dict.fromkeys(refs)))


def consultation_context(conn, facts):
    # shortcut: evaluate installed groups; select relevant groups before expanding beyond this first topic.
    graph = decision.evaluate(conn, facts)
    invalid = {i["package_id"] for i in graph["source_issues"]}
    evidence, candidates = [], []
    for a in graph["anchors"]:
        if a["package_id"] in invalid:
            continue
        unit = library.get_unit(conn, None, a["source_id"], a["unit_no"])
        evidence.append({"id": evidence_id(a["package_id"], a["package_version"], a["id"]),
                         "source_id": a["source_id"], "unit_no": a["unit_no"],
                         "title": unit["title"], "text": a["quote"], "format": unit["format"],
                         "locator": unit["locator"], "corpus_role": a["layer"], "source_layer": a["layer"],
                         "attribution": a["attribution"], "version_label": a["version_label"],
                         "reading": a.get("reading"), "reading_note": a.get("reading_note"),
                         "content_sha256": hashlib.sha256(a["quote"].encode()).hexdigest(),
                         "unit_content_sha256": a["unit_sha256"], "raw_anchor": True,
                         "warning": "定位与结构核对，不代表医学有效性；阅读整理另列，不冒充连续引文"})
    for f in graph["formulas"]:
        nodes = [n for n in graph["nodes"] if n.get("formula_version_id") == f["version_id"]
                 and n["package_id"] == f["package_id"]]
        if f["package_id"] in invalid or not any(n["status"] in ("compatible", "clue", "pending") for n in nodes):
            continue
        candidates.append({**deepcopy(f), "id": f["version_id"], "formula_id": f.get("catalog_id"),
                           "formula_version_id": f["version_id"], "decision_package_id": f["package_id"],
                           "decision_package_version": f["package_version"], "source_kind": "source_mapped",
                           "decision_nodes": [n["id"] for n in nodes],
                           "decision_statuses": [n["status"] for n in nodes],
                           "matched_features": [], "missing_features": [], "contradictions": [],
                           "score_explanation": "逐条来源情境与约束的执行结果，不是诊断概率"})
    graph["modification_previews"] = []
    for package in graph["packages"]:
        if package["id"] in invalid:
            continue
        for m in package["snapshot"]["modifications"]:
            graph["modification_previews"].append({"package_id": package["id"], "package_version": package["version"],
                "modification_id": m["id"], "base_version_id": m["base_version_id"],
                "preview": decision.preview_modifications(conn, package["id"], m["base_version_id"], [m["id"]], facts, package_version=package["version"])})
    return graph, candidates, evidence


def _claim_sources(package, ids):
    claims = {c["id"]: c for c in package["snapshot"]["claims"]}
    anchors = {a["id"]: a for a in package["snapshot"]["anchors"]}
    return [{"claim_id": c["id"], "claim": c["text"], "kind": c["kind"], "inference": c["inference"],
             "scope": c["scope"], "limitations": c["limitations"], "anchors": [
                 {**deepcopy(anchors[key]), "evidence_id": evidence_id(package["id"], package["version"], key)}
                 for key in c["anchor_ids"]]} for key in ids for c in [claims[key]]]


def node_claim_ids(node):
    ids = node.get("scope_claim_ids", []) + node.get("treatment_claim_ids", [])
    for item in node["conditions"] + node.get("cases", []) + node["questions"]:
        ids += item["claim_ids"]
    return list(dict.fromkeys(ids))


def bind_formula(proposed, graph):
    """Use one frozen source version; model-proposed medical fields are not authoritative."""
    version = proposed.get("formula_version_id")
    known = [f for f in graph.get("formulas", []) if f.get("catalog_id") == proposed.get("formula_id")
             or f["name"] == proposed["name"]]
    if not version:
        if known:
            raise ValueError("此方已有原件映射，必须明确来源包及方剂版本，不能隐式回填目录量")
        return False
    packages = [p for p in graph.get("packages", []) if p["id"] == proposed.get("decision_package_id")
                and p["version"] == proposed.get("decision_package_version")]
    if len(packages) != 1:
        raise ValueError("方剂来源包版本不在本次冻结上下文中")
    package = packages[0]
    versions = [f for f in package["snapshot"]["formulas"] if f["version_id"] == version]
    if len(versions) != 1 or versions[0]["name"] != proposed["name"]:
        raise ValueError("方剂名称或版本不对应本次原件映射")
    nodes = [n for n in graph["nodes"] if n["package_id"] == package["id"] and n.get("formula_version_id") == version]
    if any(i["package_id"] == package["id"] for i in graph.get("source_issues", [])) or not nodes or all(
            n["status"] in ("excluded", "conflict", "source_invalid") for n in nodes):
        raise ValueError("该来源版本当前被反证、冲突或来源失效阻断，不能作为可用候选方")
    formula = versions[0]
    for supplied in proposed.get("components", []):
        matches = [c for c in formula["components"] if c["name"] == supplied["name"]]
        if len(matches) != 1 or any(supplied.get(field) is not None and supplied[field] != matches[0].get(field)
                                    for field in ("processing", "source_dose", "source_unit")):
            raise ValueError("AI药味、炮制或原量与所选来源版本冲突，未静默覆盖")
    source_preparation = "\n".join(item["text"] for item in formula["preparation"]) or None
    if proposed.get("preparation") and proposed["preparation"] != source_preparation:
        raise ValueError("AI煎服与所选来源版本冲突；可留空由程序按原件回填")
    proposed["formula_id"] = formula.get("catalog_id")
    proposed["components"] = deepcopy(formula["components"])
    used = []
    for component in proposed["components"]:
        component["field_sources"] = {field: _claim_sources(package, component["provenance"].get(field, []))
                                      for field in ("name", "processing", "source_dose", "source_unit")}
        refs = [a["evidence_id"] for sources in component["field_sources"].values() for c in sources for a in c["anchors"]]
        component["source_ref"] = refs[0] if refs else None
        used.extend(refs)
    proposed["preparation"] = source_preparation
    proposed["preparation_sources"] = [_claim_sources(package, item["claim_ids"]) for item in formula["preparation"]]
    used.extend(a["evidence_id"] for sources in proposed["preparation_sources"] for c in sources for a in c["anchors"])
    proposed["identity_sources"] = _claim_sources(package, formula["identity_claim_ids"])
    used.extend(a["evidence_id"] for c in proposed["identity_sources"] for a in c["anchors"])
    proposed["decision_sources"] = _claim_sources(package, list(dict.fromkeys(
        key for node in nodes for key in node_claim_ids(node))))
    used.extend(a["evidence_id"] for c in proposed["decision_sources"] for a in c["anchors"])
    proposed["evidence_ids"] = list(dict.fromkeys(proposed["evidence_ids"] + used))
    proposed["source_kind"] = "source_mapped"
    proposed["decision_basis"] = deepcopy(nodes)
    proposed["source_limitations"] = deepcopy(formula["limitations"])
    previews = [p for p in graph.get("modification_previews", []) if p["package_id"] == package["id"]
                and p["base_version_id"] == version]
    requested = proposed.get("source_modification_ids", [])
    if requested:
        selected = [p for p in previews if p["modification_id"] in requested]
        if len(selected) != 1 or len(requested) != 1:
            raise ValueError("一次加减预览必须选择本次已冻结的单组来源动作，不能跨组拼接")
        modification = next(m for m in package["snapshot"]["modifications"] if m["id"] == requested[0])
        canonical_actions = []
        for action in modification["actions"]:
            component = action.get("component") or {}
            sources = _claim_sources(package, action["claim_ids"])
            refs = list(dict.fromkeys(a["evidence_id"] for c in sources for a in c["anchors"]))
            canonical_actions.append({"action": action["operation"],
                "herb": action.get("target_name") or component.get("name", ""),
                "replacement": component.get("name") if action["operation"] == "replace" else None,
                "trigger_symptoms": [], "source_note": "；".join(c["claim"] for c in sources), "evidence_ids": refs})
        for supplied in proposed.get("modifications", []):
            if not any(all(supplied.get(k) == action.get(k) for k in ("action", "herb", "replacement"))
                       for action in canonical_actions):
                raise ValueError("AI加减说明与所选结构化来源动作不一致，未并列冒充已应用动作")
        proposed["modifications"] = canonical_actions
        proposed["modification_sources"] = _claim_sources(package, modification["claim_ids"])
        proposed["evidence_ids"] = list(dict.fromkeys(proposed["evidence_ids"] + [
            ref for action in canonical_actions for ref in action["evidence_ids"]] + [
            a["evidence_id"] for c in proposed["modification_sources"] for a in c["anchors"]]))
        preview = deepcopy(selected[0]["preview"])
        preview["source_action_groups"] = {key: deepcopy(preview[key]) for key in ("applied", "unapplied")}
        reason = "；".join(preview.get("conflicts", [])) or "触发条件或来源动作未执行"
        preview["applied"] = deepcopy(canonical_actions) if preview["source_action_groups"]["applied"] else []
        preview["unapplied"] = [] if preview["applied"] else [{**deepcopy(a), "reason": reason} for a in canonical_actions]
        proposed["modification_preview"] = preview
    elif proposed.get("modifications"):
        proposed["modification_preview"] = {"components": deepcopy(proposed["components"]), "applied": [],
            "unapplied": [{**m, "reason": "AI说明未绑定本次结构化来源动作，未执行"} for m in proposed["modifications"]],
            "missing": [], "conflicts": [], "warnings": ["来源动作未执行，不代表已形成调整后方剂"]}
    return True
