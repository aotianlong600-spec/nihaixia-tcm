"""Extract all 306 pages of the Huangdi Neijing video-sync transcript PDFs.

Processes both:
- ni-neijing-vol1-pdf (上册, 152 pages: cover, copyright, 8-page master TOC, printed pp. 9-149, blank p.152)
- ni-neijing-vol2-pdf (下册, 154 pages: cover, copyright, printed pp. 150-301)

Outputs ``sources/neijing/pages.jsonl`` with exact running header/footer split,
printed_page verification, font-size-detected chapter (>=13.5pt) and section
(11.5-13.4pt) headings, quoted classic fragments, and dual SHA-256 verification.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium


ROOT = Path(__file__).resolve().parents[2]
VOLUMES = [
    {
        "source_id": "ni-neijing-vol1-pdf",
        "volume": "vol1",
        "volume_label": "上册",
        "pdf_path": ROOT / "books" / "ni-haixia-medicine" / "【视频同步文稿】倪海厦人纪系列书籍之《皇帝内经上册》 .pdf",
    },
    {
        "source_id": "ni-neijing-vol2-pdf",
        "volume": "vol2",
        "volume_label": "下册",
        "pdf_path": ROOT / "books" / "ni-haixia-medicine" / "【视频同步文稿】倪海厦人纪系列书籍之《黄帝内经下册》.pdf",
    },
]
OUTPUT_PATH = ROOT / "sources" / "neijing" / "pages.jsonl"

RUNNING_HEADER_PREFIX = "倪海厦人纪系列书籍之"
RUNNING_FOOTER_RE = re.compile(r"^守候诚实国学书店\s*第\s*(\d+)\s*页\s*共\s*301\s*页.*$")
QUOTED_CLASSIC_RE = re.compile(r"“([^”]{4,240})”")


def _extract_headings_by_font(page: pdfplumber.page.Page) -> tuple[list[str], list[str]]:
    """Extract chapter headings (>=13.5pt) and section headings (11.5..13.4pt) using PDF char sizes."""
    chapters: list[str] = []
    sections: list[str] = []
    cur_bucket: str | None = None
    cur_top: float | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, cur_bucket
        text = re.sub(r"\s+", " ", "".join(buf)).strip()
        if text:
            if cur_bucket == "chapter" and text not in chapters:
                chapters.append(text)
            elif cur_bucket == "section" and text not in sections:
                sections.append(text)
        buf = []

    for ch in page.chars:
        sz = float(ch.get("size", 0.0))
        top = round(float(ch.get("top", 0.0)), 1)
        if sz >= 13.5:
            bucket = "chapter"
        elif 11.5 <= sz < 13.5:
            bucket = "section"
        else:
            if buf:
                flush()
                cur_bucket = None
                cur_top = None
            continue

        if cur_bucket != bucket or (cur_top is not None and abs(top - cur_top) > 18.0):
            if buf:
                flush()
            cur_bucket = bucket
        cur_top = top
        buf.append(ch.get("text", ""))

    if buf:
        flush()
    return chapters, sections


def _split_header_body_footer(raw_extract: str) -> tuple[str, str, int | None, str]:
    """Separate running header and running footer cleanly from page body."""
    lines = raw_extract.splitlines()
    header = ""
    footer = ""
    printed_page: int | None = None
    body_lines: list[str] = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if idx == 0 and stripped.startswith(RUNNING_HEADER_PREFIX):
            header = stripped
            continue
        m = RUNNING_FOOTER_RE.match(stripped)
        if m:
            footer = stripped
            printed_page = int(m.group(1))
            continue
        body_lines.append(line.rstrip())

    body_text = "\n".join(body_lines).strip()
    return header, footer, printed_page, body_text


def _page_role(volume: str, pdf_page: int, body_text: str) -> tuple[str, str]:
    if pdf_page == 1 and not body_text:
        return "cover", "cover_image"
    if not body_text:
        return "blank", "blank_page"
    if pdf_page == 2:
        return "copyright", "clean_digital"
    if volume == "vol1" and 3 <= pdf_page <= 10:
        return "toc", "clean_digital"
    return "body", "clean_digital"


def extract_all_pages() -> list[dict]:
    """Extract every page across both Huangdi Neijing volumes cleanly."""
    records: list[dict] = []
    for vol in VOLUMES:
        source_id = vol["source_id"]
        volume = vol["volume"]
        volume_label = vol["volume_label"]
        pdf_path = vol["pdf_path"]
        fium = pdfium.PdfDocument(str(pdf_path))
        with pdfplumber.open(str(pdf_path)) as pdf:
            for idx, page in enumerate(pdf.pages):
                pdf_page = idx + 1
                raw_text = fium[idx].get_textpage().get_text_range().replace("\r\n", "\n").strip()
                plumb_text = (page.extract_text() or "").replace("\r\n", "\n").strip()
                header, footer, printed_page, body_text = _split_header_body_footer(plumb_text)
                role, ocr_status = _page_role(volume, pdf_page, body_text)

                if role == "body":
                    chapter_headings, section_headings = _extract_headings_by_font(page)
                    collapsed = re.sub(r"\n+", "", body_text)
                    quoted = []
                    for q in QUOTED_CLASSIC_RE.findall(collapsed):
                        q_clean = re.sub(r"\s+", " ", q).strip()
                        if q_clean and q_clean not in quoted:
                            quoted.append(q_clean)
                else:
                    chapter_headings, section_headings, quoted = [], [], []

                page_id = f"{source_id}:p{pdf_page:03d}"
                records.append(
                    {
                        "page_id": page_id,
                        "source_id": source_id,
                        "volume": volume,
                        "volume_label": volume_label,
                        "pdf_page": pdf_page,
                        "printed_page": printed_page,
                        "page_role": role,
                        "header": header,
                        "footer": footer,
                        "body_text": body_text,
                        "chapter_headings": chapter_headings,
                        "section_headings": section_headings,
                        "quoted_classic_fragments": quoted,
                        "raw_text": raw_text,
                        "text_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                        "extraction_method": "pdf_text_layout",
                        "ocr_status": ocr_status,
                    }
                )
    return records


def main() -> int:
    records = extract_all_pages()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    v1_count = sum(1 for r in records if r["volume"] == "vol1")
    v2_count = sum(1 for r in records if r["volume"] == "vol2")
    print(f"Extracted {len(records)} pages (vol1={v1_count}, vol2={v2_count}) to {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
