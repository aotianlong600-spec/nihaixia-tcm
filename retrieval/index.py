"""Deterministic Traditional/Simplified-aware search index across 17 digitized books & 4 modules."""
from __future__ import annotations

from functools import lru_cache
import json
import math
from pathlib import Path
import re
from typing import Any

from retrieval.t2s_table import T2S_TRANS
from retrieval.tcm_synonyms import expand_clinical_synonyms, expand_ortho_variants


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data"
LIB_SOURCES_DIR = ROOT / "sources" / "library"


_CJK_VARIANT_TRANS = str.maketrans({
    "\u3127": "一",
    "\uf9e7": "里",
    "裏": "里",
    "臓": "脏",
    "悪": "恶",
    "渇": "渴",
    "発": "发",
    "圧": "压",
    "気": "气",
    "薬": "药",
    "醫": "医",
    "證": "证",
    "脈": "脉",
    "癥": "症",
    "臍": "脐",
    "處": "处",
    "麥": "麦",
    "齋": "斋",
    "乾": "干",
    "髮": "发",
    "髪": "发",
    "朮": "术",
    "後": "后",
    "於": "于",
})


def norm_simp(text: str) -> str:
    simp = (text or "").translate(T2S_TRANS).translate(_CJK_VARIANT_TRANS)
    return re.sub(r"\s+", " ", simp).strip().lower()


_QUOTE_WS_RE = re.compile(r"[\s「」『』《》【】〔〕“”‘’\"<>〈〉]+")


def compact_cjk(text: str) -> str:
    """Strip whitespace and classic quotation brackets so line wraps & quotes do not break CJK phrase lookup."""
    return _QUOTE_WS_RE.sub("", norm_simp(text))


def _split_primary_terms(q: str) -> list[str]:
    cleaned = norm_simp(q)
    raw = [t.strip() for t in re.split(r"[\s,，、；;：:。！？!?\-\/]+", cleaned) if t.strip()]
    tokens: list[str] = []
    seen: set[str] = set()
    for part in raw:
        if part not in seen:
            seen.add(part)
            tokens.append(part)
    return tokens[:14]


def tokenize_query(q: str) -> list[str]:
    """Tokenize queries for structured entity/syndrome matching (includes 2-char subtokens for prose questions)."""
    tokens = _split_primary_terms(q)
    seen = set(tokens)
    for part in list(tokens):
        if len(part) >= 5 and re.fullmatch(r"[\u4e00-\u9fff]+", part):
            for i in range(0, len(part) - 1, 2):
                bg = part[i : i + 2]
                if bg not in seen:
                    seen.add(bg)
                    tokens.append(bg)
    return tokens[:14]


def _fallback_subtokens(primary: list[str]) -> list[str]:
    """Generate auxiliary 2-char subtokens ONLY when strict phrase/AND search yields zero hits."""
    subs: list[str] = []
    seen: set[str] = set()
    for part in primary:
        if part not in seen:
            seen.add(part)
            subs.append(part)
        if len(part) >= 4 and re.fullmatch(r"[\u4e00-\u9fff]+", part):
            for i in range(0, len(part) - 1, 2):
                bg = part[i : i + 2]
                if bg not in seen:
                    seen.add(bg)
                    subs.append(bg)
    return subs[:14]


@lru_cache(maxsize=1)
def _catalog_books() -> dict[str, dict[str, Any]]:
    cat = json.loads((DATA_DIR / "library" / "catalog.json").read_text(encoding="utf-8"))
    return {b["book_id"]: b for b in cat.get("books", [])}


@lru_cache(maxsize=1)
def _cross_links() -> dict[str, Any]:
    return json.loads((DATA_DIR / "library" / "cross_links.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _indexed_pages() -> list[dict[str, Any]]:
    books = _catalog_books()
    rows: list[dict[str, Any]] = []
    for bid, meta in books.items():
        if meta.get("search_index_status") != "indexed":
            continue
        jsonl_path = LIB_SOURCES_DIR / f"{bid}.jsonl"
        if not jsonl_path.exists():
            continue
        for raw_ln in jsonl_path.read_text(encoding="utf-8").splitlines():
            if not raw_ln.strip():
                continue
            r = json.loads(raw_ln)
            body = r.get("body_text") or ""
            if not body:
                continue
            st = norm_simp(r.get("search_text") or body)
            sec = norm_simp(r.get("section_title") or "")
            r["_stext_lower"] = st
            r["_stext_compact"] = _QUOTE_WS_RE.sub("", st)
            r["_sec_lower"] = sec
            r["_sec_compact"] = _QUOTE_WS_RE.sub("", sec)
            r["_title"] = meta["short_title"]
            r["_full_title"] = meta["title"]
            r["_shelf"] = meta["shelf"]
            r["_shelf_label"] = meta["shelf_label"]
            r["_tradition_layer"] = meta["tradition_layer"]
            rows.append(r)
    return rows


_TOC_LEADER_RE = re.compile(r"[\.·…]{4,}")
_TOC_PAREN_PAGE_RE = re.compile(r"[（(]\s*\d{2,4}\s*[）)]")


def classify_library_page_role(section_title: str, body_text: str) -> str:
    """Classify a library unit as 'toc', 'editorial', or substantive 'prose'."""
    sec = norm_simp(section_title or "")
    body = body_text or ""
    if any(k in sec for k in ("目录", "封面", "版权")):
        return "toc"
    head = norm_simp(body[:240])
    if any(k in head for k in ("法律问题", "本电子版", "仅供网络测试", "版权声明")):
        return "toc"
    if len(_TOC_LEADER_RE.findall(body)) >= 3:
        return "toc"
    if len(body) < 900 and len(_TOC_PAREN_PAGE_RE.findall(body)) >= 4:
        return "toc"
    if any(k in sec for k in ("现代编注", "现代学术研究", "著作辨考", "校注说明", "卷首概述", "自叙", "卷首")):
        return "editorial"
    return "prose"


def is_toc_or_frontmatter(section_title: str, body_text: str) -> bool:
    """Return True when a library unit is a TOC/frontmatter/modern editorial appendix rather than primary prose."""
    return classify_library_page_role(section_title, body_text) != "prose"


def _meta_page_penalty(row: dict[str, Any], wants_meta_page: bool) -> int:
    if wants_meta_page:
        return 0
    role = classify_library_page_role(row.get("section_title", ""), row.get("body_text", ""))
    if role == "toc":
        return -85
    if role == "editorial":
        return -35
    return 0


def _locate_in_body(body: str, tok: str) -> int:
    """Locate simplified/variant token in raw Traditional/wrapped body text by character span."""
    if not tok:
        return -1
    # Map body char index cleanly via translated/simplified characters (strict 1:1 index alignment)
    simp_chars = body.translate(T2S_TRANS).translate(_CJK_VARIANT_TRANS).lower()
    pos = simp_chars.find(tok)
    if pos >= 0:
        return pos
    # Fallback allowing arbitrary whitespace/newlines and quotation brackets inside CJK token
    compact_tok = _QUOTE_WS_RE.sub("", tok)
    if len(compact_tok) >= 2:
        pat = r"[\s「」『』《》【】〔〕“”‘’\"<>〈〉]*".join(re.escape(ch) for ch in compact_tok)
        m = re.search(pat, simp_chars)
        if m:
            return m.start()
    return -1


def _make_snippet(body: str, stext_lower: str, matched_tokens: list[str]) -> str:
    pos = -1
    for tok in sorted(matched_tokens, key=len, reverse=True):
        pos = _locate_in_body(body, tok)
        if pos >= 0:
            break
    if pos < 0:
        pos = 0
    start = max(0, pos - 36)
    end = min(len(body), pos + 148)
    snip = re.sub(r"\s+", " ", body[start:end]).strip()
    snip = re.sub(r"(?<=[\u4e00-\u9fff，。；：、！？「」『』（）])\s+(?=[\u4e00-\u9fff「」『』（）])", "", snip)
    if start > 0:
        snip = "…" + snip
    if end < len(body):
        snip = snip + "…"
    return snip


@lru_cache(maxsize=1)
def _curated_formulas_index() -> dict[str, dict[str, Any]]:
    """Load merged curated formula metadata from curated_formulas.json and curated_batches/."""
    merged: dict[str, dict[str, Any]] = {}
    cf_path = DATA_DIR / "curated_formulas.json"
    if cf_path.exists():
        raw = json.loads(cf_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            merged.update(raw)
    cb_dir = DATA_DIR / "curated_batches"
    if cb_dir.exists():
        for p in sorted(cb_dir.glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged.update(data)
    return merged


@lru_cache(maxsize=1024)
def _term_idf_multiplier(term_cmp: str) -> float:
    """Lightweight BM25-style IDF specificity weight across all indexed pages."""
    if not term_cmp:
        return 1.0
    pages = _indexed_pages()
    total_docs = max(len(pages), 1)
    df = sum(1 for row in pages if term_cmp in row["_sec_compact"] or term_cmp in row["_stext_compact"])
    return round(1.0 + min(1.6, math.log((total_docs + 1) / (df + 1)) / 2.8), 3)


def _score_matched_groups(
    tokens: list[str],
    term_groups: list[list[str]],
    sec_cmp: str,
    st_cmp: str,
    *,
    is_synonym_stage: bool = False,
) -> tuple[int, list[str], list[str], bool]:
    """Score one candidate page against grouped literal/variant/synonym terms."""
    combined_cmp = sec_cmp + "\n" + st_cmp
    matched_hits: list[str] = []
    snippet_terms: list[str] = []
    score = 0
    all_literal = True

    for raw_tok, alts in zip(tokens, term_groups):
        hit_alt = next((alt for alt in alts if alt and alt in combined_cmp), None)
        if hit_alt is None:
            return 0, [], [], False
        is_exact_form = hit_alt == alts[0]
        if not is_exact_form:
            all_literal = False
        in_sec = any(alt in sec_cmp for alt in alts if alt and alt in combined_cmp)
        freq = sum(combined_cmp.count(alt) for alt in alts if alt in combined_cmp)
        tf_weight = 1.0 + math.log1p(min(freq, 12))
        idf_mult = _term_idf_multiplier(hit_alt)
        len_base = 16 * max(1, min(len(hit_alt), 8))
        term_sc = int(round((len_base + tf_weight * 6) * idf_mult))
        if not is_exact_form:
            term_sc = int(round(term_sc * (0.72 if is_synonym_stage else 0.92)))
        if in_sec:
            term_sc += 28 if is_exact_form else 20
        score += term_sc
        matched_hits.append(raw_tok if is_exact_form else f"{raw_tok}→{hit_alt}")
        snippet_terms.append(hit_alt)

    return score, matched_hits, snippet_terms, all_literal


def search_library_pages(
    q: str = "",
    shelf: str = "",
    book_id: str = "",
    limit: int = 36,
) -> dict[str, Any]:
    """Full-text ranked search across digitized books (literal/variant AND -> clinical synonym -> bigram fallback)."""
    cleaned = norm_simp(q)
    cleaned_cmp = compact_cjk(q)
    tokens = _split_primary_terms(q)
    books = _catalog_books()
    cross = _cross_links()
    page_links_map = cross.get("page_links", {})

    if not cleaned:
        return {
            "query": q,
            "tokens": [],
            "expanded_terms": [],
            "total": 0,
            "exact_total": 0,
            "fallback_used": False,
            "scan_only_notice": [
                b["short_title"] for b in books.values() if b["search_index_status"] == "scan_browse_only"
            ],
            "items": [],
        }

    primary_cmp = [compact_cjk(t) for t in tokens if compact_cjk(t)]
    ortho_groups = [expand_ortho_variants(t, norm_fn=compact_cjk) for t in tokens if compact_cjk(t)]
    whole_ortho = expand_ortho_variants(q, norm_fn=compact_cjk)
    wants_meta_page = any(k in cleaned for k in ("目录", "篇目", "校注", "辨考", "考略", "自叙"))
    scored: list[tuple[int, int, str, dict[str, Any]]] = []
    shelf_bonus = {"hantang_clinical": 4, "renji_core": 3, "classical_companions": 2}
    exact_count = 0
    expanded_used: list[str] = []

    candidates = [
        row for row in _indexed_pages()
        if (not shelf or row["_shelf"] == shelf) and (not book_id or row["book_id"] == book_id)
    ]

    # Stage 1: Strict AND matching (literal + orthographic classical editions)
    for row in candidates:
        st_cmp = row["_stext_compact"]
        sec_cmp = row["_sec_compact"]
        sc, hits, snip_terms, all_literal = _score_matched_groups(
            tokens, ortho_groups, sec_cmp, st_cmp, is_synonym_stage=False
        )
        if not hits:
            continue

        combined_cmp = sec_cmp + "\n" + st_cmp
        matched_whole = next((w for w in whole_ortho if w and w in combined_cmp), None)
        is_exact = bool(matched_whole)
        if is_exact:
            exact_count += 1
            sc += (120 if len(matched_whole) >= 3 else 40)
            if matched_whole == cleaned_cmp:
                sc += 14
            if matched_whole in sec_cmp:
                sc += 50
            match_kind = "exact_phrase" if matched_whole == cleaned_cmp else "variant_phrase"
            snip_targets = [matched_whole] + snip_terms
        else:
            match_kind = "all_terms" if all_literal else "variant_terms"
            snip_targets = snip_terms

        for st in snip_terms:
            if st not in primary_cmp and st not in expanded_used:
                expanded_used.append(st)

        sc += shelf_bonus.get(row["_shelf"], 0) + _meta_page_penalty(row, wants_meta_page)
        pk = f"{row['book_id']}:{row['page_no']}"
        scored.append(
            (
                sc,
                len(hits),
                row["book_id"],
                {
                    "book_id": row["book_id"],
                    "book_title": row["_title"],
                    "book_full_title": row["_full_title"],
                    "shelf": row["_shelf"],
                    "shelf_label": row["_shelf_label"],
                    "tradition_layer": row["_tradition_layer"],
                    "page_no": row["page_no"],
                    "unit_label": row["unit_label"],
                    "section_title": row.get("section_title", ""),
                    "snippet": _make_snippet(row["body_text"], row["_stext_lower"], snip_targets),
                    "matched_tokens": hits[:6],
                    "match_kind": match_kind,
                    "text_sha256": row["text_sha256"],
                    "entity_links": page_links_map.get(pk, [])[:8],
                    "score": sc,
                },
            )
        )

    # Stage 2: Clinical synonym expansion (colloquial -> classical TCM terminology) when Stage 1 yields 0 hits
    if not scored:
        syn_groups = expand_clinical_synonyms(tokens, norm_fn=compact_cjk)
        if syn_groups and any(len(g) > len(og) for g, og in zip(syn_groups, ortho_groups)):
            for row in candidates:
                st_cmp = row["_stext_compact"]
                sec_cmp = row["_sec_compact"]
                sc, hits, snip_terms, _ = _score_matched_groups(
                    tokens, syn_groups, sec_cmp, st_cmp, is_synonym_stage=True
                )
                if not hits:
                    continue
                for st in snip_terms:
                    if st not in primary_cmp and st not in expanded_used:
                        expanded_used.append(st)
                sc += shelf_bonus.get(row["_shelf"], 0) + _meta_page_penalty(row, wants_meta_page)
                pk = f"{row['book_id']}:{row['page_no']}"
                scored.append(
                    (
                        sc,
                        len(hits),
                        row["book_id"],
                        {
                            "book_id": row["book_id"],
                            "book_title": row["_title"],
                            "book_full_title": row["_full_title"],
                            "shelf": row["_shelf"],
                            "shelf_label": row["_shelf_label"],
                            "tradition_layer": row["_tradition_layer"],
                            "page_no": row["page_no"],
                            "unit_label": row["unit_label"],
                            "section_title": row.get("section_title", ""),
                            "snippet": _make_snippet(row["body_text"], row["_stext_lower"], snip_terms),
                            "matched_tokens": hits[:6],
                            "match_kind": "synonym_expanded",
                            "text_sha256": row["text_sha256"],
                            "entity_links": page_links_map.get(pk, [])[:8],
                            "score": sc,
                        },
                    )
                )

    fallback_used = False
    if not scored:
        sub_tokens = _fallback_subtokens(primary_cmp)
        if sub_tokens:
            fallback_used = True
            for row in candidates:
                st_cmp = row["_stext_compact"]
                sec_cmp = row["_sec_compact"]
                combined_cmp = sec_cmp + "\n" + st_cmp
                hits = [tok for tok in sub_tokens if tok in combined_cmp]
                if not hits:
                    continue
                sc = (
                    sum(int(round(8 * len(t) * _term_idf_multiplier(t))) + (12 if t in sec_cmp else 0) for t in hits)
                    + shelf_bonus.get(row["_shelf"], 0)
                    + _meta_page_penalty(row, wants_meta_page)
                )
                pk = f"{row['book_id']}:{row['page_no']}"
                scored.append(
                    (
                        sc,
                        len(hits),
                        row["book_id"],
                        {
                            "book_id": row["book_id"],
                            "book_title": row["_title"],
                            "book_full_title": row["_full_title"],
                            "shelf": row["_shelf"],
                            "shelf_label": row["_shelf_label"],
                            "tradition_layer": row["_tradition_layer"],
                            "page_no": row["page_no"],
                            "unit_label": row["unit_label"],
                            "section_title": row.get("section_title", ""),
                            "snippet": _make_snippet(row["body_text"], row["_stext_lower"], hits),
                            "matched_tokens": hits[:6],
                            "match_kind": "partial_fallback",
                            "text_sha256": row["text_sha256"],
                            "entity_links": page_links_map.get(pk, [])[:8],
                            "score": sc,
                        },
                    )
                )

    scored.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]["page_no"]))
    per_cap = limit if (book_id or len(scored) <= limit) else 12
    items: list[dict[str, Any]] = []
    per_book: dict[str, int] = {}
    for _, _, bid, item in scored:
        if per_book.get(bid, 0) >= per_cap:
            continue
        per_book[bid] = per_book.get(bid, 0) + 1
        items.append(item)
        if len(items) >= limit:
            break

    return {
        "query": q,
        "tokens": tokens,
        "expanded_terms": expanded_used[:12],
        "total": len(scored),
        "exact_total": exact_count,
        "fallback_used": fallback_used,
        "scan_only_notice": [
            b["short_title"] for b in books.values() if b["search_index_status"] == "scan_browse_only"
        ],
        "items": items,
    }


def _flatten_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return " ".join(_flatten_str(v) for v in val.values())
    if isinstance(val, (list, tuple)):
        return " ".join(_flatten_str(v) for v in val)
    return str(val)


@lru_cache(maxsize=1)
def _structured_entities() -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    curated_map = _curated_formulas_index()

    for fn in ("formulas.json", "jinkui_formulas.json"):
        raw = json.loads((DATA_DIR / fn).read_text(encoding="utf-8"))
        for f in raw:
            fid = f["id"]
            cb = curated_map.get(fid, {})
            cb_syms = [
                f"{s.get('name', '')} {s.get('explanation', '')}"
                for s in (cb.get("symptoms") or [])
                if isinstance(s, dict)
            ]
            ov_txt = _flatten_str((cb.get("overview") or {}).get("paragraphs", [])) if isinstance(cb.get("overview"), dict) else ""
            why_txt = cb.get("why") or ""
            aliases = _flatten_str(f.get("aliases", []))
            blob = " ".join(
                [
                    f.get("name", ""),
                    aliases,
                    f.get("book", ""),
                    f.get("six_meridian", ""),
                    f.get("chapter", ""),
                    f.get("indication", ""),
                    f.get("notes", ""),
                    _flatten_str(f.get("ingredients", [])),
                    why_txt,
                    " ".join(cb_syms),
                    ov_txt,
                ]
            )
            summary_src = f.get("indication") or why_txt or ov_txt
            entities.append(
                {
                    "entity_id": fid,
                    "module": "formulas",
                    "module_label": "经方",
                    "title": f["name"],
                    "subtitle": f"{f.get('book', '')} · {f.get('six_meridian') or f.get('chapter') or ''}",
                    "summary": re.sub(r"\s+", " ", summary_src).strip()[:120],
                    "_title_variants": expand_ortho_variants(f["name"], norm_fn=norm_simp),
                    "_blob": norm_simp(blob),
                }
            )

    for h in json.loads((DATA_DIR / "bencao" / "entries.json").read_text(encoding="utf-8")):
        props = h.get("properties") or {}
        apps = h.get("applications") or {}
        classic_orig = h.get("classic_original") or {}
        ni_notes = h.get("ni_haixia_annotations") or {}
        proc = h.get("processing_and_compatibility") or {}
        blob = " ".join(
            [
                h.get("name", ""),
                h.get("short_name", ""),
                _flatten_str(h.get("aliases", [])),
                _flatten_str(classic_orig.get("text", "")),
                _flatten_str(props.get("qi_wei_raw", "")),
                _flatten_str(props.get("four_natures", [])),
                _flatten_str(props.get("five_flavors", [])),
                _flatten_str(apps),
                _flatten_str(ni_notes),
                _flatten_str(proc),
            ]
        )
        title_str = h.get("short_name") or h["name"]
        qi_wei = _flatten_str(props.get("qi_wei_raw", ""))
        summary_str = (
            _flatten_str(apps.get("main_summary"))
            or _flatten_str(classic_orig.get("text"))
            or qi_wei
        )
        entities.append(
            {
                "entity_id": h["id"],
                "module": "bencao",
                "module_label": "神农本草",
                "title": title_str,
                "subtitle": f"{h.get('grade', '')} · {qi_wei[:24]}",
                "summary": re.sub(r"\s+", " ", summary_str).strip()[:120],
                "_title_variants": expand_ortho_variants(title_str, norm_fn=norm_simp),
                "_blob": norm_simp(blob),
            }
        )

    for p in json.loads((DATA_DIR / "acupuncture" / "acupoints.json").read_text(encoding="utf-8")).get("items", []):
        blob = " ".join([p.get("canonical_name", ""), _flatten_str(p.get("aliases", [])), _flatten_str(p.get("indications", [])), _flatten_str(p.get("summary", ""))])
        entities.append(
            {
                "entity_id": p["id"],
                "module": "acupuncture",
                "module_label": "针灸穴位",
                "title": p["canonical_name"],
                "subtitle": p.get("meridian_name") or "穴位",
                "summary": (_flatten_str(p.get("summary")) or _flatten_str(p.get("indications", [])[:3]))[:120],
                "_title_variants": [norm_simp(p["canonical_name"])],
                "_blob": norm_simp(blob),
            }
        )

    for c in json.loads((DATA_DIR / "neijing" / "concepts.json").read_text(encoding="utf-8")).get("items", []):
        blob = " ".join([c.get("canonical_name", ""), c.get("summary", ""), c.get("clinical_relevance", "")])
        entities.append(
            {
                "entity_id": c["id"],
                "module": "neijing",
                "module_label": "黄帝内经",
                "title": c["canonical_name"],
                "subtitle": c.get("submodule", "内经专题"),
                "summary": (c.get("summary") or "")[:120],
                "_title_variants": [norm_simp(c["canonical_name"])],
                "_blob": norm_simp(blob),
            }
        )

    ht_path = DATA_DIR / "hantang" / "hantang_catalog.json"
    if ht_path.exists():
        ht_data = json.loads(ht_path.read_text(encoding="utf-8"))
        for hf in ht_data.get("formulas", []):
            ni_o = hf.get("ni_original") or {}
            zj_n = hf.get("ziji_note") or {}
            blob = " ".join(
                [
                    hf.get("ht_number", ""),
                    hf.get("name", ""),
                    hf.get("full_title", ""),
                    hf.get("category", ""),
                    _flatten_str(hf.get("clinical_tags", [])),
                    _flatten_str(ni_o),
                    _flatten_str(zj_n),
                ]
            )
            title_ht = f"{hf.get('ht_number', '')} {hf.get('name', '')}".strip()
            entities.append(
                {
                    "entity_id": hf["id"],
                    "module": "hantang",
                    "module_label": "汉唐百方",
                    "title": title_ht,
                    "subtitle": hf.get("category_short") or hf.get("category") or "汉唐临床经验方",
                    "summary": re.sub(r"\s+", " ", _flatten_str(ni_o.get("indications"))).strip()[:120],
                    "_title_variants": [norm_simp(title_ht), norm_simp(hf.get("name", ""))],
                    "_blob": norm_simp(blob),
                }
            )

    return entities


def search_all_knowledge(q: str = "", limit: int = 24) -> list[dict[str, Any]]:
    """Search structured knowledge records across all modules simultaneously."""
    cleaned = norm_simp(q)
    tokens = tokenize_query(q)
    if not tokens:
        return []
    token_groups = expand_clinical_synonyms(tokens, norm_fn=norm_simp)
    whole_ortho = expand_ortho_variants(q, norm_fn=norm_simp)

    scored: list[tuple[int, dict[str, Any]]] = []
    for ent in _structured_entities():
        blob = ent["_blob"]
        title_l = norm_simp(ent["title"])
        title_vars = ent.get("_title_variants") or [title_l]
        sc = 0
        for grp in token_groups:
            primary = grp[0]
            if primary in title_l:
                sc += 25
            elif any(alt in tv for alt in grp[:4] for tv in title_vars):
                sc += 20
            elif primary in blob:
                sc += 6
            elif any(alt in blob for alt in grp[1:] if len(alt) >= 2):
                sc += 3
        if cleaned and cleaned in title_l:
            sc += 40
        elif any(w and w in tv for w in whole_ortho[1:] for tv in title_vars):
            sc += 32
        if sc > 0:
            scored.append((sc, {k: v for k, v in ent.items() if not k.startswith("_")}))
    scored.sort(key=lambda x: (-x[0], x[1]["module"], x[1]["entity_id"]))
    return [item for _, item in scored[:limit]]
