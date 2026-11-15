"""Extract all 154 pages from Ni Haixia's Shennong Bencao Jing PDF into sources/bencao/pages.jsonl."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = ROOT / "books" / "ni-haixia-medicine" / "【倪海厦注解版】倪海厦注神农本草经(清晰版).pdf"
OUT_PATH = ROOT / "sources" / "bencao" / "pages.jsonl"

FOOTER_RE = re.compile(r"^V\d+\.\d+\s+(\d+|[IVX]+)\s*$")


def _clean_page(raw: str, pdf_page: int) -> tuple[str, str | None]:
    lines = raw.splitlines()
    printed_page: str | None = None
    cleaned = []
    for idx, line in enumerate(lines):
        st = line.strip()
        if idx == 0 and st == "倪注神农本草经":
            continue
        m_foot = FOOTER_RE.match(st)
        if m_foot and idx >= len(lines) - 2:
            printed_page = m_foot.group(1)
            continue
        cleaned.append(line.rstrip())
    text = "\n".join(cleaned).strip()
    return text, printed_page


def _page_role(pdf_page: int, text: str) -> str:
    if not text.strip():
        return "blank"
    if pdf_page == 1:
        return "cover_notice"
    if pdf_page == 4:
        return "collation_preface"
    if pdf_page == 5:
        return "ni_preface"
    if 6 <= pdf_page <= 15:
        return "toc"
    if pdf_page == 16:
        return "chapter1_preface"
    if 17 <= pdf_page <= 18:
        return "chapter2_general"
    if 19 <= pdf_page <= 73:
        return "upper_classic"
    if 74 <= pdf_page <= 107:
        return "middle_classic"
    if 108 <= pdf_page <= 134:
        return "lower_classic"
    if pdf_page == 135:
        return "lower_classic_and_supplement"
    if 136 <= pdf_page <= 144:
        return "chapter3_supplement"
    if 145 <= pdf_page <= 149:
        return "pinyin_index"
    if pdf_page == 150:
        return "pinyin_and_stroke_index"
    return "stroke_index"


def extract_pages() -> list[dict]:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"Missing PDF: {PDF_PATH}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for pdf_page, page in enumerate(pdf.pages, 1):
            raw_text = (page.extract_text() or "").strip()
            text, printed_page = _clean_page(raw_text, pdf_page)
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            rec = {
                "source_id": "ni-bencao-pdf",
                "pdf_page": pdf_page,
                "printed_page": printed_page,
                "page_role": _page_role(pdf_page, text),
                "raw_text": raw_text,
                "text": text,
                "text_sha256": sha,
            }
            records.append(rec)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return records


def main() -> None:
    recs = extract_pages()
    non_blank = sum(1 for r in recs if r["text"])
    print(json.dumps({"total_pages": len(recs), "non_blank": non_blank, "out": str(OUT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
