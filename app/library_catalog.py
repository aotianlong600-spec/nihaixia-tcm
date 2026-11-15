"""Stage 5 Book Library catalog, page reader, PDF image renderer & bidirectional entity links."""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
import uuid

from retrieval.index import compact_cjk, norm_simp, search_library_pages


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data"
LIB_SOURCES_DIR = ROOT / "sources" / "library"
IMAGE_CACHE_DIR = DATA_DIR / "library" / "page_images"
_PDFIUM_RENDER_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    return json.loads((DATA_DIR / "library" / "catalog.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _books_by_id() -> dict[str, dict[str, Any]]:
    return {b["book_id"]: b for b in _catalog().get("books", [])}


BOOK_ID_ALIASES = {
    "acupuncture-pdf": "ni-acupuncture-v2-20100703",
    "ni-acupuncture-pdf": "ni-acupuncture-v2-20100703",
    "bencao-pdf": "ni-bencao-pdf",
    "shennong-bencao-pdf": "ni-bencao-pdf",
    "neijing-suwen-pdf": "ni-neijing-vol1-pdf",
    "ni_neijing_vol1": "ni-neijing-vol1-pdf",
    "ni_neijing_vol2": "ni-neijing-vol2-pdf",
    "shanghan-lun-pdf": "ni-shanghan-pdf",
    "shanghan-pdf": "ni-shanghan-pdf",
    "jin-gui-yuhan-pdf": "ni-jinkui-pdf",
    "jinkui-pdf": "ni-jinkui-pdf",
    "jinkui-video-pdf": "ni-jinkui-video-pdf",
}


def _resolve_book_id_alias(book_id: str) -> str:
    bid = (book_id or "").strip()
    books = _books_by_id()
    if bid in books:
        return bid
    return BOOK_ID_ALIASES.get(bid, bid)


_HEADING_SCAN_RE = re.compile(
    r"^(?:"
    r"辨[^。\n]{2,18}脉证[^。\n]{0,10}"
    r"|第[一二三四五六七八九十百零\d]+[篇章节回卷][^。\n]{0,20}"
    r"|卷[一二三四五六七八九十]+(?:\s*[^\s。\n]{1,12})?"
    r"|[一二三四五六七八九十百]+、\s*[\u4e00-\u9fff]{1,14}"
    r"|HT-\d+[^\n]{0,20}"
    r")"
)


def _is_junk_chapter_title(title: str) -> bool:
    t = norm_simp((title or "").strip())
    if not t:
        return True
    if t.lower() == "blank" or t in {"上册", "下册", "封面", "目录"}:
        return True
    if any(k in t for k in ("法律问题", "本电子版", "仅供网络测试", "版权声明")):
        return True
    if re.search(r"[\.·…]{4,}", t):
        return True
    return False


def _is_frontmatter_or_toc_text(body_text: str) -> bool:
    txt = (body_text or "").strip()
    if not txt or len(compact_cjk(txt)) < 16:
        return True
    if any(k in txt[:220] for k in ("法律问题", "本电子版", "仅供网络测试")):
        return True
    if len(re.findall(r"[\.·…]{5,}", txt)) >= 2:
        return True
    return False


@lru_cache(maxsize=32)
def _clean_book_chapters(book_id: str, limit: int = 420) -> list[dict[str, Any]]:
    meta = _books_by_id().get(book_id)
    if not meta:
        return []
    pages = _book_pages(book_id)
    total = len(pages)
    if not total:
        return []

    by_p = {int(p["page_no"]): p for p in pages}
    out: list[dict[str, Any]] = []
    seen_title_page: set[tuple[str, int]] = set()
    seen_titles: set[str] = set()

    def _push(raw_title: str, pno: int, allow_dup_title: bool = False) -> None:
        if len(out) >= limit or pno < 1 or pno > total:
            return
        title = re.sub(r"\s+", " ", (raw_title or "").strip())
        title = re.sub(r"[\.…]+.*$|·{2,}.*$", "", title).strip()
        if not title or _is_junk_chapter_title(title):
            return
        if len(title) > 28:
            title = title[:27].rstrip() + "…"
        if not allow_dup_title and title in seen_titles:
            return
        key = (title, pno)
        if key in seen_title_page:
            return
        seen_title_page.add(key)
        seen_titles.add(title)
        pg = by_p.get(pno, {})
        out.append({"title": title, "page_no": pno, "unit_label": pg.get("unit_label", f"第 {pno} 页")})

    # 1. Clean declared chapters first
    for ch in meta.get("chapters", []):
        pno = int(ch.get("page_no") or 0)
        if pno in by_p and _is_frontmatter_or_toc_text(by_p[pno].get("body_text", "")) and pno <= 4 and meta.get("search_index_status") != "scan_browse_only":
            # Skip frontmatter TOC pointers if better entries exist unless tiny book
            if total > 15:
                continue
        _push(ch.get("title", ""), pno)

    # 2. Enrich sparse books from page headings, section_title changes & inline headings
    if len(out) < 15 and meta.get("search_index_status") != "scan_browse_only":
        last_sec = ""
        for p in pages:
            pno = int(p["page_no"])
            body = p.get("body_text") or ""
            if _is_frontmatter_or_toc_text(body):
                continue
            for h in p.get("headings") or []:
                _push(str(h), pno)
            sec = (p.get("section_title") or "").strip()
            if sec and sec != last_sec:
                last_sec = sec
                _push(sec, pno)
            for ln in body.splitlines()[:14]:
                s = ln.strip()
                m = _HEADING_SCAN_RE.match(s)
                if m and len(s) <= 28:
                    _push(s, pno)

    # 3. For sparse clinical/classic books (e.g. 伤寒/金匮/针灸), add primary entity landmarks so index is directly clickable
    if len(out) < 30 and meta.get("search_index_status") != "scan_browse_only":
        page_links = _cross_links().get("page_links", {})
        covered_pages = {c["page_no"] for c in out}
        for p in pages:
            pno = int(p["page_no"])
            if pno in covered_pages or _is_frontmatter_or_toc_text(p.get("body_text", "")):
                continue
            links = page_links.get(f"{book_id}:{pno}", [])
            for lk in links:
                lbl = (lk.get("label") or "").strip()
                if not lbl or len(lbl) > 20:
                    continue
                _push(f"{lbl}", pno)
                break
            if len(out) >= min(limit, 120):
                break

    # 4. For scan-only volumes, offer clean page-block landmarks so they are immediately jumpable
    if not out and meta.get("search_index_status") == "scan_browse_only":
        step = max(10, total // 24)
        for pno in range(1, total + 1, step):
            _push(f"影印第 {pno} 页起", pno, allow_dup_title=True)
        if total not in {c["page_no"] for c in out}:
            _push(f"末页（第 {total} 页）", total, allow_dup_title=True)

    out.sort(key=lambda x: (x["page_no"], x["title"]))
    return out[:limit]


@lru_cache(maxsize=1)
def _cross_links() -> dict[str, Any]:
    return json.loads((DATA_DIR / "library" / "cross_links.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _syndrome_clusters() -> list[dict[str, Any]]:
    return json.loads((DATA_DIR / "relations" / "syndrome_clusters.json").read_text(encoding="utf-8")).get("items", [])


@lru_cache(maxsize=20)
def _book_pages(book_id: str) -> list[dict[str, Any]]:
    path = LIB_SOURCES_DIR / f"{book_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def overview() -> dict[str, Any]:
    cat = _catalog()
    books = cat.get("books", [])
    shelves = []
    for key, meta in sorted(cat.get("shelves", {}).items(), key=lambda x: x[1]["order"]):
        s_books = [b for b in books if b["shelf"] == key]
        shelves.append({"key": key, **meta, "book_count": len(s_books)})
    cross = _cross_links()
    return {
        "stats": {
            **cat.get("stats", {}),
            "linked_pages": len(cross.get("page_links", {})),
            "linked_entities": len(cross.get("entity_refs", {})),
        },
        "shelves": shelves,
    }


def list_books(shelf: str = "", q: str = "") -> dict[str, Any]:
    books = _catalog().get("books", [])
    nq = norm_simp(q)
    out = []
    for b in books:
        if shelf and b["shelf"] != shelf:
            continue
        if nq:
            blob = norm_simp(" ".join([b["title"], b["short_title"], b["author_era"], b["description"]]))
            if nq not in blob:
                continue
        out.append(
            {
                "book_id": b["book_id"],
                "title": b["title"],
                "short_title": b["short_title"],
                "author_era": b["author_era"],
                "shelf": b["shelf"],
                "shelf_label": b["shelf_label"],
                "file_format": b["file_format"],
                "total_units": b["total_units"],
                "text_units": b["text_units"],
                "has_image_viewer": b["has_image_viewer"],
                "search_index_status": b["search_index_status"],
                "tradition_layer": b["tradition_layer"],
                "module_affinities": b["module_affinities"],
                "chapter_count": len(b.get("chapters", [])),
                "description": b["description"],
            }
        )
    return {"total": len(out), "items": out}


def get_book(book_id: str) -> dict[str, Any] | None:
    book_id = _resolve_book_id_alias(book_id)
    meta = _books_by_id().get(book_id)
    if not meta:
        return None
    pages = _book_pages(book_id)
    page_links = _cross_links().get("page_links", {})
    linked_count = sum(1 for p in pages if f"{book_id}:{p['page_no']}" in page_links)

    # Top mentioned entities across this book
    entity_counts: dict[str, dict[str, Any]] = {}
    for p in pages:
        for lk in page_links.get(f"{book_id}:{p['page_no']}", []):
            eid = lk["entity_id"]
            if eid not in entity_counts:
                entity_counts[eid] = {**lk, "mentions": 0, "first_page": p["page_no"]}
            entity_counts[eid]["mentions"] += 1
    top_entities = sorted(entity_counts.values(), key=lambda x: (-x["mentions"], x["first_page"]))[:24]

    return {
        **meta,
        "chapters": _clean_book_chapters(book_id),
        "linked_page_count": linked_count,
        "top_entities": top_entities,
        "preview_pages": [
            {
                "page_no": p["page_no"],
                "unit_label": p["unit_label"],
                "section_title": p.get("section_title", ""),
                "ocr_status": p.get("ocr_status", ""),
                "link_count": len(page_links.get(f"{book_id}:{p['page_no']}", [])),
                "preview": (p.get("body_text") or "")[:90],
            }
            for p in pages[:60]
        ],
    }


def list_book_pages(book_id: str, q: str = "", offset: int = 0, limit: int = 60) -> dict[str, Any] | None:
    book_id = _resolve_book_id_alias(book_id)
    meta = _books_by_id().get(book_id)
    if not meta:
        return None
    pages = _book_pages(book_id)
    page_links = _cross_links().get("page_links", {})
    if q.strip():
        nq = norm_simp(q)
        nq_cmp = compact_cjk(q)
        filtered = [
            p for p in pages
            if nq in norm_simp(p.get("search_text") or p.get("body_text") or "")
            or nq in norm_simp(p.get("section_title", ""))
            or (
                nq_cmp
                and (
                    nq_cmp in compact_cjk(p.get("search_text") or p.get("body_text") or "")
                    or nq_cmp in compact_cjk(p.get("section_title", ""))
                )
            )
        ]
    else:
        filtered = pages
    sliced = filtered[offset : offset + limit]
    return {
        "book_id": book_id,
        "book_title": meta["short_title"],
        "search_index_status": meta["search_index_status"],
        "total": len(filtered),
        "offset": offset,
        "items": [
            {
                "page_no": p["page_no"],
                "unit_label": p["unit_label"],
                "section_title": p.get("section_title", ""),
                "ocr_status": p.get("ocr_status", ""),
                "link_count": len(page_links.get(f"{book_id}:{p['page_no']}", [])),
                "preview": (p.get("body_text") or "")[:100] or meta["description"][:70],
            }
            for p in sliced
        ],
    }


def get_book_page(book_id: str, page_no: int) -> dict[str, Any] | None:
    book_id = _resolve_book_id_alias(book_id)
    meta = _books_by_id().get(book_id)
    if not meta:
        return None
    pages = _book_pages(book_id)
    if page_no < 1 or page_no > len(pages):
        return None
    row = pages[page_no - 1]
    pk = f"{book_id}:{page_no}"
    links = _cross_links().get("page_links", {}).get(pk, [])
    has_img = meta["has_image_viewer"]
    return {
        "book_id": book_id,
        "book_title": meta["short_title"],
        "book_full_title": meta["title"],
        "shelf": meta["shelf"],
        "shelf_label": meta["shelf_label"],
        "tradition_layer": meta["tradition_layer"],
        "search_index_status": meta["search_index_status"],
        "page_no": page_no,
        "total_units": len(pages),
        "prev_page": page_no - 1 if page_no > 1 else None,
        "next_page": page_no + 1 if page_no < len(pages) else None,
        "unit_type": row["unit_type"],
        "unit_label": row["unit_label"],
        "printed_page": row.get("printed_page"),
        "section_title": row.get("section_title", ""),
        "headings": row.get("headings", []),
        "body_text": row.get("body_text", ""),
        "text_sha256": row.get("text_sha256", ""),
        "extraction_method": row.get("extraction_method", ""),
        "ocr_status": row.get("ocr_status", ""),
        "has_image_viewer": has_img,
        "image_url": f"/api/library/books/{book_id}/pages/{page_no}/image" if has_img else None,
        "entity_links": links,
    }


def get_book_context(book_id: str, page_no: int = 1, before: int = 2, after: int = 4) -> dict[str, Any] | None:
    """Return a contiguous window of pages around ``page_no`` for seamless vertical reading."""
    book_id = _resolve_book_id_alias(book_id)
    meta = _books_by_id().get(book_id)
    if not meta:
        return None
    pages = _book_pages(book_id)
    total = len(pages)
    if total == 0:
        return None
    center = max(1, min(total, int(page_no or 1)))
    safe_before = max(0, min(6, int(before)))
    safe_after = max(0, min(8, int(after)))
    start_p = max(1, center - safe_before)
    end_p = min(total, center + safe_after)
    window_pages = [pg for p in range(start_p, end_p + 1) if (pg := get_book_page(book_id, p)) is not None]
    return {
        "book_id": book_id,
        "book_title": meta["short_title"],
        "book_full_title": meta["title"],
        "shelf": meta["shelf"],
        "shelf_label": meta["shelf_label"],
        "tradition_layer": meta["tradition_layer"],
        "search_index_status": meta["search_index_status"],
        "has_image_viewer": meta["has_image_viewer"],
        "total_units": total,
        "target_page": center,
        "start_page": start_p,
        "end_page": end_p,
        "has_prev_chunk": start_p > 1,
        "has_next_chunk": end_p < total,
        "pages": window_pages,
    }


def _infer_book_id(book_id: str, book_hint: str) -> str:
    """Resolve explicit book_id or Chinese source book hint to one of catalog's 17 books."""
    bid = _resolve_book_id_alias(book_id)
    books = _books_by_id()
    if bid in books:
        return bid
    hint = norm_simp(f"{bid} {book_hint}").lower()
    if not hint.strip():
        return ""
    if "辑义" in hint or "juyi" in hint:
        return "shanghan-juyi-book-txt"
    if "大冢" in hint or "敬节" in hint or "otsuka" in hint:
        return "otsuka-shanghan-docx"
    if "证因" in hint or "王儒林" in hint:
        return "wang-rulin-zhengyinfanglun-doc"
    if "金匮" in hint and ("视频" in hint or "文稿" in hint or "video" in hint):
        return "ni-jinkui-video-pdf"
    if "金匮" in hint or "jinkui" in hint:
        return "ni-jinkui-pdf"
    if "伤寒" in hint or "六经" in hint or "shanghan" in hint:
        return "ni-shanghan-pdf"
    if "本草" in hint or "神农" in hint or "bencao" in hint:
        return "ni-bencao-pdf"
    if "针灸" in hint or "acup" in hint:
        return "ni-acupuncture-v2-20100703"
    if "内经" in hint or "素问" in hint or "neijing" in hint:
        if "下" in hint or "vol2" in hint:
            return "ni-neijing-vol2-pdf"
        return "ni-neijing-vol1-pdf"
    if "汉唐" in hint and ("案" in hint or "文" in hint):
        return "ni-hantang-articles-cases-pdf"
    if "汉唐" in hint:
        return "ni-hantang-formulas-pdf"
    if "血证" in hint:
        return "tang-rongchuan-xuezhenglun-pdf"
    if "石室" in hint:
        return "chen-shiduo-shishimilu-txt"
    if any(
        k in hint
        for k in (
            "徐灵胎",
            "徐大椿",
            "明清名医",
            "难经经释",
            "百种录",
            "医贯砭",
            "医学源流论",
            "伤寒类方",
            "兰台轨范",
            "慎疾刍言",
            "洄溪医案",
        )
    ):
        return "xu-lingtai-collection-pdf"
    if "外经" in hint:
        return "huangdi-waijing-pdf"
    if any(
        kw in hint
        for kw in (
            "太阳", "阳明", "少阳", "太阴", "少阴", "厥阴", "霍乱", "阴阳易", "瘥后",
            "桂枝", "麻黄", "葛根", "青龙", "白虎", "承气", "柴胡", "陷胸", "泻心",
            "理中", "四逆", "真武", "倪注", "表实", "表寒", "伤寒例", "辨脉", "平脉",
        )
    ):
        return "ni-shanghan-pdf"
    return ""


def _clean_locate_probe(q: str) -> str:
    raw = norm_simp((q or "").strip())
    if not raw:
        return ""
    # Strip bracketed labels like 【...】 or page markers
    stripped = re.sub(r"【[^】]{1,12}】", " ", raw)
    parts = [p.strip() for p in re.split(r"[\r\n。！？!?；;…“”\"'()（）]+", stripped) if len(compact_cjk(p)) >= 4]
    if parts:
        # Prefer first substantial clause cleanly trimmed to 16 chars
        best = parts[0]
        return best[:16].strip()
    comp = compact_cjk(stripped)
    return comp[:16] if len(comp) >= 2 else raw[:20].strip()


def locate_book_context(
    book_id: str = "",
    page_no: int = 0,
    line: int = 0,
    q: str = "",
    book_hint: str = "",
    before: int = 2,
    after: int = 4,
) -> dict[str, Any] | None:
    """Resolve any module citation (book_id/hint + page/line/quote) to a scrollable library context window."""
    books = _books_by_id()
    bid = _infer_book_id(book_id, book_hint)
    resolved_bid = bid
    resolved_page = int(page_no or 0)
    probe = _clean_locate_probe(q)

    # 1. Exact line resolution for 伤寒论辑义 (units carry Lstart-Lend ranges)
    if int(line or 0) > 0 and (bid == "shanghan-juyi-book-txt" or "juyi" in norm_simp(f"{book_id} {book_hint}").lower()):
        target_line = int(line)
        for p in _book_pages("shanghan-juyi-book-txt"):
            m = re.search(r"L(\d+)\s*-\s*L(\d+)", p.get("unit_label", ""))
            if m and int(m.group(1)) <= target_line <= int(m.group(2)):
                resolved_bid = "shanghan-juyi-book-txt"
                resolved_page = int(p["page_no"])
                break

    # 2. Validate & refine page_no against actual book text (avoid TOC/cover/off-by-N misses; supports >=2 CJK chars)
    cands = list(dict.fromkeys(x for x in (probe, (q or "").strip()[:18], probe[:8]) if len(compact_cjk(x)) >= 2 or len(x) >= 2))
    if resolved_page > 0 and resolved_bid in books:
        meta = books[resolved_bid]
        if meta.get("search_index_status") != "scan_browse_only":
            pages = _book_pages(resolved_bid)
            by_p = {int(p["page_no"]): p for p in pages}
            cur_pg = by_p.get(resolved_page)
            probe_cmp = compact_cjk(probe)[:8]
            cur_cmp = compact_cjk((cur_pg.get("search_text") or cur_pg.get("body_text") or "") if cur_pg else "")
            cur_is_bad = (not cur_pg) or _is_frontmatter_or_toc_text(cur_pg.get("body_text", ""))
            cur_misses_probe = len(probe_cmp) >= 2 and probe_cmp not in cur_cmp

            if cur_is_bad or cur_misses_probe:
                found_p = 0
                if len(probe_cmp) >= 2:
                    # First scan nearby window [-3, +6] preferring real body pages over TOC/frontmatter
                    win_range = list(range(max(1, resolved_page - 3), min(len(pages), resolved_page + 6) + 1))
                    for strict_body in (True, False):
                        for cand_p in win_range:
                            nb = by_p.get(cand_p)
                            if not nb:
                                continue
                            if strict_body and _is_frontmatter_or_toc_text(nb.get("body_text", "")):
                                continue
                            if probe_cmp in compact_cjk(nb.get("search_text") or nb.get("body_text") or ""):
                                found_p = cand_p
                                break
                        if found_p:
                            break

                    # If still missing nearby (e.g., wrong chapter start page or cover), search whole book (and vol2 for Neijing)
                    if not found_p:
                        pool = [resolved_bid]
                        if resolved_bid == "ni-neijing-vol1-pdf" and "下" not in norm_simp(book_hint):
                            pool.append("ni-neijing-vol2-pdf")
                        for cand_q in cands:
                            for pool_bid in pool:
                                sr = search_library_pages(cand_q, book_id=pool_bid, limit=10)
                                hits = [h for h in (sr.get("items") or []) if h.get("match_kind") != "partial_fallback"]
                                if not hits:
                                    continue
                                pool_by_p = {int(pp["page_no"]): pp for pp in _book_pages(pool_bid)}
                                clean_hit = next(
                                    (h for h in hits if not _is_frontmatter_or_toc_text((pool_by_p.get(int(h["page_no"])) or {}).get("body_text", ""))),
                                    None,
                                )
                                chosen = clean_hit or (hits[0] if cur_is_bad else None)
                                if chosen:
                                    resolved_bid = chosen["book_id"]
                                    found_p = int(chosen["page_no"])
                                    break
                            if found_p:
                                break
                if found_p:
                    resolved_page = found_p
                elif cur_is_bad:
                    # Guarantee we don't drop user on an empty blank page if nearby content exists
                    for delta in range(1, min(20, len(pages) + 1)):
                        for cand_p in (resolved_page + delta, resolved_page - delta):
                            nb = by_p.get(cand_p)
                            if nb and not _is_frontmatter_or_toc_text(nb.get("body_text", "")):
                                resolved_page = cand_p
                                break
                        if not _is_frontmatter_or_toc_text((by_p.get(resolved_page) or {}).get("body_text", "")):
                            break

    # 3. Search by quote/title when page_no is missing OR book_id/book_hint was unrecognized
    if (resolved_page <= 0 or resolved_bid not in books) and cands:
        book_pool = [resolved_bid] if resolved_bid in books else []
        if resolved_bid == "ni-neijing-vol1-pdf" and "下" not in norm_simp(book_hint):
            book_pool = ["ni-neijing-vol1-pdf", "ni-neijing-vol2-pdf"]
        hit = None
        for allow_partial in (False, True):
            if allow_partial and not book_pool:
                break
            for cand in cands:
                for pool_bid in book_pool:
                    sr = search_library_pages(cand, book_id=pool_bid, limit=28)
                    hits = sr.get("items") or []
                    if not allow_partial:
                        hits = [h for h in hits if h.get("match_kind") != "partial_fallback"]
                    if hits:
                        pool_by_p = {int(pp["page_no"]): pp for pp in _book_pages(pool_bid)}
                        sub_hints = [
                            k
                            for k in ("难经经释", "百种录", "医贯砭", "医学源流论", "伤寒类方", "兰台轨范", "慎疾刍言", "洄溪医案")
                            if k in norm_simp(book_hint)
                        ]
                        sub_filtered = (
                            [h for h in hits if any(sk in norm_simp(h.get("section_title", "")) for sk in sub_hints)]
                            if sub_hints
                            else []
                        )
                        cand_hits = sub_filtered or hits
                        hit = next(
                            (h for h in cand_hits if not _is_frontmatter_or_toc_text((pool_by_p.get(int(h["page_no"])) or {}).get("body_text", ""))),
                            cand_hits[0],
                        )
                        break
                if hit:
                    break
            if hit:
                break
        if not hit:
            for cand in cands:
                sr = search_library_pages(cand, limit=20)
                hits = [h for h in (sr.get("items") or []) if h.get("match_kind") != "partial_fallback"]
                if hits:
                    clean_hits = [
                        h
                        for h in hits
                        if not _is_frontmatter_or_toc_text(
                            (get_book_page(h["book_id"], int(h["page_no"])) or {}).get("body_text", "")
                        )
                    ]
                    pool_hits = clean_hits or hits
                    if int(page_no or 0) > 0:
                        near = next((h for h in pool_hits if abs(int(h["page_no"]) - int(page_no)) <= 2), None)
                        hit = near or pool_hits[0]
                    else:
                        hit = pool_hits[0]
                    break
        if hit:
            resolved_bid = hit["book_id"]
            resolved_page = int(hit["page_no"])

    if not resolved_bid or resolved_bid not in books:
        return None
    ctx = get_book_context(resolved_bid, page_no=max(1, resolved_page), before=before, after=after)
    if not ctx:
        return None

    # Collect in-book hit index for one-click jumping inside the drawer
    matched_pages: list[dict[str, Any]] = []
    if cands and books[resolved_bid].get("search_index_status") != "scan_browse_only":
        seen_p: set[int] = set()
        for cand in cands[:2]:
            sr = search_library_pages(cand, book_id=resolved_bid, limit=10)
            for h in sr.get("items") or []:
                if h.get("match_kind") == "partial_fallback":
                    continue
                pno = int(h["page_no"])
                if pno in seen_p:
                    continue
                seen_p.add(pno)
                matched_pages.append(
                    {
                        "page_no": pno,
                        "unit_label": h.get("unit_label", f"第 {pno} 页"),
                        "section_title": h.get("section_title", ""),
                        "snippet": (h.get("snippet") or "")[:64],
                    }
                )
            if len(matched_pages) >= 8:
                break

    ctx["matched_query"] = probe or (q or "").strip()
    ctx["resolved_book_id"] = resolved_bid
    ctx["resolved_page_no"] = ctx["target_page"]
    ctx["chapters"] = _clean_book_chapters(resolved_bid)
    ctx["matched_pages"] = matched_pages
    return ctx


def render_book_page_image(book_id: str, page_no: int) -> Path | None:
    resolved_id = _resolve_book_id_alias(book_id)
    meta = _books_by_id().get(resolved_id)
    if not meta or not meta.get("has_image_viewer"):
        return None
    if page_no < 1 or page_no > meta["total_units"]:
        return None
    out_dir = IMAGE_CACHE_DIR / resolved_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"page_{page_no:04d}.png"
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    pdf_path = ROOT / meta["relative_path"]
    if not pdf_path.exists():
        return None
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415
    except ImportError:
        return None

    # PDFium's C runtime and PdfDocument handles are not thread-safe under FastAPI's anyio worker pool;
    # serialize rendering and write atomically via a temporary PNG before replacing the cached target.
    with _PDFIUM_RENDER_LOCK:
        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path
        tmp_path = out_dir / f".tmp_page_{page_no:04d}_{uuid.uuid4().hex}.png"
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            page = doc[page_no - 1]
            bitmap = page.render(scale=1.75)
            pil_img = bitmap.to_pil()
            pil_img.save(tmp_path, format="PNG")
            os.replace(tmp_path, out_path)
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            doc.close()
    return out_path


def get_entity_links(entity_id: str) -> dict[str, Any]:
    """Return all book references AND Stage 5A syndrome clusters connected to any entity across all 4 modules."""
    refs = _cross_links().get("entity_refs", {}).get(entity_id, [])
    syndromes = []
    for sc in _syndrome_clusters():
        all_ids = (
            sc.get("formula_ids", [])
            + sc.get("bencao_ids", [])
            + sc.get("acupuncture_condition_ids", [])
            + sc.get("acupuncture_point_ids", [])
            + sc.get("neijing_concept_ids", [])
            + sc.get("neijing_chapter_ids", [])
        )
        if entity_id in all_ids:
            syndromes.append({"id": sc["id"], "title": sc["title"], "clinical_reasoning": sc["clinical_reasoning"]})
    return {
        "entity_id": entity_id,
        "library_ref_count": len(refs),
        "library_refs": refs,
        "related_syndromes": syndromes,
    }


def search(q: str = "", shelf: str = "", book_id: str = "", limit: int = 36) -> dict[str, Any]:
    return search_library_pages(q=q, shelf=shelf, book_id=book_id, limit=limit)
