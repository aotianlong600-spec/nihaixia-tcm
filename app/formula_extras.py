"""Stage 4 read-only enrichment & structured knowledge accessors for Formulas, Jinkui chapters, modifications, cross-book variants & acupuncture links."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data"

CHANNEL_NAME_TO_ID = {
    "太阳": "taiyang",
    "阳明": "yangming",
    "少阳": "shaoyang",
    "太阴": "taiyin",
    "少阴": "shaoyin",
    "厥阴": "jueyin",
}


@lru_cache(maxsize=1)
def _load_json(rel_path: str) -> Any:
    return json.loads((DATA_DIR / rel_path).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _formulas_by_id() -> dict[str, dict]:
    items = list(_load_json("formulas.json")) + list(_load_json("jinkui_formulas.json"))
    return {x["id"]: x for x in items}


@lru_cache(maxsize=1)
def _evidence_by_id() -> dict[str, dict]:
    return _load_json("formula_evidence.json")


@lru_cache(maxsize=1)
def _modules_by_id() -> dict[str, dict]:
    return _load_json("formula_modules.json")


@lru_cache(maxsize=1)
def _acup_entities() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for fn in ("acupoints.json", "techniques.json", "meridians.json", "conditions.json"):
        p = DATA_DIR / "acupuncture" / fn
        if p.is_file():
            for it in json.loads(p.read_text(encoding="utf-8")).get("items", []):
                out[it["id"]] = it
    return out


def _formula_brief(fid: str) -> dict | None:
    rec = _formulas_by_id().get(fid)
    if not rec:
        return None
    mod = _modules_by_id().get(fid, {})
    ev = _evidence_by_id().get(fid, {})
    comp_preview = " · ".join(
        f"{i.get('name', '')}{i.get('dose_raw') or i.get('dose', '')}"
        for i in rec.get("ingredients", [])
        if i.get("name")
    )
    return {
        "id": fid,
        "name": rec.get("name", ""),
        "book": rec.get("book", ""),
        "section": rec.get("six_meridian") or rec.get("chapter") or "",
        "chapter": rec.get("chapter") or "",
        "six_meridian": rec.get("six_meridian") or "",
        "indication": rec.get("indication") or "",
        "why": mod.get("why") or ev.get("why") or "",
        "composition_preview": comp_preview or rec.get("composition_raw", ""),
        "decoction": mod.get("usage_original", {}).get("text") or rec.get("decoction") or "",
        "review_status": ev.get("review_status", "reviewed"),
        "status": rec.get("status", ""),
    }


def list_jinkui_chapters(q: str = "", review_status: str = "") -> dict:
    chapters = list(_load_json("jinkui_chapters.json").get("items", []))
    q_low = (q or "").strip().lower()
    items = []
    for ch in chapters:
        if review_status and ch.get("status") != review_status:
            continue
        if q_low:
            blob = " ".join([
                ch.get("name", ""),
                ch.get("disease_category", ""),
                ch.get("summary", ""),
                " ".join(ch.get("symptoms", [])),
                " ".join(ch.get("formula_ids", [])),
            ]).lower()
            if q_low not in blob:
                continue
        f_previews = [
            b for b in (_formula_brief(fid) for fid in ch.get("formula_ids", []))
            if b is not None
        ]
        items.append({
            **ch,
            "formula_count": len(f_previews),
            "formula_previews": f_previews[:10],
        })
    return {"total": len(items), "items": items}


def get_jinkui_chapter(chapter_id: str) -> dict | None:
    target = (chapter_id or "").strip()
    if target.startswith("jinkui:"):
        target = target[len("jinkui:"):]
    chapters = list(_load_json("jinkui_chapters.json").get("items", []))
    match = next(
        (c for c in chapters if c["id"] == chapter_id or c["id"] == target or c["name"] == target),
        None,
    )
    if not match:
        return None
    fids = set(match.get("formula_ids", []))
    formulas = [b for b in (_formula_brief(fid) for fid in match.get("formula_ids", [])) if b is not None]
    mods = [
        m for m in _load_json("formula_modifications.json").get("items", [])
        if m.get("base_formula_id") in fids or m.get("target_formula_id") in fids
    ]
    variants = [
        v for v in _load_json("formula_variants.json").get("items", [])
        if v.get("jinkui_id") in fids
    ]
    acup = []
    seen_a = set()
    for a in _load_json("formula_acupuncture_links.json").get("items", []):
        if a.get("chapter_id") == match["id"] or a.get("formula_id") in fids:
            if a["id"] not in seen_a:
                seen_a.add(a["id"])
                ent = _acup_entities().get(a.get("target_id", ""), {})
                acup.append({**a, "target_meridian": ent.get("meridian_name", ""), "target_summary": ent.get("summary", "")})
    return {
        **match,
        "formula_count": len(formulas),
        "formulas": formulas,
        "modifications": mods,
        "cross_book_variants": variants,
        "acupuncture_relations": acup,
    }


def list_formula_modifications(
    q: str = "",
    base_formula_id: str = "",
    target_formula_id: str = "",
) -> dict:
    mods = list(_load_json("formula_modifications.json").get("items", []))
    q_low = (q or "").strip().lower()
    out = []
    for m in mods:
        if base_formula_id and m.get("base_formula_id") != base_formula_id:
            continue
        if target_formula_id and m.get("target_formula_id") != target_formula_id:
            continue
        if q_low:
            blob = " ".join([
                m.get("base_formula_name", ""),
                m.get("target_formula_name", ""),
                m.get("condition", ""),
                m.get("changes", {}).get("summary", ""),
                m.get("rationale", ""),
                m.get("boundary", ""),
            ]).lower()
            if q_low not in blob:
                continue
        out.append(m)
    return {"total": len(out), "items": out}


def list_formula_variants(q: str = "", diff_only: bool = False) -> dict:
    items = list(_load_json("formula_variants.json").get("items", []))
    q_low = (q or "").strip().lower()
    filtered = []
    for v in items:
        if diff_only and v.get("same_composition_and_dose"):
            continue
        if q_low:
            blob = " ".join([
                v.get("normalized_name", ""),
                v.get("summary", ""),
                v.get("shanghan_id", ""),
                v.get("jinkui_id", ""),
            ]).lower()
            if q_low not in blob:
                continue
        filtered.append(v)
    return {
        "total": len(filtered),
        "exact_same_count": sum(1 for v in items if v.get("same_composition_and_dose")),
        "diff_count": sum(1 for v in items if not v.get("same_composition_and_dose")),
        "items": filtered,
    }


def list_formula_acupuncture_links(
    q: str = "",
    formula_id: str = "",
    channel_id: str = "",
    chapter_id: str = "",
) -> dict:
    items = list(_load_json("formula_acupuncture_links.json").get("items", []))
    q_low = (q or "").strip().lower()
    out = []
    for a in items:
        if formula_id and a.get("formula_id") != formula_id:
            continue
        if channel_id and a.get("channel_id") != channel_id:
            continue
        if chapter_id and a.get("chapter_id") != chapter_id:
            continue
        if q_low:
            blob = " ".join([
                a.get("formula_id", ""),
                a.get("target_name", ""),
                a.get("relation_kind", ""),
                a.get("quote", ""),
                a.get("note", ""),
            ]).lower()
            if q_low not in blob:
                continue
        ent = _acup_entities().get(a.get("target_id", ""), {})
        out.append({
            **a,
            "target_meridian": ent.get("meridian_name", ""),
            "target_summary": ent.get("summary", ""),
        })
    return {"total": len(out), "items": out}


def enrich_formula_payload(item: dict) -> dict:
    if not item:
        return item
    fid = item["id"]
    mods_all = _load_json("formula_modifications.json").get("items", [])
    as_base = [m for m in mods_all if m.get("base_formula_id") == fid]
    as_target = [m for m in mods_all if m.get("target_formula_id") == fid]

    var_rec = next(
        (v for v in _load_json("formula_variants.json").get("items", [])
         if v.get("shanghan_id") == fid or v.get("jinkui_id") == fid),
        None,
    )
    cross_book_variant = None
    if var_rec:
        peer_id = var_rec["jinkui_id"] if var_rec["shanghan_id"] == fid else var_rec["shanghan_id"]
        cross_book_variant = {
            **var_rec,
            "peer_formula": _formula_brief(peer_id),
        }

    # Resolve chapter or six-channel reference
    jinkui_chapter = None
    six_channel_ref = None
    chapters = _load_json("jinkui_chapters.json").get("items", [])
    if item.get("book") == "金匮要略":
        ch_obj = next((c for c in chapters if fid in c.get("formula_ids", [])), None)
        if not ch_obj and item.get("chapter"):
            ch_obj = next((c for c in chapters if c["name"] == item["chapter"]), None)
        if ch_obj:
            jinkui_chapter = {
                "id": ch_obj["id"],
                "order": ch_obj.get("order"),
                "name": ch_obj["name"],
                "disease_category": ch_obj.get("disease_category", ""),
                "summary": ch_obj.get("summary", ""),
            }
    elif item.get("six_meridian") in CHANNEL_NAME_TO_ID:
        cid = CHANNEL_NAME_TO_ID[item["six_meridian"]]
        six_channel_ref = {"id": cid, "name": item["six_meridian"]}

    # Acupuncture links: direct formula match + channel/chapter scope fallback
    acup_items = _load_json("formula_acupuncture_links.json").get("items", [])
    acup_direct = []
    acup_context = []
    seen_ids = set()
    for a in acup_items:
        ent = _acup_entities().get(a.get("target_id", ""), {})
        row = {**a, "target_meridian": ent.get("meridian_name", ""), "target_summary": ent.get("summary", "")}
        if a.get("formula_id") == fid:
            acup_direct.append({**row, "relation_scope": "formula"})
            seen_ids.add(a["id"])
        elif jinkui_chapter and a.get("chapter_id") == jinkui_chapter["id"] and a["id"] not in seen_ids:
            acup_context.append({**row, "relation_scope": "chapter"})
            seen_ids.add(a["id"])
        elif six_channel_ref and a.get("channel_id") == six_channel_ref["id"] and a["id"] not in seen_ids:
            acup_context.append({**row, "relation_scope": "channel"})
            seen_ids.add(a["id"])

    return {
        **item,
        "modifications": {
            "as_base": as_base,
            "as_target": as_target,
        },
        "cross_book_variant": cross_book_variant,
        "jinkui_chapter": jinkui_chapter,
        "six_channel_ref": six_channel_ref,
        "acupuncture_relations": acup_direct + acup_context[:3],
    }


def enrich_six_channel_payload(item: dict) -> dict:
    if not item:
        return item
    fids = set(item.get("related_formula_ids", []))
    bfids = list(item.get("bridge_formula_ids", []))
    related_detail = [b for b in (_formula_brief(fid) for fid in item.get("related_formula_ids", [])) if b is not None]
    bridge_detail = [b for b in (_formula_brief(fid) for fid in bfids) if b is not None]
    mods = [
        m for m in _load_json("formula_modifications.json").get("items", [])
        if m.get("base_formula_id") in fids or m.get("target_formula_id") in fids
    ]
    acup = []
    seen = set()
    for a in _load_json("formula_acupuncture_links.json").get("items", []):
        if a.get("channel_id") == item["id"] or a.get("formula_id") in fids:
            if a["id"] not in seen:
                seen.add(a["id"])
                ent = _acup_entities().get(a.get("target_id", ""), {})
                acup.append({**a, "target_meridian": ent.get("meridian_name", ""), "target_summary": ent.get("summary", "")})
    return {
        **item,
        "related_formulas_detail": related_detail,
        "bridge_formulas_detail": bridge_detail,
        "modifications": mods,
        "acupuncture_relations": acup,
    }


def stage4_summary() -> dict:
    ev = _evidence_by_id()
    sh = _load_json("formulas.json")
    jk = _load_json("jinkui_formulas.json")
    return {
        "formula_count": len(sh) + len(jk),
        "shanghan_count": len(sh),
        "jinkui_count": len(jk),
        "reviewed_count": sum(1 for v in ev.values() if v.get("review_status") == "reviewed"),
        "six_channels_reviewed": sum(1 for c in _load_json("six_channels.json").get("items", []) if c.get("status") == "reviewed"),
        "jinkui_chapters_count": len(_load_json("jinkui_chapters.json").get("items", [])),
        "modifications_count": len(_load_json("formula_modifications.json").get("items", [])),
        "variants_count": len(_load_json("formula_variants.json").get("items", [])),
        "acupuncture_links_count": len(_load_json("formula_acupuncture_links.json").get("items", [])),
    }
