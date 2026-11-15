"""Extract and normalize all 17 local TCM books into sources/library/*.jsonl without fabricating scan OCR."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any

import docx
import olefile
import pdfplumber
import pypdfium2 as pdfium
import zhconv


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "brain_data"
SOURCES_DIR = ROOT / "sources"
LIB_SOURCES_DIR = SOURCES_DIR / "library"
CATALOG_PATH = DATA_DIR / "source_catalog.json"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


_CJK_VARIANT_TRANS = str.maketrans({
    "\u3127": "一",  # Bopomofo I mistyped for CJK '一'
    "\uf9e7": "里",  # CJK compatibility '裏'
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
})

_SHANGHAN_MARGIN_STAMP = frozenset("觀其脈證知犯何逆隨證治之")


def normalize_search(text: str) -> str:
    if not text:
        return ""
    pre = text.translate(_CJK_VARIANT_TRANS)
    simp = zhconv.convert(pre, "zh-cn").translate(_CJK_VARIANT_TRANS)
    return re.sub(r"\s+", " ", simp).strip()


def _detect_pdf_section_titles(text: str, book_id: str) -> list[str]:
    titles: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or len(line) > 48:
            continue
        simp_line = zhconv.convert(line.translate(_CJK_VARIANT_TRANS), "zh-cn")
        if re.match(r"^(第\s*\d+\s*页|倪注《|倪海厦注《|\d{4}-\d{2}-\d{2})", simp_line):
            continue
        if book_id == "ni-hantang-formulas-pdf":
            m = re.match(r"^(HT-\d+[\s　]*[^\d\.]{1,24})", line)
            if m:
                titles.append(m.group(1).strip())
        elif book_id == "ni-hantang-articles-cases-pdf":
            if not re.search(r"[，。；！？]", simp_line) and re.match(r"^(汉唐中医|医案|诊余|病例|倪海厦).{2,30}$", simp_line):
                titles.append(line)
        elif book_id == "tang-rongchuan-xuezhenglun-pdf":
            if re.match(r"^(卷[一二三四五六七八]|.{1,16}论)$", simp_line):
                titles.append(line)
        elif (
            len(simp_line) <= 28
            and not re.search(r"[，。；！？]", simp_line)
            and re.match(r"^(第[一二三四五六七八九十百零]+[篇章节回卷]|卷[一二三四五六七八九十]+|辨.+脉证|[\u4e00-\u9fff]{2,18}篇)$", simp_line)
        ):
            titles.append(line)
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:6]


def _fast_dedupe_chars(chars: list[dict[str, Any]], tol: float = 1.8) -> list[dict[str, Any]]:
    """O(N) coordinate deduplication for PDFs with faux-bold stacked glyphs."""
    kept: list[dict[str, Any]] = []
    by_bin: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    step = max(tol, 1.0)
    for c in chars:
        t = c.get("text", "")
        bx = int(round(c["x0"] / step))
        by = int(round(c["top"] / step))
        is_dup = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for prev in by_bin.get((t, bx + dx, by + dy), ()):
                    if abs(prev["x0"] - c["x0"]) <= tol and abs(prev["top"] - c["top"]) <= tol:
                        is_dup = True
                        break
                if is_dup:
                    break
            if is_dup:
                break
        if not is_dup:
            kept.append(c)
            by_bin.setdefault((t, bx, by), []).append(c)
    return kept


def _chars_to_lines(chars: list[dict[str, Any]]) -> str:
    """Reconstruct natural reading lines top-to-bottom, left-to-right from PDF char coordinates."""
    lines: list[dict[str, Any]] = []
    for c in sorted(chars, key=lambda ch: (ch["top"], ch["x0"])):
        txt = c.get("text", "")
        if not txt or txt == "\n":
            continue
        placed = False
        c_size = float(c.get("size") or 10.5)
        for line in reversed(lines[-5:]):
            tol = max(3.5, 0.42 * min(line["size"], c_size))
            if abs(line["top"] - c["top"]) <= tol:
                line["chars"].append(c)
                placed = True
                break
        if not placed:
            lines.append({"top": c["top"], "size": c_size, "chars": [c]})

    out_lines: list[str] = []
    for line in sorted(lines, key=lambda item: item["top"]):
        chs = sorted(line["chars"], key=lambda ch: ch["x0"])
        buf: list[str] = []
        prev_x1: float | None = None
        for c in chs:
            txt = c.get("text", "")
            c_size = float(c.get("size") or 10.5)
            if prev_x1 is not None and (c["x0"] - prev_x1) > max(2.2, 0.35 * c_size):
                if not buf or buf[-1] != " ":
                    buf.append(" ")
            buf.append(txt)
            prev_x1 = float(c["x1"])
        joined = "".join(buf).strip()
        if joined:
            out_lines.append(joined)
    return "\n".join(out_lines)


def _extract_pdf_page_text(book_id: str, page: Any) -> str:
    """Extract clean, properly ordered text from a PDF page according to book layout quirks."""
    if book_id == "ni-hantang-formulas-pdf" or page.width > page.height * 1.15:
        mid_x = page.width / 2.0
        left_txt = (page.crop((0, 0, mid_x, page.height)).extract_text() or "").strip()
        right_txt = (page.crop((mid_x, 0, page.width, page.height)).extract_text() or "").strip()
        raw = "\n".join(part for part in (left_txt, right_txt) if part)
    elif book_id == "ni-shanghan-pdf":
        chars = [
            c for c in page.chars
            if not (c["x0"] < 78 and c.get("text", "") in _SHANGHAN_MARGIN_STAMP)
        ]
        raw = _chars_to_lines(chars)
    elif book_id == "ni-jinkui-pdf":
        chars = _fast_dedupe_chars(page.chars, tol=1.8)
        raw = _chars_to_lines(chars)
    else:
        raw = page.extract_text() or ""
    # Replace mistyped Bopomofo 'ㄧ' (U+3127) and compatibility '裏' (U+F9E7) for clean typography & search
    return raw.replace("\u3127", "一").replace("\uf9e7", "裏").strip()


def _extract_pdf_book(book_id: str, rel_path: str) -> list[dict[str, Any]]:
    pdf_path = ROOT / rel_path
    records: list[dict[str, Any]] = []
    current_section = ""
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            body = _extract_pdf_page_text(book_id, page)
            secs = _detect_pdf_section_titles(body, book_id)
            if secs:
                current_section = secs[0]
            ocr_status = "embedded_text" if body else "blank_page"
            records.append(
                {
                    "book_id": book_id,
                    "source_id": book_id,
                    "page_no": idx,
                    "unit_type": "pdf_page",
                    "unit_label": f"PDF 第 {idx} 页",
                    "printed_page": None,
                    "section_title": current_section,
                    "headings": secs,
                    "body_text": body,
                    "search_text": normalize_search(body),
                    "text_sha256": sha256_text(body),
                    "extraction_method": "pdfplumber_digital",
                    "ocr_status": ocr_status,
                }
            )
    return records


def _extract_scan_only_pdf(book_id: str, rel_path: str) -> list[dict[str, Any]]:
    pdf_path = ROOT / rel_path
    doc = pdfium.PdfDocument(str(pdf_path))
    total = len(doc)
    doc.close()
    records: list[dict[str, Any]] = []
    for idx in range(1, total + 1):
        records.append(
            {
                "book_id": book_id,
                "source_id": book_id,
                "page_no": idx,
                "unit_type": "scan_page",
                "unit_label": f"影印原页 第 {idx} 页",
                "printed_page": None,
                "section_title": "扫描影像页（未执行虚假OCR）",
                "headings": [],
                "body_text": "",
                "search_text": "",
                "text_sha256": sha256_text(""),
                "extraction_method": "scan_image_metadata_only",
                "ocr_status": "scan_browse_only",
            }
        )
    return records


def _split_lines_into_units(
    book_id: str,
    lines: list[str],
    heading_re: re.Pattern[str],
    extraction_method: str,
    target_chars: int = 2400,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    buf: list[str] = []
    buf_chars = 0
    start_line = 1
    current_section = "卷首"
    headings_in_buf: list[str] = []

    def flush(end_line: int) -> None:
        nonlocal buf, buf_chars, headings_in_buf
        body = "\n".join(buf).strip()
        if not body:
            return
        idx = len(units) + 1
        units.append(
            {
                "book_id": book_id,
                "source_id": book_id,
                "page_no": idx,
                "unit_type": "text_section",
                "unit_label": f"第 {idx} 节（L{start_line}-L{end_line}）",
                "printed_page": None,
                "section_title": current_section,
                "headings": list(dict.fromkeys(headings_in_buf))[:6],
                "body_text": body,
                "search_text": normalize_search(body),
                "text_sha256": sha256_text(body),
                "extraction_method": extraction_method,
                "ocr_status": "plain_text",
            }
        )
        buf = []
        buf_chars = 0
        headings_in_buf = []

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip()
        stripped = line.strip()
        is_heading = bool(stripped and len(stripped) <= 36 and heading_re.match(stripped))
        if is_heading and buf_chars >= 600:
            flush(lineno - 1)
            start_line = lineno
        if is_heading:
            current_section = stripped
            headings_in_buf.append(stripped)
        if not buf:
            start_line = lineno
        buf.append(line)
        buf_chars += len(line) + 1
        if buf_chars >= target_chars:
            flush(lineno)
            start_line = lineno + 1

    flush(len(lines))
    return units


def _extract_gb_text_file(book_id: str, rel_path: str, fallback_rel: str | None = None) -> list[dict[str, Any]]:
    path = ROOT / rel_path
    if not path.exists() and fallback_rel:
        path = ROOT / fallback_rel
    raw_bytes = path.read_bytes()
    text = ""
    for enc in ("utf-8-sig", "gb18030"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = raw_bytes.decode("gb18030", errors="replace")
    lines = text.splitlines()
    heading_re = re.compile(r"^(卷[一二三四五六七八九十百]+.*|辨.+脉证.*|.+法$|论.{1,20}|[\u4e00-\u9fff]{2,16}门)$")
    return _split_lines_into_units(book_id, lines, heading_re, "plain_text_split")


def _extract_docx_book(book_id: str, rel_path: str) -> list[dict[str, Any]]:
    doc = docx.Document(str(ROOT / rel_path))
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    heading_re = re.compile(r"^(\d+[•·.]|太陽|阳明|少陽|少阳|太陰|太阴|少陰|少阴|厥陰|厥阴|大塚|論|辨).{1,34}$")
    return _split_lines_into_units(book_id, lines, heading_re, "python_docx_paragraphs", target_chars=1800)


def _extract_ms_doc_book(book_id: str, rel_path: str) -> list[dict[str, Any]]:
    ole = olefile.OleFileIO(str(ROOT / rel_path))
    try:
        wd = ole.openstream("WordDocument").read()
        fib_flags = struct.unpack_from("<H", wd, 0x000A)[0]
        table_name = "1Table" if (fib_flags & 0x0200) else "0Table"
        tbl = ole.openstream(table_name).read()
        fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
        clx = tbl[fc_clx : fc_clx + lcb_clx]
        pos = 0
        pcdt = b""
        while pos < len(clx):
            if clx[pos] == 1:
                cb = struct.unpack_from("<H", clx, pos + 1)[0]
                pos += 3 + cb
            elif clx[pos] == 2:
                lcb_pcdt = struct.unpack_from("<I", clx, pos + 1)[0]
                pcdt = clx[pos + 5 : pos + 5 + lcb_pcdt]
                break
            else:
                break
        n_pieces = (len(pcdt) - 4) // 12
        cps = struct.unpack_from(f"<{n_pieces + 1}I", pcdt, 0)
        chunks: list[str] = []
        for i in range(n_pieces):
            fc_val = struct.unpack_from("<I", pcdt, (n_pieces + 1) * 4 + i * 8 + 2)[0]
            is_ansi = bool(fc_val & 0x40000000)
            offset = (fc_val & 0x3FFFFFFF) // 2 if is_ansi else fc_val
            char_len = cps[i + 1] - cps[i]
            raw = wd[offset : offset + char_len] if is_ansi else wd[offset : offset + char_len * 2]
            chunks.append(raw.decode("gb18030" if is_ansi else "utf-16le", errors="replace"))
    finally:
        ole.close()
    full_text = "".join(chunks).replace("\r", "\n").replace("\x07", " | ")
    # Clean stray OLE control characters other than newline/tab
    full_text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", full_text)
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
    heading_re = re.compile(r"^(自敘|自叙|卷[一二三四五六七八九十]+|[\u4e00-\u9fff]{2,14}[論论門门湯汤方])$")
    return _split_lines_into_units(book_id, lines, heading_re, "olefile_ms_doc_piece_table", target_chars=2200)


def _load_existing_acupuncture() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw_line in (SOURCES_DIR / "acupuncture" / "pages.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(raw_line)
        body = (row.get("body_text") or row.get("raw_text") or "").strip()
        pno = int(row["pdf_page"])
        out.append(
            {
                "book_id": "ni-acupuncture-v2-20100703",
                "source_id": "ni-acupuncture-v2-20100703",
                "page_no": pno,
                "unit_type": "pdf_page",
                "unit_label": f"PDF 第 {pno} 页" + (f"（原书 p.{row['printed_page']}）" if row.get("printed_page") else ""),
                "printed_page": row.get("printed_page"),
                "section_title": row.get("header") or "针灸教程",
                "headings": [row["header"]] if row.get("header") else [],
                "body_text": body,
                "search_text": normalize_search(body),
                "text_sha256": row.get("text_sha256") or sha256_text(body),
                "extraction_method": row.get("extraction_method") or "stage1_jsonl",
                "ocr_status": row.get("ocr_status") or ("embedded_text" if body else "blank_page"),
            }
        )
    return out


def _load_existing_bencao() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw_line in (SOURCES_DIR / "bencao" / "pages.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(raw_line)
        body = (row.get("text") or row.get("raw_text") or "").strip()
        pno = int(row["pdf_page"])
        secs = [line.strip() for line in body.splitlines()[:3] if 2 <= len(line.strip()) <= 28]
        out.append(
            {
                "book_id": "ni-bencao-pdf",
                "source_id": "ni-bencao-pdf",
                "page_no": pno,
                "unit_type": "pdf_page",
                "unit_label": f"PDF 第 {pno} 页" + (f"（原书 p.{row['printed_page']}）" if row.get("printed_page") else ""),
                "printed_page": row.get("printed_page"),
                "section_title": secs[0] if secs else (row.get("page_role") or "神农本草经"),
                "headings": secs,
                "body_text": body,
                "search_text": normalize_search(body),
                "text_sha256": row.get("text_sha256") or sha256_text(body),
                "extraction_method": "stage2_jsonl",
                "ocr_status": "embedded_text" if body else "blank_page",
            }
        )
    return out


def _load_existing_neijing(source_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw_line in (SOURCES_DIR / "neijing" / "pages.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(raw_line)
        if row.get("source_id") != source_id:
            continue
        body = (row.get("body_text") or row.get("raw_text") or "").strip()
        pno = int(row["pdf_page"])
        ch = row.get("chapter_headings") or []
        sh = row.get("section_headings") or []
        out.append(
            {
                "book_id": source_id,
                "source_id": source_id,
                "page_no": pno,
                "unit_type": "pdf_page",
                "unit_label": f"PDF 第 {pno} 页" + (f"（原书 p.{row['printed_page']}）" if row.get("printed_page") else ""),
                "printed_page": row.get("printed_page"),
                "section_title": (ch[0] if ch else (sh[0] if sh else row.get("volume_label") or "黄帝内经")),
                "headings": (ch + sh)[:6],
                "body_text": body,
                "search_text": normalize_search(body),
                "text_sha256": row.get("text_sha256") or sha256_text(body),
                "extraction_method": row.get("extraction_method") or "stage3_jsonl",
                "ocr_status": row.get("ocr_status") or ("embedded_text" if body else "blank_page"),
            }
        )
    return out


def _load_simple_page_jsonl(book_id: str, jsonl_path: Path, default_title: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    current_section = default_title
    for raw_line in jsonl_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(raw_line)
        pno = int(row["page"])
        body = (row.get("text") or "").strip()
        secs = _detect_pdf_section_titles(body, book_id)
        if secs:
            current_section = secs[0]
        out.append(
            {
                "book_id": book_id,
                "source_id": book_id,
                "page_no": pno,
                "unit_type": "pdf_page",
                "unit_label": f"PDF 第 {pno} 页",
                "printed_page": None,
                "section_title": current_section,
                "headings": secs,
                "body_text": body,
                "search_text": normalize_search(body),
                "text_sha256": sha256_text(body),
                "extraction_method": "stage4_jsonl",
                "ocr_status": "embedded_text" if body else "blank_page",
            }
        )
    return out


def _extract_ocr_book(book_id: str, rel_path: str) -> list[dict[str, Any]]:
    from etl.library.ocr_scans import extract_huangdi_waijing_ocr, extract_xu_lingtai_ocr

    extractors = {
        "xu-lingtai-collection-pdf": extract_xu_lingtai_ocr,
        "huangdi-waijing-pdf": extract_huangdi_waijing_ocr,
    }
    return extractors[book_id](rel_path, normalize_fn=normalize_search, sha_fn=sha256_text)


def _update_source_catalog(extracted_counts: dict[str, int]) -> None:
    if not CATALOG_PATH.exists():
        return
    cat = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    sources = cat.get("sources", [])
    updates = {
        "xu-lingtai-collection-pdf": (
            "winrt_zh_hans_ocr",
            f"Extracted {extracted_counts.get('xu-lingtai-collection-pdf', 412)}/434 pages via Windows zh-Hans-CN OCR; 22 verso/blank pages preserved blank.",
        ),
        "huangdi-waijing-pdf": (
            "winrt_zh_hans_ocr",
            f"Extracted all {extracted_counts.get('huangdi-waijing-pdf', 85)}/85 pages (4-page modern overview + 80 extant essays) via Windows zh-Hans-CN OCR.",
        ),
        "ni-hantang-clinic-notes-pdf": ("clean_digital", "Extracted 35 digital pages in Stage 5 Library ETL."),
        "tang-rongchuan-xuezhenglun-pdf": ("clean_digital_with_blank_cover", "Page 1 cover blank; pages 2-170 clean digital text extracted in Stage 5 Library ETL."),
        "otsuka-shanghan-docx": ("extracted_docx", "Extracted DOCX paragraphs into Stage 5 Library sections."),
        "wang-rulin-zhengyinfanglun-doc": ("extracted_doc_ole", "Extracted legacy MS-DOC piece table into Stage 5 Library sections."),
    }
    for s in sources:
        sid = s.get("source_id")
        if sid in updates:
            status, note = updates[sid]
            s["text_layer_status"] = status
            s["page_mapping_note"] = note
            if status == "winrt_zh_hans_ocr":
                s["known_issues"] = []
        if sid in extracted_counts and s.get("total_pages") is None and sid.endswith("-pdf"):
            s["total_pages"] = extracted_counts[sid]
    CATALOG_PATH.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    LIB_SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    cat = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    by_sid = {s["source_id"]: s for s in cat.get("sources", [])}

    extractors: dict[str, list[dict[str, Any]]] = {
        "ni-acupuncture-v2-20100703": _load_existing_acupuncture(),
        "ni-bencao-pdf": _load_existing_bencao(),
        "ni-neijing-vol1-pdf": _load_existing_neijing("ni-neijing-vol1-pdf"),
        "ni-neijing-vol2-pdf": _load_existing_neijing("ni-neijing-vol2-pdf"),
        "ni-shanghan-pdf": _extract_pdf_book("ni-shanghan-pdf", by_sid["ni-shanghan-pdf"]["relative_path"]),
        "ni-jinkui-pdf": _extract_pdf_book("ni-jinkui-pdf", by_sid["ni-jinkui-pdf"]["relative_path"]),
        "ni-jinkui-video-pdf": _load_simple_page_jsonl("ni-jinkui-video-pdf", SOURCES_DIR / "ni_jinkui_transcript.jsonl", "金匮视频同步文稿"),
        "ni-hantang-formulas-pdf": _extract_pdf_book("ni-hantang-formulas-pdf", by_sid["ni-hantang-formulas-pdf"]["relative_path"]),
        "ni-hantang-articles-cases-pdf": _extract_pdf_book("ni-hantang-articles-cases-pdf", by_sid["ni-hantang-articles-cases-pdf"]["relative_path"]),
        "ni-hantang-clinic-notes-pdf": _extract_pdf_book("ni-hantang-clinic-notes-pdf", by_sid["ni-hantang-clinic-notes-pdf"]["relative_path"]),
        "tang-rongchuan-xuezhenglun-pdf": _extract_pdf_book("tang-rongchuan-xuezhenglun-pdf", by_sid["tang-rongchuan-xuezhenglun-pdf"]["relative_path"]),
        "shanghan-juyi-book-txt": _extract_gb_text_file("shanghan-juyi-book-txt", by_sid["shanghan-juyi-book-txt"]["relative_path"], "sources/shanghan_juyi.txt"),
        "chen-shiduo-shishimilu-txt": _extract_gb_text_file("chen-shiduo-shishimilu-txt", by_sid["chen-shiduo-shishimilu-txt"]["relative_path"]),
        "otsuka-shanghan-docx": _extract_docx_book("otsuka-shanghan-docx", by_sid["otsuka-shanghan-docx"]["relative_path"]),
        "wang-rulin-zhengyinfanglun-doc": _extract_ms_doc_book("wang-rulin-zhengyinfanglun-doc", by_sid["wang-rulin-zhengyinfanglun-doc"]["relative_path"]),
        "xu-lingtai-collection-pdf": _extract_ocr_book("xu-lingtai-collection-pdf", by_sid["xu-lingtai-collection-pdf"]["relative_path"]),
        "huangdi-waijing-pdf": _extract_ocr_book("huangdi-waijing-pdf", by_sid["huangdi-waijing-pdf"]["relative_path"]),
    }

    counts: dict[str, int] = {}
    for book_id, rows in extractors.items():
        out_path = LIB_SOURCES_DIR / f"{book_id}.jsonl"
        out_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
        non_empty = sum(1 for r in rows if r["body_text"])
        counts[book_id] = len(rows)
        print(f"Extracted {book_id}: {len(rows)} units ({non_empty} text-populated)")

    _update_source_catalog(counts)
    print(f"Done. Extracted {len(extractors)} books into {LIB_SOURCES_DIR}")


if __name__ == "__main__":
    main()
